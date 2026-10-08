"""Isolated HTTP core-feature proof with strict atomic transaction mocks."""
import copy
import unittest
from unittest.mock import patch
from flask import Flask
import auth_utils
import db as storage
from routes import vendors, inventory, reviews, chat, khata, shops
from test_khata import Store, Ref
from test_orders_api import OrderTransaction


class CoreTransaction(OrderTransaction):
    def delete(self, ref):
        self.pending.append((ref.key, None, False))

    def commit(self):
        staged = copy.deepcopy(self.store.data)
        for key, data, merge in self.pending:
            if data is None:
                staged.pop(key, None)
            else:
                staged[key] = {**staged.get(key, {}), **data} if merge else data
        if self.store.fail_commit:
            raise RuntimeError("simulated write failure")
        self.store.data = staged


class CoreStore(Store):
    def transaction(self):
        return CoreTransaction(self)


class CoreRoutesTests(unittest.TestCase):
    def setUp(self):
        self.store = CoreStore()
        self.store.data = {
            (storage.USERS, "vendor"): {"role": "vendor", "full_name": "Shop", "password_hash": "private"},
            (storage.USERS, "other_vendor"): {"role": "vendor"},
            (storage.USERS, "customer"): {"role": "customer", "full_name": "Customer", "password_hash": "private"},
            (storage.USERS, "other_customer"): {"role": "customer"},
            (storage.SHOP_ITEMS, "rice"): {"vendor_id": "vendor", "name": "Rice", "price": 25.5, "stock_quantity": 10},
            (storage.SHOP_ITEMS, "milk"): {"vendor_id": "vendor", "name": "Milk", "price": 20, "stock_quantity": 10},
            (storage.CUSTOMER_ORDERS, "order"): {"vendor_id": "vendor", "customer_id": "customer", "item_id": "rice",
                "quantity": 1, "total_price": 25.5, "status": "pending", "payment_method": "cash", "payment_status": "pending"},
        }
        self.app = Flask(__name__)
        self.app.config["TESTING"] = True
        modules = (vendors, inventory, reviews, chat, khata, shops)
        for module in (vendors, inventory, reviews, chat):
            self.app.register_blueprint(getattr(module, f"{module.__name__.split('.')[-1]}_bp"))
        patches = [patch.object(storage, "doc", self.store.doc),
                   patch.object(auth_utils, "decode_token", lambda token: {"sub": token}),
                   patch.object(Ref, "set", lambda ref, data: ref.store.data.__setitem__(ref.key, copy.deepcopy(data)), create=True)]
        for module in modules:
            patches.extend([patch.object(module, "doc", self.store.doc), patch.object(module, "col", self.store.col),
                            patch.object(module, "db", lambda: self.store), patch.object(module.firestore, "transactional", self.store.transactional)])
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        self.client = self.app.test_client()

    def call(self, path, body=None, method="POST", user="vendor"):
        return self.client.open(path, method=method, json=body, headers={"Authorization": f"Bearer {user}"})

    def values(self, name):
        return [value for (collection, _), value in self.store.data.items() if collection == name]

    def test_vendor_item_creation_validates_price_stock_and_profile(self):
        response = self.call("/vendors/items", {"name": "Apples", "price": 12.5, "stock_quantity": 3})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json["vendor_id"], "vendor")
        self.assertNotIn("password_hash", response.json)
        for field, value in (("price", "NaN"), ("price", "Infinity"), ("price", -1), ("stock_quantity", -1),
                             ("stock_quantity", 1.5), ("stock_quantity", True), ("name", []), ("image_urls", "bad")):
            body = {"name": "Apples", "price": 12.5, "stock_quantity": 3, field: value}
            self.assertEqual(self.call("/vendors/items", body).status_code, 422)
        self.assertEqual(self.call("/vendors/items", []).status_code, 422)

    def test_vendor_cannot_forge_item_metadata_or_modify_other_vendor_item(self):
        for changes in ({"vendor_id": "other_vendor"}, {"average_rating": 5}, {"created_at": "fake"}, {"vendor_email": "fake"}):
            self.assertEqual(self.call("/vendors/items/rice", changes, "PUT").status_code, 422)
        self.assertEqual(self.call("/vendors/items/rice", {"price": 30}, "PUT", user="other_vendor").status_code, 403)
        self.assertEqual(self.call("/vendors/items/rice", {"price": 30}, "PUT").status_code, 200)
        self.assertEqual(self.call("/vendors/items/rice", {"stock_quantity": 0, "is_available": True}, "PUT").status_code, 422)

    def test_item_deletion_blocked_while_active_order_exists(self):
        self.assertEqual(self.call("/vendors/items/rice", method="DELETE").status_code, 409)
        self.assertEqual(self.call("/vendors/items/rice", method="DELETE", user="other_vendor").status_code, 403)
        self.assertEqual(self.call("/vendors/items/milk", method="DELETE").status_code, 200)
        self.assertNotIn((storage.SHOP_ITEMS, "milk"), self.store.data)

    def test_order_transitions_aliases_and_cash_delivery_confirmation(self):
        path = "/vendors/orders/order/status"
        self.assertEqual(self.call(path, {"status": "completed"}, "PUT").status_code, 409)
        for status in ("accepted", "packed", "completed", "completed"):
            self.assertEqual(self.call(path, {"status": status}, "PUT").status_code, 200)
        order = self.store.data[(storage.CUSTOMER_ORDERS, "order")]
        self.assertEqual(order["status"], "delivered")
        self.assertEqual(order["payment_status"], "paid")
        self.assertEqual(order["due_amount"], 0)
        self.assertEqual(self.call(path, {"status": "confirmed"}, "PUT").status_code, 409)
        self.assertEqual(self.call(path, {"status": []}, "PUT").status_code, 422)

    def test_unpaid_online_fulfillment_and_foreign_vendor_are_blocked(self):
        order = self.store.data[(storage.CUSTOMER_ORDERS, "order")]
        order["payment_method"] = "razorpay"
        path = "/vendors/orders/order/status"
        self.assertEqual(self.call(path, {"status": "confirmed"}, "PUT").status_code, 409)
        self.assertEqual(self.call(path, {"status": "confirmed"}, "PUT", user="other_vendor").status_code, 403)
        self.store.data[(storage.CUSTOMER_ORDERS, "order")]["payment_status"] = "paid"
        self.assertEqual(self.call(path, {"status": "confirmed"}, "PUT").status_code, 200)

    def test_vendor_cancel_delegates_stock_and_khata_reversal_once(self):
        order = self.store.data[(storage.CUSTOMER_ORDERS, "order")]
        order.update({"payment_method": "khata", "khata_ledger_id": "ledger"})
        self.store.data[(storage.KHATA_LEDGERS, "ledger")] = {"vendor_id": "vendor", "customer_id": "customer", "balance": 50}
        for _ in range(2):
            self.assertEqual(self.call("/vendors/orders/order/status", {"status": "cancelled"}, "PUT").status_code, 200)
        self.assertEqual(self.store.data[(storage.SHOP_ITEMS, "rice")]["stock_quantity"], 11)
        self.assertEqual(self.store.data[(storage.KHATA_LEDGERS, "ledger")]["balance"], 24.5)
        self.assertEqual(len(self.values(storage.KHATA_TRANSACTIONS)), 1)

    def test_stock_input_and_ownership_are_strict(self):
        path = "/inventory/rice/stock"
        for quantity in (-1, True, 1.5, "Infinity", [], None):
            self.assertEqual(self.call(path, {"quantity": quantity}, "PUT").status_code, 422)
        self.assertEqual(self.call(path, {"quantity": 4}, "PUT", "other_vendor").status_code, 403)
        self.assertEqual(self.call(path, {"quantity": 0}, "PUT").status_code, 200)
        self.assertFalse(self.store.data[(storage.SHOP_ITEMS, "rice")]["is_available"])

    def test_inventory_bulk_rejects_entire_batch_for_invalid_missing_foreign_or_duplicate(self):
        for second in ({"item_id": "milk", "quantity": -1}, {"item_id": "missing", "quantity": 1},
                       {"item_id": "rice", "quantity": 2}, "bad"):
            before = copy.deepcopy(self.store.data)
            response = self.call("/inventory/bulk-update", {"items": [{"item_id": "rice", "quantity": 1}, second]})
            self.assertIn(response.status_code, {422, 404})
            self.assertEqual(self.store.data, before)
        self.store.data[(storage.SHOP_ITEMS, "milk")]["vendor_id"] = "other_vendor"
        before = copy.deepcopy(self.store.data)
        response = self.call("/inventory/bulk-update", {"items": [{"item_id": "rice", "quantity": 1}, {"item_id": "milk", "quantity": 2}]})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.store.data, before)
        self.assertEqual(self.call("/inventory/bulk-update", {"items": []}).status_code, 422)
        self.assertEqual(self.call("/inventory/bulk-update", {"items": [{}] * 101}).status_code, 422)

    def test_admin_disabled_product_stays_disabled_through_vendor_stock_edits(self):
        self.store.data[(storage.SHOP_ITEMS, "rice")].update({"disabled_by_admin": True, "is_available": False})
        response = self.call("/vendors/items/rice", {"is_available": True}, "PUT")
        self.assertEqual(response.status_code, 403)
        for changes in ({"stock_quantity": 20}, {"stock_quantity": 25, "is_available": True}, {"price": 30}):
            response = self.call("/vendors/items/rice", changes, "PUT")
            self.assertEqual(response.status_code, 200)
            self.assertFalse(response.json["is_available"])
            self.assertTrue(response.json["disabled_by_admin"])
        response = self.call("/inventory/rice/stock", {"quantity": 30}, "PUT")
        self.assertEqual(response.status_code, 200)
        response = self.call("/inventory/bulk-update", {"items": [{"item_id": "rice", "quantity": 40}, {"item_id": "milk", "quantity": 20}]})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.store.data[(storage.SHOP_ITEMS, "rice")]["is_available"])
        self.assertTrue(self.store.data[(storage.SHOP_ITEMS, "rice")]["disabled_by_admin"])
        self.assertTrue(self.store.data[(storage.SHOP_ITEMS, "milk")]["is_available"])

    def test_inventory_bulk_success_and_atomic_failure(self):
        payload = {"items": [{"item_id": "rice", "quantity": 1}, {"item_id": "milk", "quantity": 2}]}
        self.assertEqual(self.call("/inventory/bulk-update", payload).json["updated"], 2)
        self.store.fail_commit = True
        before = copy.deepcopy(self.store.data)
        with self.assertRaises(RuntimeError):
            self.call("/inventory/bulk-update", payload)
        self.assertEqual(self.store.data, before)

    def review(self, rating=4, user="customer", **extra):
        return self.call("/reviews", {"item_id": "rice", "vendor_id": "vendor", "rating": rating, **extra}, user=user)

    def test_review_validates_finite_bounded_rating_customer_vendor_and_item(self):
        for rating in (True, 0, 5.1, "NaN", "Infinity", [], None):
            self.assertEqual(self.review(rating).status_code, 422)
        self.assertEqual(self.review(user="vendor").status_code, 403)
        self.assertEqual(self.review(vendor_id="other_vendor").status_code, 422)
        self.assertEqual(self.review(item_id="missing").status_code, 404)
        self.assertEqual(self.review(comment=[]).status_code, 422)
        self.assertEqual(self.review(comment="x" * 2001).status_code, 422)
        self.assertEqual(self.values(storage.REVIEWS), [])

    def test_review_one_per_customer_and_atomic_average(self):
        first = self.review(3)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(self.review(5).status_code, 200)
        self.assertEqual(self.review(3, user="other_customer").status_code, 201)
        item = self.store.data[(storage.SHOP_ITEMS, "rice")]
        self.assertEqual(item["average_rating"], 4)
        self.assertEqual(item["rating_count"], 2)
        self.assertEqual(len(self.values(storage.REVIEWS)), 2)
        self.assertNotIn("password_hash", first.json)

    def test_review_failure_does_not_leave_summary_or_review_written(self):
        self.store.fail_commit = True
        before = copy.deepcopy(self.store.data)
        with self.assertRaises(RuntimeError):
            self.review()
        self.assertEqual(self.store.data, before)

    def room(self):
        response = self.call("/chat/rooms", {"vendor_id": "vendor"}, user="customer")
        self.assertEqual(response.status_code, 200)
        return response.json["uid"]

    def test_chat_room_valid_participants_and_no_profile_leak(self):
        self.assertEqual(self.call("/chat/rooms", {"vendor_id": "missing"}, user="customer").status_code, 403)
        self.assertEqual(self.call("/chat/rooms", {"vendor_id": "vendor"}, user="vendor").status_code, 403)
        room = self.room()
        self.assertEqual(self.room(), room)
        self.assertEqual(len(self.values(storage.CHAT_ROOMS)), 1)
        self.store.data[(storage.CHAT_ROOMS, room)]["password_hash"] = "private"
        response = self.call("/chat/rooms", method="GET", user="customer")
        self.assertNotIn("password_hash", response.json[0])

    def test_chat_sender_ownership_and_text_validation(self):
        room = self.room()
        path = f"/chat/rooms/{room}/messages"
        for text in ([], "", "  ", "x" * 4001):
            self.assertEqual(self.call(path, {"text": text}, user="customer").status_code, 422)
        self.assertEqual(self.call(path, {"text": "Hello"}, user="other_customer").status_code, 403)
        self.assertEqual(self.call(path, method="GET", user="other_customer").status_code, 403)
        self.assertEqual(self.values(storage.MESSAGES), [])

    def test_chat_atomic_message_summary_notification_and_idempotency(self):
        room = self.room()
        path = f"/chat/rooms/{room}/messages"
        payload = {"text": "Hello", "idempotency_key": "request-1"}
        self.assertEqual(self.call(path, payload, user="customer").status_code, 201)
        self.assertEqual(self.call(path, payload, user="customer").status_code, 200)
        self.assertEqual(len(self.values(storage.MESSAGES)), 1)
        self.assertEqual(len(self.values(storage.NOTIFICATIONS)), 1)
        self.assertEqual(self.values(storage.NOTIFICATIONS)[0]["user_id"], "vendor")
        self.assertEqual(self.store.data[(storage.CHAT_ROOMS, room)]["last_message"], "Hello")
        self.assertEqual(self.call(path, {**payload, "text": "Changed"}, user="customer").status_code, 409)
        self.store.fail_commit = True
        before = copy.deepcopy(self.store.data)
        with self.assertRaises(RuntimeError):
            self.call(path, {"text": "Other"}, user="vendor")
        self.assertEqual(self.store.data, before)

    def test_chat_suspended_or_deleted_recipient_blocks_message(self):
        room = self.room()
        self.store.data[(storage.USERS, "vendor")]["is_suspended"] = True
        path = f"/chat/rooms/{room}/messages"
        self.assertEqual(self.call(path, {"text": "Hello"}, user="customer").status_code, 403)
        del self.store.data[(storage.USERS, "vendor")]
        self.assertEqual(self.call(path, {"text": "Hello"}, user="customer").status_code, 403)
        self.assertEqual(self.values(storage.MESSAGES), [])


if __name__ == "__main__":
    unittest.main()
