import unittest
import db as storage
import test_orders_api as fixtures


class VendorDetailsTests(unittest.TestCase):
    setUp = fixtures.OrdersTests.setUp
    order = fixtures.OrdersTests.order
    post = fixtures.OrdersTests.post

    def test_order_copies_only_public_vendor_details_and_preserves_snapshot(self):
        vendor = self.store.data[(storage.USERS, 'vendor')]
        vendor.update({'shop_name': 'Local store', 'full_name': 'Shop owner', 'phone': '12345', 'email': 'shop@example.invalid', 'shop_address': 'Market road', 'password_hash': 'private', 'fcm_tokens': ['private']})
        self.store.data[(storage.SHOP_ITEMS, 'rice')]['vendor_name'] = 'Shop owner'
        catalog = self.client.get('/shops').json
        self.assertEqual(next(item for item in catalog if item['uid'] == 'rice')['vendor_name'], 'Local store')
        response = self.order()
        self.assertEqual(response.status_code, 201)
        records = self.client.get('/orders', headers={'Authorization': 'Bearer customer'}).json
        order = records[0]
        self.assertEqual(order['vendor_name'], 'Local store')
        self.assertEqual(order['vendor_owner_name'], 'Shop owner')
        self.assertEqual(order['vendor_phone'], '12345')
        self.assertEqual(order['vendor_shop_description'], 'Market road')
        self.assertNotIn('password_hash', order)
        self.assertNotIn('fcm_tokens', order)
        vendor['phone'] = 'changed'
        self.assertEqual(self.client.get('/orders', headers={'Authorization': 'Bearer customer'}).json[0]['vendor_phone'], '12345')
        self.assertEqual(self.client.get('/orders', headers={'Authorization': 'Bearer other_customer'}).json, [])


if __name__ == '__main__': unittest.main()
