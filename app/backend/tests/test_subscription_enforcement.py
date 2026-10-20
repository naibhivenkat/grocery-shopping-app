"""Quota/migration HTTP journeys with strict transaction doubles; no provider proof."""
import copy
import io
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import unittest
from unittest.mock import patch
import db as storage
import subscription_service as service
import test_subscription_lifecycle as fixture
from routes import vendors, admin, product_import, promotions, shop_applications, auth

NOW = fixture.NOW


class EnforcementTests(unittest.TestCase):
    call = fixture.LifecycleTests.call
    plan = fixture.LifecycleTests.plan
    aggregate = fixture.LifecycleTests.aggregate
    request_plan = fixture.LifecycleTests.request_plan
    decide = fixture.LifecycleTests.decide
    action = fixture.LifecycleTests.action
    values = fixture.LifecycleTests.values

    def setUp(self):
        fixture.LifecycleTests.setUp(self)
        for module in (vendors, admin, product_import, promotions, shop_applications, auth):
            self.app.register_blueprint(getattr(module, module.__name__.split('.')[-1] + '_bp'))
            for name, value in (('doc', self.store.doc), ('col', self.store.col), ('db', lambda: self.store)):
                current = patch.object(module, name, value); current.start(); self.addCleanup(current.stop)
        for current in (patch.object(admin, 'log_admin_action'), patch.object(promotions, 'deliver_push'),
                        patch.object(auth.firestore, 'transactional', self.store.transactional)):
            current.start(); self.addCleanup(current.stop)
        self.store.data[(storage.USERS, 'admin')]['role'] = 'super_admin'
        self.store.data[(storage.USERS, 'vendor')]['city_id'] = 'city'
        self.store.data[(storage.CITIES, 'city')] = {'is_active': True}

    def prepare(self):
        response = self.call('/admin/subscriptions/rollout', {'action': 'prepare', 'revision': 0,
            'reason': 'Reviewed cutover inventory', 'cutoff_at': NOW.isoformat()})
        self.assertEqual(response.status_code, 200, response.json)
        return response.json

    def reconcile(self, vendor='vendor', limit=1):
        path = '/admin/vendors/' + vendor + '/subscription/reconciliation'
        current = service.entitlements(vendor)
        started = self.call(path, {'action':'start', 'reason':'Count all retained definitions',
                                  'expected_account_revision':current['revision']})
        self.assertEqual(started.status_code, 201, started.json)
        job = started.json
        while job['status'] == 'scanning':
            result = self.call(path, {'action':'scan', 'reason':'Continue fenced count', 'job_id':job['uid'],
                                      'revision':job['revision'], 'limit':limit})
            self.assertEqual(result.status_code, 200, result.json)
            job = result.json
        finished = self.call(path, {'action':'finish', 'reason':'Complete reviewed count', 'job_id':job['uid'], 'revision':job['revision']})
        self.assertEqual(finished.status_code, 200, finished.json)
        return finished.json

    def enable(self):
        control = self.store.data[(service.SETTINGS, 'control')]
        return self.call('/admin/subscriptions/rollout', {'action':'enable', 'revision':control['revision'],
            'reason':'Reviewed migration coverage', 'security_rules_proof':'SDK denial suite', 'client_compatibility_proof':'HTTP catalog journeys'})

    def initialize(self, maximum=2):
        self.prepare()
        self.reconcile()
        self.reconcile('other')
        self.assertEqual(self.enable().status_code, 200)
        plan = self.plan(maximum=maximum)
        granted = self.action('assign', kind='free', plan_id=plan['uid'], plan_version_id=plan['current_version_id'])
        self.assertEqual(granted.status_code, 200, granted.json)
        return plan

    def item(self, name='Rice', user='vendor'):
        return self.call('/vendors/items', {'name':name,'price':60,'stock_quantity':0}, user=user)

    def upload(self, data):
        return self.client.post('/vendors/items/import', data={'file':(io.BytesIO(data), 'products.csv')}, headers={'Authorization':'Bearer vendor'})

    def test_explicit_migration_preserves_legacy_not_paid_and_counts_unavailable(self):
        self.store.data[(storage.SHOP_ITEMS,'a')] = {'vendor_id':'vendor', 'stock_quantity':0,'is_available':False}
        self.store.data[(storage.SHOP_ITEMS,'b')] = {'vendor_id':'vendor', 'stock_quantity':3}
        legacy = {'vendor_id':'vendor','status':'active','payment_status':'paid','plan_id':'forged'}
        self.store.data[('vendor_subscriptions','legacy')] = copy.deepcopy(legacy)
        self.prepare()
        before = copy.deepcopy(self.store.data)
        dry = self.call('/admin/vendors/vendor/subscription/reconciliation', {'action':'dry_run','reason':'Preview', 'expected_account_revision':0})
        self.assertTrue(dry.json['would_grant_legacy'])
        self.assertEqual(dry.json['observed_product_count'],2)
        self.assertTrue(dry.json['product_count_is_complete'])
        self.assertEqual(self.store.data, before)
        self.assertEqual(self.enable().json['code'], 'SUBSCRIPTION_MIGRATION_REQUIRED')
        result = self.reconcile()
        self.assertEqual(result['subscription']['status'], 'legacy_unrestricted')
        self.assertEqual(result['subscription']['usage']['product_count'],2)
        self.assertEqual(result['subscription']['payment_state'], 'not_attested')
        self.assertEqual(self.store.data[('vendor_subscriptions','legacy')], legacy)
        self.reconcile()
        self.assertEqual(len(self.values(service.GRANTS)),1)
        self.assertTrue(any(row['action']=='subscription_reconciliation_scan' and row['reason'] for row in self.values(storage.AUDIT_LOGS)))
        detail = self.call('/admin/vendors/vendor/subscription?history_limit=100',method='GET').json
        seen = []
        while True:
            seen += detail['history']['items']
            cursor = detail['history']['next_cursor']
            if not cursor: break
            detail = self.call('/admin/vendors/vendor/subscription?history_limit=100&history_cursor='+cursor, method='GET').json
        self.assertTrue(any(row.get('record_type')=='legacy_subscriptions' and row['uid']=='legacy' for row in seen))

    def test_migration_fence_blocks_growth_delete_but_keeps_stock_and_admin_grant(self):
        self.store.data[(storage.SHOP_ITEMS,'old')] = {'vendor_id':'vendor','name':'Old','stock_quantity':0,'price':2}
        self.prepare()
        path='/admin/vendors/vendor/subscription/reconciliation'
        job=self.call(path,{'action':'start','reason':'Fence count','expected_account_revision':0}).json
        detail=service.account_detail('vendor')
        self.assertEqual(detail['reconciliation_job']['uid'],job['uid'])
        self.assertEqual(detail['reconciliation_job']['revision'],job['revision'])
        self.assertEqual(self.item().json['code'],'SUBSCRIPTION_MIGRATION_REQUIRED')
        self.assertEqual(self.call('/vendors/items/old',method='DELETE',user='vendor').status_code,409)
        self.assertEqual(self.call('/vendors/items/old',{'stock_quantity':4},method='PUT',user='vendor').status_code,200)
        plan=self.plan()
        self.assertEqual(self.action('assign',kind='free',plan_id=plan['uid'],plan_version_id=plan['current_version_id']).status_code,200)
        scanned=self.call(path,{'action':'scan','reason':'Count','job_id':job['uid'],'revision':job['revision']}).json
        done=self.call(path,{'action':'finish','reason':'Finish','job_id':job['uid'],'revision':scanned['revision']})
        self.assertEqual(done.json['subscription']['grant_kind'],'free')
        self.assertEqual(done.json['subscription']['usage']['product_count'],1)
        self.assertEqual(len(self.values(service.GRANTS)),1)

    def test_quota_vendor_admin_import_atomic_replay_and_actual_deletion(self):
        self.initialize(maximum=3)
        self.assertEqual(self.item().status_code,201)
        created=self.call('/admin/products',{'vendor_id':'vendor','name':'Admin item','price':5,'stock_quantity':0})
        self.assertEqual(created.status_code,200,created.json)
        self.assertEqual(self.aggregate()['usage']['product_count'],2)
        too_many=b'name,price,stock_quantity\nA,1,0\nB,2,0\n'
        before=copy.deepcopy(self.store.data)
        self.assertEqual(self.upload(too_many).json['code'],'PRODUCT_LIMIT_REACHED')
        self.assertEqual(self.store.data,before)
        one=b'name,price,stock_quantity\nImport,1,0\n'
        imported=self.upload(one)
        self.assertEqual(imported.status_code,201,imported.json)
        self.assertEqual(self.upload(one).json,imported.json)
        self.assertEqual(self.aggregate()['usage']['product_count'],3)
        self.assertEqual(self.item('Excess').json['code'],'PRODUCT_LIMIT_REACHED')
        self.assertEqual(self.call('/admin/products',{'vendor_id':'vendor','name':'Excess','price':1,'stock_quantity':0}).json['code'],'PRODUCT_LIMIT_REACHED')
        self.assertEqual(self.call('/admin/products/'+created.json['uid'],method='DELETE').status_code,200)
        self.assertEqual(self.aggregate()['usage']['product_count'],2)
        self.assertEqual(self.call('/admin/products/'+created.json['uid'],method='DELETE').status_code,404)
        self.assertEqual(self.aggregate()['usage']['product_count'],2)
        self.assertEqual(self.item('Replacement').status_code,201)

    def test_import_capability_never_bypasses_catalog_growth_restriction(self):
        self.initialize()
        plan=self.plan(entitlements={'max_items':10,'catalog_growth':False,'product_import':True,'promotions':True})
        self.assertEqual(self.action('assign',kind='free',plan_id=plan['uid'],plan_version_id=plan['current_version_id']).status_code,200)
        self.assertFalse(self.aggregate()['capabilities']['product_import'])
        self.assertEqual(self.item().json['code'],'SUBSCRIPTION_REQUIRED')
        self.assertEqual(self.upload(b'name,price,stock_quantity\nImport,1,0\n').json['code'],'SUBSCRIPTION_REQUIRED')
        self.assertEqual(self.aggregate()['usage']['product_count'],0)

    def test_concurrent_last_slot_serializes_and_commit_failure_rolls_back(self):
        self.initialize(maximum=1)
        with ThreadPoolExecutor(max_workers=2) as executor:
            statuses=list(executor.map(lambda name:self.item(name).status_code,['A','B']))
        self.assertEqual(sorted(statuses),[201,409])
        self.assertEqual(self.aggregate()['usage']['product_count'],1)
        product=next(identifier for (collection,identifier) in self.store.data if collection==storage.SHOP_ITEMS)
        self.assertEqual(self.call('/vendors/items/'+product,method='DELETE',user='vendor').status_code,200)
        before=copy.deepcopy(self.store.data)
        self.store.fail_commit=True
        with self.assertRaises(RuntimeError): self.item('Rollback')
        self.assertEqual(self.store.data,before)
        self.store.fail_commit=False
        self.assertEqual(self.aggregate()['usage']['product_count'],0)

    def test_restricted_catalog_keeps_edit_delete_orders_khata_and_promotion_pause(self):
        self.initialize()
        product=self.item().json
        content={'target_type':'shop','title':'Fresh','body':'Shop offer','image_url':'https://example.com/a.png',
                 'starts_at':(NOW-timedelta(days=1)).isoformat(),'ends_at':(NOW+timedelta(days=7)).isoformat()}
        campaign=self.call('/promotions',content,user='vendor')
        self.assertEqual(campaign.status_code,201,campaign.json)
        self.action('suspend')
        self.assertEqual(self.item('Blocked').json['code'],'SUBSCRIPTION_REQUIRED')
        self.assertEqual(self.upload(b'name,price,stock_quantity\nNew,1,0\n').json['code'],'SUBSCRIPTION_REQUIRED')
        self.assertEqual(self.call('/promotions',content,user='vendor').json['code'],'SUBSCRIPTION_REQUIRED')
        self.assertEqual(self.call('/promotions/'+campaign.json['uid'],{'title':'Edited'},method='PUT',user='vendor').json['code'],'SUBSCRIPTION_REQUIRED')
        self.assertEqual(self.call('/promotions/'+campaign.json['uid']+'/pause',{'is_paused':True},method='PATCH',user='vendor').status_code,200)
        self.assertEqual(self.call('/promotions/'+campaign.json['uid']+'/pause',{'is_paused':False},method='PATCH',user='vendor').json['code'],'SUBSCRIPTION_REQUIRED')
        self.assertEqual(self.call('/vendors/items/'+product['uid'],{'stock_quantity':3},method='PUT',user='vendor').status_code,200)
        self.assertEqual(self.call('/vendors/orders',method='GET',user='vendor').status_code,200)
        self.assertEqual(self.call('/vendors/items/'+product['uid'],method='DELETE',user='vendor').status_code,200)
        self.assertEqual(self.aggregate()['usage']['product_count'],0)

    def test_activation_before_and_after_cutover_and_pause_never_mints_new_legacy(self):
        self.prepare()
        with self.store.lock:
            tx=self.store.transaction()
            writer=service.vendor_activation_plan(tx,'new_before','admin')
            tx.create(self.store.doc(storage.USERS,'new_before'),{'role':'vendor'})
            writer(); tx.commit()
        self.assertEqual(service.entitlements('new_before')['status'],'legacy_unrestricted')
        self.reconcile();self.reconcile('other')
        self.assertEqual(self.enable().status_code,200)
        with self.store.lock:
            tx=self.store.transaction()
            writer=service.vendor_activation_plan(tx,'new_after','admin')
            tx.create(self.store.doc(storage.USERS,'new_after'),{'role':'vendor'})
            writer();tx.commit()
        self.assertEqual(service.entitlements('new_after')['status'],'none')
        self.assertTrue(service.entitlements('new_after')['usage']['initialized'])
        self.assertEqual(self.item(user='new_after').json['code'],'SUBSCRIPTION_REQUIRED')
        control=self.store.data[(service.SETTINGS,'control')]
        self.assertEqual(self.call('/admin/subscriptions/rollout',{'action':'pause','revision':control['revision'],'reason':'Pause enforcement safely'}).status_code,200)
        self.assertEqual(self.item(user='new_after').status_code,201)
        self.assertEqual(service.entitlements('new_after')['usage']['product_count'],1)

    def test_new_vendor_hooks_and_safe_unversioned_admin_catalog(self):
        self.prepare()
        self.store.data[(service.PLANS,'old_flat')]={'name':'Historical','price':999}
        canonical=self.plan()
        listed=self.call('/admin/subscription-plans',method='GET')
        self.assertEqual(listed.status_code,200)
        self.assertEqual([row['uid'] for row in listed.json['items']],[canonical['uid']])
        self.assertEqual(listed.json['legacy_records_on_page'],1)
        self.store.data[(storage.USERS,'customer')].update(full_name='New owner',created_at=NOW.isoformat())
        changed=self.call('/admin/users/customer',{'role':'vendor'},method='PUT')
        self.assertEqual(changed.status_code,200,changed.json)
        self.assertEqual(service.entitlements('customer')['status'],'legacy_unrestricted')
        created=auth._create_account_atomic({'role':'vendor','email':'new@example.test','username':'newone'})
        self.assertEqual(service.entitlements(created['uid'])['status'],'legacy_unrestricted')
        self.store.data[(storage.USERS,'applicant')]={'role':'customer'}
        self.store.data[('shop_applications','applicant')]={'applicant_id':'applicant','status':'pending','revision':1,
            'shop_name':'Applied Shop','address':'Market Road','phone':'123','city_id':'city'}
        approved=self.call('/admin/shop-applications/applicant/decision',{'decision':'approved','revision':1,'reason':'Reviewed shop'})
        self.assertEqual(approved.status_code,200,approved.json)
        self.assertEqual(service.entitlements('applicant')['status'],'legacy_unrestricted')

    def test_comp_override_restores_latest_store_state_and_unlinked_token_is_rejected(self):
        plan=self.plan(price=9900,renewal_rule='store',google_play={'product_id':'basic','base_plan_id':'monthly'})
        request=self.request_plan(plan);self.decide(request.json)
        args=dict(provider_state='active',plan_version_id=plan['current_version_id'],starts_at=NOW.isoformat(),ends_at=(NOW+timedelta(days=30)).isoformat(),source_revision=1)
        service.apply_verified_store_state('vendor',event_id='store-first',purchase_fingerprint='token_a',request_id=request.json['uid'],**args)
        self.assertEqual(self.action('suspend').json['status'],'suspended')
        self.assertIn('reactivate',service.account_detail('vendor')['admin_available_actions'])
        self.assertEqual(self.action('reactivate').json['status'],'active')
        self.assertEqual(self.aggregate()['store_state'],'active')
        service.apply_verified_store_state('vendor',event_id='store-grace',purchase_fingerprint='token_a',**{**args,'provider_state':'grace','source_revision':2})
        self.assertEqual(self.aggregate()['status'],'grace')
        self.assertTrue(self.aggregate()['capabilities']['catalog_growth'])
        service.apply_verified_store_state('vendor',event_id='store-hold',purchase_fingerprint='token_a',**{**args,'provider_state':'hold','source_revision':3})
        self.action('suspend')
        self.assertEqual(self.action('reactivate').json['status'],'suspended')
        self.assertEqual(self.aggregate()['access_state'],'active')
        service.apply_verified_store_state('vendor',event_id='store-recover',purchase_fingerprint='token_a',**{**args,'provider_state':'active','source_revision':4})
        second=self.request_plan(plan);self.decide(second.json)
        with self.assertRaises(service.SubscriptionError) as caught:
            service.apply_verified_store_state('vendor',event_id='unlinked',purchase_fingerprint='token_b',request_id=second.json['uid'],**args)
        self.assertEqual(caught.exception.code,'STORE_REPLACEMENT_REQUIRED')
        override=self.action('assign',kind='complimentary',plan_id=plan['uid'],plan_version_id=plan['current_version_id'],ends_at=(NOW+timedelta(days=1)).isoformat())
        self.assertEqual(override.status_code,200)
        self.assertEqual(self.aggregate()['store_state'],'active')
        with patch.object(service,'_now',return_value=NOW+timedelta(days=5)):
            aggregate=self.aggregate()
            self.assertEqual(aggregate['grant_kind'],'google_play')
            self.assertEqual(aggregate['payment_state'],'store_verified')
            audits=len(self.values(storage.AUDIT_LOGS))
            self.aggregate()
            self.assertEqual(len(self.values(storage.AUDIT_LOGS)),audits)
        self.assertEqual(self.action('assign',kind='complimentary',plan_id=plan['uid'],plan_version_id=plan['current_version_id'],ends_at=(NOW+timedelta(days=1)).isoformat()).status_code,200)
        self.assertEqual(self.action('schedule_cancel',effective_at=(NOW+timedelta(hours=12)).isoformat()).status_code,200)
        with patch.object(service,'_now',return_value=NOW+timedelta(hours=18)):
            self.assertEqual(self.aggregate()['grant_kind'],'google_play')
            self.assertEqual(self.aggregate()['store_state'],'active')


if __name__=='__main__': unittest.main()
