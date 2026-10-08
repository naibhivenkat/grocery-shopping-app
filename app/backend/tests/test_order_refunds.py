"""Strict mock refunds: no live payments or refunds; durable retry and stock once."""
import copy
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from unittest.mock import MagicMock,patch
import unittest
from flask import Flask
from test_orders_api import OrderStore
from concurrent.futures import ThreadPoolExecutor
import threading
import auth_utils
import routes.order_refunds as refunds

class OrderRefundTests(unittest.TestCase):
    def setUp(self):
        self.store=OrderStore()
        self.store.data={('customer_orders','a'):{'vendor_id':'vendor','customer_id':'customer','item_id':'item',
            'quantity':2,'total_paise':10000,'total_price':100,'status':'pending','payment_status':'paid',
            'payment_method':'razorpay','payment_intent_id':'intent','razorpay_payment_id':'pay_original'},
            ('customer_orders','b'):{'vendor_id':'vendor','customer_id':'customer','item_id':'item2','quantity':1,
            'total_paise':15000,'status':'pending','payment_status':'paid','payment_method':'razorpay','payment_intent_id':'intent'},
            ('payment_orders','intent'):{'status':'paid','purpose':'order','user_id':'customer','currency':'INR',
                'amount_paise':25000,'target_ids':['a','b'],'payment_id':'pay_original','razorpay_order_id':'order_original'},
            ('shop_items','item'):{'stock_quantity':8},('shop_items','item2'):{'stock_quantity':4}}
        self.provider=MagicMock()
        self.provider.payment.fetch.return_value={'id':'pay_original','order_id':'order_original',
            'amount':25000,'currency':'INR','captured':True,'status':'captured'}
        self.provider.payment.refund.side_effect=lambda pid,body,**kw:self.entity(amount=body['amount'])
        for p in (patch.object(refunds,'doc',self.store.doc),patch.object(refunds,'db',return_value=self.store),
            patch.object(refunds.firestore,'transactional',self.store.transactional),patch.object(refunds,'get_razorpay_client',return_value=self.provider)):
            p.start();self.addCleanup(p.stop)
    def entity(self,status='pending',amount=10000):
        return {'id':'rfnd_original','payment_id':'pay_original','amount':amount,'currency':'INR','status':status}
    def test_pending_refund_is_submitted_cancels_and_restores_stock_once(self):
        result=refunds.refund_order('a','vendor')
        self.assertEqual(result['status'],'submitted')
        order=self.store.data[('customer_orders','a')]
        self.assertEqual(order['status'],'cancelled');self.assertEqual(order['payment_status'],'refund_pending')
        self.assertEqual(self.store.data[('shop_items','item')]['stock_quantity'],10)
        self.assertEqual(self.store.data[('customer_orders','b')]['status'],'pending')
        self.provider.refund.fetch.return_value=self.entity('pending')
        self.assertEqual(refunds.refund_order('a','vendor')['status'],'submitted')
        self.assertEqual(self.store.data[('shop_items','item')]['stock_quantity'],10)
        self.provider.payment.refund.assert_called_once()
    def test_processed_refund_reconciles_existing_id_and_completed_replay_is_noop(self):
        refunds.refund_order('a','vendor')
        self.provider.refund.fetch.return_value=self.entity('processed')
        self.assertEqual(refunds.refund_order('a','vendor')['status'],'completed')
        self.assertEqual(self.store.data[('customer_orders','a')]['payment_status'],'refunded')
        before=copy.deepcopy(self.store.data)
        self.assertEqual(refunds.refund_order('a','vendor')['status'],'completed')
        self.assertEqual(before,self.store.data)
        self.assertEqual(self.store.data[('shop_items','item')]['stock_quantity'],10)
    def test_ambiguous_timeout_retries_exact_persisted_body_and_key_without_stock_changes(self):
        self.provider.payment.refund.side_effect=TimeoutError('lost response')
        self.assertEqual(refunds.refund_order('a','vendor')['status'],'retryable')
        first=self.provider.payment.refund.call_args
        self.assertEqual(self.store.data[('customer_orders','a')]['status'],'pending')
        self.assertEqual(self.store.data[('shop_items','item')]['stock_quantity'],8)
        self.provider.payment.refund.side_effect=lambda pid,body,**kw:self.entity('processed')
        self.assertEqual(refunds.refund_order('a','vendor')['status'],'completed')
        self.assertEqual(first,self.provider.payment.refund.call_args)
        self.assertEqual(self.store.data[('payment_refund_quotas','pay_original')]['reserved_paise'],10000)
    def test_same_capture_line_allocations_sum_to_original_capture(self):
        self.provider.payment.refund.side_effect=lambda pid,body,**kw:self.entity('processed',body['amount'])
        self.assertEqual(refunds.refund_order('a','vendor')['status'],'completed')
        self.assertEqual(refunds.refund_order('b','vendor')['status'],'completed')
        self.assertEqual(self.store.data[('payment_refund_quotas','pay_original')]['reserved_paise'],25000)
        self.assertEqual([call.args[1]['amount'] for call in self.provider.payment.refund.call_args_list],[10000,15000])
    def test_foreign_vendor_unauthenticated_and_client_values_never_influence_refund(self):
        with self.assertRaises(PermissionError):refunds.refund_order('a','attacker')
        self.provider.payment.refund.assert_not_called()
        app=Flask(__name__);app.register_blueprint(refunds.order_refunds_bp)
        self.assertEqual(app.test_client().post('/vendors/orders/a/refund',json={}).status_code,401)
        with patch('db.doc',return_value=SimpleNamespace(get=lambda:SimpleNamespace(id='vendor',exists=True,to_dict=lambda:{'role':'vendor'}))):
            response=app.test_client().post('/vendors/orders/a/refund',json={'amount':1,'payment_id':'pay_attacker'},
                headers={'Authorization':'Bearer '+auth_utils.create_token('vendor','vendor')})
            self.assertEqual(response.status_code,422)
        self.provider.payment.refund.assert_not_called()
    def test_paid_completed_order_and_foreign_capture_are_rejected_without_provider(self):
        self.store.data[('customer_orders','a')]['status']='completed'
        with self.assertRaises(ValueError):refunds.refund_order('a','vendor')
        self.store.data[('customer_orders','a')]['status']='pending'
        self.store.data[('payment_orders','intent')]['user_id']='attacker'
        with self.assertRaises(ValueError):refunds.refund_order('a','vendor')
        self.provider.payment.refund.assert_not_called()
    def test_capture_quota_blocks_overallocation_before_provider(self):
        self.store.data[('payment_refund_quotas','pay_original')]={'payment_intent_id':'intent','captured_paise':25000,'reserved_paise':20000}
        with self.assertRaises(ValueError):refunds.refund_order('a','vendor')
        self.provider.payment.refund.assert_not_called()
    def test_processing_lease_blocks_concurrent_worker(self):
        self.provider.payment.refund.side_effect=TimeoutError('unknown')
        refunds.refund_order('a','vendor')
        self.store.data[('order_refunds','a')].update(status='processing',started_at=datetime.now(timezone.utc).isoformat())
        self.provider.reset_mock()
        self.assertEqual(refunds.refund_order('a','vendor')['status'],'processing')
        self.provider.payment.refund.assert_not_called()
    def test_expired_lease_retries_same_key(self):
        self.provider.payment.refund.side_effect=TimeoutError('unknown')
        refunds.refund_order('a','vendor');original=copy.deepcopy(self.store.data[('order_refunds','a')]['request'])
        self.store.data[('order_refunds','a')].update(status='processing',started_at=(datetime.now(timezone.utc)-timedelta(minutes=10)).isoformat())
        self.provider.payment.refund.side_effect=lambda pid,body,**kw:self.entity('processed')
        self.assertEqual(refunds.refund_order('a','vendor')['status'],'completed')
        self.assertEqual(self.store.data[('order_refunds','a')]['request'],original)
    def test_cancelled_capture_requiring_review_refunds_without_restoring_stock_twice(self):
        self.store.data[('customer_orders','a')].update(status='cancelled',payment_status='pending')
        self.store.data[('shop_items','item')]['stock_quantity']=10
        self.store.data[('payment_orders','intent')]['settlement_status']='requires_review'
        self.provider.payment.refund.side_effect=lambda pid,body,**kw:self.entity('processed')
        self.assertEqual(refunds.refund_order('a','vendor')['status'],'completed')
        self.assertEqual(self.store.data[('shop_items','item')]['stock_quantity'],10)
    def test_provider_capture_or_refund_mismatch_requires_review_without_stock_mutation(self):
        self.provider.payment.fetch.return_value['amount']=1
        self.assertEqual(refunds.refund_order('a','vendor')['status'],'requires_review')
        self.provider.payment.refund.assert_not_called()
        self.assertEqual(self.store.data[('shop_items','item')]['stock_quantity'],8)
    def test_provider_failed_refund_never_claims_completed_or_cancels(self):
        self.provider.payment.refund.side_effect=lambda pid,body,**kw:self.entity('failed')
        self.assertEqual(refunds.refund_order('a','vendor')['status'],'requires_review')
        self.assertEqual(self.store.data[('customer_orders','a')]['status'],'pending')
        self.assertEqual(self.store.data[('shop_items','item')]['stock_quantity'],8)
    def test_concurrent_workers_submit_one_provider_refund(self):
        entered=threading.Event(); release=threading.Event()
        def provider(pid,body,**kwargs):
            entered.set()
            release.wait(timeout=5)
            return self.entity('processed')
        self.provider.payment.refund.side_effect=provider
        with ThreadPoolExecutor(max_workers=2) as pool:
            first=pool.submit(refunds.refund_order,'a','vendor')
            self.assertTrue(entered.wait(timeout=2))
            second=pool.submit(refunds.refund_order,'a','vendor')
            self.assertEqual(second.result(timeout=2)['status'],'processing')
            release.set()
            self.assertEqual(first.result(timeout=2)['status'],'completed')
        self.provider.payment.refund.assert_called_once()
        self.assertEqual(self.store.data[('shop_items','item')]['stock_quantity'],10)
    def test_finalize_commit_failure_preserves_request_for_same_key_retry(self):
        def accepted(pid,body,**kwargs):
            self.store.fail_commit=True
            return self.entity('processed')
        self.provider.payment.refund.side_effect=accepted
        with self.assertRaises(RuntimeError):refunds.refund_order('a','vendor')
        original=self.provider.payment.refund.call_args
        self.assertEqual(self.store.data[('customer_orders','a')]['status'],'pending')
        self.assertEqual(self.store.data[('shop_items','item')]['stock_quantity'],8)
        self.store.fail_commit=False
        self.store.data[('order_refunds','a')]['started_at']=(datetime.now(timezone.utc)-timedelta(minutes=10)).isoformat()
        self.provider.payment.refund.side_effect=lambda pid,body,**kwargs:self.entity('processed')
        self.assertEqual(refunds.refund_order('a','vendor')['status'],'completed')
        self.assertEqual(original,self.provider.payment.refund.call_args)
        self.assertEqual(self.store.data[('shop_items','item')]['stock_quantity'],10)

    def test_stored_admin_authorization_required_and_admin_can_refund_foreign_vendor_order(self):
        self.store.data[('users','admin')]={'role':'admin'}
        self.assertEqual(refunds.refund_order('a','admin',allow_admin=True)['status'],'submitted')
        self.store.data[('users','other')]={'role':'customer'}
        with self.assertRaises(PermissionError):refunds.refund_order('b','other',allow_admin=True)
        with self.assertRaises(PermissionError):refunds.refund_order('b','deleted',allow_admin=True)
        self.store.data[('users','suspended')]={'role':'super_admin','is_suspended':True}
        with self.assertRaises(PermissionError):refunds.refund_order('b','suspended',allow_admin=True)
    def test_invalid_inventory_before_refund_prevents_provider_call(self):
        self.store.data[('shop_items','item')]['stock_quantity']=1.5
        with self.assertRaises(ValueError):refunds.refund_order('a','vendor')
        self.provider.payment.refund.assert_not_called()
    def test_progressed_fulfillment_during_provider_call_records_refund_without_false_restock(self):
        def accepted(pid,body,**kwargs):
            self.store.data[('customer_orders','a')]['status']='completed'
            return self.entity('processed')
        self.provider.payment.refund.side_effect=accepted
        result=refunds.refund_order('a','vendor')
        self.assertEqual(result['status'],'completed')
        self.assertIn('reconciliation_required',result)
        self.assertEqual(self.store.data[('customer_orders','a')]['status'],'completed')
        self.assertEqual(self.store.data[('customer_orders','a')]['payment_status'],'refunded')
        self.assertEqual(self.store.data[('shop_items','item')]['stock_quantity'],8)

    def test_refund_restocks_without_enabling_admin_disabled_item(self):
        self.store.data[('shop_items','item')].update(disabled_by_admin=True,is_available=False)
        self.provider.payment.refund.side_effect=lambda pid,body,**kwargs:self.entity('processed')
        self.assertEqual(refunds.refund_order('a','vendor')['status'],'completed')
        item=self.store.data[('shop_items','item')]
        self.assertEqual(item['stock_quantity'],10)
        self.assertFalse(item['is_available'])

    def test_mutated_original_amount_cannot_change_retry_request(self):
        self.provider.payment.refund.side_effect=TimeoutError('unknown')
        refunds.refund_order('a','vendor')
        self.store.data[('customer_orders','a')]['total_paise']=1
        with self.assertRaises(ValueError):refunds.refund_order('a','vendor')
        self.assertEqual(self.provider.payment.refund.call_count,1)

if __name__=='__main__':unittest.main()
