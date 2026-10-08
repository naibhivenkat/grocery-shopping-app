"""Atomic registration uniqueness and OTP consumption without provider access."""
import copy
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from flask import Flask
import auth_utils
import db as storage
from routes import auth
from test_khata import Query, Ref
from test_core_routes import CoreStore


class RegistrationTests(unittest.TestCase):
    def setUp(self):
        self.store = CoreStore()
        self.app = Flask(__name__)
        self.app.config["TESTING"] = True
        self.app.register_blueprint(auth.auth_bp)
        def update_ref(ref, data):
            ref.store.data[ref.key] = {**ref.store.data[ref.key], **copy.deepcopy(data)}
        patches = [patch.object(auth, "col", self.store.col), patch.object(auth, "doc", self.store.doc),
                   patch.object(auth, "db", lambda: self.store),
                   patch.object(auth.firestore, "transactional", self.store.transactional),
                   patch.object(Query, "limit", lambda query, count: query, create=True),
                   patch.object(Ref, "update", update_ref, create=True)]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        self.client = self.app.test_client()

    def register(self, path="/auth/register", **extra):
        return self.client.post(path, json={"email": "alice@example.test", "username": "alice", "password": "strong-password", **extra})

    def otp(self, email="alice@example.test", verified=True, expired=False, **extra):
        ref = auth._otp_ref(email)
        self.store.data[ref.key] = {"email": email, "verified": verified,
            "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=-10 if expired else 10)).isoformat(), **extra}
        return ref

    def users(self):
        return [data for (name, _), data in self.store.data.items() if name == storage.USERS]

    def test_legacy_registration_requires_no_otp_and_password_is_verbatim(self):
        password = " strong-password "
        response = self.register(password=password, email=" Alice@Example.Test ")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json["user"]["email"], "alice@example.test")
        self.assertNotIn("password_hash", response.json["user"])
        self.assertTrue(response.json["access_token"])
        self.assertTrue(auth_utils.verify_password(password, self.users()[0]["password_hash"]))
        self.assertFalse(auth_utils.verify_password(password.strip(), self.users()[0]["password_hash"]))
        self.assertEqual(sum(name == "auth_identifiers" for name, _ in self.store.data), 2)

    def test_public_roles_never_grant_administrative_access(self):
        for index, role in enumerate(("customer", "vendor", "service", "shopkeeper", "admin", "super_admin")):
            response = self.register(email=f"person{index}@example.test", username=f"person{index}", role=role)
            self.assertEqual(response.status_code, 201)
            expected = "vendor" if role == "shopkeeper" else "customer" if role in {"admin", "super_admin"} else role
            self.assertEqual(response.json["user"]["role"], expected)

    def test_invalid_bounded_email_username_password_and_other_fields(self):
        for email in ("invalid", "a@b", "a..b@example.test", ".alice@example.test", "a@-domain.test", "a@domain_.test", "x" * 65 + "@example.test"):
            self.assertEqual(self.register(email=email).status_code, 422)
        for username in ("ab", "...", "has space", "bad/slash", "x" * 65, []):
            self.assertEqual(self.register(username=username).status_code, 422)
        for password in ("short", "x" * 129, None, []):
            self.assertEqual(self.register(password=password).status_code, 422)
        self.assertEqual(self.register(full_name="x" * 201).status_code, 422)
        self.assertEqual(self.register(phone="x" * 41).status_code, 422)
        self.assertEqual(self.register(city_id="bad/id").status_code, 422)
        self.assertEqual(self.client.post("/auth/register", json=[]).status_code, 422)
        self.assertEqual(self.users(), [])

    def test_default_username_supports_short_and_plus_address_local_part(self):
        first = self.register(email="ab@example.test", username=None)
        second = self.register(email="alice+shop@example.test", username=None)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(first.json["user"]["username"], "ab_user")
        self.assertEqual(second.status_code, 201)
        self.assertEqual(second.json["user"]["username"], "alice_shop")

    def test_legacy_user_email_username_checked_without_rewriting_accounts(self):
        existing = {"email": "alice@example.test", "username": "legacy_name", "role": "vendor", "full_name": "Preserved"}
        self.store.data[(storage.USERS, "legacy")] = copy.deepcopy(existing)
        self.assertEqual(self.register().status_code, 422)
        self.assertEqual(self.register(email="new@example.test", username="legacy_name").status_code, 422)
        self.assertEqual(self.store.data[(storage.USERS, "legacy")], existing)
        self.assertEqual(len(self.users()), 1)

    def test_duplicate_registration_does_not_replace_original(self):
        first = self.register()
        original = copy.deepcopy(self.users()[0])
        self.assertEqual(self.register(password="different-password").status_code, 422)
        self.assertEqual(self.register(email="different@example.test").status_code, 422)
        self.assertEqual(self.users(), [original])
        self.assertEqual(first.json["user"]["role"], "customer")

    def test_otp_aliases_require_verified_unexpired_same_email_registration_otp(self):
        for path in ("/auth/register_after_otp", "/register_after_otp"):
            self.assertEqual(self.register(path).status_code, 400)
        for options in ({"verified": False}, {"expired": True}, {"purpose": "password_reset"}):
            self.otp(**options)
            self.assertEqual(self.register("/auth/register_after_otp").status_code, 400)
            self.assertEqual(self.users(), [])
        ref = self.otp()
        self.store.data[ref.key]["email"] = "other@example.test"
        self.assertEqual(self.register("/auth/register_after_otp").status_code, 400)
        self.otp()
        self.assertEqual(self.register("/register_after_otp").status_code, 201)
        self.assertNotIn(auth._otp_ref("alice@example.test").key, self.store.data)

    def test_otp_creation_and_consumption_are_atomic(self):
        ref = self.otp()
        self.store.fail_commit = True
        before = copy.deepcopy(self.store.data)
        with self.assertRaises(RuntimeError):
            self.register("/auth/register_after_otp")
        self.assertEqual(self.store.data, before)
        self.assertIn(ref.key, self.store.data)
        self.store.fail_commit = False
        self.assertEqual(self.register("/auth/register_after_otp").status_code, 201)
        self.assertNotIn(ref.key, self.store.data)

    def test_duplicate_username_does_not_consume_verified_otp(self):
        self.store.data[(storage.USERS, "legacy")] = {"email": "old@example.test", "username": "alice", "role": "customer"}
        ref = self.otp()
        self.assertEqual(self.register("/auth/register_after_otp").status_code, 422)
        self.assertIn(ref.key, self.store.data)
        self.assertEqual(len(self.users()), 1)

    def test_concurrent_duplicate_email_and_username_creation_is_once_only(self):
        def create(index):
            with self.app.test_client() as client:
                return client.post("/auth/register", json={"email": "shared@example.test", "username": f"user{index}", "password": "strong-password"}).status_code
        with ThreadPoolExecutor(max_workers=4) as pool:
            statuses = list(pool.map(create, range(8)))
        self.assertEqual(statuses.count(201), 1)
        self.assertEqual(statuses.count(422), 7)
        self.assertEqual(len(self.users()), 1)
        self.store.data.clear()
        def same_username(index):
            with self.app.test_client() as client:
                return client.post("/auth/register", json={"email": f"user{index}@example.test", "username": "shared", "password": "strong-password"}).status_code
        with ThreadPoolExecutor(max_workers=4) as pool:
            statuses = list(pool.map(same_username, range(8)))
        self.assertEqual(statuses.count(201), 1)
        self.assertEqual(len(self.users()), 1)

    def google(self, email="alice@example.test", role="customer"):
        identity = {"uid": "firebase-alice", "email": email, "email_verified": True, "name": "Google Alice"}
        with patch.object(auth.firebase_auth, "verify_id_token", return_value=identity):
            return self.client.post("/auth/google", json={"id_token": "test-verified-token", "role": role})

    def test_google_signup_uses_same_reservations_and_unique_username_suffix(self):
        self.store.data[(storage.USERS, "legacy")] = {"email": "old@example.test", "username": "alice", "role": "customer"}
        response = self.google()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["user"]["username"], "alice2")
        self.assertEqual(sum(name == "auth_identifiers" for name, _ in self.store.data), 2)
        self.assertEqual(self.register(username="different").status_code, 422)

    def test_google_stale_precheck_cannot_create_duplicate_of_password_registration(self):
        response = self.register(role="vendor")
        original = copy.deepcopy(self.users()[0])
        snapshot = self.store.doc(storage.USERS, response.json["user"]["uid"]).get()
        with patch.object(auth, "_find_user_by_email", side_effect=[None, snapshot]):
            google = self.google(role="customer")
        self.assertEqual(google.status_code, 200)
        self.assertEqual(google.json["user"]["uid"], response.json["user"]["uid"])
        self.assertEqual(google.json["user"]["role"], "vendor")
        self.assertEqual(self.users(), [original])

    def test_google_existing_user_keeps_role_username_and_existing_profile(self):
        self.store.data[(storage.USERS, "legacy")] = {"email": "alice@example.test", "username": "legacy_username", "role": "vendor",
            "full_name": "Existing Name", "avatar_url": "https://example.test/avatar", "firebase_id": "firebase-alice", "auth_provider": "google"}
        before = copy.deepcopy(self.store.data)
        response = self.google(role="customer")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["user"]["role"], "vendor")
        self.assertEqual(self.store.data, before)

    def test_stale_reservation_reclaimed_without_modifying_prior_user(self):
        self.store.data[(storage.USERS, "prior")] = {"email": "new@example.test", "username": "new_username", "role": "customer"}
        reservation = auth._identifier_reservation("email", "alice@example.test")
        self.store.data[reservation.key] = {"user_id": "prior", "kind": "email", "value": "alice@example.test"}
        before = copy.deepcopy(self.store.data[(storage.USERS, "prior")])
        self.assertEqual(self.register().status_code, 201)
        self.assertEqual(self.store.data[(storage.USERS, "prior")], before)
        self.assertNotEqual(self.store.data[reservation.key]["user_id"], "prior")


if __name__ == "__main__":
    unittest.main()
