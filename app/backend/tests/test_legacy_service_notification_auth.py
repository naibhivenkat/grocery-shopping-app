"""HTTP contract for the optional legacy service inbox without identity mapping."""
import unittest
from unittest.mock import MagicMock, patch
from flask import Flask
from firebase_admin import firestore
import auth_utils
import db as storage
import service_notifications_routes as routes


class LegacyNotificationAuthTests(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.config['TESTING'] = True
        app.register_blueprint(routes.service_notifications_bp)
        self.client = app.test_client()
        def user_doc(collection, identifier):
            snap = MagicMock()
            snap.exists = identifier in ('alice', 'bob')
            snap.id = identifier
            snap.to_dict.return_value = {'role': 'customer'}
            return snap
        patches = [patch.object(storage, 'doc', side_effect=lambda c, i: MagicMock(get=lambda: user_doc(c, i))),
                   patch.object(auth_utils, 'decode_token', side_effect=lambda token: {'sub': token})]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def call(self, method, path, body=None, user='alice'):
        headers = {'Authorization': 'Bearer ' + user} if user else {}
        return self.client.open(path, method=method, json=body, headers=headers)

    @staticmethod
    def requests(provider):
        return [('GET', '/service/notifications?provider_id=' + provider, None),
                ('GET', '/service/notifications/unread-count?provider_id=' + provider, None),
                ('POST', '/service/notifications/mark-read', {'notification_id': 'collision'}),
                ('POST', '/service/notifications/mark-all-read', {'provider_id': provider})]

    def test_all_routes_require_authentication(self):
        for method, path, body in self.requests('alice'):
            with self.subTest(path=path):
                self.assertEqual(self.call(method, path, body, user=None).status_code, 401)

    def test_cross_namespace_collision_and_foreign_rejected_without_storage_access(self):
        # A legacy provider named alice may be a different person from user alice.
        with patch.object(firestore, 'client') as collection:
            for provider in ('alice', 'bob'):
                for method, path, body in self.requests(provider):
                    with self.subTest(provider=provider, path=path):
                        self.assertEqual(self.call(method, path, body).status_code, 403)
            collection.assert_not_called()

    def test_missing_and_invalid_inputs_also_fail_closed(self):
        for method, path, body in [('GET', '/service/notifications', None),
                                    ('GET', '/service/notifications/unread-count', None),
                                    ('POST', '/service/notifications/mark-read', {'notification_id': 'missing'}),
                                    ('POST', '/service/notifications/mark-read', {}),
                                    ('POST', '/service/notifications/mark-all-read', {})]:
            with self.subTest(path=path, body=body):
                self.assertEqual(self.call(method, path, body).status_code, 403)

    def test_default_registration_is_disabled(self):
        import main
        app = Flask(__name__)
        with patch.dict('os.environ', {}, clear=True), patch('importlib.import_module') as loader:
            main._register_legacy_blueprints(app)
        loader.assert_not_called()
        self.assertNotIn('service_notifications', app.blueprints)


if __name__ == '__main__':
    unittest.main()
