"""Canonical subscription lifecycle with strict atomic Firestore fixtures only."""
import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch
from flask import Flask
import auth_utils
import db as storage
import subscription_service as service
from routes import subscriptions
from test_core_routes import CoreStore
from test_khata import Query

NOW = datetime(2026, 10, 20, 10, tzinfo=timezone.utc)


class PagedQuery(Query):
    def __init__(self, store, collection, filters=(), maximum=None, after=None):
        super().__init__(store, collection, filters)
        self.maximum, self.after = maximum, after
    def where(self, *, filter):
        return PagedQuery(self.store, self.collection, self.filters + ((filter.field_path, filter.value),), self.maximum, self.after)
    def order_by(self, field):
        return self
    def start_after(self, values):
        return PagedQuery(self.store, self.collection, self.filters, self.maximum, values['__name__'].id)
    def limit(self, maximum):
        return PagedQuery(self.store, self.collection, self.filters, maximum, self.after)
    def stream(self):
        values = sorted(super().stream(), key=lambda row: row.id)
        values = [row for row in values if not self.after or row.id > self.after]
        return values[:self.maximum] if self.maximum is not None else values


class SubscriptionStore(CoreStore):
    def col(self, collection):
        return PagedQuery(self, collection)


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.store = SubscriptionStore()
        self.store.data = {(storage.USERS, 'admin'): {'role': 'admin'},
                           (storage.USERS, 'vendor'): {'role': 'vendor', 'shop_name': 'Shop', 'created_at': (NOW-timedelta(days=1)).isoformat()},
                           (storage.USERS, 'other'): {'role': 'vendor', 'created_at': (NOW-timedelta(days=1)).isoformat()},
                           (storage.USERS, 'customer'): {'role': 'customer'}}
        self.app = Flask(__name__)
        self.app.config['TESTING'] = True
        self.app.register_blueprint(subscriptions.subscriptions_bp)
        for module in (service, subscriptions):
            for name, value in (('doc', self.store.doc), ('col', self.store.col)):
                current = patch.object(module, name, value); current.start(); self.addCleanup(current.stop)
        for current in (patch.object(service, 'db', lambda: self.store),
                        patch.object(storage, 'doc', self.store.doc),
                        patch.object(service.firestore, 'transactional', self.store.transactional),
                        patch.object(auth_utils, 'decode_token', lambda token: {'sub': token}),
                        patch.object(service, '_now', return_value=NOW), patch.object(service, 'deliver_push')):
            current.start(); self.addCleanup(current.stop)
        self.client, self.sequence = self.app.test_client(), 0

    def call(self, path, payload=None, method='POST', user='admin', key=None):
        self.sequence += 1
        return self.client.open(path, method=method, json=payload,
            headers={'Authorization': 'Bearer ' + user, 'Idempotency-Key': key or f'operation-key-{self.sequence}'})

    def plan(self, price=0, trial=7, maximum=10, **extra):
        response = self.call('/admin/subscription-plans', {'name': 'Basic', 'description': '', 'reason': 'Configure reviewed terms',
            'price_paise': price, 'duration_days': 30, 'trial_days': trial, 'grace_days': 3,
            'entitlements': {'max_items': maximum, 'catalog_growth': True, 'product_import': True, 'promotions': True}, **extra})
        self.assertEqual(response.status_code, 201, response.json)
        return response.json

    def aggregate(self, user='vendor'):
        response = self.call('/subscriptions/entitlements', method='GET', user=user)
        self.assertEqual(response.status_code, 200, response.json)
        return response.json

    def request_plan(self, plan, kind='subscription', key=None, user='vendor'):
        return self.call('/subscriptions/requests', {'plan_id': plan['uid'], 'plan_version_id': plan['current_version_id'],
            'request_kind': kind, 'expected_account_revision': self.aggregate(user)['revision']}, user=user, key=key)

    def decide(self, request, decision='approved', key=None):
        return self.call('/admin/subscription-requests/' + request['uid'] + '/decision',
            {'decision': decision, 'revision': request['revision'], 'expected_account_revision': self.aggregate()['revision'],
             'reason': 'Reviewed exact version'}, key=key)

    def action(self, action, **extra):
        return self.call('/admin/vendors/vendor/subscription', {'action': action, 'reason': 'Reviewed access change',
            'expected_account_revision': self.aggregate()['revision'], **extra})

    def values(self, collection):
        return [value for (name, _), value in self.store.data.items() if name == collection]

    def test_immutable_version_and_operation_replay(self):
        plan = self.plan()
        frozen = copy.deepcopy(self.store.data[(service.VERSIONS, plan['current_version_id'])])
        body = {'revision': 1, 'reason': 'New price applies to future requests', 'price_paise': 9900}
        first = self.call('/admin/subscription-plans/' + plan['uid'], body, 'PUT', key='same-plan-edit')
        self.assertEqual(first.status_code, 200, first.json)
        second = self.call('/admin/subscription-plans/' + plan['uid'], body, 'PUT', key='same-plan-edit')
        self.assertEqual(first.json, second.json)
        self.assertEqual(first.json['revision'], 2)
        self.assertNotEqual(first.json['current_version_id'], plan['current_version_id'])
        self.assertEqual(self.store.data[(service.VERSIONS, plan['current_version_id'])], frozen)
        self.assertEqual(len(self.values(service.VERSIONS)), 2)
        changed = self.call('/admin/subscription-plans/' + plan['uid'], {**body, 'price_paise': 1}, 'PUT', key='same-plan-edit')
        self.assertEqual(changed.status_code, 409)
        self.assertEqual(changed.json['code'], 'IDEMPOTENCY_CONFLICT')

    def test_free_request_requires_admin_and_fulfills_once(self):
        plan = self.plan()
        pending = self.request_plan(plan)
        self.assertEqual(pending.status_code, 201, pending.json)
        self.assertEqual(self.aggregate()['status'], 'none')
        response = self.decide(pending.json, key='approve-free-request')
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(response.json['request']['status'], 'fulfilled')
        self.assertEqual(response.json['subscription']['payment_state'], 'not_required')
        self.assertTrue(response.json['subscription']['capabilities']['catalog_growth'])
        self.assertEqual(len(self.values(service.GRANTS)), 1)
        replay = self.call('/admin/subscription-requests/' + pending.json['uid'] + '/decision',
                           {'decision': 'approved', 'revision': 1, 'expected_account_revision': 1, 'reason': 'Reviewed exact version'}, key='approve-free-request')
        self.assertEqual(replay.json, response.json)
        self.assertEqual(len(self.values(service.GRANTS)), 1)
        self.assertEqual(self.values(storage.NOTIFICATIONS)[0]['reference_type'], 'vendor_subscription')

    def test_paid_approval_never_grants_and_legacy_claims_are_ignored(self):
        plan = self.plan(price=9900, google_play={'product_id': 'shop_basic', 'base_plan_id': 'monthly'})
        self.store.data[('vendor_subscriptions', 'forged')] = {'vendor_id': 'vendor', 'status': 'active',
            'payment_status': 'paid', 'start_date': (NOW-timedelta(days=1)).isoformat(), 'end_date': (NOW+timedelta(days=300)).isoformat()}
        pending = self.request_plan(plan)
        response = self.decide(pending.json)
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(response.json['request']['status'], 'approved_checkout')
        self.assertEqual(self.aggregate()['status'], 'none')
        self.assertEqual(self.values(service.GRANTS), [])
        self.assertEqual(self.call('/subscriptions/me', method='GET', user='vendor').status_code, 404)
        context = service.prepare_google_play_checkout('vendor', pending.json['uid'])
        self.assertEqual(context['plan_version']['uid'], plan['current_version_id'])
        self.assertEqual(len(context['billing_account_id']), 64)

    def test_trial_is_once_per_vendor_across_plans_and_never_paid(self):
        first = self.plan(price=9900)
        request = self.request_plan(first, 'trial')
        decision = self.decide(request.json)
        self.assertEqual(decision.status_code, 200, decision.json)
        grant = self.values(service.GRANTS)[0]
        self.assertEqual(grant['kind'], 'trial')
        self.assertEqual(grant['payment_state'], 'not_charged')
        self.assertEqual(service._date(grant['ends_at']) - service._date(grant['starts_at']), timedelta(days=7))
        second = self.plan(price=19900)
        self.assertEqual(self.request_plan(second, 'trial').json['code'], 'TRIAL_ALREADY_USED')
        self.assertEqual(self.action('extend', ends_at=(NOW+timedelta(days=90)).isoformat()).status_code, 409)
        self.assertEqual(len(self.values(service.GRANTS)), 1)

    def test_paid_access_requires_explicit_bounded_complimentary_override(self):
        plan = self.plan(price=10000)
        args = {'plan_id': plan['uid'], 'plan_version_id': plan['current_version_id']}
        self.assertEqual(self.action('assign', kind='free', **args).json['code'], 'STORE_BILLING_REQUIRED')
        self.assertEqual(self.action('assign', kind='complimentary', **args).status_code, 422)
        response = self.action('assign', kind='complimentary', ends_at=(NOW+timedelta(days=4)).isoformat(), **args)
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(response.json['payment_state'], 'not_charged')
        self.assertEqual(self.action('suspend').json['status'], 'suspended')
        self.assertEqual(self.action('reactivate').json['status'], 'active')
        with patch.object(service, '_now', return_value=NOW+timedelta(days=5)):
            self.assertEqual(self.aggregate()['status'], 'grace')
        with patch.object(service, '_now', return_value=NOW+timedelta(days=8)):
            self.assertEqual(self.aggregate()['status'], 'expired')

    def test_schedule_frozen_terms_applies_once_with_original_audit(self):
        first, second = self.plan(), self.plan(maximum=25)
        self.assertEqual(self.action('assign', kind='free', plan_id=first['uid'], plan_version_id=first['current_version_id']).status_code, 200)
        response = self.action('schedule_change', kind='free', plan_id=second['uid'], plan_version_id=second['current_version_id'],
                               effective_at=(NOW+timedelta(days=1)).isoformat())
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(self.aggregate()['usage']['max_items'], 10)
        with patch.object(service, '_now', return_value=NOW+timedelta(days=2)):
            self.assertEqual(self.aggregate()['usage']['max_items'], 25)
            count = len(self.values(storage.AUDIT_LOGS))
            self.assertEqual(self.aggregate()['usage']['max_items'], 25)
            self.assertEqual(len(self.values(storage.AUDIT_LOGS)), count)
        event = next(row for row in self.values(storage.AUDIT_LOGS) if row['action']=='subscription_schedule_applied')
        self.assertEqual(event['actor_id'], 'admin')
        self.assertEqual(event['reason'], 'Reviewed access change')
        self.assertIsNotNone(event['before']['scheduled_change'])
        self.assertIsNone(event['after']['scheduled_change'])

    def test_schedule_cancel_and_cancel_scheduled_preserve_history(self):
        plan = self.plan()
        self.action('assign', kind='free', plan_id=plan['uid'], plan_version_id=plan['current_version_id'])
        scheduled = self.action('schedule_cancel', effective_at=(NOW+timedelta(days=1)).isoformat())
        self.assertEqual(scheduled.status_code, 200, scheduled.json)
        self.assertEqual(self.action('cancel_scheduled').status_code, 200)
        with patch.object(service, '_now', return_value=NOW+timedelta(days=2)):
            self.assertEqual(self.aggregate()['status'], 'active')
        self.action('schedule_cancel', effective_at=(NOW+timedelta(days=1)).isoformat())
        with patch.object(service, '_now', return_value=NOW+timedelta(days=2)):
            self.assertEqual(self.aggregate()['status'], 'none')
        self.assertEqual(len(self.values(service.GRANTS)), 1)

    def test_referenced_plan_cannot_delete_and_archiving_preserves_access(self):
        plan = self.plan()
        self.action('assign', kind='free', plan_id=plan['uid'], plan_version_id=plan['current_version_id'])
        deleted = self.call('/admin/subscription-plans/'+plan['uid'], {'revision':1,'reason':'Remove'}, 'DELETE')
        self.assertEqual(deleted.status_code, 409, deleted.json)
        self.assertEqual(deleted.json['code'], 'PLAN_REFERENCED')
        self.assertGreater(self.store.data[(service.PLANS, plan['uid'])]['reference_count'], 0)
        archived = self.call('/admin/subscription-plans/'+plan['uid']+'/archive', {'revision':1,'reason':'No future requests'})
        self.assertEqual(archived.status_code, 200, archived.json)
        self.assertEqual(self.call('/subscriptions/plans', method='GET', user='customer').json, [])
        self.assertEqual(self.aggregate()['status'], 'active')

    def test_current_role_validation_revision_and_rollback(self):
        plan = self.plan()
        self.assertEqual(self.call('/admin/subscription-plans', {}, user='vendor').status_code, 403)
        request = self.request_plan(plan)
        self.assertEqual(self.request_plan(plan).json['code'], 'REQUEST_EXISTS')
        self.assertEqual(self.call('/subscriptions/requests/'+request.json['uid']+'/cancel',
            {'revision':1,'expected_account_revision':1}, user='other').status_code, 404)
        before = copy.deepcopy(self.store.data)
        self.store.fail_commit = True
        with self.assertRaises(RuntimeError):
            self.decide(request.json)
        self.assertEqual(self.store.data, before)

    def test_bounded_pages_include_vendor_without_grant_and_history(self):
        self.plan()
        response = self.call('/admin/subscriptions?limit=1', method='GET')
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(len(response.json['items']), 1)
        self.assertIsNotNone(response.json['next_cursor'])
        cursor = response.json['next_cursor']
        next_page = self.call('/admin/subscriptions?limit=1&cursor='+cursor, method='GET')
        self.assertNotEqual(response.json['items'][0]['vendor_id'], next_page.json['items'][0]['vendor_id'])
        self.assertEqual(self.call('/admin/vendors/vendor/subscription?history_limit=1', method='GET').status_code, 200)

    def test_account_search_fills_matching_pages_and_scopes_continuation(self):
        for number in range(90):
            self.store.data[(storage.USERS,f'a_vendor_{number:03}')]= {'role':'vendor','shop_name':'Ordinary shop'}
        self.store.data[(storage.USERS,'z_target')]= {'role':'vendor','shop_name':'Distinct target','phone':'555900'}
        with patch.object(service,'entitlements',wraps=service.entitlements) as lookup:
            result=self.call('/admin/subscriptions?limit=1&q=Distinct',method='GET')
            self.assertEqual(result.status_code,200,result.json)
            self.assertEqual([row['vendor_id'] for row in result.json['items']],['z_target'])
            self.assertGreater(result.json['scanned_count'],25)
            self.assertEqual(lookup.call_count,1)
        for number in range(500):
            self.store.data[(storage.USERS,f'b_vendor_{number:03}')]= {'role':'vendor','shop_name':'Ordinary shop'}
        first=self.call('/admin/subscriptions?limit=1&q=Distinct',method='GET')
        self.assertEqual(first.json['items'],[])
        self.assertEqual(first.json['scanned_count'],500)
        self.assertTrue(first.json['search_incomplete'])
        cursor=first.json['next_cursor']
        changed=self.call('/admin/subscriptions?limit=1&q=Different&cursor='+cursor,method='GET')
        self.assertEqual(changed.status_code,422)
        second=self.call('/admin/subscriptions?limit=1&q=Distinct&cursor='+cursor,method='GET')
        self.assertEqual([row['vendor_id'] for row in second.json['items']],['z_target'])
        self.assertIsNone(second.json['next_cursor'])
        plan=self.plan()
        self.action('assign',kind='free',plan_id=plan['uid'],plan_version_id=plan['current_version_id'])
        filtered=self.call('/admin/subscriptions?limit=1&q=vendor&status=active',method='GET')
        if filtered.json['next_cursor']:
            filtered=self.call('/admin/subscriptions?limit=1&q=vendor&status=active&cursor='+filtered.json['next_cursor'],method='GET')
        self.assertEqual([row['vendor_id'] for row in filtered.json['items']],['vendor'])

    def test_verified_store_state_owns_request_and_replay_and_old_token_cannot_regrant(self):
        plan = self.plan(price=9900, google_play={'product_id':'shop_basic','base_plan_id':'monthly'})
        pending = self.request_plan(plan).json
        self.decide(pending)
        args = {'event_id':'verified-event-1','provider_state':'active','plan_version_id':plan['current_version_id'],
                'starts_at':NOW.isoformat(),'ends_at':(NOW+timedelta(days=30)).isoformat(),
                'purchase_fingerprint':'first_fingerprint','source_revision':1,'request_id':pending['uid']}
        first = service.apply_verified_store_state('vendor', **args)
        self.assertEqual(first['status'], 'active')
        self.assertEqual(first['payment_state'], 'store_verified')
        self.assertEqual(service.apply_verified_store_state('vendor', **args), first)
        replacement = service.apply_verified_store_state('vendor', **{**args,'event_id':'replacement-event','purchase_fingerprint':'second_fingerprint',
            'linked_purchase_fingerprint':'first_fingerprint','request_id':None})
        self.assertEqual(replacement['status'], 'active')
        stale = service.apply_verified_store_state('vendor', **{**args,'event_id':'old-token-expired','provider_state':'expired','source_revision':2,'request_id':None})
        self.assertEqual(stale['current_grant_id'], replacement['current_grant_id'])
        self.assertEqual(stale['status'], 'active')
        self.assertEqual(self.store.data[(service.REQUESTS,pending['uid'])]['status'], 'fulfilled')

    def test_invalid_terms_and_fingerprints_are_validation_errors(self):
        for value in (True, -1, float('nan')):
            response = self.call('/admin/subscription-plans', {'name':'Invalid','reason':'Validation','price_paise':value})
            self.assertEqual(response.status_code, 422, response.json)
        self.assertEqual(self.call('/subscriptions/subscribe', {'plan_id':'legacy'}, user='vendor').status_code, 409)
