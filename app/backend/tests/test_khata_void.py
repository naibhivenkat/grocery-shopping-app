"""Audited corrections with mocked atomic Firestore, not a live database."""
import copy
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import db as storage
from routes import khata
import test_khata as fixtures


class KhataVoidTests(unittest.TestCase):
    # Reuse fixture helpers without inheriting and collecting its test methods.
    setUp = fixtures.KhataTests.setUp
    request = fixtures.KhataTests.request
    ledger = fixtures.KhataTests.ledger
    record = fixtures.KhataTests.record
    balance = fixtures.KhataTests.balance

    def entry(self, kind="credit"):
        self.ledger(100)
        response = self.record(20, kind)
        self.assertEqual(response.status_code, 201)
        return response.json["uid"]

    def void(self, identifier, user="vendor", reason="Mistaken entry"):
        return self.request("POST", f"/khata/transactions/{identifier}/void", {"reason": reason}, user=user)

    def events(self):
        return [value for (collection, _), value in self.store.data.items() if collection == storage.NOTIFICATIONS]

    def test_credit_audit_visibility_and_idempotent_retry(self):
        identifier = self.entry()
        before = len(self.events())
        with patch.object(khata, "deliver_push") as push:
            response = self.void(identifier)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(self.balance(), 100)
            self.assertEqual(response.json["status"], "voided")
            self.assertEqual(response.json["amount"], 20)
            self.assertEqual(response.json["type"], "credit")
            self.assertEqual(response.json["void_reason"], "Mistaken entry")
            self.assertEqual(response.json["voided_by"], "vendor")
            self.assertTrue(response.json["voided_at"])
            self.assertFalse(response.json["can_void"])
            self.assertEqual(self.void(identifier, reason="Retry").json, response.json)
            self.assertEqual(push.call_args_list[0].args[0]["type"], "khata_transaction_voided")
            self.assertIsNone(push.call_args_list[1].args[0])
        self.assertEqual(len(self.events()), before + 1)
        self.assertEqual(self.balance(), 100)
        rows = self.request("GET", "/khata/ledgers/legacy/transactions").json
        self.assertEqual(rows[0]["status"], "voided")
        self.assertFalse(rows[0]["can_void"])

    def test_debit_and_settlement_restore_balance(self):
        for kind in ("debit", "settlement"):
            identifier = self.entry(kind)
            self.assertEqual(self.balance(), 80)
            self.assertEqual(self.void(identifier).status_code, 200)
            self.assertEqual(self.balance(), 100)

    def test_auth_ownership_and_suspended_party(self):
        identifier = self.entry()
        before = copy.deepcopy(self.store.data)
        for user, expected in ((None, 401), ("customer", 403), ("other_vendor", 403)):
            self.assertEqual(self.void(identifier, user=user).status_code, expected)
        self.assertEqual(self.store.data, before)
        self.store.data[(storage.USERS, "customer")]["is_suspended"] = True
        self.assertEqual(self.void(identifier).status_code, 403)

    def test_confirmed_manual_unlinked_only_and_server_eligibility(self):
        identifier = self.entry()
        key = (storage.KHATA_TRANSACTIONS, identifier)
        base = copy.deepcopy(self.store.data[key])
        for changes in ({"order_id": "order"}, {"payment_id": "pay_1"}, {"payment_reference": "bank"},
                        {"payment_intent_id": "intent"}, {"razorpay_payment_id": "pay_2"},
                        {"payment_method": "razorpay"}, {"recorded_by": "customer"},
                        {"status": "pending"}, {"status": "rejected"}, {"status": None},
                        {"customer_id": "other_customer"}, {"vendor_id": "other_vendor"}):
            with self.subTest(changes=changes):
                self.store.data[key] = {**base, **changes}
                before = copy.deepcopy(self.store.data)
                self.assertEqual(self.void(identifier).status_code, 409)
                self.assertEqual(self.store.data, before)
                self.assertFalse(self.request("GET", "/khata/ledgers/legacy/transactions").json[0]["can_void"])
        self.store.data[key] = base
        self.assertTrue(self.request("GET", "/khata/ledgers/legacy/transactions").json[0]["can_void"])
        self.assertFalse(self.request("GET", "/khata/ledgers/legacy/transactions", user="customer").json[0]["can_void"])

    def test_validation_and_missing_documents(self):
        identifier = self.entry()
        before = copy.deepcopy(self.store.data)
        for reason in (None, "", "  ", 4, [], "x" * 501):
            self.assertEqual(self.void(identifier, reason=reason).status_code, 422)
        self.assertEqual(self.request("POST", f"/khata/transactions/{identifier}/void", {"reason": "x", "amount": 1}).status_code, 422)
        self.assertEqual(self.void("missing").status_code, 404)
        self.assertEqual(self.store.data, before)
        del self.store.data[(storage.KHATA_LEDGERS, "legacy")]
        self.assertEqual(self.void(identifier).status_code, 404)

    def test_balance_bounds_and_pending_requests(self):
        identifier = self.entry()
        ledger = self.store.data[(storage.KHATA_LEDGERS, "legacy")]
        ledger["balance"] = 10
        before = copy.deepcopy(self.store.data)
        self.assertEqual(self.void(identifier).status_code, 409)
        self.assertEqual(self.store.data, before)
        ledger["balance"] = 120
        self.assertEqual(self.record(110, "debit", user="customer", payment_method="cash").status_code, 201)
        before = copy.deepcopy(self.store.data)
        self.assertEqual(self.void(identifier).status_code, 409)
        self.assertEqual(self.store.data, before)
        self.store.data[(storage.KHATA_TRANSACTIONS, identifier)]["type"] = "debit"
        self.store.data[(storage.KHATA_LEDGERS, "legacy")]["balance"] = 10000000
        self.assertEqual(self.void(identifier).status_code, 409)

    def test_new_manual_settlement_can_be_corrected_without_losing_opening_balance(self):
        self.ledger(100)
        self.assertEqual(self.request('POST', '/khata/ledgers/legacy/settle').status_code, 200)
        self.assertEqual(self.balance(), 0)
        entries = self.request('GET', '/khata/ledgers/legacy/transactions').json
        self.assertEqual(len(entries), 1)
        self.assertTrue(entries[0]['can_void'])
        identifier = entries[0]['uid']
        self.assertEqual(self.void(identifier).status_code, 200)
        self.assertEqual(self.balance(), 100)
        self.assertEqual(self.void(identifier).status_code, 200)
        self.assertEqual(self.balance(), 100)

    def test_atomic_rollback(self):
        identifier = self.entry()
        before = copy.deepcopy(self.store.data)
        self.store.fail_commit = True
        with self.assertRaisesRegex(RuntimeError, "simulated write failure"):
            self.void(identifier)
        self.assertEqual(self.store.data, before)

    def test_concurrent_retries_reverse_once(self):
        identifier = self.entry()
        before = len(self.events())
        def correct(_):
            with self.app.test_client() as client:
                return client.post(f"/khata/transactions/{identifier}/void", json={"reason": "Mistake"},
                                   headers={"Authorization": "Bearer vendor"}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(list(pool.map(correct, range(2))), [200, 200])
        self.assertEqual(self.balance(), 100)
        self.assertEqual(len(self.events()), before + 1)


if __name__ == "__main__":
    unittest.main()
