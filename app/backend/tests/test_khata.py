"""Isolated HTTP/business tests. Mock atomicity, not live Firestore retries."""
import copy
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from functools import wraps
from unittest.mock import patch
from flask import Flask
import auth_utils
import db as storage
from routes import khata


class Snapshot:
    def __init__(self, ref, data):
        self.reference, self.id = ref, ref.id
        self.exists = data is not None
        self.data = copy.deepcopy(data)

    def to_dict(self):
        return copy.deepcopy(self.data)


class Ref:
    def __init__(self, store, collection, identifier):
        self.store, self.collection, self.id = store, collection, identifier

    @property
    def key(self):
        return self.collection, self.id

    def get(self, transaction=None):
        if transaction:
            transaction.read()
        return Snapshot(self, self.store.data.get(self.key))


class Query:
    def __init__(self, store, collection, filters=()):
        self.store, self.collection, self.filters = store, collection, filters

    def where(self, *, filter):
        return Query(self.store, self.collection, self.filters + ((filter.field_path, filter.value),))

    def stream(self):
        return [Snapshot(Ref(self.store, collection, identifier), data)
                for (collection, identifier), data in list(self.store.data.items())
                if collection == self.collection and all(data.get(field) == value for field, value in self.filters)]

    def document(self, identifier=None):
        if identifier is None:
            with self.store.lock:
                self.store.next_id += 1
                identifier = f"auto_{self.store.next_id}"
        return Ref(self.store, self.collection, identifier)


class Transaction:
    def __init__(self, store):
        self.store, self.pending = store, []

    def read(self):
        if self.pending:
            raise AssertionError("Firestore reads must precede writes")

    def get(self, query):
        self.read()
        return query.stream()

    def set(self, ref, data, merge=False):
        self.pending.append((ref.key, copy.deepcopy(data), merge))

    def commit(self):
        staged = copy.deepcopy(self.store.data)
        for key, data, merge in self.pending:
            staged[key] = {**staged.get(key, {}), **data} if merge else data
        if self.store.fail_commit:
            raise RuntimeError("simulated write failure")
        self.store.data = staged


class Store:
    def __init__(self):
        self.data, self.next_id = {}, 0
        self.lock = threading.RLock()
        self.fail_commit = False

    def col(self, collection):
        return Query(self, collection)

    def doc(self, collection, identifier):
        return self.col(collection).document(identifier)

    def transaction(self):
        return Transaction(self)

    def transactional(self, fn):
        @wraps(fn)
        def run(transaction):
            with self.lock:
                result = fn(transaction)
                transaction.commit()
                return result
        return run


