"""Isolated payment tests: strict transaction ordering, no provider/network calls."""
import copy
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from flask import Flask, g
import routes.razorpay_api as api
import razorpay_webhook as webhook


class Snapshot:
    def __init__(self, ref):
        self.reference = ref
        self.id = ref.id
        self.exists = ref.key in ref.store.data
    def to_dict(self):
        return copy.deepcopy(self.reference.store.data.get(self.reference.key))

class Ref:
    def __init__(self, store, collection, key):
        self.store, self.collection, self.id = store, collection, key
        self.key = (collection, key)
    def get(self, transaction=None):
        if transaction and transaction.wrote:
            raise AssertionError("Firestore read after write")
        return Snapshot(self)
    def set(self, data, merge=False):
        self.store.data[self.key] = {**(self.store.data.get(self.key, {}) if merge else {}), **copy.deepcopy(data)}
    def update(self, data):
        if self.key not in self.store.data: raise AssertionError("missing update")
        self.store.data[self.key].update(copy.deepcopy(data))

class Store:
    def __init__(self, data): self.data = copy.deepcopy(data)
    def doc(self, collection, key): return Ref(self, collection, key)
    def transaction(self): return Transaction(self)

class Transaction:
    def __init__(self, store): self.store, self.wrote = store, False
    def update(self, ref, data): self.wrote = True; ref.update(data)
    def set(self, ref, data, merge=False): self.wrote = True; ref.set(data, merge)
    def delete(self, ref): self.wrote = True; self.store.data.pop(ref.key, None)
    def create(self, ref, data):
        if ref.key in self.store.data: raise AssertionError("duplicate create")
        self.set(ref, data)

