"""HTTP authorization contract for the optional legacy service inbox."""
import unittest
from unittest.mock import MagicMock, patch

from flask import Flask
from firebase_admin import firestore
import auth_utils
import db as storage

# The legacy helper constructs a client at import time; no provider is contacted.
with patch.object(firestore, 'client', return_value=MagicMock()):
    import service_notifications_routes as routes


class LegacyNotificationAuthTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config['TESTING'] = True
        self.app.register_blueprint(routes.service_notifications_bp)
        self.client = self.app.test_client()
        self.records = {'own': {'provider_id': 'alice', 'is_read': False},
                        'foreign': {'provider_id': 'bob', 'is_read': False}}
        self.db = MagicMock()
        def document(identifier):
            ref = MagicMock()
            ref.identifier = identifier
            ref.get.side_effect = lambda **kwargs: self.snapshot(identifier)
            return ref
        self.db.collection.return_value.document.side_effect = document
        def stream():
            docs = []
            for identifier, record in self.records.items():
                if record['provider_id'] == 'alice' and not record['is_read']:
                    snap = self.snapshot(identifier)
                    snap.reference = document(identifier)
                    docs.append(snap)
            return docs
        self.db.collection.return_value.where.return_value.where.return_value.stream.side_effect = stream
        tx = self.db.transaction.return_value
        tx.update.side_effect = lambda ref, value: self.records[ref.identifier].update(value)
        def user_doc(collection, identifier):
            snap = MagicMock()
            snap.exists = identifier in ('alice', 'bob')
            snap.id = identifier
            snap.to_dict.return_value = {'role': 'customer'}
            return snap
        patches = [patch.object(storage, 'doc', side_effect=lambda c, i: MagicMock(get=lambda: user_doc(c, i))),
                   patch.object(auth_utils, 'decode_token', side_effect=lambda token: {'sub': token}),
                   patch.object(routes, 'db', self.db),
                   patch.object(routes.firestore, 'transactional', side_effect=lambda fn: fn),
                   patch.object(routes, 'get_service_notifications', side_effect=lambda owner: [v for v in self.records.values() if v['provider_id'] == owner]),
                   patch.object(routes, 'get_unread_service_notification_count', side_effect=lambda owner: sum(not v['is_read'] for v in self.records.values() if v['provider_id'] == owner))]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def snapshot(self, identifier):
        snap = MagicMock()
        snap.exists = identifier in self.records
        snap.to_dict.return_value = self.records.get(identifier)
        return snap

    def mark_all(self, owner):
        for record in self.records.values():
            if record['provider_id'] == owner:
                record['is_read'] = True

    def call(self, method, path, body=None, user='alice'):
        headers = {'Authorization': 'Bearer ' + user} if user else {}
        return self.client.open(path, method=method, json=body, headers=headers)

    def test_all_routes_require_authentication(self):
        for method, path, body in [('GET', '/service/notifications?provider_id=alice', None),
                                   ('GET', '/service/notifications/unread-count?provider_id=alice', None),
                                   ('POST', '/service/notifications/mark-read', {'notification_id': 'own'}),
                                   ('POST', '/service/notifications/mark-all-read', {'provider_id': 'alice'})]:
            with self.subTest(path=path):
                self.assertEqual(self.call(method, path, body, user=None).status_code, 401)
        self.assertFalse(self.records['own']['is_read'])

    def test_list_count_and_bulk_are_scoped(self):
        for path in ('/service/notifications', '/service/notifications/unread-count'):
            self.assertEqual(self.call('GET', path + '?provider_id=bob').status_code, 403)
            self.assertEqual(self.call('GET', path).status_code, 400)
            self.assertEqual(self.call('GET', path + '?provider_id=alice').status_code, 200)
        self.assertEqual(len(self.call('GET', '/service/notifications?provider_id=alice').json), 1)
        self.assertEqual(self.call('GET', '/service/notifications/unread-count?provider_id=alice').json['unread'], 1)
        self.assertEqual(self.call('POST', '/service/notifications/mark-all-read', {'provider_id': 'bob'}).status_code, 403)
        self.assertEqual(self.call('POST', '/service/notifications/mark-all-read', {}).status_code, 400)
        self.assertEqual(self.call('POST', '/service/notifications/mark-all-read', {'provider_id': 'alice'}).status_code, 200)
        self.assertTrue(self.records['own']['is_read'])
        self.assertFalse(self.records['foreign']['is_read'])

    def test_single_read_checks_record_owner_and_missing(self):
        path = '/service/notifications/mark-read'
        for body, status in [({}, 400), ({'notification_id': '../x'}, 400),
                             ({'notification_id': 'missing'}, 404), ({'notification_id': 'foreign'}, 403)]:
            self.assertEqual(self.call('POST', path, body).status_code, status)
        self.assertFalse(self.records['foreign']['is_read'])
        self.assertEqual(self.call('POST', path, {'notification_id': 'own'}).status_code, 200)
        self.assertTrue(self.records['own']['is_read'])

    def test_bulk_rechecks_ownership_after_query(self):
        ref = MagicMock()
        ref.identifier = 'foreign'
        ref.get.return_value = self.snapshot('foreign')
        queried = MagicMock(reference=ref)
        self.db.collection.return_value.where.return_value.where.return_value.stream.return_value = [queried]
        self.db.collection.return_value.where.return_value.where.return_value.stream.side_effect = None
        self.assertEqual(self.call('POST', '/service/notifications/mark-all-read', {'provider_id': 'alice'}).status_code, 200)
        self.assertFalse(self.records['foreign']['is_read'])
        self.db.transaction.return_value.update.assert_not_called()

    def test_default_registration_is_disabled(self):
        import main
        app = Flask(__name__)
        with patch.dict('os.environ', {}, clear=True), patch('importlib.import_module') as loader:
            main._register_legacy_blueprints(app)
        loader.assert_not_called()
        self.assertNotIn('service_notifications', app.blueprints)


if __name__ == '__main__':
    unittest.main()
