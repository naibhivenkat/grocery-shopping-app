"""All password signup aliases consume a verified signup OTP."""
import copy
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
import test_auth_registration as fixtures
from routes import auth


class RegistrationOtpBoundaryTests(unittest.TestCase):
    setUp = fixtures.RegistrationTests.setUp
    register = fixtures.RegistrationTests.register
    otp = fixtures.RegistrationTests.otp
    users = fixtures.RegistrationTests.users

    def test_aliases_reject_missing_unverified_expired_wrong_email_and_purpose(self):
        for path in ('/auth/register', '/auth/register_after_otp', '/register_after_otp'):
            for options in (None, {'verified': False}, {'expired': True}, {'purpose': 'password_reset'}, {'email': 'other@example.test'}):
                self.store.data.clear()
                if options is not None:
                    if options.get('email'):
                        ref = self.otp()
                        self.store.data[ref.key]['email'] = options['email']
                    else:
                        self.otp(**options)
                before = copy.deepcopy(self.store.data)
                response = self.register(path)
                self.assertEqual(response.status_code, 400, (path, options))
                self.assertNotIn('token', response.json)
                self.assertEqual(self.store.data, before)
                self.assertEqual(self.users(), [])

    def test_aliases_and_roles_consume_once_and_reject_replay(self):
        for path in ('/auth/register', '/auth/register_after_otp', '/register_after_otp'):
            for role in ('customer', 'vendor', 'service'):
                self.store.data.clear()
                ref = self.otp()
                response = self.register(path, role=role)
                self.assertEqual(response.status_code, 201, (path, role, response.json))
                self.assertEqual(response.json['user']['role'], role)
                self.assertNotIn(ref.key, self.store.data)
                self.assertNotEqual(self.register(path, email='other@example.test', username='other').status_code, 201)
                self.assertEqual(len(self.users()), 1)

    def test_verified_challenge_proof_is_caller_bound_rotated_and_consumed(self):
        ref = self.otp(verified=False, otp_hash=auth.hash_password('123456'))
        first = self.client.post('/auth/verify_otp', json={'email': 'alice@example.test', 'otp': '123456'})
        self.assertEqual(first.status_code, 200)
        proof = first.json['registration_proof']
        self.assertNotIn(proof, str(self.store.data[ref.key]))
        for path in ('/auth/register', '/auth/register_after_otp', '/register_after_otp'):
            for candidate in (None, '', 'wrong'):
                response = self.register(path, registration_proof=candidate)
                self.assertEqual(response.status_code, 400)
                self.assertNotIn('token', response.json)
                self.assertEqual(self.users(), [])
        second = self.client.post('/auth/verify_otp', json={'email': 'alice@example.test', 'otp': '123456'})
        self.assertEqual(second.status_code, 200)
        self.assertEqual(self.register(registration_proof=proof).status_code, 400)
        self.assertEqual(self.register(registration_proof=second.json['registration_proof']).status_code, 201)
        self.assertNotIn(ref.key, self.store.data)
        self.assertNotEqual(self.register(registration_proof=second.json['registration_proof']).status_code, 201)

    def test_verify_returns_stored_nondefault_expiry_on_both_aliases_and_reverification(self):
        now = datetime(2030, 1, 1, 12, 0, tzinfo=timezone.utc)
        with patch.object(auth, '_utcnow', return_value=now), \
             patch.object(auth, '_OTP_TTL_MINUTES', 37), \
             patch.object(auth, '_send_otp_email') as send:
            response = self.client.post('/auth/send_otp', json={'email': 'alice@example.test'})
            self.assertEqual(response.status_code, 200)
            otp = send.call_args.args[1]
            ref = auth._otp_ref('alice@example.test')
            stored = self.store.data[ref.key]['expires_at']
            self.assertEqual(stored, (now + timedelta(minutes=37)).isoformat())
            first = self.client.post('/auth/verify_otp', json={'email': 'alice@example.test', 'otp': otp})
            self.assertEqual(first.status_code, 200)
            self.assertEqual(first.json['expires_at'], stored)
            with patch.object(auth, '_utcnow', return_value=now + timedelta(minutes=5)):
                second = self.client.post('/verify_otp', json={'email': 'alice@example.test', 'otp': otp})
            self.assertEqual(second.status_code, 200)
            self.assertEqual(second.json['expires_at'], stored)
            self.assertNotEqual(first.json['registration_proof'], second.json['registration_proof'])

    def test_invalid_or_equal_expiry_fails_closed_for_verification_and_consumption(self):
        now = datetime(2030, 1, 1, 12, 0, tzinfo=timezone.utc)
        for expiry in (None, 'invalid', '2030-01-01T12:30:00', now.isoformat()):
            for path in ('/auth/verify_otp', '/verify_otp'):
                self.store.data.clear()
                ref = self.otp(verified=False, otp_hash=auth.hash_password('123456'))
                if expiry is None:
                    del self.store.data[ref.key]['expires_at']
                else:
                    self.store.data[ref.key]['expires_at'] = expiry
                with patch.object(auth, '_utcnow', return_value=now):
                    response = self.client.post(path, json={'email': 'alice@example.test', 'otp': '123456'})
                self.assertEqual(response.status_code, 400, (path, expiry))
                self.assertNotIn('registration_proof', response.json)
            self.store.data.clear()
            ref = self.otp()
            if expiry is None:
                del self.store.data[ref.key]['expires_at']
            else:
                self.store.data[ref.key]['expires_at'] = expiry
            with patch.object(auth, '_utcnow', return_value=now):
                response = self.register()
            self.assertEqual(response.status_code, 400, expiry)
            self.assertEqual(self.users(), [])

    def test_verify_normalizes_stored_offset_to_utc(self):
        now = datetime(2030, 1, 1, 12, 0, tzinfo=timezone.utc)
        self.otp(verified=False, otp_hash=auth.hash_password('123456'),
                 expires_at='2030-01-01T18:00:00+05:30')
        with patch.object(auth, '_utcnow', return_value=now):
            response = self.client.post('/verify_otp', json={'email': 'alice@example.test', 'otp': '123456'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['expires_at'], '2030-01-01T12:30:00+00:00')

    def test_atomic_failure_and_concurrent_reservation(self):
        ref = self.otp()
        before = copy.deepcopy(self.store.data)
        self.store.fail_commit = True
        with self.assertRaises(RuntimeError):
            self.register()
        self.assertEqual(self.store.data, before)
        self.store.fail_commit = False
        def create(index):
            with self.app.test_client() as client:
                return client.post('/auth/register', json={'email': 'alice@example.test', 'username': f'user{index}', 'password': 'strong-password', 'registration_proof': 'test-proof'}).status_code
        with ThreadPoolExecutor(max_workers=4) as pool:
            statuses = list(pool.map(create, range(4)))
        self.assertEqual(statuses.count(201), 1)
        self.assertEqual(len(self.users()), 1)
        self.assertNotIn(ref.key, self.store.data)
