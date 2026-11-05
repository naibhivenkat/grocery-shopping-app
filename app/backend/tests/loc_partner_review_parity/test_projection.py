import unittest
import db as storage
import test_core_routes as core

class PublicProjectionTests(unittest.TestCase):
    def setUp(self):
        core.CoreRoutesTests.setUp(self)
        self.store.data.update({
            (storage.REVIEWS, 'a'): {'vendor_id':'a', 'item_id':'item-a', 'rating':5, 'comment':'A', 'secret':'hidden', 'created_at':'2025'},
            (storage.REVIEWS, 'b'): {'vendor_id':'b', 'item_id':'item-b', 'rating':3, 'comment':'B', 'secret':'hidden'},
            (storage.REVIEWS, 'pa'): {'provider_id':'a', 'service_id':'svc-a', 'rating':4, 'booking_id':'private-a'},
            (storage.REVIEWS, 'pb'): {'provider_id':'b', 'service_id':'svc-b', 'rating':2, 'booking_id':'private-b'},
        })

    def test_public_own_and_other_targets(self):
        for family, field in [('vendor', 'vendor_id'), ('provider', 'provider_id')]:
            for target in ('a', 'b'):
                for viewer in (None, 'vendor', 'customer'):
                    headers = {'Authorization': 'Bearer ' + viewer} if viewer else {}
                    response = self.client.get('/reviews/%s/%s' % (family, target), headers=headers)
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(len(response.json), 1)
                    self.assertEqual(response.json[0][field], target)
                    self.assertNotIn('secret', response.json[0])
                    self.assertNotIn('booking_id', response.json[0])

if __name__ == '__main__': unittest.main()
