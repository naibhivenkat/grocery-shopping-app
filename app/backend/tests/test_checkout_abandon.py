"""Abandonment transaction proof; isolated strict mocks, no provider or database."""
import copy
import hashlib
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import db as storage
from routes import checkout_abandon as abandon
import test_orders_api as fixture


def batch_id(key, owner='customer'):
    return hashlib.sha256(f'{owner}:{key}'.encode()).hexdigest()


class CheckoutAbandonTests(unittest.TestCase):
    def setUp(self):
        fixture.OrdersTests.setUp(self)
        self.app.register_blueprint(abandon.checkout_abandon_bp)
        for name, value in (('doc', self.store.doc), ('col', self.store.col), ('db', lambda: self.store)):
            current = patch.object(abandon, name, value)
            current.start()
            self.addCleanup(current.stop)
        current = patch.object(abandon, 'deliver_push')
        self.push = current.start()
        self.addCleanup(current.stop)

    def create(self, key='checkout-first', method='cash', item='rice', quantity=1):
        return fixture.OrdersTests.post(self, '/orders/batch', {
            'items': [{'item_id': item, 'quantity': quantity}], 'payment_method': method}, key=key)

    def call(self, keys=None, user='customer', body=None):
        return self.client.post('/orders/checkout/abandon', json=body if body is not None else {
            'keys': ['checkout-first', 'checkout-missing'] if keys is None else keys},
            headers={'Authorization': 'Bearer ' + user} if user else {})

    def test_created_first_missing_second_tombstone_replay_and_late_creation(self):
        created = self.create()
        self.assertEqual(created.status_code, 201)
        identifier = created.json['order_id']
        self.assertEqual(self.store.data[(storage.SHOP_ITEMS, 'rice')]['stock_quantity'], 9)
        response = self.call()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {'cancelled_order_ids': [identifier], 'kept_order_ids': []})
        self.assertEqual(self.store.data[(storage.SHOP_ITEMS, 'rice')]['stock_quantity'], 10)
        self.assertEqual(self.call().json, response.json)
        self.assertEqual(self.store.data[(storage.SHOP_ITEMS, 'rice')]['stock_quantity'], 10)
        self.assertEqual(sum(name == storage.CUSTOMER_ORDERS for name, _ in self.store.data), 1)
        self.assertTrue(self.store.data[('order_batches', batch_id('checkout-missing'))]['abandoned'])
        self.assertEqual(self.store.data[('order_batches', batch_id('checkout-first'))]['response'], created.json)
        # The creator's tombstone guard is owned by shops.py, and must prevent
        # both delayed missing-shop creation and stale successful-key replays.
        for key in ('checkout-first', 'checkout-missing'):
            late = self.create(key)
            self.assertEqual(late.status_code, 409)
        self.assertEqual(self.store.data[(storage.SHOP_ITEMS, 'rice')]['stock_quantity'], 10)

    def test_paid_shop_is_kept_other_shop_cancelled(self):
        paid = self.create().json['order_id']
        self.store.data[(storage.CUSTOMER_ORDERS, paid)]['payment_status'] = 'paid'
        self.store.data[(storage.CUSTOMER_ORDERS, paid)]['payment_method'] = 'razorpay'
        unpaid = self.create('checkout-second', item='milk').json['order_id']
        response = self.call(['checkout-first', 'checkout-second'])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {'cancelled_order_ids': [unpaid], 'kept_order_ids': [paid]})
        self.assertEqual(self.store.data[(storage.SHOP_ITEMS, 'rice')]['stock_quantity'], 9)
        self.assertEqual(self.store.data[(storage.SHOP_ITEMS, 'milk')]['stock_quantity'], 5)

    def test_free_paid_order_is_kept(self):
        identifier = self.create().json['order_id']
        self.store.data[(storage.CUSTOMER_ORDERS, identifier)].update({
            'total_price': 0, 'total_paise': 0, 'payment_status': 'paid', 'payment_exempt': True})
        self.assertEqual(self.call().json, {'cancelled_order_ids': [], 'kept_order_ids': [identifier]})
        self.assertEqual(self.store.data[(storage.SHOP_ITEMS, 'rice')]['stock_quantity'], 9)

    def test_two_keys_restore_same_product_and_ledger_once(self):
        fixture.OrdersTests.ledger(self, balance=100)
        self.create(method='khata', quantity=2)
        self.create('checkout-second', method='khata', quantity=3)
        self.assertEqual(self.store.data[(storage.KHATA_LEDGERS, 'legacy')]['balance'], 161.75)
        response = self.call(['checkout-first', 'checkout-second'])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json['cancelled_order_ids']), 2)
        self.assertEqual(self.store.data[(storage.SHOP_ITEMS, 'rice')]['stock_quantity'], 10)
        self.assertEqual(self.store.data[(storage.KHATA_LEDGERS, 'legacy')]['balance'], 100)
        self.assertEqual(self.call(['checkout-first', 'checkout-second']).json, response.json)
        self.assertEqual(self.store.data[(storage.KHATA_LEDGERS, 'legacy')]['balance'], 100)

    def test_unresolved_payment_rejects_atomically_without_tombstone(self):
        self.create()
        identifier = self.create('checkout-second').json['order_id']
        self.store.data[(storage.CUSTOMER_ORDERS, identifier)]['payment_intent_id'] = 'intent'
        self.store.data[('payment_orders', 'intent')] = {'status': 'failed'}
        before = copy.deepcopy(self.store.data)
        self.assertEqual(self.call(['checkout-first', 'checkout-second', 'checkout-missing']).status_code, 409)
        self.assertEqual(self.store.data, before)
        self.push.assert_not_called()

    def test_refund_amendment_review_and_capture_states_rejected(self):
        identifier = self.create().json['order_id']
        key = (storage.CUSTOMER_ORDERS, identifier)
        original = copy.deepcopy(self.store.data[key])
        for changes in ({'refund_status': 'processing'}, {'pending_amendment_id': 'change'},
                        {'amendment_status': 'pending'}, {'payment_status': 'requires_review'},
                        {'payment_id': 'captured'}, {'partial_amount_paid': 1}, {'status': 'packed'}):
            with self.subTest(changes=changes):
                self.store.data[key] = {**original, **changes}
                before = copy.deepcopy(self.store.data)
                self.assertEqual(self.call().status_code, 409)
                self.assertEqual(self.store.data, before)

    def test_dimension_mismatch_pending_khata_and_rollback_are_atomic(self):
        fixture.OrdersTests.ledger(self, balance=0)
        identifier = self.create(method='khata').json['order_id']
        self.store.data[(storage.SHOP_ITEMS, 'rice')].update({
            'selling_unit': 'kg', 'stock_unit': 'g', 'pricing_quantity': 1000})
        before = copy.deepcopy(self.store.data)
        self.assertEqual(self.call().status_code, 409)
        self.assertEqual(self.store.data, before)
        for field in ('selling_unit', 'stock_unit', 'pricing_quantity'):
            self.store.data[(storage.SHOP_ITEMS, 'rice')].pop(field)
        self.store.data[(storage.KHATA_TRANSACTIONS, 'pending')] = {
            'ledger_id': 'legacy', 'status': 'pending', 'amount': 1}
        before = copy.deepcopy(self.store.data)
        self.assertEqual(self.call().status_code, 409)
        self.assertEqual(self.store.data, before)
        del self.store.data[(storage.KHATA_TRANSACTIONS, 'pending')]
        before = copy.deepcopy(self.store.data)
        self.store.fail_commit = True
        with self.assertRaisesRegex(RuntimeError, 'simulated write failure'):
            self.call()
        self.assertEqual(self.store.data, before)

    def test_foreign_keys_hash_to_buyers_own_namespace_and_owner_verified(self):
        created = self.create().json
        before_order = copy.deepcopy(self.store.data[(storage.CUSTOMER_ORDERS, created['order_id'])])
        response = self.call(['checkout-first'], user='other_customer')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {'cancelled_order_ids': [], 'kept_order_ids': []})
        self.assertEqual(self.store.data[(storage.CUSTOMER_ORDERS, created['order_id'])], before_order)
        self.assertTrue(self.store.data[('order_batches', batch_id('checkout-first', 'other_customer'))]['abandoned'])
        self.store.data[('order_batches', batch_id('checkout-first'))]['customer_id'] = 'other_customer'
        self.assertEqual(self.call(['checkout-first']).status_code, 403)

    def test_validation(self):
        for keys in ([], ['short'], ['x' * 201], ['12345678'] * 2, ['key-'+str(n).zfill(6) for n in range(21)], [False]):
            with self.subTest(keys=keys):
                self.assertEqual(self.call(keys).status_code, 422)
        self.assertEqual(self.call(body={'keys': ['12345678'], 'customer_id': 'other'}).status_code, 422)
        self.assertEqual(self.call(user=None).status_code, 401)

    def test_total_line_bound_rejects_before_any_writes(self):
        created = self.create().json
        template = self.store.data[(storage.CUSTOMER_ORDERS, created['order_id'])]
        identifiers = []
        for number in range(101):
            identifier = f'line_{number}'
            identifiers.append(identifier)
            self.store.data[(storage.CUSTOMER_ORDERS, identifier)] = {**template, 'batch_id': batch_id('checkout-many')}
        self.store.data[('order_batches', batch_id('checkout-many'))] = {
            'customer_id': 'customer', 'response': {'order_ids': identifiers}}
        before = copy.deepcopy(self.store.data)
        # One batch is bounded independently, as well as all keys together.
        self.assertEqual(self.call(['checkout-many']).status_code, 409)
        self.assertEqual(self.store.data, before)
        self.store.data[('order_batches', batch_id('checkout-many'))]['response']['order_ids'] = identifiers[:100]
        del self.store.data[(storage.CUSTOMER_ORDERS, identifiers[-1])]
        before = copy.deepcopy(self.store.data)
        self.assertEqual(self.call(['checkout-first', 'checkout-many']).status_code, 422)
        self.assertEqual(self.store.data, before)

    def test_partly_collected_discounted_batch_requires_reconciliation(self):
        response = fixture.OrdersTests.post(self, '/orders/batch', {'payment_method': 'cash',
            'items': [{'item_id': 'rice', 'quantity': 1}, {'item_id': 'milk', 'quantity': 1}]}, key='checkout-first')
        first, second = response.json['order_ids']
        self.store.data[(storage.CUSTOMER_ORDERS, first)]['payment_status'] = 'paid'
        self.store.data[(storage.CUSTOMER_ORDERS, second)]['discount_amount'] = 1
        before = copy.deepcopy(self.store.data)
        self.assertEqual(self.call().status_code, 409)
        self.assertEqual(self.store.data, before)

    def test_concurrent_create_abandon_serializes_and_never_reserves_twice(self):
        def create(_):
            with self.app.test_client() as client:
                return client.post('/orders/batch', json={'payment_method': 'cash',
                    'items': [{'item_id': 'rice', 'quantity': 1}]}, headers={
                    'Authorization': 'Bearer customer', 'Idempotency-Key': 'checkout-first'}).status_code
        def cancel(_):
            with self.app.test_client() as client:
                return client.post('/orders/checkout/abandon', json={'keys': ['checkout-first']},
                                   headers={'Authorization': 'Bearer customer'}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda job: job(None), (create, cancel)))
        self.assertIn(results[0], (201, 409))
        self.assertEqual(results[1], 200)
        self.assertEqual(self.store.data[(storage.SHOP_ITEMS, 'rice')]['stock_quantity'], 10)
        self.assertTrue(self.store.data[('order_batches', batch_id('checkout-first'))]['abandoned'])


if __name__ == '__main__':
    unittest.main()
