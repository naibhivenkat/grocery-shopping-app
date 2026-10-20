"""Deterministic promotion math and atomic checkout/payment regression proof."""
import copy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

import db as storage
from routes import billing, discounts, razorpay_api, order_refunds, vendors
import test_orders_api as orders_fixture
import test_billing_import as bill_fixture
import test_promotions_api as promotion_fixture
from test_khata import Ref


def promotion(**changes):
    now = datetime.now(timezone.utc)
    return {'vendor_id': 'vendor', 'shop_id': 'vendor', 'target_type': 'shop', 'product_id': None,
            'status': 'approved', 'revision': 1, 'approved_revision': 1, 'is_paused': False,
            'starts_at': (now - timedelta(days=1)).isoformat(), 'ends_at': (now + timedelta(days=1)).isoformat(),
            'discount_type': 'percentage', 'discount_value': 10, **changes}


class DiscountMathTests(unittest.TestCase):
    def test_largest_remainder_and_tie_are_exact(self):
        self.assertEqual(discounts.allocate([('b', 1), ('a', 1), ('c', 1)], 2), {'b': 1, 'a': 1, 'c': 0})
        self.assertEqual(discounts.allocate([('rice', 12000), ('milk', 4000)], 1000), {'rice': 750, 'milk': 250})
        for amount in (-1, 4, True):
            with self.assertRaises(ValueError):
                discounts.allocate([('a', 3)], amount)

    def test_rules_validate_money_percentage_and_defaults(self):
        self.assertEqual(discounts.rules({})['discount_type'], 'none')
        for fields in ({'discount_type': []}, {'discount_type': 'percentage', 'discount_value': True},
                       {'discount_type': 'percentage', 'discount_value': 100.01},
                       {'discount_type': 'percentage', 'discount_value': 'NaN'},
                       {'discount_type': 'fixed', 'discount_value': -1}, {'minimum_order_amount': False},
                       {'maximum_discount_amount': -1}, {'discount_type': 'none', 'discount_value': False},
                       {'discount_type': 'fixed', 'discount_value': 1.001}, {'minimum_order_amount': 2.345},
                       {'maximum_discount_amount': 0.001}, {'discount_type': 'percentage', 'discount_value': 10, 'maximum_discount_amount': 0}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                discounts.rules(fields)

    def test_best_single_threshold_cap_target_and_revision(self):
        def snap(identifier, **changes):
            return SimpleNamespace(id=identifier, to_dict=lambda: promotion(**changes))
        lines = [('rice', 10000), ('milk', 5000)]
        result = discounts.best_promotion([snap('z'), snap('a')], 'vendor', lines)
        self.assertEqual(result['promotion_id'], 'a')
        self.assertEqual(sum(result['shares'].values()), 1500)
        self.assertEqual(result['promotion_rules']['target_type'], 'shop')
        result = discounts.best_promotion([snap('product', target_type='product', product_id='rice', discount_value=50,
                                                minimum_order_amount=100, maximum_discount_amount=20)], 'vendor', lines)
        self.assertEqual(result['amount_paise'], 2000)
        self.assertEqual(result['shares'], {'rice': 2000})
        for changes in ({'vendor_id': 'other'}, {'shop_id': 'other'}, {'approved_revision': 2},
                        {'is_paused': True}, {'minimum_order_amount': 151}, {'target_type': 'product', 'product_id': 'missing'},
                        {'ends_at': 'invalid'}, {'status': 'pending'}):
            with self.subTest(changes=changes):
                self.assertEqual(discounts.best_promotion([snap('bad', **changes)], 'vendor', lines)['amount_paise'], 0)


class DiscountCheckoutTests(unittest.TestCase):
    post = orders_fixture.OrdersTests.post
    order = orders_fixture.OrdersTests.order
    batch = orders_fixture.OrdersTests.batch
    values = orders_fixture.OrdersTests.values
    stock = orders_fixture.OrdersTests.stock
    cancel = orders_fixture.OrdersTests.cancel
    ledger = orders_fixture.OrdersTests.ledger

    def setUp(self):
        orders_fixture.OrdersTests.setUp(self)
        self.app.register_blueprint(razorpay_api.razorpay_api_bp)
        for module in (razorpay_api, vendors):
            for name, value in (('doc', self.store.doc), ('col', self.store.col), ('db', lambda: self.store)):
                current = patch.object(module, name, value)
                current.start()
                self.addCleanup(current.stop)
        self.app.register_blueprint(vendors.vendors_bp)
        update_patch = patch.object(Ref, 'update', lambda ref, data: ref.store.data[ref.key].update(copy.deepcopy(data)), create=True)
        update_patch.start()
        self.addCleanup(update_patch.stop)
        self.provider = MagicMock()
        self.provider.order.create.return_value = {'id': 'order_provider'}
        for current in (patch.object(razorpay_api, 'get_razorpay_client', return_value=self.provider),
                        patch.object(razorpay_api, 'get_razorpay_key_id', return_value='test-key')):
            current.start()
            self.addCleanup(current.stop)

    def promo(self, identifier='promo', **changes):
        self.store.data[('promotions', identifier)] = promotion(**changes)

    def test_checkout_net_snapshot_gross_tamper_and_retry(self):
        self.promo(discount_value=25)
        result = self.order(quantity=2, total_price=24.7, idempotency_key='discount-retry')
        self.assertEqual(result.status_code, 201)
        self.assertEqual(result.json['subtotal'], 24.7)
        self.assertEqual(result.json['discount_amount'], 6.18)
        self.assertEqual(result.json['total_price'], 18.52)
        record = self.values(storage.CUSTOMER_ORDERS)[0]
        self.assertEqual(record['promotion_revision'], 1)
        self.assertEqual(record['promotion_rules']['target_type'], 'shop')
        self.store.data[('promotions', 'promo')]['discount_value'] = 100
        self.assertEqual(self.order(quantity=2, total_price=24.7, idempotency_key='discount-retry').json, result.json)
        self.assertEqual(self.stock(), 8)
        before = copy.deepcopy(self.store.data)
        self.assertEqual(self.order(total_price=1).status_code, 422)
        self.assertEqual(self.store.data, before)

    def test_best_single_discount_and_khata_charges_net(self):
        self.promo('percentage', discount_value=20)
        self.promo('fixed', discount_type='fixed', discount_value=10)
        self.ledger(balance=50)
        response = self.batch(payment_method='khata')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json['promotion_id'], 'fixed')
        self.assertEqual(response.json['total_price'], 34.7)
        self.assertEqual(self.store.data[(storage.KHATA_LEDGERS, 'legacy')]['balance'], 84.7)
        self.assertEqual(sum(entry['amount'] for entry in self.values(storage.KHATA_TRANSACTIONS)), 34.7)
        self.assertEqual(sum(entry['discount_amount'] for entry in self.values(storage.CUSTOMER_ORDERS)), 10)

    def test_all_free_cash_cancel_and_no_provider(self):
        self.promo(discount_value=100)
        response = self.order(method='razorpay')
        self.assertEqual(response.json['total_price'], 0)
        self.assertTrue(response.json['payment_exempt'])
        order = self.values(storage.CUSTOMER_ORDERS)[0]
        self.assertEqual(order['payment_status'], 'paid')
        self.assertEqual(order['partial_amount_paid'], 0)
        checkout = self.post('/razorpayApi/orders', {'purpose': 'order', 'reference_id': response.json['order_id']})
        self.assertEqual(checkout.status_code, 409)
        self.provider.order.create.assert_not_called()
        self.assertEqual(self.cancel(response).status_code, 200)
        self.assertEqual(self.stock(), 10)

    def test_free_khata_has_no_zero_credit_or_reversal(self):
        self.promo(discount_value=100)
        self.ledger(balance=50)
        response = self.order(method='khata')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.values(storage.KHATA_TRANSACTIONS), [])
        self.assertEqual(self.cancel(response).status_code, 200)
        self.assertEqual(self.values(storage.KHATA_TRANSACTIONS), [])
        self.assertEqual(self.store.data[(storage.KHATA_LEDGERS, 'legacy')]['balance'], 50)

    def test_positive_capture_includes_free_line_and_settles_zero_paid(self):
        self.promo(target_type='product', product_id='rice', discount_value=100)
        response = self.batch(payment_method='razorpay')
        self.assertEqual(response.json['total_price'], 20)
        orders = self.values(storage.CUSTOMER_ORDERS)
        self.assertTrue(all(entry['payment_status'] == 'pending' for entry in orders))
        checkout = self.post('/razorpayApi/orders', {'purpose': 'order', 'reference_id': response.json['order_id'], 'amount': 20})
        self.assertEqual(checkout.status_code, 201)
        self.provider.order.create.assert_called_once()
        self.assertEqual(self.provider.order.create.call_args.args[0]['amount'], 2000)
        result = razorpay_api.settle_payment_order(checkout.json['backend_order_id'], 'pay_capture')
        self.assertEqual(result['settlement_status'], 'settled')
        free = next(entry for entry in self.values(storage.CUSTOMER_ORDERS) if entry['item_id'] == 'rice')
        self.assertEqual(free['payment_status'], 'paid')
        self.assertEqual(free['partial_amount_paid'], 0)
        self.assertTrue(free['payment_exempt'])
        with patch.object(order_refunds, 'doc', self.store.doc), patch.object(order_refunds, 'db', lambda: self.store), patch.object(order_refunds, 'get_razorpay_client') as client:
            with self.assertRaises(ValueError):
                order_refunds.refund_order(response.json['order_ids'][0], 'vendor')
            client.assert_not_called()

    def test_cash_free_line_confirmation_never_claims_cash_collected(self):
        self.promo(target_type='product', product_id='rice', discount_value=100)
        response = self.batch()
        free_id = response.json['order_ids'][0]
        confirmed = self.post(f'/vendors/orders/{free_id}/payment/confirm', user='vendor')
        self.assertEqual(confirmed.status_code, 200)
        entry = self.store.data[(storage.CUSTOMER_ORDERS, free_id)]
        self.assertEqual(entry['partial_amount_paid'], 0)
        self.assertEqual(entry['payment_status'], 'paid')
        self.assertNotIn('paid_at', entry)
        self.assertFalse(any(event['type'] == 'order_payment' for event in self.values(storage.NOTIFICATIONS)))

    def test_unverified_zero_line_rejected_before_provider(self):
        response = self.batch(payment_method='razorpay')
        first = self.store.data[(storage.CUSTOMER_ORDERS, response.json['order_ids'][0])]
        first.update({'total_price': 0, 'total_paise': 0, 'payment_exempt': False})
        checkout = self.post('/razorpayApi/orders', {'purpose': 'order', 'reference_id': response.json['order_id']})
        self.assertEqual(checkout.status_code, 409)
        self.provider.order.create.assert_not_called()

    def test_discount_checkout_atomic_rollback(self):
        self.promo(discount_value=100)
        self.store.fail_commit = True
        before = copy.deepcopy(self.store.data)
        with self.assertRaisesRegex(RuntimeError, 'simulated write failure'):
            self.batch()
        self.assertEqual(self.store.data, before)


