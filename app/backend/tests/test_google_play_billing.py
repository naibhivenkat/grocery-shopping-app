"""Local provider doubles and strict atomic storage, never real purchases."""
import base64
import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import os
import threading
import unittest
from unittest.mock import Mock, patch

from flask import Flask
import auth_utils
import db as storage
import google_play_billing as billing
from routes import google_play as routes
from test_core_routes import CoreStore
from test_khata import Ref, Snapshot


NOW = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
START = (NOW - timedelta(days=1)).isoformat()
END = (NOW + timedelta(days=30)).isoformat()
ACCOUNT = "a" * 64
TOKEN = "test-provider-token-local-only"


def purchase(*, state="ACTIVE", account=ACCOUNT, product="vendor_pro", base="monthly", ack=False, end=END):
    return {"subscriptionState": "SUBSCRIPTION_STATE_" + state, "startTime": START,
            "acknowledgementState": "ACKNOWLEDGEMENT_STATE_ACKNOWLEDGED" if ack else "ACKNOWLEDGEMENT_STATE_PENDING",
            "externalAccountIdentifiers": {"obfuscatedExternalAccountId": account},
            "lineItems": [{"productId": product, "expiryTime": end, "offerDetails": {"basePlanId": base},
                           "autoRenewingPlan": {"autoRenewEnabled": state != "CANCELED"}}]}


