"""Shop approvals against strict transaction mocks, without live mutations."""
import copy
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from flask import Flask

import auth_utils
import db as storage
from routes import shop_applications as apps
from test_khata import Store


class ShopApplicationsTests(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        self.store.data = {
            (storage.USERS, 'customer'): {'role': 'customer', 'full_name': 'Customer'},
            (storage.USERS, 'other'): {'role': 'customer'},
            (storage.USERS, 'vendor'): {'role': 'vendor', 'shop_name': 'Existing'},
            (storage.USERS, 'admin'): {'role': 'admin'},
            (storage.USERS, 'super'): {'role': 'super_admin'},
            (storage.CITIES, 'city'): {'name': 'City', 'is_active': True},
        }
        self.app = Flask(__name__)
        self.app.config['TESTING'] = True
        self.app.register_blueprint(apps.shop_applications_bp)
        for item in (patch.object(storage, 'doc', self.store.doc),
                     patch.object(apps, 'doc', self.store.doc), patch.object(apps, 'col', self.store.col),
                     patch.object(apps, 'db', lambda: self.store),
                     patch.object(apps.firestore, 'transactional', self.store.transactional),
                     patch.object(auth_utils, 'decode_token', lambda token: {'sub': token, 'role': 'admin'})):
            item.start()
            self.addCleanup(item.stop)
        self.client = self.app.test_client()
        self.content = {'shop_name': 'New Shop', 'address': 'Street', 'phone': '1234567890', 'city_id': 'city'}

    def request(self, method, path, body=None, user='customer'):
        return self.client.open(path, method=method, json=body,
                                headers={'Authorization': 'Bearer ' + user} if user else {})

    def apply(self, content=None, user='customer'):
        return self.request('POST', '/shop-applications', self.content if content is None else content, user)

    def decide(self, decision='approved', revision=1, reason=None, user='admin'):
        return self.request('POST', '/admin/shop-applications/customer/decision',
                            {'decision': decision, 'revision': revision, 'reason': reason}, user)

    def count(self, collection):
        return sum(name == collection for name, _ in self.store.data)

    def test_submission_pending_replay_and_private_read(self):
        self.assertIsNone(self.request('GET', '/shop-applications/mine').json)
        self.assertEqual(self.apply().status_code, 201)
        self.assertEqual(self.apply().status_code, 200)
        self.assertEqual(self.count(apps.APPLICATIONS), 1)
        self.assertEqual(self.count(storage.AUDIT_LOGS), 1)
        self.assertEqual(self.store.data[(storage.USERS, 'customer')]['role'], 'customer')
        self.assertEqual(self.request('GET', '/shop-applications/mine').json['status'], 'pending')
        self.assertIsNone(self.request('GET', '/shop-applications/mine', user='other').json)
        before = copy.deepcopy(self.store.data)
        self.assertEqual(self.apply({**self.content, 'shop_name': 'Changed'}).status_code, 409)
        self.assertEqual(self.store.data, before)

    def test_approval_preserves_account_and_is_idempotent(self):
        self.apply()
        with patch.object(apps, 'deliver_push') as push:
            response = self.decide()
            self.assertEqual(response.status_code, 200)
            self.assertEqual(self.decide().json, response.json)
            self.assertEqual(push.call_args_list[0].args[0]['type'], 'shop_application_approved')
            self.assertIsNone(push.call_args_list[1].args[0])
        user = self.store.data[(storage.USERS, 'customer')]
        self.assertEqual(user['role'], 'vendor')
        self.assertEqual(user['shop_address'], 'Street')
        self.assertEqual(user['full_name'], 'Customer')
        self.assertEqual(user['shop_approval_status'], 'approved')
        self.assertEqual(self.count(storage.NOTIFICATIONS), 1)
        self.assertEqual(self.apply().json['status'], 'approved')
        self.assertEqual(self.count(storage.AUDIT_LOGS), 2)

    def test_rejection_resubmission_and_stale_revision(self):
        self.apply()
        self.assertEqual(self.decide('rejected').status_code, 422)
        self.assertEqual(self.decide('rejected', reason='Missing details').status_code, 200)
        self.assertEqual(self.store.data[(storage.USERS, 'customer')]['role'], 'customer')
        self.assertEqual(self.decide('rejected', reason='Missing details').status_code, 200)
        self.assertEqual(self.decide().status_code, 409)
        response = self.apply({**self.content, 'address': 'New Street'})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json['revision'], 2)
        before = copy.deepcopy(self.store.data)
        self.assertEqual(self.decide(revision=1).status_code, 409)
        self.assertEqual(self.store.data, before)
        self.assertEqual(self.decide(revision=2, user='super').status_code, 200)

    def test_roles_suspension_and_existing_vendors(self):
        self.assertEqual(self.apply(user=None).status_code, 401)
        self.assertEqual(self.apply(user='admin').status_code, 403)
        before = copy.deepcopy(self.store.data[(storage.USERS, 'vendor')])
        self.assertEqual(self.apply(user='vendor').status_code, 409)
        self.assertEqual(self.store.data[(storage.USERS, 'vendor')], before)
        self.apply()
        self.assertEqual(self.decide(user='customer').status_code, 403)
        self.assertEqual(self.request('GET', '/admin/shop-applications').status_code, 403)
        self.assertEqual(len(self.request('GET', '/admin/shop-applications', user='admin').json), 1)
        self.store.data[(storage.USERS, 'customer')]['is_suspended'] = True
        self.assertEqual(self.decide().status_code, 403)
        self.store.data[(storage.USERS, 'customer')].pop('is_suspended')
        self.store.data[(storage.USERS, 'customer')]['role'] = 'admin'
        self.assertEqual(self.decide().status_code, 403)

    def test_input_validation_and_missing_or_inactive_city(self):
        for content in ([], {}, {**self.content, 'role': 'vendor'}, {**self.content, 'shop_name': ' '},
                        {**self.content, 'phone': 1}, {**self.content, 'city_id': 'bad/id'},
                        {**self.content, 'city_id': 'missing'}):
            before = copy.deepcopy(self.store.data)
            self.assertEqual(self.apply(content).status_code, 422)
            self.assertEqual(self.store.data, before)
        self.store.data[(storage.CITIES, 'city')]['is_active'] = False
        self.assertEqual(self.apply().status_code, 422)
        self.store.data[(storage.CITIES, 'city')]['is_active'] = True
        self.apply()
        for revision in (True, 0, '1', None):
            self.assertEqual(self.decide(revision=revision).status_code, 422)
        self.assertEqual(self.decide(decision=[]).status_code, 422)
        del self.store.data[(storage.CITIES, 'city')]
        self.assertEqual(self.decide().status_code, 409)
        self.assertEqual(self.decide('rejected', reason='Unavailable city').status_code, 200)

    def test_missing_applicant_and_application(self):
        self.assertEqual(self.decide().status_code, 404)
        self.apply()
        del self.store.data[(storage.USERS, 'customer')]
        self.assertEqual(self.decide().status_code, 403)

    def test_atomic_submission_and_decision_rollback(self):
        before = copy.deepcopy(self.store.data)
        self.store.fail_commit = True
        with self.assertRaisesRegex(RuntimeError, 'simulated write failure'):
            self.apply()
        self.assertEqual(self.store.data, before)
        self.store.fail_commit = False
        self.apply()
        before = copy.deepcopy(self.store.data)
        self.store.fail_commit = True
        with self.assertRaisesRegex(RuntimeError, 'simulated write failure'):
            self.decide()
        self.assertEqual(self.store.data, before)

    def test_concurrent_approval_is_single_effect(self):
        self.apply()
        def approve(_):
            with self.app.test_client() as client:
                return client.post('/admin/shop-applications/customer/decision',
                                   json={'decision': 'approved', 'revision': 1},
                                   headers={'Authorization': 'Bearer admin'}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(list(pool.map(approve, range(2))), [200, 200])
        self.assertEqual(self.count(storage.NOTIFICATIONS), 1)
        self.assertEqual(self.count(storage.AUDIT_LOGS), 2)


if __name__ == '__main__':
    unittest.main()