class ManualDiscountTests(unittest.TestCase):
    setUp = bill_fixture.BillingImportTests.setUp
    headers = bill_fixture.BillingImportTests.headers
    discount = bill_fixture.BillingImportTests.discount

    def test_manual_whole_batch_allocation_and_zero_replacement(self):
        response = self.discount(40)
        self.assertEqual(response.status_code, 200)
        rows = {line['order_id']: line for line in response.json['lines']}
        self.assertEqual(rows['rice']['discount'], 30)
        self.assertEqual(rows['milk']['discount'], 10)
        self.assertEqual(self.discount(160).json['total'], 0)
        self.assertTrue(all(line['payment_exempt'] and line['partial_amount_paid'] == 0 for line in self.discount(160).json['lines']))
        self.assertEqual(self.discount(10).json['total'], 150)
        self.assertFalse(any(line['payment_exempt'] for line in self.discount(10).json['lines']))

    def test_one_captured_foreign_or_intent_line_blocks_entire_batch(self):
        original = copy.deepcopy(self.store.data)
        for changes in ({'partial_amount_paid': 1}, {'payment_intent_id': 'intent'}, {'refund_status': 'processing'},
                        {'customer_id': 'other'}, {'payment_status': 'paid'}, {'status': 'cancelled'}):
            self.store.data = copy.deepcopy(original)
            self.store.data[(storage.CUSTOMER_ORDERS, 'milk')].update(changes)
            before = copy.deepcopy(self.store.data)
            self.assertEqual(self.discount(10).status_code, 409)
            self.assertEqual(self.store.data, before)


class PromotionRulesHTTPTests(unittest.TestCase):
    setUp = promotion_fixture.PromotionsApiTests.setUp
    create = promotion_fixture.PromotionsApiTests.create
    headers = promotion_fixture.PromotionsApiTests.headers

    def test_discount_fields_create_and_reject_invalid(self):
        response = self.create({**self.content, 'discount_type': 'percentage', 'discount_value': 100,
                                'minimum_order_amount': 100, 'maximum_discount_amount': 50})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json['discount_value'], 100)
        for fields in ({'discount_type': 'fixed', 'discount_value': -1}, {'discount_type': 'percentage', 'discount_value': 101}):
            self.assertEqual(self.create({**self.content, **fields}).status_code, 422)