class ProviderTests(unittest.TestCase):
    def parse(self, data):
        return billing.parse_subscription(data, product_id="vendor_pro", base_plan_id="monthly", billing_account_id=ACCOUNT, now=NOW)

    def test_active_grace_and_canceled_use_provider_period_not_client_duration(self):
        for state, expected in [("ACTIVE", "active"), ("IN_GRACE_PERIOD", "grace"), ("CANCELED", "canceled")]:
            result = self.parse(purchase(state=state))
            self.assertEqual(result["provider_state"], expected)
            self.assertEqual(result["ends_at"], END)
            self.assertEqual(result["grace_ends_at"], END if state == "IN_GRACE_PERIOD" else None)
        self.assertEqual(self.parse(purchase(end=(NOW - timedelta(seconds=1)).isoformat()))["provider_state"], "expired")

    def test_hold_pause_pending_and_canceled_pending_are_never_active(self):
        for state, expected in [("ON_HOLD", "hold"), ("PAUSED", "paused"), ("PENDING", "pending"),
                                ("PENDING_PURCHASE_CANCELED", "pending_canceled"), ("EXPIRED", "expired")]:
            self.assertEqual(self.parse(purchase(state=state))["provider_state"], expected)
        data = purchase(state="PENDING")
        data.pop("startTime")
        data["lineItems"][0].pop("expiryTime")
        self.assertIsNone(self.parse(data)["ends_at"])

    def test_wrong_account_product_baseplan_and_duplicate_matching_lines_are_rejected(self):
        for data in [purchase(account="b" * 64), purchase(product="foreign"), purchase(base="annual")]:
            with self.assertRaises(billing.PlayBillingError):
                self.parse(data)
        data = purchase()
        data["lineItems"] *= 2
        with self.assertRaises(billing.PlayBillingError):
            self.parse(data)

    def test_invalid_provider_state_period_and_account_shapes_fail_closed(self):
        cases = [dict(purchase(), subscriptionState="FUTURE_STATE"), dict(purchase(), startTime="2026-10-20"),
                 dict(purchase(), externalAccountIdentifiers="bad"), dict(purchase(), acknowledgementState="unknown"),
                 dict(purchase(), lineItems=[]), dict(purchase(), startTime=END)]
        for data in cases:
            with self.assertRaises(billing.PlayBillingError):
                self.parse(data)

    def test_deferred_future_product_does_not_grant_future_features(self):
        data = purchase(product="old_product")
        data["lineItems"][0]["deferredItemReplacement"] = {"productId": "vendor_pro"}
        with self.assertRaises(billing.PlayBillingError) as caught:
            self.parse(data)
        self.assertEqual(caught.exception.code, "BILLING_REPLACEMENT_PENDING")

    def test_out_of_app_expired_account_binding_and_linked_token_are_retained(self):
        data = purchase()
        data.pop("externalAccountIdentifiers")
        data["outOfAppPurchaseContext"] = {"expiredExternalAccountIdentifiers": {"obfuscatedExternalAccountId": ACCOUNT},
                                           "expiredPurchaseToken": "old-expired-local-token"}
        self.assertEqual(self.parse(data)["expired_purchase_token"], "old-expired-local-token")
        self.assertTrue(self.parse(data)["needs_account_rebinding"])
        self.assertFalse(self.parse(purchase())["needs_account_rebinding"])
        data["externalAccountIdentifiers"] = {"obfuscatedExternalAccountId": ACCOUNT}
        self.assertFalse(self.parse(data)["needs_account_rebinding"])

    def test_server_config_is_disabled_by_default_and_requires_package_and_push_identity(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(billing.PlayBillingError):
                billing.PlayConfig.from_env()
        with patch.dict(os.environ, {"GOOGLE_PLAY_BILLING_ENABLED": "true", "GOOGLE_PLAY_PACKAGE_NAME": "com.alllocal.app"}, clear=True):
            self.assertEqual(billing.PlayConfig.from_env().package_name, "com.alllocal.app")
            with self.assertRaises(billing.PlayBillingError):
                billing.PlayConfig.from_env(rtdn=True)

    def test_http_uses_server_package_encoded_token_and_bounded_no_redirect_requests(self):
        session = Mock()
        session.request.return_value = Mock(status_code=200, content=b"{}")
        session.request.return_value.json.return_value = purchase()
        client = billing.GooglePlayClient(billing.PlayConfig("com.alllocal.app"), session)
        client.get_subscription("local/token?no-secrets")
        args, kwargs = session.request.call_args
        self.assertIn("/com.alllocal.app/purchases/subscriptionsv2/tokens/local%2Ftoken%3Fno-secrets", args[1])
        self.assertEqual(kwargs["timeout"], (5, 20))
        self.assertFalse(kwargs["allow_redirects"])
        client.acknowledge(TOKEN, "vendor_pro")
        self.assertEqual(session.request.call_args.args[0], "POST")
        self.assertEqual(session.request.call_args.kwargs["json"], {})

    def test_resubscription_ack_can_rebind_verified_account(self):
        session = Mock()
        session.request.return_value = Mock(status_code=200, content=b"")
        client = billing.GooglePlayClient(billing.PlayConfig("com.alllocal.app"), session)
        client.acknowledge(TOKEN, "vendor_pro", billing_account_id=ACCOUNT)
        self.assertEqual(session.request.call_args.kwargs["json"], {"externalAccountIds": {"obfuscatedAccountId": ACCOUNT}})

    def test_http_credentials_errors_timeouts_and_provider_bodies_never_leak_tokens(self):
        session = Mock()
        client = billing.GooglePlayClient(billing.PlayConfig("com.alllocal.app"), session)
        for status in [401, 403, 404, 410, 429, 500, 400, 302]:
            session.request.return_value = Mock(status_code=status, text=TOKEN)
            with self.assertRaises(billing.PlayBillingError) as caught:
                client.get_subscription(TOKEN)
            self.assertNotIn(TOKEN, str(caught.exception))
        session.request.side_effect = RuntimeError("provider failed " + TOKEN)
        with self.assertRaises(billing.PlayBillingError) as caught:
            client.get_subscription(TOKEN)
        self.assertNotIn(TOKEN, str(caught.exception))

    def test_push_checks_signature_audience_issuer_and_expected_verified_service_account(self):
        config = billing.PlayConfig("com.alllocal.app", rtdn_audience="https://example.test/rtdn",
                                    rtdn_push_email="push@project.iam.gserviceaccount.com")
        good = {"iss": "https://accounts.google.com", "aud": config.rtdn_audience,
                "email": config.rtdn_push_email, "email_verified": True}
        with patch.object(billing.id_token, "verify_oauth2_token", return_value=good) as verify:
            self.assertEqual(billing.verify_push_identity("Bearer local-oidc-test", config), good)
            self.assertEqual(verify.call_args.kwargs["audience"], config.rtdn_audience)
        for changed in [{"iss": "attacker"}, {"aud": "other"}, {"email": "other@project.iam.gserviceaccount.com"},
                        {"email_verified": False}, {"email_verified": "true"}]:
            with patch.object(billing.id_token, "verify_oauth2_token", return_value={**good, **changed}):
                with self.assertRaises(billing.PlayBillingError):
                    billing.verify_push_identity("Bearer local-oidc-test", config)
        with patch.object(billing.id_token, "verify_oauth2_token", side_effect=ValueError()):
            with self.assertRaises(billing.PlayBillingError):
                billing.verify_push_identity("Bearer invalid", config)


class GoogleRef(Ref):
    def set(self, data, merge=False):
        self.store.data[self.key] = {**self.store.data.get(self.key, {}), **copy.deepcopy(data)} if merge else copy.deepcopy(data)


class GoogleQuery:
    def __init__(self, store, collection, filters=(), maximum=None):
        self.store, self.collection, self.filters, self.maximum = store, collection, filters, maximum

    def where(self, *, filter):
        return GoogleQuery(self.store, self.collection, self.filters + ((filter.field_path, filter.op_string, filter.value),), self.maximum)

    def limit(self, value):
        return GoogleQuery(self.store, self.collection, self.filters, value)

    def stream(self):
        rows = []
        for (collection, identifier), data in list(self.store.data.items()):
            if collection != self.collection:
                continue
            def matches(field, op, value):
                actual = data.get(field)
                return actual == value if op == "==" else actual is not None and actual <= value
            if all(matches(*f) for f in self.filters):
                rows.append(Snapshot(GoogleRef(self.store, collection, identifier), data))
        return rows[:self.maximum] if self.maximum is not None else rows

    def document(self, identifier=None):
        if identifier is None:
            self.store.next_id += 1
            identifier = "google_auto_" + str(self.store.next_id)
        return GoogleRef(self.store, self.collection, identifier)


class GoogleStore(CoreStore):
    def col(self, collection):
        return GoogleQuery(self, collection)


class FakeProvider:
    def __init__(self):
        self.purchases = {TOKEN: purchase()}
        self.gets, self.acks, self.ack_bindings = [], [], []
        self.failure, self.ack_failure = None, None
        self.entered, self.resume = None, None

    def get_subscription(self, token):
        self.gets.append(token)
        if self.entered:
            self.entered.set()
            self.resume.wait(timeout=5)
        if self.failure:
            raise self.failure
        return copy.deepcopy(self.purchases[token])

    def acknowledge(self, token, product, *, billing_account_id=None):
        self.acks.append((token, product))
        self.ack_bindings.append(billing_account_id)
        if self.ack_failure == "before":
            raise billing.PlayBillingError("Timeout", retryable=True)
        self.purchases[token]["acknowledgementState"] = "ACKNOWLEDGEMENT_STATE_ACKNOWLEDGED"
        if billing_account_id:
            self.purchases[token]["externalAccountIdentifiers"] = {"obfuscatedExternalAccountId": billing_account_id}
        if self.ack_failure == "after":
            raise billing.PlayBillingError("Timeout", retryable=True)


class GoogleRoutesTests(unittest.TestCase):
    def setUp(self):
        self.store, self.provider = GoogleStore(), FakeProvider()
        self.calls, self.markers = [], {}
        self.accounts = {"vendor": ACCOUNT, "other_vendor": "b" * 64}
        self.versions = {"request": {"uid": "version", "price_paise": 10000, "renewal_rule": "store",
                                    "google_play": {"product_id": "vendor_pro", "base_plan_id": "monthly"}}}
        self.store.data = {(storage.USERS, "vendor"): {"role": "vendor"},
                           (storage.USERS, "other_vendor"): {"role": "vendor"},
                           (storage.USERS, "customer"): {"role": "customer"},
                           (storage.USERS, "admin"): {"role": "admin"}}
        self.app = Flask(__name__)
        self.app.config["TESTING"] = True
        self.app.register_blueprint(routes.google_play_bp)
        self.env = {"GOOGLE_PLAY_BILLING_ENABLED": "true", "GOOGLE_PLAY_PACKAGE_NAME": "com.alllocal.app",
                    "GOOGLE_PLAY_RTDN_AUDIENCE": "https://example.test/rtdn",
                    "GOOGLE_PLAY_RTDN_PUSH_EMAIL": "push@project.iam.gserviceaccount.com",
                    "GOOGLE_PLAY_RTDN_SUBSCRIPTION": "projects/project/subscriptions/play-events"}
        patches = [patch.dict(os.environ, self.env), patch.object(storage, "doc", self.store.doc),
            patch.object(auth_utils, "decode_token", lambda token: {"sub": token}),
            patch.object(routes, "doc", self.store.doc), patch.object(routes, "col", self.store.col),
            patch.object(routes, "db", lambda: self.store), patch.object(routes.firestore, "transactional", self.store.transactional),
            patch.object(routes, "_core_call", side_effect=self.core), patch.object(routes, "GooglePlayClient", lambda config: self.provider),
            patch.object(routes, "_now", return_value=NOW), patch.object(routes, "verify_push_identity", return_value={})]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        self.clock = patch.object(billing, "datetime", wraps=datetime).start()
        self.clock.now.return_value = NOW
        self.addCleanup(patch.stopall)
        self.client = self.app.test_client()

    def core(self, name, vendor, *args, **kwargs):
        if name == "prepare_google_play_checkout":
            return {"request": {"uid": args[0]}, "plan_version": self.versions[args[0]], "billing_account_id": self.accounts[vendor]}
        if name == "apply_verified_store_state":
            self.calls.append((vendor, copy.deepcopy(kwargs)))
            event = kwargs["event_id"]
            if event not in self.markers:
                self.markers[event] = {"vendor_id": vendor, "status": "active" if kwargs["provider_state"] in {"active", "grace", "canceled"} else "expired",
                                       "plan_version_id": kwargs["plan_version_id"], "payment_state": "store_verified"}
            self.store.data[("vendor_subscription_accounts", vendor)] = {"store_purchase_fingerprint": kwargs["purchase_fingerprint"]}
            return self.markers[event]
        if name == "entitlements":
            return getattr(self, "current_entitlement", None) or list(self.markers.values())[-1]
        raise AssertionError(name)

    def post(self, path, body=None, *, user="vendor", key="local-key-0001"):
        return self.client.post(path, json=body, headers={"Authorization": "Bearer " + user, "Idempotency-Key": key})

    def prepare(self, request_id="request", user="vendor"):
        return self.post("/subscriptions/google-play/checkout-context", {"request_id": request_id}, user=user)

    def verify(self, token=TOKEN, request_id="request", key="verify-local-0001", user="vendor"):
        body = {"purchase_token": token}
        if request_id is not None:
            body["request_id"] = request_id
        return self.post("/subscriptions/google-play/verify", body, user=user, key=key)

    def notification(self, *, mid="message-local-1", kind="subscriptionNotification", token=TOKEN, notification_type=4):
        data = {"version": "1.0", "packageName": "com.alllocal.app", "eventTimeMillis": "1792497600000",
                kind: {"version": "1.0", "notificationType": notification_type, "purchaseToken": token}}
        return {"message": {"messageId": mid, "data": base64.b64encode(json.dumps(data).encode()).decode()},
                "subscription": self.env["GOOGLE_PLAY_RTDN_SUBSCRIPTION"]}

    def test_purchase_requires_prepared_approved_context_and_never_accepts_client_paid_fields(self):
        self.assertEqual(self.verify().status_code, 409)
        self.assertFalse(self.calls)
        self.assertEqual(self.prepare().status_code, 200)
        bad = self.post("/subscriptions/google-play/verify", {"purchase_token": TOKEN, "paid": True})
        self.assertEqual(bad.status_code, 422)
        self.assertEqual(self.verify().status_code, 200)
        self.assertEqual(self.calls[-1][1]["provider_state"], "active")
        self.assertEqual(self.provider.acks, [(TOKEN, "vendor_pro")])
        self.assertEqual(self.provider.ack_bindings, [None])

    def test_successful_key_replay_has_no_provider_or_grant_side_effect_and_changed_payload_conflicts(self):
        self.prepare()
        first = self.verify()
        counts = len(self.provider.gets), len(self.provider.acks), len(self.calls)
        second = self.verify()
        self.assertEqual(first.json, second.json)
        self.assertEqual(counts, (len(self.provider.gets), len(self.provider.acks), len(self.calls)))
        self.assertEqual(self.verify(token="changed-local-token").status_code, 409)

    def test_checkout_replay_revalidates_revoked_request_and_verify_replay_refreshes_admin_access(self):
        self.prepare()
        original = self.core
        def revoked(name, *args, **kwargs):
            if name == "prepare_google_play_checkout":
                raise billing.PlayBillingError("Request is no longer approved", 409, "REQUEST_NOT_APPROVED")
            return original(name, *args, **kwargs)
        with patch.object(routes, "_core_call", side_effect=revoked):
            self.assertEqual(self.prepare().status_code, 409)
        self.verify()
        self.current_entitlement = {"status": "suspended", "capabilities": {"catalog_growth": False}}
        self.assertEqual(self.verify().json["entitlements"]["status"], "suspended")

    def test_cross_account_token_replay_and_wrong_product_never_apply(self):
        self.prepare()
        self.verify()
        self.assertEqual(self.verify(user="other_vendor", key="foreign-local-1").status_code, 403)
        self.provider.purchases["wrong-product-local-token"] = purchase(product="foreign")
        self.assertEqual(self.verify(token="wrong-product-local-token", key="wrong-product-key").status_code, 409)
        self.assertEqual(len(self.calls), 1)

    def test_failed_account_claim_does_not_poison_token_ownership(self):
        self.prepare()
        self.provider.purchases[TOKEN] = purchase(account=self.accounts["other_vendor"])
        self.assertEqual(self.verify().status_code, 403)
        self.assertNotIn("vendor_id", self.store.data[(routes.TOKENS, routes._hash(TOKEN))])
        self.assertEqual(self.prepare(user="other_vendor").status_code, 200)
        self.assertEqual(self.verify(user="other_vendor", key="right-owner-key").status_code, 200)
        self.assertEqual(self.calls[-1][0], "other_vendor")

    def test_pending_purchase_and_prepaid_do_not_grant_access_or_acknowledge(self):
        self.prepare()
        self.provider.purchases[TOKEN] = purchase(state="PENDING")
        response = self.verify()
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json["provider_state"], "pending")
        self.assertFalse(self.calls)
        self.assertFalse(self.provider.acks)
        self.provider.purchases[TOKEN] = purchase()
        self.provider.purchases[TOKEN]["lineItems"][0].pop("autoRenewingPlan")
        self.assertEqual(self.verify(key="prepaid-local-key").json["code"], "BILLING_PLAN_UNSUPPORTED")
        self.assertFalse(self.calls)

    def test_test_purchases_are_separate_explicitly_allowlisted_and_marked(self):
        self.prepare()
        self.provider.purchases[TOKEN]["testPurchase"] = {}
        self.assertEqual(self.verify().json["code"], "BILLING_TEST_PURCHASE_DISABLED")
        with patch.dict(os.environ, {"GOOGLE_PLAY_TEST_VENDOR_IDS": "vendor"}):
            result = self.verify()
        self.assertEqual(result.status_code, 200)
        self.assertTrue(result.json["test_purchase"])
        self.assertTrue(self.calls[-1][1]["test_purchase"])

    def test_ack_timeout_after_success_is_reconciled_without_second_purchase(self):
        self.prepare()
        self.provider.ack_failure = "after"
        response = self.verify()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["acknowledgement_state"], "ACKNOWLEDGEMENT_STATE_ACKNOWLEDGED")
        self.assertEqual(len(self.provider.acks), 1)

    def test_ack_failure_journal_resumes_same_core_event_after_process_recovery(self):
        self.prepare()
        self.provider.ack_failure = "before"
        response = self.verify()
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json["code"], "BILLING_ACKNOWLEDGEMENT_PENDING")
        first = self.calls[0][1]
        self.assertIsNotNone(self.store.data[(routes.TOKENS, routes._hash(TOKEN))]["pending_transition"])
        self.provider.ack_failure = None
        self.assertEqual(self.verify().status_code, 200)
        self.assertEqual(self.calls[1][1]["event_id"], first["event_id"])
        self.assertEqual(self.calls[1][1]["source_revision"], first["source_revision"])
        self.assertIsNone(self.store.data[(routes.TOKENS, routes._hash(TOKEN))]["pending_transition"])

    def test_provider_outage_persists_retry_and_does_not_create_entitlement(self):
        self.prepare()
        self.provider.failure = billing.PlayBillingError("Temporarily unavailable", retryable=True)
        self.assertEqual(self.verify().status_code, 503)
        self.assertFalse(self.calls)
        token = self.store.data[(routes.TOKENS, routes._hash(TOKEN))]
        self.assertEqual(token["status"], "retry")
        self.assertIn((routes.WORK, "token_" + routes._hash(TOKEN)), self.store.data)

    def test_concurrent_receipt_verification_is_fenced_before_provider_response(self):
        self.prepare()
        self.provider.entered, self.provider.resume = threading.Event(), threading.Event()
        with ThreadPoolExecutor(max_workers=2) as pool:
            future = pool.submit(self.verify)
            self.assertTrue(self.provider.entered.wait(timeout=2))
            second = pool.submit(self.verify, key="concurrent-2").result(timeout=2)
            self.assertEqual(second.status_code, 409)
            self.provider.resume.set()
            self.assertEqual(future.result(timeout=3).status_code, 200)
        self.assertEqual(len(self.calls), 1)

    def test_rtdn_is_durable_deduplicated_and_fetches_current_state_instead_of_event_type(self):
        self.prepare()
        body = self.notification(notification_type=999)
        for _ in range(2):
            self.assertEqual(self.client.post("/webhooks/google-play/rtdn", json=body).status_code, 204)
        events = [v for (c, _), v in self.store.data.items() if c == routes.EVENTS]
        self.assertEqual(len(events), 1)
        self.assertFalse(self.calls)
        self.provider.purchases[TOKEN] = purchase(state="EXPIRED", ack=True, end=(NOW - timedelta(seconds=1)).isoformat())
        result = routes.reconcile_google_play(client=self.provider)
        self.assertEqual(result["completed"], 1)
        self.assertEqual(self.calls[-1][1]["provider_state"], "expired")

    def test_old_cancellation_notification_cannot_override_current_active_provider_state(self):
        self.prepare()
        self.client.post("/webhooks/google-play/rtdn", json=self.notification(notification_type=3))
        routes.reconcile_google_play(client=self.provider)
        self.assertEqual(self.calls[-1][1]["provider_state"], "active")

    def test_worker_rechecks_fresh_due_time_to_skip_obsolete_queued_token_snapshot(self):
        self.prepare()
        self.client.post("/webhooks/google-play/rtdn", json=self.notification())
        self.store.data[(routes.TOKENS, routes._hash(TOKEN))] = {"purchase_token": TOKEN}
        self.store.data[(routes.WORK, "token_" + routes._hash(TOKEN))] = routes._work_data("token", routes._hash(TOKEN))
        response = routes.reconcile_google_play(client=self.provider)
        self.assertEqual(response["processed"], 1)
        self.assertEqual(len(self.provider.gets), 1)

    def test_retry_backoff_survives_claim_and_invalid_work_is_quarantined(self):
        self.prepare()
        self.provider.failure = billing.PlayBillingError("Offline", retryable=True)
        self.assertEqual(self.verify().status_code, 503)
        key = (routes.WORK, "token_" + routes._hash(TOKEN))
        self.assertEqual(self.store.data[key]["attempts"], 1)
        with patch.object(routes, "_now", return_value=NOW + timedelta(seconds=30)):
            routes.reconcile_google_play(client=self.provider)
        self.assertEqual(self.store.data[key]["attempts"], 2)
        self.store.data[(routes.WORK, "invalid_work")] = routes._work_data("token", "nonexistent")
        routes.reconcile_google_play(client=self.provider)
        self.assertNotIn((routes.WORK, "invalid_work"), self.store.data)
        self.assertEqual(self.store.data[("google_play_work_failures", "invalid_work")]["status"], "requires_review")

    def test_authenticated_push_failure_never_persists_an_event(self):
        with patch.object(routes, "verify_push_identity", side_effect=billing.PlayBillingError("Unauthorized", 401, "BILLING_PUSH_UNAUTHORIZED")):
            self.assertEqual(self.client.post("/webhooks/google-play/rtdn", json=self.notification()).status_code, 401)
        self.assertFalse(any(c == routes.EVENTS for c, _ in self.store.data))

    def test_rtdn_envelope_scope_and_reused_message_identity_are_checked(self):
        body = self.notification()
        bad = {**body, "subscription": "projects/other/subscriptions/attacker"}
        self.assertEqual(self.client.post("/webhooks/google-play/rtdn", json=bad).status_code, 403)
        bad = {**body, "message": {"messageId": "bad", "data": "not-base64"}}
        self.assertEqual(self.client.post("/webhooks/google-play/rtdn", json=bad).status_code, 422)
        self.assertEqual(self.client.post("/webhooks/google-play/rtdn", json=body).status_code, 204)
        changed = self.notification(notification_type=12)
        self.assertEqual(self.client.post("/webhooks/google-play/rtdn", json=changed).status_code, 409)

    def test_refund_and_revocation_notifications_reconcile_v2_not_client_claims(self):
        self.prepare()
        self.verify()
        self.provider.purchases[TOKEN] = purchase(state="EXPIRED", ack=True, end=(NOW - timedelta(seconds=1)).isoformat())
        self.client.post("/webhooks/google-play/rtdn", json=self.notification(kind="voidedPurchaseNotification"))
        routes.reconcile_google_play(client=self.provider)
        self.assertEqual(self.calls[-1][1]["provider_state"], "expired")

    def test_replacement_modes_require_verified_auto_renewing_prior_and_no_independent_double_subscription(self):
        self.prepare()
        self.verify()
        context = {"vendor_id": "vendor", "product_id": "vendor_pro", "base_plan_id": "annual"}
        same = routes._replacement(context)
        self.assertEqual(same["replacement_mode"], "WITHOUT_PRORATION")
        cross = routes._replacement({**context, "product_id": "vendor_premium"})
        self.assertEqual(cross["replacement_mode"], "WITH_TIME_PRORATION")
        self.provider.purchases["second-subscription-local-token"] = purchase()
        response = self.verify(token="second-subscription-local-token", key="no-double-subscription")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json["code"], "BILLING_REPLACEMENT_REQUIRED")
        self.assertEqual(len(self.calls), 1)

    def test_legitimate_linked_replacement_retains_owner_and_frozen_mapping(self):
        self.prepare()
        self.verify()
        newer = "replacement-local-token"
        self.provider.purchases[newer] = {**purchase(), "linkedPurchaseToken": TOKEN}
        response = self.verify(token=newer, key="replacement-local-key")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.calls[-1][1]["linked_purchase_fingerprint"], routes._hash(TOKEN))

    def test_linked_token_owned_by_another_vendor_is_rejected_before_central_transition(self):
        self.prepare()
        old_token = "other-vendor-old-token"
        self.store.data[(routes.TOKENS, routes._hash(old_token))] = {"vendor_id": "other_vendor"}
        self.provider.purchases[TOKEN]["linkedPurchaseToken"] = old_token
        self.assertEqual(self.verify().status_code, 403)
        self.assertFalse(self.calls)

    def test_restore_out_of_app_resubscription_uses_expired_owned_token_and_retains_binding_after_ack(self):
        self.prepare()
        self.verify()
        self.provider.purchases[TOKEN] = purchase(state="EXPIRED", ack=True, end=(NOW - timedelta(seconds=1)).isoformat())
        self.verify(key="expire-before-restore")
        newer = "out-of-app-local-token"
        data = purchase()
        data.pop("externalAccountIdentifiers")
        data["outOfAppPurchaseContext"] = {"expiredPurchaseToken": TOKEN,
            "expiredExternalAccountIdentifiers": {"obfuscatedExternalAccountId": ACCOUNT}}
        self.provider.purchases[newer] = data
        original = self.core
        def fulfilled(name, *args, **kwargs):
            if name == "prepare_google_play_checkout":
                raise billing.PlayBillingError("Request was already fulfilled", 409, "REQUEST_NOT_APPROVED")
            return original(name, *args, **kwargs)
        with patch.object(routes, "_core_call", side_effect=fulfilled):
            response = self.verify(token=newer, request_id=None, key="outofapp-restore-key")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.provider.ack_bindings, [None, ACCOUNT])
        self.assertIsNone(self.calls[-1][1]["request_id"])
        self.assertEqual(self.calls[-1][1]["linked_purchase_fingerprint"], routes._hash(TOKEN))
        self.provider.purchases[newer].pop("outOfAppPurchaseContext")
        restored = self.verify(token=newer, request_id=None, key="restore-after-ack-key")
        self.assertEqual(restored.status_code, 200)

    def test_deferred_provider_replacement_keeps_old_features_until_actual_switch(self):
        self.prepare()
        self.verify()
        self.versions["upgrade"] = {**self.versions["request"], "uid": "premium_version",
                                    "google_play": {"product_id": "vendor_premium", "base_plan_id": "monthly"}}
        self.assertEqual(self.post("/subscriptions/google-play/checkout-context", {"request_id": "upgrade"}, key="prepare-upgrade-key").status_code, 200)
        newer = "deferred-local-token"
        data = {**purchase(ack=False), "linkedPurchaseToken": TOKEN}
        data["lineItems"][0]["deferredItemReplacement"] = {"productId": "vendor_premium"}
        self.provider.purchases[newer] = data
        pending = self.verify(token=newer, request_id="upgrade", key="deferred-key-1")
        self.assertEqual(pending.status_code, 202)
        self.assertEqual(pending.json["provider_state"], "pending_replacement")
        self.assertEqual(self.calls[-1][1]["plan_version_id"], "version")
        self.assertIsNone(self.calls[-1][1]["request_id"])
        self.provider.purchases[newer] = {**purchase(product="vendor_premium", ack=True), "linkedPurchaseToken": TOKEN}
        applied = self.verify(token=newer, request_id="upgrade", key="deferred-key-2")
        self.assertEqual(applied.status_code, 200)
        self.assertEqual(self.calls[-1][1]["plan_version_id"], "premium_version")
        self.assertEqual(self.calls[-1][1]["request_id"], "upgrade")

    def test_real_core_transition_preserves_suspension_and_complimentary_override(self):
        import subscription_service as core
        version = {**self.versions["request"], "plan_id": "pro", "version": 1, "currency": "INR", "duration_days": 30,
                   "trial_days": 0, "grace_days": 0,
                   "entitlements": {"max_items": 50, "catalog_growth": True, "product_import": True, "promotions": True}}
        self.store.data.update({
            (core.PLANS, "pro"): {"name": "Pro", "revision": 1, "current_version_id": "version", "is_active": True},
            (core.VERSIONS, "version"): {k: v for k, v in version.items() if k != "uid"},
            (core.REQUESTS, "request"): {"vendor_id": "vendor", "plan_id": "pro", "plan_version_id": "version",
                                         "status": "approved_checkout", "revision": 1},
            (core.ACCOUNTS, "vendor"): {**core._empty_account("vendor"), "current_grant_id": "complimentary",
                                       "access_state": "suspended", "pending_request_id": "request"},
            (core.GRANTS, "complimentary"): {"vendor_id": "vendor", "kind": "complimentary", "plan_id": "pro",
                "plan_version_id": "version", "plan_name": "Pro", "payment_state": "not_charged",
                "starts_at": START, "ends_at": END, "grace_ends_at": END, "terms_snapshot": version}})
        patches = [patch.object(core, "doc", self.store.doc), patch.object(core, "col", self.store.col),
                   patch.object(core, "db", lambda: self.store), patch.object(core, "deliver_push"),
                   patch.object(core.firestore, "transactional", self.store.transactional),
                   patch.object(core, "_now", return_value=NOW),
                   patch.object(routes, "_core_call", side_effect=lambda name, *a, **k: getattr(core, name)(*a, **k))]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.accounts["vendor"] = routes._hash("alllocal:vendor-billing:vendor")
        self.provider.purchases[TOKEN] = purchase(account=self.accounts["vendor"])
        self.assertEqual(self.prepare().status_code, 200)
        response = self.verify()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["entitlements"]["status"], "suspended")
        account = self.store.data[(core.ACCOUNTS, "vendor")]
        self.assertEqual(account["current_grant_id"], "complimentary")
        self.assertNotEqual(account["store_grant_id"], "complimentary")
        self.assertEqual(self.store.data[(core.GRANTS, account["store_grant_id"])]["payment_state"], "store_verified")
        self.assertEqual(self.store.data[(core.REQUESTS, "request")]["status"], "fulfilled")

    def test_customer_and_vendor_cannot_invoke_admin_reconciliation_or_forge_checkout_terms(self):
        self.assertEqual(self.prepare(user="customer").status_code, 403)
        self.assertEqual(self.post("/admin/subscriptions/google-play/reconcile", {}).status_code, 403)
        self.assertEqual(self.post("/subscriptions/google-play/checkout-context", {"request_id": "request", "amount": 0}).status_code, 422)

    def test_durable_notification_commit_failure_never_acknowledges_transport(self):
        self.store.fail_commit = True
        with self.assertRaises(RuntimeError):
            self.client.post("/webhooks/google-play/rtdn", json=self.notification())
        self.assertFalse(any(c in {routes.EVENTS, routes.WORK} for c, _ in self.store.data))


if __name__ == "__main__":
    unittest.main()