class PaymentSecurityTests(unittest.TestCase):
    def setUp(self):
        self.intent = {"user_id": "u", "purpose": "order", "amount_paise": 25000,
            "currency": "INR", "status": "created", "razorpay_order_id": "order_1",
            "reference_id": "a", "target_ids": ["a", "b"]}
        self.store = Store({("payment_orders", "i"): self.intent,
            ("customer_orders", "a"): {"customer_id": "u", "total_price": 100, "status": "pending"},
            ("customer_orders", "b"): {"customer_id": "u", "total_price": 150, "status": "pending"}})
        self.patches = [patch.object(api, 'doc', self.store.doc), patch.object(api, 'db', lambda: self.store),
            patch.object(api.firestore, 'transactional', lambda fn: fn)]
        for p in self.patches: p.start(); self.addCleanup(p.stop)
        self.payment = {"id": "pay_1", "order_id": "order_1", "status": "captured", "captured": True,
                        "amount": 25000, "currency": "INR"}
    def test_capture_requires_exact_provider_amount_currency_order_and_status(self):
        self.assertTrue(api.captured_payment_matches(self.intent, self.payment))
        for field, value in (("amount", 1), ("amount", 25000.0), ("currency", "USD"),
                             ("order_id", "other"), ("status", "authorized"), ("captured", False), ("id", None)):
            candidate = {**self.payment, field: value}
            self.assertFalse(api.captured_payment_matches(self.intent, candidate), field)
    def test_batch_paid_atomically_and_replay_no_duplicate_changes(self):
        self.assertEqual(api.settle_payment_order('i', 'pay_1')['settlement_status'], 'settled')
        for oid in ('a', 'b'):
            order = self.store.data[('customer_orders', oid)]
            self.assertEqual(order['payment_status'], 'paid')
            self.assertEqual(order['due_amount'], 0)
        before = copy.deepcopy(self.store.data)
        self.assertEqual(api.settle_payment_order('i', 'pay_1')['status'], 'already_paid')
        self.assertEqual(before, self.store.data)
    def test_late_capture_after_failed_attempt_settles_and_failed_callback_cannot_undo(self):
        api.fail_payment_order('i', 'failed_attempt')
        self.assertEqual(api.settle_payment_order('i', 'pay_1')['status'], 'paid')
        self.assertEqual(api.fail_payment_order('i', 'failed_attempt')['status'], 'paid')
    def test_cancelled_or_foreign_order_retains_capture_for_review_without_fulfilling(self):
        for field, value in (('status', 'cancelled'), ('customer_id', 'attacker')):
            self.store.data[('payment_orders', 'i')] = copy.deepcopy(self.intent)
            self.store.data[('customer_orders', 'a')][field] = value
            result = api.settle_payment_order('i', 'pay_1')
            self.assertEqual(result['settlement_status'], 'requires_review')
            self.assertNotIn('payment_status', self.store.data[('customer_orders', 'b')])
    def test_historical_wallet_capture_credits_once_after_failure(self):
        self.store.data[('payment_orders', 'i')].update(purpose='wallet', status='failed')
        self.store.data[('wallets', 'u')] = {'balance': 5, 'total_credit': 5}
        api.settle_payment_order('i', 'pay_1')
        api.settle_payment_order('i', 'pay_1')
        self.assertEqual(self.store.data[('wallets', 'u')]['balance'], 255)
        self.assertEqual(len([key for key in self.store.data if key[0] == 'wallet_transactions']), 1)
    def _app(self):
        app = Flask(__name__)
        app.register_blueprint(api.razorpay_api_bp)
        @app.before_request
        def auth(): g.user_id = 'u'
        return app
    def test_wallet_creation_is_disabled_before_provider_call(self):
        app = self._app()
        with app.test_request_context('/razorpayApi/orders', json={'purpose': 'wallet', 'amount': 500}):
            g.user_id = 'u'
            response, status = api.create_razorpay_order.__wrapped__()
            self.assertEqual(status, 403)
            self.assertEqual(response.json['code'], 'WALLET_DISABLED')
    def test_valid_checkout_signature_cannot_settle_authorized_uncaptured_payment(self):
        app = self._app(); provider = MagicMock()
        provider.payment.fetch.return_value = {**self.payment, 'status': 'authorized', 'captured': False}
        with patch.object(api, 'get_razorpay_client', return_value=provider), app.test_request_context(
            '/razorpayApi/verify', json={'backend_order_id': 'i', 'order_id': 'order_1', 'payment_id': 'pay_1', 'signature': 's'}):
            g.user_id = 'u'
            _, status = api.verify_razorpay_payment.__wrapped__()
            self.assertEqual(status, 409)
            self.assertEqual(self.store.data[('payment_orders', 'i')]['status'], 'created')
    def test_webhook_rejects_valid_signature_with_wrong_capture_amount(self):
        app = Flask(__name__); app.register_blueprint(webhook.razorpay_webhook_bp)
        with patch.object(webhook, 'verify_webhook_signature', return_value=True), patch.object(
            webhook, '_find_payment_order', return_value=('payment_orders', self.store.doc('payment_orders', 'i').get(), None)):
            response = app.test_client().post('/webhooks/razorpay', json={'event': 'payment.captured',
                'payload': {'payment': {'entity': {**self.payment, 'amount': 1}}}})
            self.assertEqual(response.status_code, 400)
            self.assertEqual(self.store.data[('payment_orders', 'i')]['status'], 'created')
    def test_new_digital_subscription_checkout_requires_play_billing(self):
        with self._app().test_request_context('/razorpayApi/orders', json={'purpose':'subscription','reference_id':'sub','amount':50}):
            g.user_id = 'u'
            response, status = api.create_razorpay_order.__wrapped__()
            self.assertEqual(status, 403)
            self.assertEqual(response.json['code'], 'BILLING_REQUIRED')

    def test_checkout_rejects_client_undercharge_without_provider_creation(self):
        self.store.data[('customer_orders', 'a')]['payment_method'] = 'razorpay'
        provider = MagicMock()
        with patch.object(api, 'get_razorpay_client', return_value=provider), self._app().test_request_context(
            '/razorpayApi/orders', json={'purpose': 'order', 'reference_id': 'a', 'amount': 1}):
            g.user_id = 'u'
            _, status = api.create_razorpay_order.__wrapped__()
            self.assertEqual(status, 409)
            provider.order.create.assert_not_called()
    def test_server_checkout_and_reopen_reuse_same_provider_order(self):
        self.store.data[('customer_orders', 'a')]['payment_method'] = 'razorpay'
        provider = MagicMock(); provider.order.create.return_value = {'id': 'order_new'}
        collection = SimpleNamespace(document=lambda: self.store.doc('payment_orders', 'new_i'))
        with patch.object(api, 'get_razorpay_client', return_value=provider), patch.object(api, 'get_razorpay_key_id', return_value='public_key'), patch.object(api, 'col', return_value=collection):
            for expected_status in (201, 200):
                with self._app().test_request_context('/razorpayApi/orders', json={'purpose':'order', 'reference_id':'a'}):
                    g.user_id = 'u'
                    response, status = api.create_razorpay_order.__wrapped__()
                    self.assertEqual(status, expected_status)
                    self.assertEqual(response.json['amount'], 10000)
                    self.assertEqual(response.json['backend_order_id'], 'new_i')
            provider.order.create.assert_called_once()
            self.assertEqual(provider.order.create.call_args.args[0]['amount'], 10000)
    def test_price_change_before_reservation_prevents_provider_order(self):
        self.store.data[('customer_orders', 'a')]['payment_method'] = 'razorpay'
        provider = MagicMock()
        def price_changed():
            self.store.data[('customer_orders', 'a')]['total_price'] = 200
            return provider
        collection = SimpleNamespace(document=lambda: self.store.doc('payment_orders', 'new_i'))
        with patch.object(api, 'get_razorpay_client', side_effect=price_changed), patch.object(api, 'col', return_value=collection), self._app().test_request_context('/razorpayApi/orders', json={'purpose':'order','reference_id':'a'}):
            g.user_id = 'u'
            _, status = api.create_razorpay_order.__wrapped__()
            self.assertEqual(status, 409)
            provider.order.create.assert_not_called()
    def test_service_capture_records_payment_without_skipping_slot_confirmation(self):
        self.store.data[('payment_orders','i')].update(purpose='service', reference_id='booking', target_ids=['booking'])
        self.store.data[('service_bookings','booking')] = {'requester_id':'u', 'status':'pending_payment'}
        api.settle_payment_order('i','pay_1')
        booking = self.store.data[('service_bookings','booking')]
        self.assertEqual(booking['payment_status'], 'paid')
        self.assertEqual(booking['status'], 'pending_payment')
    def test_subscription_capture_activates_once_with_paid_period(self):
        self.store.data[('payment_orders','i')].update(purpose='subscription', reference_id='sub', target_ids=['sub'], duration_days=90)
        self.store.data[('vendor_subscriptions','sub')] = {'vendor_id':'u','status':'pending'}
        api.settle_payment_order('i','pay_1')
        subscription = self.store.data[('vendor_subscriptions','sub')]
        self.assertEqual(subscription['status'], 'active')
        self.assertEqual(subscription['payment_status'], 'paid')

    def test_untrusted_checkout_amount_is_not_source_of_price(self):
        target = self.store.doc('customer_orders', 'a')
        self.store.data[target.key]['payment_method'] = 'upi'
        _, amount = api._trusted_checkout('order', 'a', 'u')
        self.assertEqual(amount, 10000)
        with self.assertRaises(PermissionError): api._trusted_checkout('order', 'a', 'attacker')

if __name__ == '__main__': unittest.main()
