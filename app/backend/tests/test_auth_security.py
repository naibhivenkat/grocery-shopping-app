"""Auth regression tests using mocked document and identity providers."""
from datetime import datetime, timedelta, timezone
import os
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
import jwt
from flask import Flask, g, jsonify
import auth_utils
import routes.auth as routes
from test_payment_security import Store


def snapshot(exists=True, role='customer', **fields):
    return SimpleNamespace(exists=exists, id='u', to_dict=lambda: {'role': role, **fields})

class AuthSecurityTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        @self.app.get('/protected')
        @auth_utils.require_auth
        def protected(): return jsonify({'role': g.user_role, 'uid': g.user_id})
        @self.app.get('/admin')
        @auth_utils.require_role('admin')
        def admin(): return jsonify({'ok': True})
        self.app.register_blueprint(routes.auth_bp)
        self.client = self.app.test_client()
        self.headers = {'Authorization': 'Bearer ' + auth_utils.create_token('u', 'admin')}
    def test_deleted_account_cannot_use_claimed_admin_role(self):
        with patch('db.doc', return_value=SimpleNamespace(get=lambda: snapshot(exists=False))):
            self.assertEqual(self.client.get('/admin', headers=self.headers).status_code, 401)
    def test_database_unavailable_fails_closed(self):
        with patch('db.doc', side_effect=RuntimeError('unavailable')):
            self.assertEqual(self.client.get('/admin', headers=self.headers).status_code, 503)
    def test_stored_role_wins_over_signed_stale_admin_claim(self):
        with patch('db.doc', return_value=SimpleNamespace(get=lambda: snapshot(role='customer'))):
            self.assertEqual(self.client.get('/admin', headers=self.headers).status_code, 403)
    def test_missing_role_never_falls_back_to_admin_claim(self):
        with patch('db.doc', return_value=SimpleNamespace(get=lambda: snapshot(role=None))):
            response = self.client.get('/protected', headers=self.headers)
            self.assertEqual(response.json['role'], 'customer')
    def test_suspended_account_blocked(self):
        with patch('db.doc', return_value=SimpleNamespace(get=lambda: snapshot(is_suspended=True))):
            self.assertEqual(self.client.get('/protected', headers=self.headers).status_code, 403)
    def test_missing_subject_is_401(self):
        token = jwt.encode({'exp': datetime.now(timezone.utc)+timedelta(hours=1)}, auth_utils.JWT_SECRET, algorithm='HS256')
        self.assertEqual(self.client.get('/protected', headers={'Authorization': 'Bearer '+token}).status_code, 401)
    def test_firebase_verified_uid_maps_to_backend_account_and_stored_role(self):
        users = MagicMock(); users.where.return_value.limit.return_value.stream.return_value = [snapshot(role='vendor')]
        with patch.object(auth_utils.firebase_auth, 'verify_id_token', return_value={'uid': 'firebase_u'} ) as verify, patch.object(auth_utils, 'col', return_value=users):
            response = self.client.get('/protected', headers={'Authorization': 'Bearer firebase-token'})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json, {'uid': 'u', 'role': 'vendor'})
            verify.assert_called_once_with('firebase-token', check_revoked=True)
    def test_old_jwt_invalid_after_password_reset(self):
        with patch('db.doc', return_value=SimpleNamespace(get=lambda: snapshot(password_reset_at=(datetime.now(timezone.utc)+timedelta(seconds=10)).isoformat()))):
            self.assertEqual(self.client.get('/protected', headers=self.headers).status_code, 401)
    def test_public_role_normalization_prevents_admin_registration(self):
        for role in ('admin', 'super_admin', ' ADMIN '):
            self.assertEqual(routes._normalize_role(role), 'customer')
        self.assertEqual(routes._normalize_role('shopkeeper'), 'vendor')
    def test_production_otp_without_delivery_configuration_fails(self):
        with patch.dict(os.environ, {'FLASK_ENV': 'production'}, clear=True):
            with self.assertRaises(RuntimeError): routes._send_otp_email('test@example.test', '123456')
    def test_password_reset_uses_reset_namespace_and_rejects_registration_otp(self):
        ref = SimpleNamespace(get=lambda: SimpleNamespace(exists=True, to_dict=lambda: {'purpose': 'registration'}))
        with patch.object(routes, '_password_reset_otp_ref', return_value=ref) as reset_ref, patch.object(routes, '_otp_ref') as registration_ref:
            response = self.client.post('/auth/reset_password', json={'email':'test@example.test','otp':'123456','new_password':'new-password'})
            self.assertEqual(response.status_code, 400)
            reset_ref.assert_called_once_with('test@example.test')
            registration_ref.assert_not_called()
    def test_malformed_auth_json_is_validation_error(self):
        for payload in (['not-an-object'], {'email':123, 'password':'password'}):
            self.assertEqual(self.client.post('/auth/login', json=payload).status_code, 422)

    def test_otp_failed_attempts_lock_after_five_and_correct_code_cannot_bypass(self):
        store = Store({('auth_otps','x'):{'otp_hash':auth_utils.hash_password('123456'),
            'expires_at':(datetime.now(timezone.utc)+timedelta(minutes=10)).isoformat()}})
        ref = store.doc('auth_otps','x')
        with patch.object(routes, 'db', return_value=store), patch.object(routes.firestore, 'transactional', lambda fn:fn):
            for _ in range(5):
                self.assertEqual(routes._check_otp(ref,'000000')[2],400)
            self.assertEqual(routes._check_otp(ref,'123456')[2],429)
            self.assertEqual(store.data[ref.key]['failed_attempts'],5)
    def test_otp_resend_cooldown_preserves_current_code(self):
        store = Store({}); ref = store.doc('auth_otps','x')
        data = {'otp_hash':'original','created_at':datetime.now(timezone.utc).isoformat()}
        with patch.object(routes,'db',return_value=store), patch.object(routes.firestore,'transactional',lambda fn:fn):
            self.assertTrue(routes._save_otp(ref,data))
            self.assertFalse(routes._save_otp(ref,{**data,'otp_hash':'replacement'}))
            self.assertEqual(store.data[ref.key]['otp_hash'],'original')
    def test_reset_atomically_consumes_otp_and_cannot_replay(self):
        store = Store({('auth_otps','reset'):{'purpose':'password_reset','otp_hash':auth_utils.hash_password('123456'),
            'expires_at':(datetime.now(timezone.utc)+timedelta(minutes=10)).isoformat()},
            ('users','u'):{'role':'customer','password_hash':auth_utils.hash_password('old-password')}})
        ref=store.doc('auth_otps','reset')
        with patch.object(routes,'db',return_value=store), patch.object(routes,'doc',store.doc), patch.object(routes.firestore,'transactional',lambda fn:fn), patch.object(routes,'_password_reset_otp_ref',return_value=ref), patch.object(routes,'_find_user_by_email',return_value=store.doc('users','u').get()):
            payload={'email':'test@example.test','otp':'123456','new_password':'new-password'}
            self.assertEqual(self.client.post('/auth/reset_password',json=payload).status_code,200)
            self.assertNotIn(ref.key,store.data)
            self.assertTrue(auth_utils.verify_password('new-password',store.data[('users','u')]['password_hash']))
            self.assertEqual(self.client.post('/auth/reset_password',json=payload).status_code,400)

    def test_google_requires_verified_email(self):
        with patch.object(routes.firebase_auth, 'verify_id_token', return_value={'uid':'firebase_u', 'email':'test@example.test', 'email_verified':False}):
            self.assertEqual(self.client.post('/auth/google', json={'id_token':'token','role':'admin'}).status_code, 422)

if __name__ == '__main__': unittest.main()
