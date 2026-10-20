"""Access/payment precedence and reviewed legacy cohort regressions."""
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch

from google.api_core.datetime_helpers import DatetimeWithNanoseconds
import db as storage
import subscription_service as service
import test_subscription_lifecycle as fixture

NOW = fixture.NOW


class AuthorityTests(unittest.TestCase):
    setUp = fixture.LifecycleTests.setUp
    call = fixture.LifecycleTests.call
    plan = fixture.LifecycleTests.plan
    aggregate = fixture.LifecycleTests.aggregate
    request_plan = fixture.LifecycleTests.request_plan
    decide = fixture.LifecycleTests.decide
    action = fixture.LifecycleTests.action
    values = fixture.LifecycleTests.values

    def paid(self):
        plan = self.plan(price=9900, renewal_rule='store', google_play={'product_id': 'basic', 'base_plan_id': 'monthly'})
        request = self.request_plan(plan).json
        self.assertEqual(self.decide(request).status_code, 200)
        self.args = dict(provider_state='active', plan_version_id=plan['current_version_id'], starts_at=NOW.isoformat(),
                         ends_at=(NOW+timedelta(days=30)).isoformat(), purchase_fingerprint='token_a', source_revision=1)
        service.apply_verified_store_state('vendor', event_id='store-first', request_id=request['uid'], **self.args)
        return plan

    def blocked_approval(self, kind):
        paid = self.paid()
        free = self.plan()
        for override in (False, True):
            if override:
                result = self.action('assign', kind='complimentary', plan_id=paid['uid'], plan_version_id=paid['current_version_id'],
                                     ends_at=(NOW+timedelta(days=1)).isoformat())
                self.assertEqual(result.status_code, 200, result.json)
            request = self.request_plan(free, kind='trial' if kind == 'trial' else 'subscription').json
            before = self.aggregate()
            grants = len(self.values(service.GRANTS))
            result = self.decide(request)
            self.assertEqual(result.status_code, 409, result.json)
            self.assertEqual(result.json['code'], 'STORE_MANAGED')
            self.assertEqual(self.aggregate()['current_grant_id'], before['current_grant_id'])
            self.assertEqual(len(self.values(service.GRANTS)), grants)
            self.assertEqual(self.store.data[(service.REQUESTS, request['uid'])]['status'], 'pending')
            self.assertFalse(self.aggregate()['trial_used'])
            self.assertEqual(self.aggregate()['payment_state'], 'not_charged' if override else 'store_verified')
            self.assertEqual(self.decide(request, 'rejected').status_code, 200)

    def test_free_approval_cannot_hide_google_even_under_complimentary(self):
        self.blocked_approval('free')

    def test_trial_approval_cannot_hide_google_even_under_complimentary(self):
        self.blocked_approval('trial')

    def test_verified_terminal_google_allows_later_free_grant_without_claiming_payment(self):
        self.paid()
        service.apply_verified_store_state('vendor', event_id='store-expired', **{**self.args, 'provider_state': 'expired', 'source_revision': 2})
        request = self.request_plan(self.plan()).json
        result = self.decide(request)
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(result.json['subscription']['grant_kind'], 'free')
        self.assertEqual(result.json['subscription']['payment_state'], 'not_required')
        self.assertEqual(result.json['subscription']['billing_provider'], 'google_play')

    def test_scheduled_and_direct_grants_preserve_explicit_suspension(self):
        plan = self.plan()
        args = dict(plan_id=plan['uid'], plan_version_id=plan['current_version_id'], kind='free')
        self.action('assign', **args)
        self.action('suspend')
        self.assertEqual(self.action('assign', **args).json['status'], 'suspended')
        self.assertEqual(self.action('schedule_change', effective_at=(NOW+timedelta(days=1)).isoformat(), **args).status_code, 200)
        with patch.object(service, '_now', return_value=NOW+timedelta(days=2)):
            result = self.aggregate()
            self.assertEqual(result['access_state'], 'suspended')
            self.assertFalse(result['capabilities']['catalog_growth'])
            self.assertIsNone(result['scheduled_change'])
            self.assertEqual(self.action('reactivate').json['status'], 'active')

    def test_comp_grace_survives_store_poll_and_exposes_separate_billing(self):
        plan = self.paid()
        override = self.action('assign', kind='complimentary', plan_id=plan['uid'], plan_version_id=plan['current_version_id'],
                               ends_at=(NOW+timedelta(days=1)).isoformat()).json
        with patch.object(service, '_now', return_value=NOW+timedelta(days=2)):
            before = self.aggregate()
            self.assertEqual(before['status'], 'grace')
            result = service.apply_verified_store_state('vendor', event_id='store-hold', **{**self.args, 'provider_state': 'hold', 'source_revision': 2})
            self.assertEqual(result['current_grant_id'], override['current_grant_id'])
            self.assertEqual(result['grant_kind'], 'complimentary')
            self.assertEqual(result['status'], 'grace')
            self.assertEqual(result['payment_state'], 'not_charged')
            self.assertEqual(result['billing_provider'], 'google_play')
            self.assertEqual(result['store_subscription'], {'provider_state': 'hold', 'ends_at': self.args['ends_at'], 'product_id': 'basic'})
            self.assertNotIn('purchase_fingerprint', result)
        with patch.object(service, '_now', return_value=NOW+timedelta(days=5)):
            self.assertEqual(self.aggregate()['grant_kind'], 'google_play')
            self.assertEqual(self.aggregate()['status'], 'suspended')

    def test_old_free_schedule_is_blocked_once_after_google_purchase(self):
        free = self.plan()
        self.action('assign', kind='free', plan_id=free['uid'], plan_version_id=free['current_version_id'])
        self.action('schedule_change', kind='free', plan_id=free['uid'], plan_version_id=free['current_version_id'],
                    effective_at=(NOW+timedelta(days=1)).isoformat())
        self.paid()
        with patch.object(service, '_now', return_value=NOW+timedelta(days=2)):
            result = self.aggregate()
            self.assertEqual(result['grant_kind'], 'google_play')
            self.assertIsNone(result['scheduled_change'])
            self.assertEqual(result['blocked_scheduled_change']['status'], 'blocked')
            self.assertEqual(result['blocked_scheduled_change']['blocked_reason'], 'STORE_MANAGED')
            self.assertEqual(result['blocked_scheduled_change']['reason'], 'Reviewed access change')
            self.assertEqual(result['blocked_scheduled_change']['created_by'], 'admin')
            audits = [row for row in self.values(storage.AUDIT_LOGS) if row['action'] == 'subscription_schedule_blocked_store_managed']
            self.assertEqual(len(audits), 1)
            self.assertEqual(audits[0]['reason'], 'Reviewed access change')
            self.aggregate()
            self.assertEqual(len([row for row in self.values(storage.AUDIT_LOGS) if row['action'] == 'subscription_schedule_blocked_store_managed']), 1)

    def test_archived_plan_request_remains_rejectable(self):
        plan = self.plan()
        request = self.request_plan(plan).json
        archived = self.call('/admin/subscription-plans/'+plan['uid']+'/archive', {'revision': 1, 'reason': 'Retired catalog'})
        self.assertEqual(archived.status_code, 200, archived.json)
        self.assertEqual(self.decide(request).json['code'], 'PLAN_CHANGED')
        result = self.decide(request, 'rejected')
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(result.json['request']['status'], 'rejected')
        self.assertIsNone(self.aggregate()['pending_request'])
        self.assertFalse(self.values(service.GRANTS))

    def test_pre_google_cancel_schedule_cannot_remove_live_google_access(self):
        free = self.plan()
        self.action('assign', kind='free', plan_id=free['uid'], plan_version_id=free['current_version_id'])
        self.action('schedule_cancel', effective_at=(NOW+timedelta(days=1)).isoformat())
        self.paid()
        with patch.object(service, '_now', return_value=NOW+timedelta(days=2)):
            result = self.aggregate()
            self.assertEqual(result['grant_kind'], 'google_play')
            self.assertEqual(result['status'], 'active')
            self.assertEqual(result['payment_state'], 'store_verified')
            self.assertIsNone(result['scheduled_change'])
            self.assertEqual(result['blocked_scheduled_change']['action'], 'cancel')
            self.assertEqual(result['blocked_scheduled_change']['blocked_reason'], 'STORE_MANAGED')
            audits = [row for row in self.values(storage.AUDIT_LOGS) if row['action'] == 'subscription_schedule_blocked_store_managed']
            self.assertEqual(len(audits), 1)
            self.assertEqual(audits[0]['actor_id'], 'admin')
            self.assertEqual(audits[0]['reason'], 'Reviewed access change')
            self.aggregate()
            self.assertEqual(len([row for row in self.values(storage.AUDIT_LOGS) if row['action'] == 'subscription_schedule_blocked_store_managed']), 1)

    def prepare_migration(self):
        result = self.call('/admin/subscriptions/rollout', {'action': 'prepare', 'revision': 0, 'reason': 'Reviewed fixture cutoff', 'cutoff_at': NOW.isoformat()})
        self.assertEqual(result.status_code, 200, result.json)

    def migration(self, action, vendor='vendor', **extra):
        return self.call('/admin/vendors/'+vendor+'/subscription/reconciliation',
                         {'action': action, 'reason': 'Reviewed historical cohort evidence', **extra})

    def finish_migration(self, job, vendor='vendor'):
        while job['status'] == 'scanning':
            result = self.migration('scan', vendor, job_id=job['uid'], revision=job['revision'], limit=1)
            self.assertEqual(result.status_code, 200, result.json)
            job = result.json
        result = self.migration('finish', vendor, job_id=job['uid'], revision=job['revision'])
        self.assertEqual(result.status_code, 200, result.json)
        return result.json

    def test_legacy_firestore_datetime_and_offset_iso_normalize_without_relaxing_api_dates(self):
        self.prepare_migration()
        for value in (NOW-timedelta(days=1), DatetimeWithNanoseconds(2026, 10, 19, 10, tzinfo=timezone.utc),
                      datetime(2026, 10, 19, 15, 30, tzinfo=timezone(timedelta(hours=5, minutes=30))), '2026-10-19T15:30:00+05:30'):
            self.store.data[(storage.USERS, 'vendor')]['created_at'] = value
            result = self.migration('dry_run', expected_account_revision=0)
            self.assertEqual(result.status_code, 200, result.json)
            self.assertEqual(result.json['cohort_date_status'], 'valid')
            self.assertEqual(result.json['cohort_created_at'], (NOW-timedelta(days=1)).isoformat())
            self.assertTrue(result.json['would_grant_legacy'])
        with self.assertRaises(service.SubscriptionError):
            service._date(NOW)

    def test_unknown_dates_require_explicit_audited_cohort_review(self):
        self.prepare_migration()
        for value in (None, '', 'invalid-date', True, {}, NOW.replace(tzinfo=None)):
            self.store.data[(storage.USERS, 'vendor')]['created_at'] = value
            preview = self.migration('dry_run', expected_account_revision=0)
            self.assertEqual(preview.status_code, 200, preview.json)
            self.assertTrue(preview.json['cohort_review_required'])
            self.assertFalse(preview.json['would_grant_legacy'])
            self.assertEqual(self.migration('start', expected_account_revision=0).json['code'], 'SUBSCRIPTION_COHORT_REVIEW_REQUIRED')
        job = self.migration('start', expected_account_revision=0, cohort_review='preexisting')
        self.assertEqual(job.status_code, 201, job.json)
        self.assertEqual(job.json['cohort_basis'], 'admin_reviewed_preexisting')
        self.assertEqual(job.json['cohort_reviewed_by'], 'admin')
        result = self.finish_migration(job.json)
        self.assertEqual(result['subscription']['status'], 'legacy_unrestricted')
        self.assertEqual(result['subscription']['payment_state'], 'not_attested')

    def test_reviewed_post_cutoff_cohort_enables_without_minting_legacy(self):
        self.prepare_migration()
        self.store.data[(storage.USERS, 'vendor')].pop('created_at')
        job = self.migration('start', expected_account_revision=0, cohort_review='post_cutoff')
        result = self.finish_migration(job.json)
        self.assertEqual(result['subscription']['status'], 'none')
        self.assertFalse(self.store.data[(service.ACCOUNTS, 'vendor')]['legacy_baseline_migrated'])
        self.assertTrue(self.store.data[(service.ACCOUNTS, 'vendor')]['legacy_cohort_reviewed'])
        self.finish_migration(self.migration('start', vendor='other', expected_account_revision=0).json, 'other')
        enabled = self.call('/admin/subscriptions/rollout', {'action': 'enable', 'revision': 1, 'reason': 'Reviewed coverage',
                                                          'security_rules_proof': 'SDK denial fixture', 'client_compatibility_proof': 'HTTP fixture'})
        self.assertEqual(enabled.status_code, 200, enabled.json)
        self.assertFalse([g for g in self.values(service.GRANTS) if g['vendor_id'] == 'vendor'])

    def test_canonical_preparing_activation_is_trusted_when_profile_date_is_missing(self):
        self.prepare_migration()
        with self.store.lock:
            tx = self.store.transaction()
            write = service.vendor_activation_plan(tx, 'vendor', 'admin')
            write()
            tx.commit()
        self.store.data[(storage.USERS, 'vendor')].pop('created_at')
        result = self.migration('dry_run', expected_account_revision=1)
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(result.json['cohort_date_status'], 'missing')
        self.assertEqual(result.json['cohort_basis'], 'canonical_pre_enforcement_activation')
        self.assertFalse(result.json['cohort_review_required'])
        self.assertFalse(result.json['would_grant_legacy'])
        self.assertEqual(self.aggregate()['payment_state'], 'not_attested')

    def test_unknown_date_review_cannot_mint_legacy_after_first_enforcement(self):
        self.prepare_migration()
        self.store.data[(storage.USERS, 'vendor')].pop('created_at')
        self.store.data[(service.SETTINGS, 'control')]['ever_enforced'] = True
        result = self.migration('start', expected_account_revision=0, cohort_review='preexisting')
        self.assertEqual(result.status_code, 409, result.json)
        self.assertEqual(result.json['code'], 'SUBSCRIPTION_COHORT_REVIEW_REQUIRED')
        self.assertFalse(self.values(service.GRANTS))

    def repeated_reviewed_cohort(self, classification):
        self.prepare_migration()
        self.store.data[(storage.USERS, 'vendor')].pop('created_at')
        job = self.migration('start', expected_account_revision=0, cohort_review=classification).json
        first = self.finish_migration(job)
        before = len(self.values(service.GRANTS))
        self.store.data[(service.SETTINGS, 'control')]['ever_enforced'] = True
        preview = self.migration('dry_run', expected_account_revision=first['subscription']['revision'])
        self.assertEqual(preview.status_code, 200, preview.json)
        self.assertFalse(preview.json['cohort_review_required'])
        self.assertFalse(preview.json['would_grant_legacy'])
        self.assertEqual(preview.json['cohort_basis'], 'admin_reviewed_'+classification)
        self.assertEqual(preview.json['cohort_review_reference'], job['uid'])
        repeated = self.migration('start', expected_account_revision=first['subscription']['revision'])
        self.assertEqual(repeated.status_code, 201, repeated.json)
        self.assertFalse(repeated.json['grant_baseline'])
        second = self.finish_migration(repeated.json)
        self.assertEqual(len(self.values(service.GRANTS)), before)
        self.assertEqual(second['subscription']['grant_kind'], 'legacy_unrestricted' if classification == 'preexisting' else None)
        account = self.store.data[(service.ACCOUNTS, 'vendor')]
        self.assertEqual(account['legacy_cohort_eligible'], classification == 'preexisting')
        self.assertEqual(account['legacy_cohort_manifest_id'], repeated.json['uid'])

    def test_reviewed_preexisting_cohort_can_reconcile_again_after_enforcement(self):
        self.repeated_reviewed_cohort('preexisting')

    def test_reviewed_post_cutoff_cohort_can_reconcile_again_after_enforcement(self):
        self.repeated_reviewed_cohort('post_cutoff')


if __name__ == '__main__':
    unittest.main()
