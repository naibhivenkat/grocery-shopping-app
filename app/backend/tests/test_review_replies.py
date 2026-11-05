"""Reply HTTP contract against isolated transactional Firestore-shaped fixtures."""
import copy
import unittest
from concurrent.futures import ThreadPoolExecutor
import db as storage
import test_core_routes as core


class ReviewReplyTests(unittest.TestCase):
    setUp = core.CoreRoutesTests.setUp
    call = core.CoreRoutesTests.call

    def prepare(self):
        self.store.data[(storage.CUSTOMER_ORDERS, 'order')]['status'] = 'delivered'
        product = self.call('/reviews', dict(item_id='rice', vendor_id='vendor', rating=4), user='customer').json['uid']
        self.store.data[(storage.USERS, 'provider')] = {'role': 'service_provider'}
        self.store.data[(storage.USERS, 'other_provider')] = {'role': 'service_provider'}
        self.store.data[('provider_profiles', 'provider')] = {'is_active': True}
        self.store.data[('provider_services', 'svc')] = {'provider_id': 'provider', 'is_active': True}
        self.store.data[('service_bookings', 'booking')] = dict(requester_id='customer', service_id='svc', provider_id='provider', status='completed', payment_status='paid')
        service = self.call('/reviews', dict(service_id='svc', provider_id='provider', booking_id='booking', rating=3), user='customer').json['uid']
        return product, service

    def test_owner_create_update_and_unchanged_review_projections(self):
        product, service = self.prepare()
        before = copy.deepcopy(self.store.data)
        projections = [self.client.get(p).json for p in ('/reviews/item/rice', '/reviews/vendor/vendor', '/reviews/service/svc', '/reviews/provider/provider')]
        for review, user in ((product, 'vendor'), (service, 'provider')):
            path = f'/reviews/{review}/reply'
            self.assertEqual(self.client.get(path).status_code, 404)
            first = self.call(path, {'text': ' Thanks '}, 'PUT', user)
            self.assertEqual(first.status_code, 201)
            self.assertEqual(first.json['text'], 'Thanks')
            updated = self.call(path, {'text': 'Updated'}, 'PUT', user)
            self.assertEqual(updated.status_code, 200)
            self.assertEqual(updated.json['created_at'], first.json['created_at'])
            self.assertEqual(self.client.get(path).json, updated.json)
        self.assertEqual(projections, [self.client.get(p).json for p in ('/reviews/item/rice', '/reviews/vendor/vendor', '/reviews/service/svc', '/reviews/provider/provider')])
        for key, value in before.items():
            self.assertEqual(value, self.store.data[key])
        # Customer edits must not erase separate replies.
        self.assertEqual(self.call('/reviews', dict(item_id='rice', vendor_id='vendor', rating=5), user='customer').status_code, 200)
        self.assertEqual(self.client.get(f'/reviews/{product}/reply').json['text'], 'Updated')

    def test_denials_and_validation_are_atomic(self):
        product, service = self.prepare()
        before = copy.deepcopy(self.store.data)
        for review, user in ((product, 'other_vendor'), (service, 'other_provider'), (product, 'provider'), (service, 'vendor'), (product, 'customer')):
            self.assertEqual(self.call(f'/reviews/{review}/reply', {'text': 'x'}, 'PUT', user).status_code, 403)
        self.assertEqual(self.client.put(f'/reviews/{product}/reply', json={'text': 'x'}).status_code, 401)
        self.assertEqual(self.call('/reviews/missing/reply', {'text':'x'}, 'PUT').status_code, 404)
        for body in ({}, [], {'text': ''}, {'text': '  '}, {'text': None}, {'text': []}, {'text': 'x'*2001}, {'text': 'x', 'vendor_id':'vendor'}):
            self.assertEqual(self.call(f'/reviews/{product}/reply', body, 'PUT').status_code, 422)
        self.assertEqual(before, self.store.data)
        self.store.data[(storage.SHOP_ITEMS, 'rice')]['vendor_id'] = 'other_vendor'
        self.assertEqual(self.call(f'/reviews/{product}/reply', {'text':'x'}, 'PUT').status_code, 403)

    def test_concurrent_updates_and_failed_commit(self):
        product, _ = self.prepare()
        path = f'/reviews/{product}/reply'
        def put(value):
            with self.app.test_client() as client:
                return client.put(path, json={'text': value}, headers={'Authorization':'Bearer vendor'}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(put, ['one', 'two'])), [200, 201])
        self.assertEqual(len([k for k in self.store.data if k[0] == 'review_replies']), 1)
        before = copy.deepcopy(self.store.data)
        self.store.fail_commit = True
        with self.assertRaises(RuntimeError):
            self.call(path, {'text':'failure'}, 'PUT')
        self.assertEqual(before, self.store.data)