class KhataTests(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        self.store.data.update({
            (storage.USERS, "vendor"): {"role": "vendor", "shop_name": "Test Shop"},
            (storage.USERS, "other_vendor"): {"role": "vendor"},
            (storage.USERS, "customer"): {"role": "customer", "full_name": "Test Customer"},
            (storage.USERS, "other_customer"): {"role": "customer"},
        })
        self.app = Flask(__name__)
        self.app.config["TESTING"] = True
        self.app.register_blueprint(khata.khata_bp)
        patches = [patch.object(khata, "col", self.store.col), patch.object(khata, "doc", self.store.doc),
                   patch.object(khata, "db", lambda: self.store), patch.object(storage, "doc", self.store.doc),
                   patch.object(khata.firestore, "transactional", self.store.transactional),
                   patch.object(auth_utils, "decode_token", lambda token: {"sub": token, "role": "customer"})]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        self.client = self.app.test_client()

    def request(self, method, path, body=None, user="vendor", key=None):
        headers = {"Authorization": f"Bearer {user}"} if user else {}
        if key:
            headers["Idempotency-Key"] = key
        return self.client.open(path, method=method, json=body, headers=headers)

    def ledger(self, balance=0, identifier="legacy"):
        self.store.data[(storage.KHATA_LEDGERS, identifier)] = {
            "vendor_id": "vendor", "customer_id": "customer", "balance": balance, "status": "active"}
        return identifier

    def record(self, amount, kind="credit", user="vendor", key=None, **extra):
        return self.request("POST", "/khata/transactions", {
            "ledger_id": "legacy", "type": kind, "amount": amount, **extra}, user=user, key=key)

    def entries(self):
        return [value for (collection, _), value in self.store.data.items() if collection == storage.KHATA_TRANSACTIONS]

    def balance(self):
        return self.store.data[(storage.KHATA_LEDGERS, "legacy")]["balance"]

    def test_vendor_creation_is_idempotent_and_authoritative_party_names(self):
        first = self.request("POST", "/khata/ledgers", {"customer_id": "customer", "customer_name": "Forged Name"})
        second = self.request("POST", "/khata/ledgers", {"customer_id": "customer"})
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json["uid"], second.json["uid"])
        self.assertEqual(first.json["customer_name"], "Test Customer")

    def test_legacy_ledger_reused_without_erasing_opening_balance(self):
        self.ledger(150)
        response = self.request("POST", "/khata/ledgers", {"customer_id": "customer"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["uid"], "legacy")
        self.assertEqual(self.record(25).status_code, 201)
        self.assertEqual(self.balance(), 175)

    def test_duplicate_legacy_ledgers_fail_without_mutation(self):
        self.ledger(10)
        self.ledger(20, "duplicate")
        before = copy.deepcopy(self.store.data)
        response = self.request("POST", "/khata/ledgers", {"customer_id": "customer"})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.store.data, before)

    def test_invalid_party_creation_and_suspension(self):
        for identifier, status in (("missing", 404), ("vendor", 404), ("bad/id", 422), ([], 422)):
            with self.subTest(identifier=identifier):
                response = self.request("POST", "/khata/ledgers", {"customer_id": identifier})
                self.assertEqual(response.status_code, status)
        self.store.data[(storage.USERS, "customer")]["is_suspended"] = True
        self.assertEqual(self.request("POST", "/khata/ledgers", {"customer_id": "customer"}).status_code, 403)

    def test_customer_cannot_forge_payment_or_clear_debt(self):
        self.ledger(100)
        for kind in ("credit", "debit", "settlement"):
            self.assertEqual(self.record(10, kind, user="customer").status_code, 403)
        self.assertEqual(self.request("POST", "/khata/ledgers/legacy/settle", user="customer").status_code, 403)
        self.assertEqual(self.balance(), 100)
        self.assertEqual(self.entries(), [])

    def test_foreign_vendor_cannot_mutate_or_read(self):
        self.ledger(100)
        self.assertEqual(self.record(10, user="other_vendor").status_code, 403)
        self.assertEqual(self.request("POST", "/khata/ledgers/legacy/settle", user="other_vendor").status_code, 403)
        self.assertEqual(self.request("GET", "/khata/ledgers/legacy", user="other_customer").status_code, 403)
        self.assertEqual(self.request("GET", "/khata/ledgers/legacy/transactions", user="other_customer").status_code, 403)

    def test_invalid_money_and_payloads_leave_no_writes(self):
        self.ledger()
        for amount in (None, True, False, "NaN", "Infinity", "-Infinity", [], {}, 0, -1, "garbage", 10000001, 0.001):
            with self.subTest(amount=amount):
                self.assertEqual(self.record(amount).status_code, 422)
        self.assertEqual(self.record(1, kind=[]).status_code, 422)
        self.assertEqual(self.request("POST", "/khata/transactions", []).status_code, 422)
        self.assertEqual(self.entries(), [])

    def test_paise_arithmetic_and_overpayment(self):
        self.ledger(0.1)
        self.assertEqual(self.record(0.2).status_code, 201)
        self.assertEqual(self.balance(), 0.3)
        self.assertEqual(self.record(0.31, "debit").status_code, 422)
        self.assertEqual(self.record(0.3, "debit").status_code, 201)
        self.assertEqual(self.balance(), 0)

    def test_idempotent_retry_does_not_charge_twice_and_mismatch_conflicts(self):
        self.ledger()
        self.assertEqual(self.record(100, key="same-request").status_code, 201)
        self.assertEqual(self.record(100, key="same-request").status_code, 200)
        self.assertEqual(self.record(101, key="same-request").status_code, 409)
        self.assertEqual(self.record(100, "debit", key="same-request").status_code, 409)
        self.assertEqual(self.balance(), 100)
        self.assertEqual(len(self.entries()), 1)

    def test_settlement_is_atomic_and_repeat_does_not_add_duplicate(self):
        self.ledger(175.75)
        for _ in range(2):
            self.assertEqual(self.request("POST", "/khata/ledgers/legacy/settle").status_code, 200)
        self.assertEqual(self.balance(), 0)
        self.assertEqual(len(self.entries()), 1)
        self.assertEqual(self.entries()[0]["amount"], 175.75)
        self.assertEqual(self.store.data[(storage.KHATA_LEDGERS, "legacy")]["status"], "settled")

    def test_commit_failure_does_not_leave_entry_without_balance_update(self):
        self.ledger(20)
        self.store.fail_commit = True
        with self.assertRaisesRegex(RuntimeError, "simulated write failure"):
            self.record(10)
        self.assertEqual(self.balance(), 20)
        self.assertEqual(self.entries(), [])

    def test_deleted_customer_blocks_mutation(self):
        self.ledger(20)
        del self.store.data[(storage.USERS, "customer")]
        self.assertEqual(self.record(10).status_code, 404)
        self.assertEqual(self.balance(), 20)

    def test_customer_can_read_own_balance_and_transactions(self):
        self.ledger(20)
        self.assertEqual(self.request("GET", "/khata/ledgers/legacy", user="customer").json["balance"], 20)
        self.assertEqual(self.request("GET", "/khata/ledgers/legacy/transactions", user="customer").status_code, 200)
        self.assertEqual(self.request("GET", "/khata/ledgers", user="customer").status_code, 200)
        self.assertEqual(self.request("GET", "/khata/ledgers", user=None).status_code, 401)

    def test_concurrent_customer_ledger_creation_has_one_ledger(self):
        def create(_):
            with self.app.test_client() as client:
                return client.post("/khata/ledgers", json={"customer_id": "customer"},
                                   headers={"Authorization": "Bearer vendor"}).status_code
        with ThreadPoolExecutor(max_workers=8) as pool:
            statuses = list(pool.map(create, range(20)))
        self.assertEqual(statuses.count(201), 1)
        self.assertEqual(statuses.count(200), 19)
        ledgers = [key for key in self.store.data if key[0] == storage.KHATA_LEDGERS]
        self.assertEqual(len(ledgers), 1)

    def test_concurrent_payments_cannot_overdraw(self):
        self.ledger(100)
        def pay(_):
            with self.app.test_client() as client:
                return client.post("/khata/transactions", json={"ledger_id": "legacy", "type": "debit", "amount": 60},
                                   headers={"Authorization": "Bearer vendor"}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(pay, range(2)))
        self.assertEqual(sorted(statuses), [201, 422])
        self.assertEqual(self.balance(), 40)
        self.assertEqual(len(self.entries()), 1)


if __name__ == "__main__":
    unittest.main()
