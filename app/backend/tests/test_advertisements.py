"""Admin advertisement CRUD/feed proof against strict isolated transactions."""
import copy
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import db as storage
from routes import advertisements as ads
import test_orders_api as fixture


class AdvertisementsTests(unittest.TestCase):
    def setUp(self):
        fixture.OrdersTests.setUp(self)
        self.app.register_blueprint(ads.advertisements_bp)
        self.store.data[(storage.USERS, 'admin')] = {'role': 'admin'}
        self.store.data[(storage.USERS, 'super')] = {'role': 'super_admin'}
        for name, value in (('doc', self.store.doc), ('col', self.store.col), ('db', lambda: self.store)):
            current = patch.object(ads, name, value)
            current.start()
            self.addCleanup(current.stop)
        now = datetime.now(timezone.utc)
        self.content = {'title': 'Welcome', 'body': 'Discover local shops',
                        'image_url': 'https://firebasestorage.googleapis.com/v0/b/example/o/ad.jpg?alt=media&token=public',
                        'starts_at': (now - timedelta(hours=1)).isoformat(),
                        'ends_at': (now + timedelta(days=1)).isoformat(), 'is_active': True, 'priority': 10}

    def request(self, method, path, body=None, user='admin'):
        return self.client.open(path, method=method, json=body,
                                headers={'Authorization': 'Bearer ' + user} if user else {})

    def create(self, **changes):
        return self.request('POST', '/admin/advertisements', {**self.content, **changes})

    def active(self, user='customer'):
        return self.request('GET', '/advertisements/active', user=user)

    def test_create_public_projection_and_separate_collection(self):
        self.assertIsNone(self.active().json)
        created = self.create()
        self.assertEqual(created.status_code, 201)
        identifier = created.json['uid']
        self.assertEqual(created.json['revision'], 1)
        self.assertEqual(created.json['created_by'], 'admin')
        public = self.active().json
        self.assertEqual(set(public), ads.PUBLIC_FIELDS)
        self.assertEqual(public['uid'], identifier)
        self.assertEqual(public['image_url'], self.content['image_url'])
        self.assertNotIn('created_by', public)
        self.assertEqual(sum(name == 'promotions' for name, _ in self.store.data), 0)
        self.assertEqual(self.request('GET', '/admin/advertisements').json[0]['uid'], identifier)

    def test_only_highest_priority_current_active_ad_with_stable_id_tie(self):
        first = self.create().json
        second = self.create().json
        self.assertEqual(self.active().json['uid'], min(first['uid'], second['uid']))
        high = self.create(priority=100).json
        self.assertEqual(self.active().json['uid'], high['uid'])
        self.create(priority=999, is_active=False)
        now = datetime.now(timezone.utc)
        self.create(priority=999, starts_at=(now + timedelta(days=1)).isoformat(), ends_at=(now + timedelta(days=2)).isoformat())
        self.create(priority=999, starts_at=(now - timedelta(days=2)).isoformat(), ends_at=(now - timedelta(days=1)).isoformat())
        self.assertEqual(self.active().json['uid'], high['uid'])

    def test_update_revision_activation_and_delete_are_audited(self):
        created = self.create().json
        path = '/admin/advertisements/' + created['uid']
        updated = self.request('PUT', path, {'revision': 1, 'title': 'Updated', 'is_active': False}, user='super')
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json['revision'], 2)
        self.assertEqual(updated.json['created_by'], 'admin')
        self.assertEqual(updated.json['updated_by'], 'super')
        self.assertIsNone(self.active().json)
        before = copy.deepcopy(self.store.data)
        self.assertEqual(self.request('PUT', path, {'revision': 1, 'is_active': True}).status_code, 409)
        self.assertEqual(self.store.data, before)
        deleted = self.request('DELETE', path, {'revision': 2})
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(self.request('DELETE', path, {'revision': 2}).json, deleted.json)
        self.assertEqual(self.request('GET', '/admin/advertisements').json, [])
        self.assertIsNone(self.active().json)
        self.assertEqual(self.request('PUT', path, {'revision': 3, 'is_active': True}).status_code, 404)
        actions = [value['action'] for (name, _), value in self.store.data.items() if name == storage.AUDIT_LOGS]
        self.assertEqual(actions, ['advertisement_created', 'advertisement_updated', 'advertisement_deleted'])

    def test_roles_deleted_and_suspended_accounts_cannot_write_or_read_feed(self):
        for user, status in ((None, 401), ('customer', 403), ('vendor', 403)):
            self.assertEqual(self.request('POST', '/admin/advertisements', self.content, user=user).status_code, status)
            self.assertEqual(self.request('GET', '/admin/advertisements', user=user).status_code, status)
        self.assertEqual(self.active(user=None).status_code, 401)
        self.store.data[(storage.USERS, 'admin')]['is_suspended'] = True
        self.assertEqual(self.create().status_code, 403)
        self.store.data[(storage.USERS, 'customer')]['is_suspended'] = True
        self.assertEqual(self.active().status_code, 403)
        del self.store.data[(storage.USERS, 'admin')]
        self.assertEqual(self.create().status_code, 401)
        self.assertEqual(sum(name == ads.ADVERTISEMENTS for name, _ in self.store.data), 0)

    def test_content_validation_and_timezone_normalization(self):
        for changes in ({'title': ''}, {'title': ['x']}, {'body': 'x' * 1001}, {'image_url': 'javascript:alert(1)'},
                        {'image_url': None}, {'image_url': 'https://user:pass@example.com/ad.png'},
                        {'image_url': 'http://example.com/ad.png'}, {'image_url': 'https://example.com/ad.png#fragment'},
                        {'starts_at': '2026-10-15'}, {'ends_at': self.content['starts_at']},
                        {'priority': True}, {'priority': -1}, {'priority': 1001}, {'is_active': 1}, {'role': 'admin'}):
            with self.subTest(changes=changes):
                self.assertEqual(self.create(**changes).status_code, 422)
        starts = datetime.now(timezone(timedelta(hours=5, minutes=30))) - timedelta(hours=1)
        created = self.create(starts_at=starts.isoformat())
        self.assertEqual(created.status_code, 201)
        self.assertEqual(datetime.fromisoformat(created.json['starts_at']), starts)
        self.assertTrue(created.json['starts_at'].endswith('+00:00'))

    def test_malformed_persisted_ad_is_hidden_without_breaking_valid_one(self):
        valid = self.create().json
        for number, changes in enumerate(({'priority': False}, {'ends_at': 'invalid'}, {'revision': True},
                                         {'image_url': 'file:///etc/passwd'}, {'deleted_at': 'now'})):
            self.store.data[(ads.ADVERTISEMENTS, f'broken-{number}')] = {**self.content, 'revision': 1, **changes}
        self.assertEqual(self.active().json['uid'], valid['uid'])

    def test_missing_revision_unknown_fields_and_missing_records(self):
        created = self.create().json
        path = '/admin/advertisements/' + created['uid']
        for body in ({'is_active': False}, {'revision': True, 'is_active': False}, {'revision': 1},
                     {'revision': 1, 'created_by': 'other'}, {'revision': 0, 'title': 'X'}):
            self.assertEqual(self.request('PUT', path, body).status_code, 422)
        self.assertEqual(self.request('DELETE', path, {}).status_code, 422)
        self.assertEqual(self.request('PUT', '/admin/advertisements/missing', {'revision': 1, 'is_active': False}).status_code, 404)
        self.assertEqual(self.request('DELETE', '/admin/advertisements/missing', {'revision': 1}).status_code, 404)

    def test_concurrent_revision_updates_and_commit_rollback(self):
        identifier = self.create().json['uid']
        path = '/admin/advertisements/' + identifier
        def update(title):
            with self.app.test_client() as client:
                return client.put(path, json={'revision': 1, 'title': title},
                                  headers={'Authorization': 'Bearer admin'}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(update, ('First', 'Second'))), [200, 409])
        before = copy.deepcopy(self.store.data)
        self.store.fail_commit = True
        with self.assertRaisesRegex(RuntimeError, 'simulated write failure'):
            self.request('PUT', path, {'revision': 2, 'is_active': False})
        self.assertEqual(self.store.data, before)


if __name__ == '__main__':
    unittest.main()
