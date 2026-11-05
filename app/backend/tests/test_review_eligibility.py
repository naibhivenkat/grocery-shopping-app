"""Review eligibility HTTP checks; isolated atomic Firestore store, no live data."""
import copy
import unittest
import test_core_routes as core
import db as storage


class ReviewEligibilityTests(unittest.TestCase):
    setUp = core.CoreRoutesTests.setUp
    call = core.CoreRoutesTests.call
    review = core.CoreRoutesTests.review
    values = core.CoreRoutesTests.values
    # Reuse the HTTP/store setup without inheriting unrelated feature tests.
    def order(self, identifier='order', **changes):
        data = {'customer_id': 'customer', 'vendor_id': 'vendor', 'item_id': 'rice',
                'status': 'delivered', 'payment_status': 'paid'}
        data.update(changes)
        self.store.data[(storage.CUSTOMER_ORDERS, identifier)] = data

    def test_ineligible_orders_cannot_create_or_change_ratings(self):
        cases = [{}, {'customer_id': 'other_customer'}, {'item_id': 'milk'},
                 {'vendor_id': 'other_vendor'}, {'status': 'pending'},
                 {'status': 'confirmed'}, {'status': 'packed'}, {'status': 'cancelled'}]
        for changes in cases:
            with self.subTest(changes=changes):
                if changes:
                    self.order(**changes)
                before = copy.deepcopy(self.store.data)
                response = self.review(user_id='other_customer', order_id='forged', booking_id='forged')
                self.assertEqual(response.status_code, 403)
                self.assertEqual(before, self.store.data)

    def test_completed_purchase_preserves_create_update_and_summary(self):
        self.order()
        first = self.review(3)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(first.json['user_id'], 'customer')
        self.assertEqual(self.review(5).status_code, 200)
        self.order('second', customer_id='other_customer')
        self.assertEqual(self.review(3, user='other_customer').status_code, 201)
        item = self.store.data[(storage.SHOP_ITEMS, 'rice')]
        self.assertEqual((item['average_rating'], item['rating_count']), (4, 2))
        self.assertEqual(len(self.values(storage.REVIEWS)), 2)

    def test_update_requires_eligibility_and_rejects_forged_author(self):
        self.order()
        self.assertEqual(self.review().status_code, 201)
        self.assertEqual(self.review(user='other_customer', user_id='customer').status_code, 403)
        self.order(status='cancelled')
        before = copy.deepcopy(self.store.data)
        self.assertEqual(self.review(1).status_code, 403)
        self.assertEqual(before, self.store.data)

    def test_completed_purchase_write_failure_is_atomic(self):
        self.order()
        before = copy.deepcopy(self.store.data)
        self.store.fail_commit = True
        with self.assertRaises(RuntimeError):
            self.review()
        self.assertEqual(before, self.store.data)

