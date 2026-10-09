"""Requested customer/owner flows with strict transactional Firestore mocks.

These prove local authorization, accounting, retry and quota logic; they do not
prove real Firestore transaction retries or receipt of a push on a device.
"""
import copy
import unittest
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from flask import Flask
import auth_utils
import db as storage
import notification_delivery
from routes import chat, khata, notifications, shops, vendors
from test_core_routes import CoreStore


class RequestedWorkflowsTests(unittest.TestCase):
    def setUp(self):
        self.store = CoreStore()
        self.store.data = {
            (storage.USERS, "customer"): {"role": "customer"},
            (storage.USERS, "other_customer"): {"role": "customer"},
            (storage.USERS, "vendor"): {"role": "vendor", "shop_name": "Shop"},
            (storage.USERS, "other_vendor"): {"role": "vendor"},
            (storage.USERS, "service_buyer"): {"role": "service"},
            (storage.KHATA_LEDGERS, "ledger"): {"customer_id": "customer", "vendor_id": "vendor", "balance": 100, "status": "active"},
            (storage.SHOP_ITEMS, "item"): {"name": "Rice", "vendor_id": "vendor", "price": 100, "stock_quantity": 10},
            (storage.CUSTOMER_ORDERS, "order"): {"customer_id": "customer", "vendor_id": "vendor", "status": "pending",
                "payment_method": "cash", "payment_status": "pending", "total_price": 90, "total_paise": 9000,
                "subtotal_price": 100, "discount_amount": 10, "quantity": 1, "item_id": "item"},
        }
        self.app = Flask(__name__)
        self.app.config["TESTING"] = True
        for module in (chat, khata, notifications, shops, vendors):
            self.app.register_blueprint(getattr(module, module.__name__.split(".")[-1] + "_bp"))
        patches = [patch.object(storage, "doc", self.store.doc),
            patch.object(auth_utils, "decode_token", lambda token: {"sub": token})]
        for module in (chat, khata, notifications, shops, vendors):
            patches.extend([patch.object(module, "doc", self.store.doc), patch.object(module, "col", self.store.col),
                patch.object(module, "db", lambda: self.store),
                patch.object(module.firestore, "transactional", self.store.transactional)])
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        self.client = self.app.test_client()

    def call(self, path, payload=None, user="customer", method="POST", key=None):
        headers = {"Authorization": "Bearer " + user}
        if key:
            headers["Idempotency-Key"] = key
        return self.client.open(path, json=payload, headers=headers, method=method)

    def payment(self, amount=40, method="cash", key="payment-1"):
        return self.call("/khata/transactions", {"ledger_id": "ledger", "type": "debit", "amount": amount,
            "payment_method": method, "payment_reference": "UPI123" if method == "upi" else None}, key=key)

    def balance(self):
        return self.store.data[(storage.KHATA_LEDGERS, "ledger")]["balance"]

    def events(self):
        return [data for (collection, _), data in self.store.data.items() if collection == storage.NOTIFICATIONS]

    def test_cash_and_upi_customer_requests_require_owner_approval_and_retry_once(self):
        for method in ("cash", "upi"):
            first = self.payment(method=method, key=method)
            self.assertEqual(first.status_code, 201)
            self.assertEqual(first.json["status"], "pending")
            self.assertEqual(self.balance(), 100 if method == "cash" else 60)
            identifier = first.json["uid"]
            path = f"/khata/transactions/{identifier}/approve"
            self.assertEqual(self.call(path).status_code, 403)
            self.assertEqual(self.call(path, user="other_vendor").status_code, 403)
            approved = self.call(path, user="vendor")
            self.assertEqual(approved.json["status"], "confirmed")
            self.assertEqual(self.call(path, user="vendor").status_code, 200)
            retried = self.payment(method=method, key=method)
            self.assertEqual(retried.status_code, 200)
            self.assertEqual(retried.json["status"], "confirmed")
        self.assertEqual(self.balance(), 20)
        self.assertEqual(len(self.events()), 4)

    def test_pending_payments_cannot_overcommit_and_rejection_releases_allowance(self):
        payment = self.payment(70)
        self.assertEqual(self.payment(40, key="different").status_code, 422)
        identifier = payment.json["uid"]
        self.assertEqual(self.call(f"/khata/transactions/{identifier}/reject", user="vendor").json["status"], "rejected")
        self.assertEqual(self.balance(), 100)
        self.assertEqual(self.payment(100, key="different").status_code, 201)
        self.assertEqual(self.call(f"/khata/transactions/{identifier}/approve", user="vendor").status_code, 409)

    def test_concurrent_pending_payment_requests_cannot_reserve_more_than_balance(self):
        def submit(index):
            with self.app.test_client() as client:
                return client.post("/khata/transactions", json={"ledger_id": "ledger", "type": "debit", "amount": 60,
                    "payment_method": "upi"}, headers={"Authorization": "Bearer customer", "Idempotency-Key": str(index)}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(submit, range(2)))
        self.assertEqual(sorted(responses), [201, 422])
        self.assertEqual(self.balance(), 100)

    def test_approval_commit_failure_preserves_balance_pending_request_and_notifications(self):
        payment = self.payment()
        before = copy.deepcopy(self.store.data)
        self.store.fail_commit = True
        with self.assertRaises(RuntimeError):
            self.call(f"/khata/transactions/{payment.json['uid']}/approve", user="vendor")
        self.assertEqual(self.store.data, before)

    def test_customer_cannot_forge_credit_payment_method_or_foreign_ledger_payment(self):
        self.assertEqual(self.payment(method="wallet").status_code, 403)
        self.assertEqual(self.call("/khata/transactions", {"ledger_id": "ledger", "type": "credit", "amount": 1, "payment_method": "cash"}).status_code, 403)
        self.assertEqual(self.call("/khata/transactions", {"ledger_id": "ledger", "type": "debit", "amount": 1, "payment_method": "cash"}, user="other_customer").status_code, 403)
        self.assertEqual(self.balance(), 100)

    def room(self, vendor="vendor"):
        return self.call("/chat/rooms", {"vendor_id": vendor}).json["uid"]

    def test_chat_limit_is_global_three_per_day_and_retry_does_not_consume_again(self):
        room, second = self.room(), self.room("other_vendor")
        first = f"/chat/rooms/{room}/messages"
        other = f"/chat/rooms/{second}/messages"
        self.assertEqual(self.call(first, {"text": "One"}, key="first").status_code, 201)
        self.assertEqual(self.call(first, {"text": "One"}, key="first").status_code, 200)
        self.assertEqual(self.call(other, {"text": "Two"}).status_code, 201)
        self.assertEqual(self.call(first, {"text": "Three"}).status_code, 201)
        self.assertEqual(self.call(other, {"text": "Four"}).status_code, 429)
        # Vendor replies remain available even after the customer's quota.
        for _ in range(4):
            self.assertEqual(self.call(first, {"text": "Reply"}, user="vendor").status_code, 201)
        self.assertEqual(len(self.events()), 7)

    def test_concurrent_messages_cannot_bypass_quota(self):
        path = f"/chat/rooms/{self.room()}/messages"
        def send(index):
            with self.app.test_client() as client:
                return client.post(path, json={"text": str(index)}, headers={"Authorization": "Bearer customer"}).status_code
        with ThreadPoolExecutor(max_workers=8) as pool:
            responses = list(pool.map(send, range(12)))
        self.assertEqual(responses.count(201), 3)
        self.assertEqual(responses.count(429), 9)
        self.assertEqual(len(self.events()), 3)

    def test_customer_quota_resets_at_indian_calendar_midnight(self):
        path = f"/chat/rooms/{self.room()}/messages"
        with patch.object(chat, "datetime") as clock:
            clock.now.return_value = datetime(2026, 10, 9, 18, 29, tzinfo=timezone.utc)
            for _ in range(3):
                self.assertEqual(self.call(path, {"text": "Before midnight"}).status_code, 201)
            self.assertEqual(self.call(path, {"text": "Limit"}).status_code, 429)
            clock.now.return_value = datetime(2026, 10, 9, 18, 31, tzinfo=timezone.utc)
            self.assertEqual(self.call(path, {"text": "After midnight"}).status_code, 201)
        counts = {data["day"]: data["count"] for (collection, _), data in self.store.data.items() if collection == "chat_daily_usage"}
        self.assertEqual(counts, {"2026-10-09": 3, "2026-10-10": 1})

    def test_chat_failure_does_not_consume_quota_or_send_push(self):
        path = f"/chat/rooms/{self.room()}/messages"
        before = copy.deepcopy(self.store.data)
        self.store.fail_commit = True
        with patch.object(chat, "deliver_push") as push:
            with self.assertRaises(RuntimeError):
                self.call(path, {"text": "Hello"})
            push.assert_not_called()
        self.assertEqual(self.store.data, before)

    def test_token_registration_and_delivery_use_modern_account_and_push_failure_keeps_message(self):
        token = "device-token-for-local-test"
        for _ in range(2):
            self.assertEqual(self.call("/notifications/device-token", {"token": token}, user="vendor").status_code, 200)
        self.assertEqual(self.store.data[(storage.USERS, "vendor")]["fcm_tokens"], [token])
        path = f"/chat/rooms/{self.room()}/messages"
        with patch.object(notification_delivery.messaging, "send", side_effect=RuntimeError("provider offline")) as push:
            self.assertEqual(self.call(path, {"text": "Hello"}).status_code, 201)
            self.assertEqual(push.call_args.args[0].token, token)
            self.assertEqual(push.call_args.args[0].data, {
                "user_id": "vendor", "type": "chat_message", "reference_id": path.split("/")[3]})
        self.assertEqual(len(self.events()), 1)
        self.assertEqual(self.call("/notifications/device-token", {"token": token}, user="vendor", method="DELETE").status_code, 200)
        self.assertEqual(self.store.data[(storage.USERS, "vendor")]["fcm_tokens"], [])

    def test_status_notifications_are_atomic_and_repeated_status_emits_once(self):
        for _ in range(2):
            self.assertEqual(self.call("/vendors/orders/order/status", {"status": "confirmed"}, user="vendor", method="PUT").status_code, 200)
        self.assertEqual(len(self.events()), 1)
        self.assertEqual(self.events()[0]["user_id"], "customer")
        self.store.fail_commit = True
        before = copy.deepcopy(self.store.data)
        with self.assertRaises(RuntimeError):
            self.call("/vendors/orders/order/status", {"status": "packed"}, user="vendor", method="PUT")
        self.assertEqual(self.store.data, before)

    def test_device_switch_transfers_push_ownership_even_when_old_logout_failed(self):
        token = "shared-device-installation-token"
        path = "/notifications/device-token"
        self.assertEqual(self.call(path, {"token": token}).status_code, 200)
        self.assertEqual(self.call(path, {"token": token}, user="other_customer").status_code, 200)
        first = notification_delivery.notification_data("customer", "chat_message", "Private", "Old account", "room")
        second = notification_delivery.notification_data("other_customer", "chat_message", "Private", "Current account", "room")
        with patch.object(notification_delivery.messaging, "send") as push:
            notification_delivery.deliver_push(first, lookup=self.store.doc)
            push.assert_not_called()
            # An old account's delayed logout cannot revoke the new owner.
            self.assertEqual(self.call(path, {"token": token}, method="DELETE").status_code, 200)
            notification_delivery.deliver_push(second, lookup=self.store.doc)
            self.assertEqual(push.call_count, 1)
            self.assertEqual(self.call(path, {"token": token}, user="other_customer", method="DELETE").status_code, 200)
            notification_delivery.deliver_push(second, lookup=self.store.doc)
            self.assertEqual(push.call_count, 1)

    def test_explicit_cash_confirmation_uses_discounted_price_and_cannot_fake_online_payment(self):
        path = "/vendors/orders/order/payment/confirm"
        self.assertEqual(self.call(path).status_code, 403)
        self.assertEqual(self.call(path, user="other_vendor").status_code, 403)
        for _ in range(2):
            self.assertEqual(self.call(path, user="vendor").status_code, 200)
        order = self.store.data[(storage.CUSTOMER_ORDERS, "order")]
        self.assertEqual(order["partial_amount_paid"], 90)
        self.assertEqual(order["due_amount"], 0)
        self.assertEqual(len(self.events()), 1)
        self.assertEqual(self.call("/orders/order/cancel").status_code, 409)
        order["payment_method"] = "razorpay"
        order["payment_status"] = "pending"
        self.assertEqual(self.call(path, user="vendor").status_code, 409)

    def test_vendor_and_service_accounts_can_shop_without_owner_privileges_over_other_shops(self):
        for user in ("other_vendor", "service_buyer"):
            response = self.call("/orders/batch", {"items": [{"item_id": "item", "quantity": 1}], "payment_method": "cash"}, user=user)
            self.assertEqual(response.status_code, 201)
            identifier = response.json["order_id"]
            order = self.store.data[(storage.CUSTOMER_ORDERS, identifier)]
            self.assertEqual(order["customer_id"], user)
            self.assertEqual(self.call(f"/vendors/orders/{identifier}/payment/confirm", user=user).status_code, 403)
            self.assertEqual(self.call(f"/orders/{identifier}/cancel", user=user).status_code, 200)

    def test_vendor_buyer_can_request_khata_payment_but_cannot_confirm_it(self):
        created = self.call("/khata/ledgers", {"customer_id": "other_vendor"}, user="vendor")
        self.assertEqual(created.status_code, 201)
        identifier = created.json["uid"]
        credit = {"ledger_id": identifier, "type": "credit", "amount": 50}
        self.assertEqual(self.call("/khata/transactions", credit, user="vendor").status_code, 201)
        self.assertEqual(self.call("/khata/transactions", credit, user="other_vendor").status_code, 403)
        payment = self.call("/khata/transactions", {"ledger_id": identifier, "type": "debit", "amount": 20, "payment_method": "cash"}, user="other_vendor")
        self.assertEqual(payment.status_code, 201)
        self.assertEqual(payment.json["status"], "pending")
        self.assertEqual(self.call(f"/khata/transactions/{payment.json['uid']}/approve", user="other_vendor").status_code, 403)
        self.assertEqual(self.call("/khata/ledgers", user="other_vendor", method="GET").json[0]["uid"], identifier)

    def test_vendor_requester_quota_and_customer_provider_capability(self):
        room = self.call("/chat/rooms", {"vendor_id": "vendor"}, user="other_vendor").json["uid"]
        for index in range(4):
            response = self.call(f"/chat/rooms/{room}/messages", {"text": str(index)}, user="other_vendor")
            self.assertEqual(response.status_code, 201 if index < 3 else 429)
        self.assertEqual(self.call("/chat/rooms", user="other_vendor", method="GET").json[0]["uid"], room)
        self.assertEqual(self.call("/chat/rooms", {"vendor_id": "other_customer"}).status_code, 403)
        self.store.data[("provider_profiles", "other_customer")] = {"is_active": True}
        response = self.call("/chat/rooms", {"vendor_id": "other_customer"})
        self.assertEqual(response.status_code, 200)
        room = response.json["uid"]
        # A provider responding in the vendor slot is not charged customer quota.
        for _ in range(4):
            self.assertEqual(self.call(f"/chat/rooms/{room}/messages", {"text": "Reply"}, user="other_customer").status_code, 201)


if __name__ == "__main__":
    unittest.main()
