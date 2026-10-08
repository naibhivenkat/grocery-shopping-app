"""Read-only provider reconciliation; mocked captures never hit real Razorpay."""
import copy
import os
from unittest.mock import MagicMock,patch
import unittest
from flask import Flask
import auth_utils
import db as storage
import razorpay_config as config
import routes.razorpay_api as api
from test_payment_security import Store

class ReconcileTests(unittest.TestCase):
    def setUp(self):
        self.intent={'user_id':'owner','purpose':'order','amount_paise':10000,'currency':'INR',
            'status':'created','razorpay_order_id':'order_original','reference_id':'order','target_ids':['order']}
        self.store=Store({('payment_orders','intent'):self.intent,
            ('customer_orders','order'):{'customer_id':'owner','status':'pending','total_price':100},
            ('users','owner'):{'role':'customer'},('users','foreign'):{'role':'customer'}})
        self.provider=MagicMock();self.provider.order.payments.return_value={'items':[]}
        self.capture={'id':'pay_original','order_id':'order_original','amount':10000,'currency':'INR','captured':True,'status':'captured'}
        for p in (patch.object(api,'doc',self.store.doc),patch.object(api,'db',return_value=self.store),
            patch.object(api.firestore,'transactional',lambda fn:fn),patch.object(api,'get_razorpay_client',return_value=self.provider),
            patch.object(storage,'doc',self.store.doc),patch.object(auth_utils,'decode_token',lambda token:{'sub':token,'role':'admin'})):
            p.start();self.addCleanup(p.stop)
        self.app=Flask(__name__);self.app.register_blueprint(api.razorpay_api_bp);self.client=self.app.test_client()
    def post(self,body=None,user='owner',intent='intent'):
        headers={'Authorization':'Bearer '+user} if user else {}
        return self.client.post('/razorpayApi/intents/'+intent+'/reconcile',json={} if body is None else body,headers=headers)
    def tearDown(self):
        self.provider.order.create.assert_not_called()
        self.provider.payment.capture.assert_not_called()
        self.provider.payment.refund.assert_not_called()
    def test_owner_auth_and_deleted_account_guard_precede_provider(self):
        for user,status in ((None,401),('foreign',404),('deleted',401)):
            self.assertEqual(self.post(user=user).status_code,status)
        self.assertEqual(self.post(intent='missing').status_code,404)
        self.provider.order.payments.assert_not_called()
    def test_only_empty_json_object_accepted(self):
        for body in ({'payment_id':'pay_forged'},{'amount':1},['bad']):
            self.assertEqual(self.post(body).status_code,422)
        self.assertEqual(self.client.post('/razorpayApi/intents/intent/reconcile',headers={'Authorization':'Bearer owner'}).status_code,422)
        self.provider.order.payments.assert_not_called()
    def test_pending_authorization_does_not_settle(self):
        self.provider.order.payments.return_value={'items':[{**self.capture,'status':'authorized','captured':False}]}
        response=self.post()
        self.assertEqual(response.status_code,200);self.assertEqual(response.json['status'],'pending')
        self.assertFalse(response.json['success']);self.assertTrue(response.json['retryable'])
        self.assertEqual(self.store.data[('payment_orders','intent')]['status'],'created')
        self.provider.order.payments.assert_called_once_with('order_original',timeout=20)
    def test_capture_after_failed_attempt_settles_once_and_repeat_does_not_fetch(self):
        self.store.data[('payment_orders','intent')]['status']='failed'
        self.provider.order.payments.return_value={'items':[{**self.capture,'id':'pay_failed','status':'failed','captured':False},self.capture]}
        first=self.post();before=copy.deepcopy(self.store.data);second=self.post()
        self.assertEqual(first.status_code,200);self.assertEqual(first.json['status'],'paid')
        self.assertEqual(first.json['payment_id'],'pay_original');self.assertTrue(first.json['success'])
        self.assertEqual(second.json['status'],'paid');self.assertEqual(before,self.store.data)
        self.assertEqual(self.store.data[('customer_orders','order')]['payment_status'],'paid')
        self.provider.order.payments.assert_called_once()
    def test_existing_paid_skips_provider_even_if_configuration_missing(self):
        self.store.data[('payment_orders','intent')].update(status='paid',payment_id='pay_original',settlement_status='settled')
        with patch.object(api,'get_razorpay_client',side_effect=RuntimeError('configuration missing')) as client:
            self.assertEqual(self.post().json['status'],'paid');client.assert_not_called()
    def test_existing_paid_review_not_reported_as_success(self):
        self.store.data[('payment_orders','intent')].update(status='paid',settlement_status='requires_review')
        response=self.post();self.assertEqual(response.status_code,409)
        self.assertEqual(response.json['status'],'requires_review');self.assertFalse(response.json['success'])
        self.provider.order.payments.assert_not_called()
    def test_amount_currency_order_or_id_mismatch_never_settles(self):
        before=copy.deepcopy(self.store.data)
        for updates in ({'amount':1},{'amount':10000.0},{'currency':'USD'},{'order_id':'order_other'},
            {'id':'forged'},{'id':'pay_bad/id'},{'captured':False}):
            self.provider.order.payments.return_value={'items':[{**self.capture,**updates}]}
            response=self.post();self.assertEqual(response.status_code,409)
            self.assertEqual(response.json['status'],'requires_review');self.assertEqual(before,self.store.data)
    def test_duplicate_same_capture_deduplicates_but_distinct_captures_require_review(self):
        self.provider.order.payments.return_value={'items':[self.capture,{**self.capture,'id':'pay_second'}]}
        self.assertEqual(self.post().status_code,409)
        self.assertEqual(self.store.data[('payment_orders','intent')]['status'],'created')
        self.provider.order.payments.return_value={'items':[self.capture,copy.deepcopy(self.capture)]}
        self.assertEqual(self.post().json['status'],'paid')
    def test_failed_attempts_are_failed_but_do_not_permanently_prevent_late_capture(self):
        self.provider.order.payments.return_value={'items':[{**self.capture,'status':'failed','captured':False}]}
        response=self.post();self.assertEqual(response.json['status'],'failed');self.assertTrue(response.json['retryable'])
        self.assertEqual(self.store.data[('payment_orders','intent')]['status'],'created')
        self.provider.order.payments.return_value={'items':[self.capture]}
        self.assertEqual(self.post().json['status'],'paid')
    def test_missing_config_and_provider_timeout_return_retryable_503_without_writes(self):
        before=copy.deepcopy(self.store.data)
        with patch.object(api,'get_razorpay_client',side_effect=RuntimeError('configuration missing')):
            response=self.post();self.assertEqual(response.status_code,503);self.assertTrue(response.json['retryable'])
        self.provider.order.payments.side_effect=TimeoutError('timeout')
        self.assertEqual(self.post().status_code,503);self.assertEqual(before,self.store.data)
    def test_provider_malformed_collection_safe_503(self):
        for response in ({'items':'bad'},{'items':[None]},None):
            self.provider.order.payments.return_value=response
            self.assertEqual(self.post().status_code,503)
    def test_cancelled_target_capture_retained_for_review_not_fulfilled(self):
        self.store.data[('customer_orders','order')]['status']='cancelled'
        self.provider.order.payments.return_value={'items':[self.capture]}
        response=self.post();self.assertEqual(response.status_code,409);self.assertEqual(response.json['status'],'requires_review')
        self.assertEqual(self.store.data[('payment_orders','intent')]['status'],'paid')
        self.assertEqual(self.store.data[('customer_orders','order')]['status'],'cancelled')
    def test_creation_not_ready_returns_pending_without_provider(self):
        self.store.data[('payment_orders','intent')].update(status='initializing',razorpay_order_id=None)
        self.assertEqual(self.post().json['status'],'pending');self.provider.order.payments.assert_not_called()
    def test_settlement_database_failure_returns_retryable_503(self):
        self.provider.order.payments.return_value={'items':[self.capture]}
        with patch.object(api,'settle_payment_order',side_effect=RuntimeError('unavailable')):
            response=self.post();self.assertEqual(response.status_code,503);self.assertTrue(response.json['retryable'])

