"""Boot and boundary checks without credentials, Firestore or provider calls."""
import unittest
from unittest.mock import patch

import main


class AppContractTests(unittest.TestCase):
    def setUp(self):
        self.client = main.create_app().test_client()

    def test_health_and_feature_contract(self):
        self.assertEqual(self.client.get('/health').json, {'status': 'healthy'})
        features = self.client.get('/features').json
        self.assertFalse(features['wallet_enabled'])
        self.assertTrue(features['promotions_enabled'])
        self.assertEqual(features['promotion_billing'], 'free')

    def test_disabled_wallet_never_reaches_storage(self):
        with patch('db.db', side_effect=AssertionError('Unexpected database access')):
            for method, route in [('GET','/wallet'), ('GET','/wallet/transactions'),
                                  ('POST','/wallet/deduct'), ('POST','/wallet/refund'),
                                  ('POST','/service-wallet/withdraw')]:
                response = self.client.open(route, method=method, json={})
                self.assertEqual(response.status_code, 410)
                self.assertEqual(response.json['code'], 'WALLET_DISABLED')

    def test_mutating_smoke_test_is_disabled(self):
        with patch('db.db', side_effect=AssertionError('Unexpected database access')):
            self.assertEqual(self.client.get('/debug/smoke-test').status_code, 404)

    def test_protected_features_require_authentication(self):
        for method, route in [('GET','/khata/ledgers'), ('POST','/khata/transactions'),
                              ('POST','/orders'), ('GET','/promotions/mine'),
                              ('GET','/promotions/admin'), ('POST','/razorpayApi/orders'),
                              ('POST','/razorpayApi/verify'), ('GET','/profile'),
                              ('GET','/admin/stats'), ('GET','/inventory'),
                              ('GET','/chat/rooms'), ('GET','/notifications'),
                              ('GET','/provider/profile'), ('GET','/bookings')]:
            with self.subTest(route=route):
                self.assertEqual(self.client.open(route,method=method,json={}).status_code,401)

    def test_array_or_invalid_json_is_validation_error(self):
        for body in ('[]','{"bad":'):
            response=self.client.post('/auth/login',data=body,content_type='application/json')
            self.assertEqual(response.status_code,422)

    def test_existing_apk_empty_action_body_reaches_authentication(self):
        response = self.client.post('/bookings/test-only/cancel',
                                    content_type='application/json')
        self.assertEqual(response.status_code, 401)

    def test_profile_cannot_unsuspend_or_change_identity(self):
        with patch('auth_utils.decode_token',return_value={'sub':'user'}), patch('db.doc') as document:
            document.return_value.get.return_value.exists=True
            document.return_value.get.return_value.to_dict.return_value={'role':'customer'}
            for fields in ({'is_suspended':False}, {'firebase_id':'another'}, {'password_reset_at':None}, {'role':'admin'}):
                response=self.client.put('/profile',json=fields,headers={'Authorization':'Bearer test-only'})
                self.assertEqual(response.status_code,422)

    def test_route_errors_keep_http_status(self):
        self.assertEqual(self.client.get('/no-such-route').status_code,404)
        self.assertEqual(self.client.delete('/health').status_code,405)


if __name__ == '__main__':
    unittest.main()
