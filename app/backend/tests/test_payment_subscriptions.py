"""Mocked subscription financial validation and atomic moderation regressions."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch
import unittest
from flask import Flask, g
import routes.payments as payments
import routes.subscriptions as subscriptions
from test_payment_security import Store

class SubscriptionPaymentTests(unittest.TestCase):
    def setUp(self):
        self.app=Flask(__name__)
        self.sub={'vendor_id':'vendor','status':'pending','amount_paise':9900,'amount':99,'duration_days':90,'plan_id':'p'}
        self.store=Store({('vendor_subscriptions','sub'):self.sub,
            ('subscription_payments','pay'):{'vendor_id':'vendor','subscription_id':'sub','amount':99,'currency':'INR','status':'pending'}})
        for module in (payments,subscriptions):
            for attr, value in [('doc',self.store.doc), ('col',lambda c:SimpleNamespace(document=lambda:self.store.doc(c,'new')))]:
                p=patch.object(module,attr,value);p.start();self.addCleanup(p.stop)
        for p in [patch.object(payments,'db',return_value=self.store),patch.object(payments.firestore,'transactional',lambda fn:fn)]:
            p.start();self.addCleanup(p.stop)
    def submit(self,payload,uid='vendor'):
        with self.app.test_request_context('/payments',json=payload):
            g.user_id=uid
            try:
                return payments.submit_payment.__wrapped__()
            except payments.SubscriptionError as error:
                return payments._subscription_policy_error(error)
    def moderate(self,approve=True):
        with self.app.test_request_context('/payments/pay/verify'):
            g.user_id='admin'
            try:
                result = payments._moderate('pay',approve)
            except payments.SubscriptionError as error:
                result = payments._subscription_policy_error(error)
            return result if isinstance(result,tuple) else (result,result.status_code)
    def test_submit_rejects_foreign_subscription_and_underpayment(self):
        payload={'subscription_id':'sub','transaction_id':'bank-123','amount':99}
        self.assertEqual(self.submit(payload,uid='attacker')[1],403)
        self.assertEqual(self.submit({**payload,'amount':1})[1],409)
        self.assertNotIn(('subscription_payments','new'),self.store.data)
    def test_submit_valid_server_amount_without_activating(self):
        response,status=self.submit({'subscription_id':'sub','transaction_id':'bank-123','amount':99})
        self.assertEqual(status,403)
        self.assertEqual(response.json['code'],'STORE_BILLING_REQUIRED')
        self.assertNotIn(('subscription_payments','new'),self.store.data)
        self.assertEqual(self.store.data[('vendor_subscriptions','sub')]['status'],'pending')
    def test_invalid_amount_and_json_types(self):
        for amount in ('NaN','Infinity',-1,0,True):
            self.assertEqual(self.submit({'subscription_id':'sub','transaction_id':'bank-123','amount':amount})[1],422)
        self.assertEqual(self.submit(['invalid'])[1],422)
    def test_legacy_manual_approval_cannot_unlock_or_attest_payment(self):
        before=dict(self.store.data[('vendor_subscriptions','sub')])
        self.assertEqual(self.moderate()[1],409)
        self.assertEqual(self.store.data[('vendor_subscriptions','sub')],before)
        self.assertEqual(self.store.data[('subscription_payments','pay')]['status'],'pending')
        self.assertEqual(self.moderate()[1],409)
        self.assertEqual(len([key for key in self.store.data if key[0]=='notifications']),0)
    def test_moderation_rejects_owner_or_amount_mismatch_before_writes(self):
        for field,value in [('vendor_id','attacker'),('amount',1),('currency','USD')]:
            self.store.data[('subscription_payments','pay')][field]=value
            self.assertEqual(self.moderate()[1],409)
            self.assertEqual(self.store.data[('vendor_subscriptions','sub')]['status'],'pending')
            self.assertEqual(self.store.data[('subscription_payments','pay')]['status'],'pending')
    def test_legacy_rejection_requires_canonical_review_without_history_rewrite(self):
        self.assertEqual(self.moderate(False)[1],409)
        self.assertEqual(self.moderate()[1],409)
        self.assertEqual(self.store.data[('vendor_subscriptions','sub')]['status'],'pending')
    def test_legacy_me_projects_only_canonical_grant(self):
        aggregate={'status':'active','current_grant_id':'canonical','plan_name':'Reviewed','usage':{'max_items':5},
                   'starts_at':'2026-10-20T10:00:00+00:00','ends_at':'2026-11-20T10:00:00+00:00'}
        with patch.object(subscriptions.service,'entitlements',return_value=aggregate) as canonical, self.app.test_request_context('/subscriptions/me'):
            g.user_id='vendor'
            response=subscriptions.my_subscription.__wrapped__()
            self.assertEqual(response.json['uid'],'canonical')
            self.assertEqual(response.json['max_items'],5)
            canonical.assert_called_once_with('vendor')

    def test_plan_validation_rejects_nonfinite_and_invalid_duration(self):
        for plan in ({}, {'price':'NaN'}, {'price':-1}, {'price':1,'duration_days':-30},
                     {'price':1,'duration_days':True}, {'price':1,'max_items':0}):
            with self.assertRaises(ValueError): subscriptions.plan_terms(plan)
        self.assertEqual(subscriptions.plan_terms({'price':99,'duration_days':90,'max_items':20}),(9900,90,20))
    def test_active_subscription_requires_valid_started_unexpired_period(self):
        now=datetime.now(timezone.utc)
        valid={'status':'active','start_date':(now-timedelta(days=1)).isoformat(),'end_date':(now+timedelta(days=1)).isoformat()}
        self.assertTrue(subscriptions.active_subscription(valid,now))
        for updates in ({'status':'pending'},{'end_date':(now-timedelta(seconds=1)).isoformat()}, {'start_date':(now+timedelta(days=1)).isoformat()}, {'end_date':'not-date'}):
            self.assertFalse(subscriptions.active_subscription({**valid,**updates},now))

if __name__=='__main__':unittest.main()
