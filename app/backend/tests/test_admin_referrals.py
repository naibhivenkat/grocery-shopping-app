"""Critical admin authorization and referral integrity, with isolated mocks."""
import copy
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from flask import Flask
import auth_utils
import db as storage
from routes import admin, referrals, khata, vendors, shops, support
from test_khata import Ref, Query
from test_core_routes import CoreStore


class AdminReferralTests(unittest.TestCase):
    def setUp(self):
        self.store = CoreStore()
        self.store.data = {
            (storage.USERS, "admin"): {"role": "admin", "email": "admin@example.test", "password_hash": "private"},
            (storage.USERS, "super"): {"role": "super_admin", "email": "super@example.test"},
            (storage.USERS, "customer"): {"role": "customer", "email": "customer@example.test", "full_name": "Customer", "password_hash": "private", "reset_token": "private"},
            (storage.USERS, "other_customer"): {"role": "customer", "email": "other@example.test"},
            (storage.USERS, "third_customer"): {"role": "customer"},
            (storage.USERS, "vendor"): {"role": "vendor", "shop_name": "Trusted Shop"},
            (storage.SHOP_ITEMS, "rice"): {"vendor_id": "vendor", "price": 25, "stock_quantity": 10},
            (storage.CUSTOMER_ORDERS, "order"): {"vendor_id": "vendor", "customer_id": "customer", "item_id": "rice",
                "quantity": 1, "total_price": 25, "status": "pending", "payment_method": "cash", "payment_status": "pending"},
        }
        self.app = Flask(__name__)
        self.app.config["TESTING"] = True
        self.app.register_blueprint(admin.admin_bp)
        self.app.register_blueprint(referrals.referrals_bp)
        def set_ref(ref, data, merge=False):
            ref.store.data[ref.key] = {**ref.store.data.get(ref.key, {}), **copy.deepcopy(data)} if merge else copy.deepcopy(data)
        patches = [patch.object(storage, "doc", self.store.doc),
                   patch.object(auth_utils, "decode_token", lambda token: {"sub": token, "role": "super_admin"}),
                   patch.object(admin, "log_admin_action", lambda *args, **kwargs: None),
                   patch.object(Ref, "set", set_ref, create=True),
                   patch.object(Ref, "update", lambda ref, data: set_ref(ref, data, True), create=True),
                   patch.object(Query, "_client", property(lambda query: query.store), create=True),
                   patch.object(CoreStore, "batch", lambda store: store.transaction(), create=True)]
        for module in (admin, referrals, khata, vendors, shops, support):
            patches += [patch.object(module, "col", self.store.col), patch.object(module, "doc", self.store.doc),
                        patch.object(module, "db", lambda: self.store), patch.object(module.firestore, "transactional", self.store.transactional)]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        self.client = self.app.test_client()

    def call(self, path, body=None, method="POST", user="admin"):
        return self.client.open(path, json=body, method=method, headers={"Authorization": f"Bearer {user}"})

    def values(self, name):
        return [value for (collection, _), value in self.store.data.items() if collection == name]

    def test_users_aliases_retain_admin_authorization_and_service_role_rules(self):
        self.assertEqual(self.call("/admin/users", method="GET", user="customer").status_code, 403)
        self.assertEqual(self.call("/admin/users/customer", method="GET").json["uid"], "customer")
        self.assertEqual(self.call("/admin/users/customer", {"role": "service"}, "PUT").status_code, 403)
        self.assertEqual(self.call("/admin/users/customer", {"role": "service"}, "PUT", "super").status_code, 200)
        self.assertEqual(self.store.data[(storage.USERS, "customer")]["role"], "service")
        self.assertEqual(self.call("/admin/users/customer/suspend").status_code, 200)
        self.assertEqual(self.call("/admin/users/customer/unsuspend").status_code, 200)

    def test_admin_cannot_grant_roles_or_manage_privileged_target(self):
        for role in ("vendor", "admin", "super_admin"):
            before = copy.deepcopy(self.store.data)
            response = self.call("/admin/customers/customer", {"role": role}, "PUT")
            self.assertEqual(response.status_code, 403)
            self.assertEqual(self.store.data, before)
        for target in ("admin", "super"):
            for method, suffix, payload in (("PUT", "", {"full_name": "Altered"}), ("DELETE", "", None),
                                            ("POST", "/suspend", None), ("POST", "/unsuspend", None)):
                self.assertEqual(self.call(f"/admin/customers/{target}{suffix}", payload, method).status_code, 403)

    def test_super_admin_role_grant_and_stored_role_enforcement(self):
        self.assertEqual(self.call("/admin/customers/customer", {"role": "admin"}, "PUT", "super").status_code, 200)
        self.assertEqual(self.store.data[(storage.USERS, "customer")]["role"], "admin")
        # JWT claims in the mock say super_admin; stored role still governs access.
        self.assertEqual(self.call("/admin/customers/other_customer", {"role": "super_admin"}, "PUT", "customer").status_code, 403)
        self.assertEqual(len(self.values(storage.AUDIT_LOGS)), 1)

    def test_missing_role_profile_edit_preserves_role_and_audit_is_atomic(self):
        response = self.call("/admin/customers/customer", {"full_name": "Updated"}, "PUT")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.store.data[(storage.USERS, "customer")]["role"], "customer")
        audit = self.values(storage.AUDIT_LOGS)[0]
        self.assertEqual(audit["admin_email"], "admin@example.test")
        before = copy.deepcopy(self.store.data)
        self.store.fail_commit = True
        with self.assertRaises(RuntimeError):
            self.call("/admin/customers/customer", {"full_name": "Failed"}, "PUT")
        self.assertEqual(self.store.data, before)

    def test_user_validation_and_email_uniqueness(self):
        for body in ({"role": None}, {"role": []}, {"is_suspended": "false"}, {"email": "bad"}, {"phone": []},
                     {"password_hash": "replace"}, [], {}):
            self.assertEqual(self.call("/admin/customers/customer", body, "PUT").status_code, 422)
        self.assertEqual(self.call("/admin/customers/customer", {"email": "other@example.test"}, "PUT").status_code, 409)

    def test_suspend_unsuspend_missing_docs_do_not_create_phantoms(self):
        for path in ("/admin/customers/missing/suspend", "/admin/customers/missing/unsuspend", "/admin/vendors/missing/suspend"):
            self.assertEqual(self.call(path).status_code, 404)
        self.assertNotIn((storage.USERS, "missing"), self.store.data)
        self.assertEqual(self.call("/admin/vendors/customer/suspend").status_code, 404)
        self.assertEqual(self.call("/admin/customers/customer/suspend").status_code, 200)
        self.assertTrue(self.store.data[(storage.USERS, "customer")]["is_suspended"])
        self.assertEqual(self.call("/admin/customers/customer/unsuspend").status_code, 200)
        self.assertEqual(self.store.data[(storage.USERS, "customer")]["role"], "customer")

    def test_super_admin_cannot_lock_out_self_or_last_active_super(self):
        for method, suffix, body in (("POST", "/suspend", None), ("DELETE", "", None), ("PUT", "", {"role": "customer"})):
            self.assertEqual(self.call("/admin/customers/super" + suffix, body, method, "super").status_code, 409)
        self.store.data[(storage.USERS, "second_super")] = {"role": "super_admin", "is_suspended": True}
        self.assertEqual(self.call("/admin/customers/super/suspend", user="second_super").status_code, 403)

    def test_super_admin_can_remove_suspended_peer_and_password_preserves_spaces(self):
        self.store.data[(storage.USERS, "inactive_super")] = {"role": "super_admin", "is_suspended": True}
        self.assertEqual(self.call("/admin/customers/inactive_super", method="DELETE", user="super").status_code, 200)
        self.store.data[(storage.USERS, "admin")]["password_hash"] = auth_utils.hash_password(" current password ")
        response = self.call("/admin/change-password", {"current_password": " current password ", "new_password": " new password "})
        self.assertEqual(response.status_code, 200)
        user = self.store.data[(storage.USERS, "admin")]
        self.assertTrue(auth_utils.verify_password(" new password ", user["password_hash"]))
        self.assertIn("password_reset_at", user)

    def test_admin_lists_remove_credentials_and_current_role_failclosed(self):
        response = self.call("/admin/customers", method="GET")
        customer = next(item for item in response.json if item["uid"] == "customer")
        self.assertNotIn("password_hash", customer)
        self.assertNotIn("reset_token", customer)
        self.store.data[(storage.USERS, "admin")]["role"] = "customer"
        self.assertEqual(self.call("/admin/stats", method="GET").status_code, 403)
        del self.store.data[(storage.USERS, "admin")]
        self.assertEqual(self.call("/admin/stats", method="GET").status_code, 401)

    def test_admin_product_validation_and_authoritative_vendor(self):
        response = self.call("/admin/products", {"name": "Apples", "price": 12.5, "stock_quantity": 3,
                                                "vendor_id": "vendor", "vendor_name": "Forged"})
        self.assertEqual(response.status_code, 200)
        product = self.store.data[(storage.SHOP_ITEMS, response.json["uid"])]
        self.assertEqual(product["vendor_name"], "Trusted Shop")
        for field, value in (("price", "NaN"), ("stock_quantity", -1), ("stock_quantity", True), ("average_rating", 5)):
            self.assertEqual(self.call("/admin/products/rice", {field: value}, "PUT").status_code, 422)
        self.assertEqual(self.call("/admin/products", {"name": "Apples", "price": 1, "vendor_id": "missing"}).status_code, 404)
        self.assertEqual(self.call("/admin/products/rice", method="DELETE").status_code, 409)
        self.store.data[(storage.SHOP_ITEMS, "rice")]["stock_quantity"] = 0
        self.assertEqual(self.call("/admin/products/rice/enable").status_code, 409)

    def test_admin_cancel_reverses_stock_once_without_phantom_order(self):
        self.assertEqual(self.call("/admin/orders/missing/cancel").status_code, 404)
        for _ in range(2):
            self.assertEqual(self.call("/admin/orders/order/cancel").status_code, 200)
        self.assertEqual(self.store.data[(storage.SHOP_ITEMS, "rice")]["stock_quantity"], 11)
        self.assertEqual(self.store.data[(storage.CUSTOMER_ORDERS, "order")]["status"], "cancelled")

    def test_admin_refund_delegates_provider_processor_without_fake_success(self):
        for status, http in (("completed", 200), ("submitted", 202), ("processing", 202), ("retryable", 503), ("requires_review", 409)):
            with patch("routes.order_refunds.refund_order", return_value={"status": status}) as processor:
                response = self.call("/admin/orders/order/refund")
                self.assertEqual(response.status_code, http)
                self.assertEqual(response.json["refund"]["status"], status)
                processor.assert_called_once_with("order", "admin", allow_admin=True)
        self.assertNotIn("refund_status", self.store.data[(storage.CUSTOMER_ORDERS, "order")])

    def test_subscription_support_and_maintenance_validation_no_phantoms(self):
        for suffix in ("activate", "suspend"):
            self.assertEqual(self.call("/admin/subscriptions/missing/" + suffix).status_code, 404)
        self.assertEqual(self.call("/admin/support/reply", {"ticket_id": "missing", "reply": "Answer"}).status_code, 404)
        self.assertEqual(self.call("/admin/support/reply", {"ticket_id": "missing", "reply": []}).status_code, 422)
        self.assertEqual(self.call("/admin/maintenance", {"maintenance_mode": "false"}).status_code, 422)
        self.assertEqual(self.call("/admin/maintenance", {"maintenance_mode": False}).status_code, 200)

    def test_revenue_counts_paid_orders_only_and_rejects_invalid_legacy_amounts(self):
        self.store.data[(storage.CUSTOMER_ORDERS, "paid")] = {"status": "delivered", "payment_status": "paid", "total_price": 100}
        self.store.data[(storage.CUSTOMER_ORDERS, "fake")] = {"status": "confirmed", "payment_status": "pending", "total_price": 200}
        self.store.data[(storage.CUSTOMER_ORDERS, "invalid")] = {"status": "delivered", "payment_status": "paid", "total_price": "NaN"}
        self.store.data[(storage.CUSTOMER_ORDERS, "refunded")] = {"status": "cancelled", "payment_status": "paid", "total_price": 300, "refund_status": "completed"}
        self.assertEqual(self.call("/admin/stats", method="GET").json["total_revenue"], 100)
        self.assertEqual(self.call("/admin/analytics", method="GET").json["revenue"], 100)

    def test_admin_notification_body_matches_client(self):
        response = self.call("/admin/notifications/send", {"title": "Notice", "message": "Details", "target": "all"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["sent"], len(self.values(storage.USERS)))
        self.assertEqual(self.values(storage.NOTIFICATIONS)[0]["body"], "Details")

    def test_announcement_push_occurs_after_inbox_commit_and_skips_suspended(self):
        self.store.data[(storage.USERS, 'third_customer')]['is_suspended'] = True
        seen = []
        def delivered(event, **kwargs):
            matches = [value for value in self.values(storage.NOTIFICATIONS) if value['user_id'] == event['user_id']]
            self.assertEqual(len(matches), 1)
            self.assertEqual(matches[0]['uid'], event['reference_id'])
            seen.append(event['user_id'])
        with patch.object(admin, 'deliver_push', side_effect=delivered):
            response = self.call('/admin/notifications/send', {'title':'Notice', 'message':'Details', 'target':'customers'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(seen), {'customer', 'other_customer'})
        self.assertEqual(response.json['sent'], 2)

    def generate(self, user="customer"):
        return self.call("/referrals/generate", user=user)

    def apply(self, code, user="other_customer"):
        return self.call("/referrals/apply", {"code": code}, user=user)

    def test_referral_one_code_per_user_even_after_consumption_no_wallet_credit(self):
        first = self.generate().json["code"]
        self.assertEqual(self.generate().json["code"], first)
        response = self.apply(first)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json["reward_credited"])
        self.assertEqual(self.generate().json["code"], first)
        self.assertEqual(len(self.values(storage.REFERRALS)), 1)
        self.assertEqual(self.values(storage.WALLETS), [])
        self.assertEqual(self.values(storage.WALLET_TRANSACTIONS), [])

    def test_referral_invalid_own_consumed_or_second_apply_is_blocked(self):
        first = self.generate().json["code"]
        second = self.generate(user="vendor").json["code"]
        self.assertEqual(self.apply(first, user="customer").status_code, 422)
        self.assertEqual(self.apply("AAAAAAAA").status_code, 404)
        self.assertEqual(self.apply([]).status_code, 422)
        self.assertEqual(self.apply(first).status_code, 200)
        self.assertEqual(self.apply(first).status_code, 200)
        self.assertEqual(self.apply(second).status_code, 409)
        self.assertEqual(self.apply(first, user="third_customer").status_code, 409)

    def test_legacy_referral_reused_and_legacy_application_prevents_second(self):
        self.store.data[(storage.REFERRALS, "legacy")] = {"referrer_id": "customer", "referee_id": "other_customer", "code": "LEGACY88", "status": "applied"}
        self.assertEqual(self.generate().json["code"], "LEGACY88")
        code = self.generate(user="vendor").json["code"]
        self.assertEqual(self.apply(code).status_code, 409)
        self.assertEqual(self.apply("LEGACY88").status_code, 200)

    def test_referral_atomic_failure_does_not_consume_code(self):
        code = self.generate().json["code"]
        before = copy.deepcopy(self.store.data)
        self.store.fail_commit = True
        with self.assertRaises(RuntimeError):
            self.apply(code)
        self.assertEqual(self.store.data, before)

    def test_referral_collision_retries_and_active_accounts_required(self):
        first = self.generate().json["code"]
        with patch.object(referrals, "_generate_code", side_effect=[first, "UNIQUE88"]):
            self.assertEqual(self.generate(user="vendor").json["code"], "UNIQUE88")
        self.store.data[(storage.USERS, "customer")]["is_suspended"] = True
        self.assertEqual(self.apply(first).status_code, 403)
        self.assertEqual(self.generate(user="admin").status_code, 403)

    def test_concurrent_referral_generation_and_application_are_once_only(self):
        def generate(_):
            with self.app.test_client() as client:
                return client.post("/referrals/generate", headers={"Authorization": "Bearer customer"}).json["code"]
        with ThreadPoolExecutor(max_workers=4) as pool:
            codes = list(pool.map(generate, range(12)))
        self.assertEqual(len(set(codes)), 1)
        self.assertEqual(len(self.values(storage.REFERRALS)), 1)
        def apply(user):
            with self.app.test_client() as client:
                return client.post("/referrals/apply", json={"code": codes[0]}, headers={"Authorization": f"Bearer {user}"}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(apply, ("other_customer", "third_customer")))
        self.assertEqual(sorted(statuses), [200, 409])
        self.assertEqual(len(self.values("referral_applications")), 1)


if __name__ == "__main__":
    unittest.main()
