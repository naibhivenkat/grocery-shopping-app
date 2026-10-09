"""Order API tests with strict read-before-write atomic Firestore mocks.

No real database, stock, payment or provider operations are performed. The mock
serializes transaction callbacks; live Firestore retry behavior is not tested.
"""
import copy
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from flask import Flask
import auth_utils
import db as storage
from routes import shops, khata
from test_khata import Store, Transaction


class OrderTransaction(Transaction):
    def create(self, ref, data):
        if ref.key in self.store.data:
            raise AssertionError("create must not overwrite existing data")
        self.set(ref, data)

    def update(self, ref, data):
        if ref.key not in self.store.data:
            raise AssertionError("update requires an existing document")
        self.set(ref, data, merge=True)


class OrderStore(Store):
    def transaction(self):
        return OrderTransaction(self)


class OrdersTests(unittest.TestCase):
    def setUp(self):
        self.store = OrderStore()
        self.store.data = {
            (storage.USERS, "customer"): {"role": "customer", "full_name": "Customer"},
            (storage.USERS, "other_customer"): {"role": "customer"},
            (storage.USERS, "vendor"): {"role": "vendor", "shop_name": "Shop"},
            (storage.USERS, "other_vendor"): {"role": "vendor"},
            (storage.SHOP_ITEMS, "rice"): {"vendor_id": "vendor", "price": 12.35, "stock_quantity": 10, "name": "Rice"},
            (storage.SHOP_ITEMS, "milk"): {"vendor_id": "vendor", "price": 20, "stock_quantity": 5, "name": "Milk"},
        }
        self.app = Flask(__name__)
        self.app.config["TESTING"] = True
        self.app.register_blueprint(shops.shops_bp)
        patches = [patch.object(storage, "doc", self.store.doc),
                   patch.object(auth_utils, "decode_token", lambda token: {"sub": token, "role": "customer"})]
        for module in (shops, khata):
            patches.extend([patch.object(module, "doc", self.store.doc), patch.object(module, "col", self.store.col),
                            patch.object(module, "db", lambda: self.store),
                            patch.object(module.firestore, "transactional", self.store.transactional)])
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        self.client = self.app.test_client()

    def post(self, path, payload=None, user="customer", key=None):
        headers = {"Authorization": f"Bearer {user}"}
        if key:
            headers["Idempotency-Key"] = key
        return self.client.post(path, json=payload, headers=headers)

    def order(self, method="cash", quantity=1, **extra):
        return self.post("/orders", {"item_id": "rice", "quantity": quantity, "payment_method": method, **extra})

    def batch(self, lines=None, **extra):
        return self.post("/orders/batch", {"items": lines if lines is not None else [
            {"item_id": "rice", "quantity": 2}, {"item_id": "milk", "quantity": 1}], **extra})

    def ledger(self, balance=50, status="active"):
        self.store.data[(storage.KHATA_LEDGERS, "legacy")] = {
            "vendor_id": "vendor", "customer_id": "customer", "balance": balance, "status": status}

    def values(self, collection):
        return [value for (name, _), value in self.store.data.items() if name == collection]

    def stock(self, identifier="rice"):
        return self.store.data[(storage.SHOP_ITEMS, identifier)]["stock_quantity"]

    def cancel(self, response, user="customer"):
        return self.post(f"/orders/{response.json['order_id']}/cancel", user=user)

    def test_cash_exact_price_and_stock_reservation(self):
        response = self.order(quantity=3, total_price="37.05")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json["total_price"], 37.05)
        self.assertEqual(self.stock(), 7)
        order = self.values(storage.CUSTOMER_ORDERS)[0]
        self.assertEqual(order["total_paise"], 3705)
        self.assertEqual(order["partial_amount_paid"], 0)

    def test_client_price_tampering_and_invalid_totals_have_no_writes(self):
        for total in (1, "NaN", "Infinity", [], -1):
            with self.subTest(total=total):
                before = copy.deepcopy(self.store.data)
                self.assertEqual(self.order(total_price=total).status_code, 422)
                self.assertEqual(self.store.data, before)

    def test_wallet_is_disabled_and_invalid_payment_method_is_validation_error(self):
        self.assertEqual(self.order(method="wallet").status_code, 410)
        self.assertEqual(self.order(method=[]).status_code, 422)
        self.assertEqual(self.order(method="unknown").status_code, 422)
        self.assertEqual(self.values(storage.CUSTOMER_ORDERS), [])

    def test_invalid_payloads_and_quantities(self):
        for payload in ([1], "text", 1):
            self.assertEqual(self.post("/orders", payload).status_code, 422)
            self.assertEqual(self.post("/orders/batch", payload).status_code, 422)
        for quantity in (True, 0, -1, 1.5, 10001, "Infinity", None, []):
            self.assertEqual(self.order(quantity=quantity).status_code, 422)
        self.assertEqual(self.post("/orders", {"item_id": "bad/id", "quantity": 1}).status_code, 422)
        self.assertEqual(self.values(storage.CUSTOMER_ORDERS), [])

    def test_stock_rejects_fractional_nonfinite_and_invalid_types(self):
        for stock in (1.5, "1.5", True, "NaN", "Infinity", [], {}, -1):
            with self.subTest(stock=stock):
                self.store.data[(storage.SHOP_ITEMS, "rice")]["stock_quantity"] = stock
                before = copy.deepcopy(self.store.data)
                self.assertEqual(self.order().status_code, 422)
                self.assertEqual(self.store.data, before)

    def test_atomic_batch_decrements_each_item_and_no_partial_commit(self):
        self.assertEqual(self.batch().status_code, 201)
        self.assertEqual(self.stock(), 8)
        self.assertEqual(self.stock("milk"), 4)
        self.assertEqual(len(self.values(storage.CUSTOMER_ORDERS)), 2)
        before = copy.deepcopy(self.store.data)
        response = self.batch([{"item_id": "rice", "quantity": 1}, {"item_id": "milk", "quantity": 100}])
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.store.data, before)

    def test_mixed_vendors_duplicate_items_or_missing_item_are_atomic_failures(self):
        for lines in ([{"item_id": "rice", "quantity": 1}, {"item_id": "rice", "quantity": 1}],
                      [{"item_id": "rice", "quantity": 1}, {"item_id": "missing", "quantity": 1}]):
            before = copy.deepcopy(self.store.data)
            self.assertEqual(self.batch(lines).status_code, 422)
            self.assertEqual(self.store.data, before)
        self.store.data[(storage.SHOP_ITEMS, "milk")]["vendor_id"] = "other_vendor"
        before = copy.deepcopy(self.store.data)
        self.assertEqual(self.batch().status_code, 422)
        self.assertEqual(self.store.data, before)

    def test_vendor_role_and_suspension_enforced(self):
        self.store.data[(storage.USERS, "vendor")]["role"] = "customer"
        self.assertEqual(self.order().status_code, 422)
        self.store.data[(storage.USERS, "vendor")]["role"] = "vendor"
        self.store.data[(storage.USERS, "vendor")]["is_suspended"] = True
        self.assertEqual(self.order().status_code, 422)
        self.assertEqual(self.post("/orders", {"item_id": "rice", "quantity": 1}, user="other_vendor").status_code, 422)
        self.store.data[(storage.USERS, "vendor")]["is_suspended"] = False
        self.assertEqual(self.post("/orders", {"item_id": "rice", "quantity": 1}, user="other_vendor").status_code, 201)

    def test_khata_requires_active_vendor_opened_ledger(self):
        self.assertEqual(self.order(method="khata").status_code, 422)
        self.ledger(status="settled")
        self.assertEqual(self.order(method="khata").status_code, 422)
        self.ledger()
        self.assertEqual(self.order(method="khata", partial_amount_paid=1).status_code, 422)
        response = self.order(method="khata", quantity=2)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.store.data[(storage.KHATA_LEDGERS, "legacy")]["balance"], 74.7)
        transaction = self.values(storage.KHATA_TRANSACTIONS)[0]
        self.assertEqual(transaction["type"], "credit")
        self.assertEqual(transaction["amount"], 24.7)
        self.assertEqual(transaction["order_id"], response.json["order_id"])

    def test_khata_cancel_reverses_full_amount_once_and_restores_stock(self):
        self.ledger()
        response = self.order(method="khata", quantity=2)
        self.assertEqual(self.cancel(response).status_code, 200)
        self.assertEqual(self.cancel(response).status_code, 200)
        self.assertEqual(self.stock(), 10)
        self.assertEqual(self.store.data[(storage.KHATA_LEDGERS, "legacy")]["balance"], 50)
        entries = self.values(storage.KHATA_TRANSACTIONS)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[1]["type"], "debit")
        self.assertEqual(entries[1]["amount"], 24.7)
        order = self.values(storage.CUSTOMER_ORDERS)[0]
        self.assertEqual(order["status"], "cancelled")
        self.assertEqual(order["due_amount"], 0)

    def test_khata_paid_debt_and_missing_ledger_require_reconciliation(self):
        self.ledger(balance=0)
        response = self.order(method="khata")
        self.store.data[(storage.KHATA_LEDGERS, "legacy")]["balance"] = 0
        before = copy.deepcopy(self.store.data)
        self.assertEqual(self.cancel(response).status_code, 409)
        self.assertEqual(self.store.data, before)
        del self.store.data[(storage.KHATA_LEDGERS, "legacy")]
        before = copy.deepcopy(self.store.data)
        self.assertEqual(self.cancel(response).status_code, 409)
        self.assertEqual(self.store.data, before)

    def test_razorpay_paid_order_and_completed_order_cannot_be_cancelled(self):
        response = self.order(method="razorpay")
        order_key = (storage.CUSTOMER_ORDERS, response.json["order_id"])
        self.store.data[order_key]["payment_status"] = "paid"
        self.assertEqual(self.cancel(response).status_code, 409)
        self.store.data[order_key]["payment_status"] = "pending"
        self.store.data[order_key]["status"] = "delivered"
        self.assertEqual(self.cancel(response).status_code, 409)
        self.assertEqual(self.stock(), 9)

    def test_other_customer_cannot_cancel(self):
        response = self.order()
        self.assertEqual(self.cancel(response, user="other_customer").status_code, 403)
        self.assertEqual(self.stock(), 9)

    def test_idempotent_order_retry_changes_neither_stock_nor_debt(self):
        self.ledger()
        first = self.order(method="khata", idempotency_key="request-001")
        second = self.order(method="khata", idempotency_key="request-001")
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        self.assertEqual(first.json, second.json)
        self.assertEqual(self.stock(), 9)
        self.assertEqual(len(self.values(storage.CUSTOMER_ORDERS)), 1)
        self.assertEqual(len(self.values(storage.KHATA_TRANSACTIONS)), 1)
        self.assertEqual(self.order(method="khata", quantity=2, idempotency_key="request-001").status_code, 422)
        self.assertEqual(self.stock(), 9)

    def test_header_idempotency_key_supported(self):
        payload = {"item_id": "rice", "quantity": 1}
        first = self.post("/orders", payload, key="header-001")
        second = self.post("/orders", payload, key="header-001")
        self.assertEqual(first.json, second.json)
        self.assertEqual(self.stock(), 9)

    def test_admin_disabled_item_hidden_and_unorderable_even_if_available_flag_is_stale(self):
        self.store.data[(storage.SHOP_ITEMS, "rice")].update({"disabled_by_admin": True, "is_available": True})
        catalog = self.client.get("/shops")
        self.assertNotIn("rice", [item["uid"] for item in catalog.json])
        self.assertEqual(self.client.get("/shops/rice").status_code, 404)
        before = copy.deepcopy(self.store.data)
        self.assertEqual(self.order().status_code, 422)
        self.assertEqual(self.batch().status_code, 422)
        self.assertEqual(self.store.data, before)

    def test_cancellation_restores_stock_without_reenabling_admin_disabled_item(self):
        response = self.order()
        self.store.data[(storage.SHOP_ITEMS, "rice")].update({"disabled_by_admin": True, "is_available": False})
        self.assertEqual(self.cancel(response).status_code, 200)
        item = self.store.data[(storage.SHOP_ITEMS, "rice")]
        self.assertEqual(item["stock_quantity"], 10)
        self.assertFalse(item["is_available"])
        self.assertTrue(item["disabled_by_admin"])

    def test_atomic_commit_failure_leaves_stock_debt_and_history_unchanged(self):
        self.ledger()
        self.store.fail_commit = True
        before = copy.deepcopy(self.store.data)
        with self.assertRaisesRegex(RuntimeError, "simulated write failure"):
            self.order(method="khata")
        self.assertEqual(self.store.data, before)

    def test_concurrent_orders_cannot_oversell(self):
        self.store.data[(storage.SHOP_ITEMS, "rice")]["stock_quantity"] = 1
        def buy(_):
            with self.app.test_client() as client:
                return client.post("/orders", json={"item_id": "rice", "quantity": 1},
                                   headers={"Authorization": "Bearer customer"}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(buy, range(2)))
        self.assertEqual(sorted(statuses), [201, 422])
        self.assertEqual(self.stock(), 0)
        self.assertEqual(len(self.values(storage.CUSTOMER_ORDERS)), 1)


if __name__ == "__main__":
    unittest.main()
