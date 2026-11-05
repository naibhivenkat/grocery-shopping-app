"""Service review contract checks using isolated atomic storage."""
import copy
import unittest
from concurrent.futures import ThreadPoolExecutor
import db as storage
import test_core_routes as core


class ServiceReviewTests(unittest.TestCase):
    call = core.CoreRoutesTests.call
    values = core.CoreRoutesTests.values

    def setUp(self):
        core.CoreRoutesTests.setUp(self)
        self.store.data.update({
            (storage.USERS, 'provider'): {'role': 'service_provider'},
            ('provider_profiles', 'provider'): {'is_active': True},
            ('provider_services', 'svc'): {'provider_id': 'provider', 'is_active': True},
        })
        self.booking()

    def booking(self, identifier='booking', **changes):
        data = dict(requester_id='customer', service_id='svc', provider_id='provider',
                    status='completed', payment_status='paid')
        self.store.data[('service_bookings', identifier)] = {**data, **changes}

    def review(self, user='customer', **changes):
        return self.call('/reviews', {**dict(service_id='svc', provider_id='provider',
                         booking_id='booking', rating=4), **changes}, user=user)

    def reject(self, status, **changes):
        before = copy.deepcopy(self.store.data)
        self.assertEqual(self.review(**changes).status_code, status)
        self.assertEqual(before, self.store.data)

    def test_create_repeat_update_other_customer_and_rebooking(self):
        first = self.review(user_id='other_customer', user_name='Forged')
        self.assertEqual(first.status_code, 201)
        self.assertEqual(first.json['user_id'], 'customer')
        self.assertEqual(first.json['user_name'], 'Customer')
        uid = first.json['uid']
        self.assertEqual(self.review().status_code, 200)
        self.booking('again')
        update = self.call('/reviews', dict(service_id='svc', provider_id='provider', booking_id='again', rating=5), user='customer')
        self.assertEqual(update.status_code, 200)
        self.assertEqual(update.json['uid'], uid)
        self.assertEqual(update.json['created_at'], first.json['created_at'])
        self.assertEqual(update.json['booking_id'], 'again')
        self.booking('other', requester_id='other_customer')
        other = self.call('/reviews', dict(service_id='svc', provider_id='provider', booking_id='other', rating=3), user='other_customer')
        self.assertEqual(other.status_code, 201)
        service = self.store.data[('provider_services', 'svc')]
        self.assertEqual((service['average_rating'], service['rating_count']), (4, 2))
        self.assertEqual(len(self.values(storage.REVIEWS)), 2)
        self.assertNotIn('average_rating', self.store.data[(storage.USERS, 'provider')])

    def test_booking_eligibility_and_update_rejection_are_atomic(self):
        self.assertEqual(self.review().status_code, 201)
        for changes in [dict(requester_id='other_customer'), dict(service_id='other'),
                        dict(provider_id='other'), dict(payment_status='pending'),
                        *[dict(status=s) for s in ('pending_payment', 'confirmed', 'in_progress', 'cancelled', 'delivered', 'complete', '')]]:
            with self.subTest(changes=changes):
                self.booking(**changes)
                self.reject(403)
        self.booking()
        self.reject(403, user='other_customer', user_id='customer')
        self.reject(403, booking_id='missing')
        del self.store.data[('service_bookings', 'booking')]
        self.reject(403)

    def test_unavailable_targets_and_identities(self):
        cases = [('provider_services', 'svc', 'is_active', False, 404),
                 ('provider_services', 'svc', 'is_deleted', True, 404),
                 ('provider_services', 'svc', 'provider_id', 'wrong', 422),
                 (storage.USERS, 'provider', 'is_suspended', True, 404),
                 ('provider_profiles', 'provider', 'is_active', False, 404),
                 (storage.USERS, 'customer', 'is_suspended', True, 403)]
        for collection, identifier, field, value, status in cases:
            with self.subTest(field=field, collection=collection):
                original = copy.deepcopy(self.store.data[(collection, identifier)])
                self.store.data[(collection, identifier)][field] = value
                self.reject(status)
                self.store.data[(collection, identifier)] = original
        for key in [('provider_services', 'svc'), (storage.USERS, 'provider'), ('provider_profiles', 'provider')]:
            original = self.store.data.pop(key)
            self.reject(404)
            self.store.data[key] = original

    def test_validation_auth_and_partial_or_mixed_targets(self):
        base = dict(service_id='svc', provider_id='provider', booking_id='booking', rating=4)
        bodies = [{k:v for k,v in base.items() if k != field} for field in ('service_id', 'provider_id', 'booking_id')]
        bodies += [{**base, 'item_id':'rice'}, {**base, 'vendor_id':'vendor'}]
        bodies += [{**base, 'rating':r} for r in (True, 0, 6, 'NaN', 'Infinity', [], None)]
        bodies += [{**base, 'comment':c} for c in ([], 'x'*2001)]
        bodies += [{**base, field:val} for field in ('service_id','provider_id','booking_id') for val in ('', 'a/b', [], None)]
        before = copy.deepcopy(self.store.data)
        for body in bodies:
            with self.subTest(body=body):
                self.assertEqual(self.call('/reviews', body, user='customer').status_code, 422)
                self.assertEqual(before, self.store.data)
        self.assertEqual(self.call('/reviews', base, user='vendor').status_code, 403)
        self.assertEqual(self.client.post('/reviews', json=base).status_code, 401)

    def test_failure_duplicate_and_legacy_rating(self):
        self.store.fail_commit = True
        before = copy.deepcopy(self.store.data)
        with self.assertRaises(RuntimeError):
            self.review()
        self.assertEqual(before, self.store.data)
        self.store.fail_commit = False
        self.store.data[(storage.REVIEWS, 'bad')] = dict(service_id='svc', user_id='legacy', rating='NaN')
        self.assertEqual(self.review().status_code, 201)
        self.assertEqual(self.store.data[('provider_services','svc')]['rating_count'], 1)
        self.store.data[(storage.REVIEWS, 'duplicate')] = dict(service_id='svc', user_id='customer', rating=2)
        self.reject(409)

    def test_public_listings_exclude_booking_and_product_cross_contamination(self):
        self.assertEqual(self.review().status_code, 201)
        self.store.data[(storage.REVIEWS, 'product')] = dict(item_id='rice', vendor_id='provider', rating=2, created_at='9999')
        for path in ('/reviews/service/svc', '/reviews/provider/provider'):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(response.json), 1)
            self.assertEqual(response.json[0]['service_id'], 'svc')
            self.assertNotIn('booking_id', response.json[0])
            self.assertNotIn('item_id', response.json[0])
        self.assertEqual(len(self.client.get('/reviews/vendor/provider').json), 1)
        self.assertEqual(len(self.client.get('/reviews/item/rice').json), 1)

    def test_concurrent_repeat_posts_remain_one_review_in_serialized_store(self):
        def post(_):
            with self.app.test_client() as client:
                return client.post('/reviews', json=dict(service_id='svc', provider_id='provider',
                    booking_id='booking', rating='4'), headers={'Authorization':'Bearer customer'}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(post, range(2)))
        self.assertEqual(sorted(statuses), [200, 201])
        self.assertEqual(len(self.values(storage.REVIEWS)), 1)
        self.assertEqual(self.store.data[('provider_services','svc')]['rating_count'], 1)