class BoundedSessionTests(unittest.TestCase):
    def test_default_and_explicit_timeout_preserve_request_options_without_retries(self):
        session=config.BoundedRazorpaySession()
        with patch('requests.Session.request',return_value='response') as request:
            session.request('POST','https://api.razorpay.com/test',auth=('test','test'),verify='ca-bundle')
            self.assertEqual(request.call_args.kwargs['timeout'],(5,20))
            self.assertEqual(request.call_args.kwargs['verify'],'ca-bundle')
            session.request('GET','https://api.razorpay.com/test',timeout=(2,3))
            self.assertEqual(request.call_args.kwargs['timeout'],(2,3))
            session.request('GET','https://api.razorpay.com/test',timeout=None)
            self.assertEqual(request.call_args.kwargs['timeout'],(5,20))
        self.assertEqual(session.get_adapter('https://').max_retries.total,0)
        session.close()
    def test_sdk_uses_bounded_session_and_keeps_auth_and_certificate(self):
        config.get_razorpay_client.cache_clear()
        with patch.dict(os.environ,{'RAZORPAY_KEY_ID':'test_key','RAZORPAY_KEY_SECRET':'test_secret'}):
            client=config.get_razorpay_client()
            self.assertIsInstance(client.session,config.BoundedRazorpaySession)
            response=MagicMock(status_code=200);response.json.return_value={'items':[]}
            with patch('requests.Session.request',return_value=response) as request:
                client.order.payments('order_original')
                self.assertEqual(request.call_args.kwargs['timeout'],(5,20))
                self.assertEqual(request.call_args.kwargs['auth'],('test_key','test_secret'))
                self.assertEqual(request.call_args.kwargs['verify'],client.cert_path)
            client.session.close()
        config.get_razorpay_client.cache_clear()

if __name__=='__main__':unittest.main()
