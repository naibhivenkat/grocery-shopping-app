"""Strict fake transactions catch Firestore read-after-write and duplicate credits.

No Razorpay/Firebase requests are made. SDK refund calls are mocked; emulator,
provider sandbox and deployment checks remain separate proof requirements.
"""

import copy
import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from flask import Flask

from auth_utils import create_token
from routes.availability import (
    SERVICE_TIMEZONE, availability_bp, get_slot_times, lock_slots_txn, release_slots_txn,
)
from routes.bookings import bookings_bp
from routes.service_wallet import process_refund


class Snapshot:
    def __init__(self, reference):
        self.id = reference.id
        self.exists = reference.key in reference.store.records
        self.data = copy.deepcopy(reference.store.records.get(reference.key))

    def to_dict(self):
        return copy.deepcopy(self.data)


class Reference:
    def __init__(self, store, collection, identity):
        self.store, self.collection, self.id = store, collection, identity
        self.key = (collection, identity)

    def get(self, transaction=None):
        if transaction is not None and transaction.writes:
            raise AssertionError("Firestore transaction read after first write")
        return Snapshot(self)

    def set(self, data, merge=False):
        if merge:
            self.store.records.setdefault(self.key, {}).update(copy.deepcopy(data))
        else:
            self.store.records[self.key] = copy.deepcopy(data)

    def update(self, data):
        if self.key not in self.store.records:
            raise AssertionError("Update requires an existing document")
        self.store.records[self.key].update(copy.deepcopy(data))


class Collection:
    def __init__(self, store, collection):
        self.store, self.name = store, collection

    def document(self, identity=None):
        return Reference(self.store, self.name, identity or "auto-id")


class Transaction:
    def __init__(self, store):
        self.store, self.writes = store, []

    def set(self, ref, data, merge=False):
        self.writes.append((ref, "set", copy.deepcopy(data), merge))

    def update(self, ref, data):
        if ref.key not in self.store.records:
            raise AssertionError("Update of missing document (including queued creates)")
        self.writes.append((ref, "update", copy.deepcopy(data), False))

    def commit(self):
        for ref, operation, data, merge in self.writes:
            if operation == "set":
                ref.set(data, merge=merge)
            else:
                ref.update(data)


class Store:
    def __init__(self):
        self.records = {}

    def col(self, collection):
        return Collection(self, collection)

    def ref(self, collection, identity):
        return self.col(collection).document(identity)

    def put(self, collection, identity, data):
        self.ref(collection, identity).set(data)

    def data(self, collection, identity):
        return self.records.get((collection, identity), {})

    def transaction(self):
        return Transaction(self)


def transactional(function):
    def run(transaction, *args, **kwargs):
        result = function(transaction, *args, **kwargs)
        transaction.commit()
        return result
    return run


class BookingTransactionTests(unittest.TestCase):
    def setUp(self):
        push = patch("routes.bookings.deliver_push")
        self.push = push.start()
        self.addCleanup(push.stop)
        self.store = Store()
        patches = [
            patch("db.col", self.store.col),
            patch("routes.bookings.db", return_value=self.store),
            patch("routes.availability.db", return_value=self.store),
            patch("routes.service_wallet.db", return_value=self.store),
            patch("routes.bookings.firestore.transactional", side_effect=transactional),
        ]
        for current in patches:
            current.start()
            self.addCleanup(current.stop)
        app = Flask(__name__)
        app.config["TESTING"] = True
        app.register_blueprint(bookings_bp)
        app.register_blueprint(availability_bp)
        self.client = app.test_client()
        for identity, role in (("customer-a", "customer"), ("provider-a", "vendor"), ("other", "customer")):
            self.store.put("users", identity, {"role": role, "full_name": identity})
        self.store.put("provider_profiles", "provider-a", {
            "working_schedule": {day: {"from": "09:00 AM", "to": "06:00 PM"} for day in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")},
        })
        self.date = (datetime.now(SERVICE_TIMEZONE) + timedelta(days=2)).strftime("%Y-%m-%d")
        self.store.put("provider_services", "service-a", {
            "provider_id": "provider-a", "title": "Plumbing", "pricing_type": "fixed", "fixed_price": 100,
        })
        self.base = {
            "booking_id": "booking-a", "requester_id": "customer-a", "provider_id": "provider-a",
            "service_id": "service-a", "slot_date": self.date, "slot_time": "10:00", "duration": 60,
            "service_price": 100, "provider_earning": 100, "platform_fee": 5, "tax": 18.9,
            "final_total": 123.9, "status": "pending_payment", "payment_status": "paid",
            "payment_method": "razorpay", "payment_intent_id": "intent-a", "razorpay_payment_id": "pay_a",
        }
        self.store.put("service_bookings", "booking-a", self.base)
        self.store.put("payment_orders", "intent-a", {
            "status": "paid", "purpose": "service", "user_id": "customer-a", "reference_id": "booking-a",
            "payment_id": "pay_a", "amount_paise": 12390, "settlement_status": "settled",
            "currency": "INR", "razorpay_order_id": "order_a",
        })
        self.razorpay = MagicMock()
        self.razorpay.payment.fetch.return_value = {"id": "pay_a", "order_id": "order_a", "amount": 12390,
            "currency": "INR", "captured": True, "status": "captured"}
        self.razorpay.payment.refund.return_value = {
            "id": "rfnd_a", "payment_id": "pay_a", "amount": 12390, "currency": "INR", "status": "processed",
        }
        self.razorpay.refund.fetch.return_value = self.razorpay.payment.refund.return_value
        current = patch("routes.service_wallet.get_razorpay_client", return_value=self.razorpay)
        current.start()
        self.addCleanup(current.stop)

    def headers(self, identity="customer-a"):
        role = self.store.data("users", identity)["role"]
        return {"Authorization": "Bearer " + create_token(identity, role)}

    def post(self, operation, identity="customer-a", body=None):
        return self.client.post(f"/bookings/booking-a/{operation}", json=body or {}, headers=self.headers(identity))

    def confirm(self):
        return self.post("confirm", body={"payment_method": "razorpay", "payment_intent_id": "intent-a"})

    def booking(self):
        return self.store.data("service_bookings", "booking-a")

    def calendar(self):
        return self.store.data("provider_availability", f"provider-a:{self.date}")

    def test_confirm_new_calendar_has_no_read_after_write_and_retry_is_idempotent(self):
        self.assertEqual(self.confirm().status_code, 200)
        self.assertEqual(self.booking()["status"], "confirmed")
        booked = [slot for slot in self.calendar()["slots"] if slot["status"] == "booked"]
        self.assertEqual([slot["time"] for slot in booked], ["10:00", "10:30"])
        self.assertTrue(all(slot["booking_id"] == "booking-a" for slot in booked))
        self.assertEqual(self.confirm().status_code, 200)
        self.assertEqual(len([slot for slot in self.calendar()["slots"] if slot["status"] == "booked"]), 2)

    def test_booking_events_are_committed_once_and_push_follows_transition(self):
        self.assertEqual(self.confirm().status_code, 200)
        self.assertEqual(self.confirm().status_code, 200)
        self.assertEqual(self.push.call_count, 1)
        event = self.push.call_args.args[0]
        self.assertEqual(event['user_id'], 'provider-a')
        self.assertEqual(event['reference_id'], 'booking-a')
        self.assertEqual(event['type'], 'service_booking')
        self.assertEqual(self.post('accept', identity='provider-a').status_code, 200)
        self.assertEqual(self.push.call_args.args[0]['user_id'], 'customer-a')
        events = [value for (collection, _), value in self.store.records.items() if collection == 'notifications']
        self.assertEqual(len(events), 2)
        self.assertEqual(self.post('accept', identity='other').status_code, 403)
        self.assertEqual(self.push.call_count, 2)

    def test_confirm_preserves_server_quote_when_current_service_price_changes(self):
        self.store.data("provider_services", "service-a")["fixed_price"] = 300
        self.assertEqual(self.confirm().status_code, 200)
        self.assertEqual(self.booking()["final_total"], 123.9)
        self.assertEqual(self.booking()["provider_earning"], 100)

    def test_unsettled_foreign_mismatched_amount_or_review_payment_cannot_lock(self):
        intent = self.store.data("payment_orders", "intent-a")
        original = copy.deepcopy(intent)
        for change in ({"status": "created"}, {"user_id": "other"}, {"reference_id": "another"},
                       {"amount_paise": 100}, {"settlement_status": "requires_review"}, {"payment_id": None}):
            with self.subTest(change=change):
                intent.update(change)
                self.assertEqual(self.confirm().status_code, 400)
                self.assertEqual(self.calendar(), {})
                self.assertEqual(self.booking()["status"], "pending_payment")
                intent.clear()
                intent.update(original)
        self.assertEqual(self.post("confirm", body={"payment_method": "wallet"}).status_code, 410)
        self.assertEqual(self.post("confirm", identity="other").status_code, 403)

    def test_pending_creation_validates_date_schedule_and_numeric_duration(self):
        base = {"provider_id": "provider-a", "service_id": "service-a", "slot_date": self.date, "slot_time": "11:00", "duration": 60}
        invalid = [{"slot_date": "2026-02-30"}, {"slot_date": "2020-01-01"}, {"slot_time": "11:15"},
                   {"slot_time": "bad"}, {"slot_time": "23:30"}, {"duration": 0}, {"duration": True},
                   {"duration": 60.5}, {"duration": 31}, {"duration": 510}]
        for fields in invalid:
            response = self.client.post("/bookings/create-pending", json={**base, **fields}, headers=self.headers())
            self.assertEqual(response.status_code, 422, fields)
        self.assertEqual(self.client.post("/bookings/create-pending", json={**base, "slot_time": "07:00"}, headers=self.headers()).status_code, 409)
        response = self.client.post("/bookings/create-pending", json=base, headers=self.headers())
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json["final_total"], 123.9)

    def test_no_empty_invalid_or_missing_schedule_slot_lock_succeeds(self):
        for time, duration in (("bad", 60), ("10:15", 60), ("23:30", 60), ("10:00", 0), ("10:00", -30), ("10:00", True), ("10:00", 45)):
            self.assertFalse(lock_slots_txn(self.store.transaction(), "provider-a", self.date, time, duration, "booking-a"))
        self.store.put("provider_profiles", "provider-a", {"working_schedule": {}})
        self.assertFalse(lock_slots_txn(self.store.transaction(), "provider-a", self.date, "10:00", 60, "booking-a"))
        self.assertEqual(self.calendar(), {})
        self.assertEqual(get_slot_times("23:30", 30), ["23:30"])

    def test_service_price_must_be_finite_positive_and_provider_available(self):
        payload = {"provider_id": "provider-a", "service_id": "service-a", "slot_date": self.date, "slot_time": "11:00", "duration": 60}
        service = self.store.data("provider_services", "service-a")
        for price in (0, -10, "NaN", "Infinity", "0.001", "not-money", 10_000_001):
            service["fixed_price"] = price
            response = self.client.post("/bookings/create-pending", json=payload, headers=self.headers())
            self.assertEqual(response.status_code, 422, price)
        service["fixed_price"] = 100
        self.store.data("users", "provider-a")["is_suspended"] = True
        self.assertEqual(self.client.post("/bookings/create-pending", json=payload, headers=self.headers()).status_code, 409)
        self.assertEqual(self.confirm().status_code, 400)
        self.assertEqual(self.calendar(), {})

    def test_provider_cannot_free_booked_slot_and_public_calendar_omits_booking_id(self):
        self.confirm()
        response = self.client.put("/provider/availability", json={"date": self.date, "updates": [{"time": "10:00", "status": "available"}]}, headers=self.headers("provider-a"))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(next(slot for slot in self.calendar()["slots"] if slot["time"] == "10:00")["status"], "booked")
        response = self.client.get(f"/providers/provider-a/availability?date={self.date}")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(all("booking_id" not in slot for slot in response.json["slots"]))

    def test_app_full_calendar_can_retain_booked_rows_while_blocking_other_slots(self):
        self.confirm()
        updates = [{"time": slot["time"], "status": "blocked" if slot["time"] == "11:00" else slot["status"]} for slot in self.calendar()["slots"]]
        response = self.client.put("/provider/availability", json={"date": self.date, "updates": updates}, headers=self.headers("provider-a"))
        self.assertEqual(response.status_code, 200)
        booked = [slot for slot in self.calendar()["slots"] if slot["status"] == "booked"]
        self.assertTrue(all(slot["booking_id"] == "booking-a" for slot in booked))
        self.assertEqual(len(booked), 2)

    def test_inactive_provider_profile_cannot_use_existing_calendar_and_get_is_read_only(self):
        response = self.client.get(f"/providers/provider-a/availability?date={self.date}")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json["slots"])
        self.assertEqual(self.calendar(), {})
        self.confirm()
        self.store.put("service_bookings", "booking-a", self.base)
        self.store.data("provider_profiles", "provider-a")["is_active"] = False
        self.assertEqual(self.confirm().status_code, 400)
        self.assertEqual(self.client.get(f"/providers/provider-a/availability?date={self.date}").status_code, 404)

    def test_availability_new_calendar_has_single_create_and_only_allowed_updates(self):
        payload = {"date": self.date, "updates": [{"time": "10:00", "status": "blocked"}]}
        response = self.client.put("/provider/availability", json=payload, headers=self.headers("provider-a"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(next(slot for slot in self.calendar()["slots"] if slot["time"] == "10:00")["status"], "blocked")
        for updates in ([{"time": "10:00", "status": "booked"}], [{"time": "07:00", "status": "available"}], [None], [], [{"time": "10:00", "status": "available"}] * 2):
            response = self.client.put("/provider/availability", json={"date": self.date, "updates": updates}, headers=self.headers("provider-a"))
            self.assertEqual(response.status_code, 422)
        self.assertEqual(self.client.get("/providers/provider-a/availability?date=bad").status_code, 422)

    def test_completion_atomic_earnings_settlement_and_repeat_never_double_credit(self):
        self.booking()["status"] = "started"
        self.store.put("service_wallets", "provider-a", {"balance": 25})
        self.store.put("provider_earnings", "provider-a", {"lifetime_total": 50})
        self.assertEqual(self.post("complete", identity="provider-a").status_code, 200)
        self.assertEqual(self.store.data("service_wallets", "provider-a")["balance"], 125)
        self.assertEqual(self.store.data("provider_earnings", "provider-a")["lifetime_total"], 150)
        self.assertEqual(self.post("complete", identity="provider-a").status_code, 200)
        self.assertEqual(self.store.data("service_wallets", "provider-a")["balance"], 125)
        self.assertEqual(self.post("complete", identity="other").status_code, 403)

    def test_existing_income_marker_prevents_credit_again_and_unpaid_cannot_complete(self):
        self.booking()["status"] = "started"
        self.store.put("service_wallet_transactions", "credit_booking-a", {"amount": 100})
        self.store.put("service_wallets", "provider-a", {"balance": 100})
        self.assertEqual(self.post("complete", identity="provider-a").status_code, 200)
        self.assertEqual(self.store.data("service_wallets", "provider-a")["balance"], 100)
        self.booking().update({"status": "started", "payment_status": "unpaid"})
        self.assertEqual(self.post("complete", identity="provider-a").status_code, 400)

    def test_cancel_and_reject_release_before_writes_refund_once_and_keep_earnings(self):
        for operation, identity in (("cancel", "customer-a"), ("reject", "provider-a")):
            with self.subTest(operation=operation):
                self.store.put("service_bookings", "booking-a", self.base)
                self.store.records.pop(("provider_availability", f"provider-a:{self.date}"), None)
                self.confirm()
                self.store.put("service_wallets", "provider-a", {"balance": 75})
                self.razorpay.payment.refund.reset_mock()
                response = self.post(operation, identity=identity)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json["refund"]["status"], "completed")
                self.assertEqual(self.booking()["payment_status"], "refunded")
                self.assertTrue(all(slot["status"] != "booked" for slot in self.calendar()["slots"]))
                self.assertEqual(self.store.data("service_wallets", "provider-a")["balance"], 75)
                self.assertEqual(self.post(operation, identity=identity).status_code, 200)
                self.razorpay.payment.refund.assert_called_once()

    def test_reject_accepts_existing_apk_bodyless_json_action(self):
        self.confirm()
        response = self.client.post("/bookings/booking-a/reject", headers={**self.headers("provider-a"), "Content-Type": "application/json"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.booking()["status"], "rejected")

    def test_paid_pending_can_cancel_without_releasing_another_booking_slots(self):
        calendar_id = f"provider-a:{self.date}"
        self.store.put("provider_availability", calendar_id, {"slots": [{"time": "10:00", "status": "booked", "booking_id": "another-booking"}]})
        self.assertEqual(self.confirm().status_code, 409)
        self.assertEqual(self.post("cancel").status_code, 200)
        self.assertEqual(self.calendar()["slots"][0]["status"], "booked")
        transaction = self.store.transaction()
        release_slots_txn(transaction, "provider-a", self.date, "10:00", 60, "booking-a")
        transaction.commit()
        self.assertEqual(self.calendar()["slots"][0]["status"], "booked")

    def test_historical_wallet_refund_credit_and_marker_are_atomic_once(self):
        self.booking().update({"status": "cancelled", "payment_method": "wallet"})
        self.store.put("wallets", "customer-a", {"balance": 10, "total_credit": 20})
        self.assertEqual(process_refund("booking-a")["status"], "completed")
        self.assertEqual(self.store.data("wallets", "customer-a")["balance"], 133.9)
        self.assertEqual(self.store.data("wallets", "customer-a")["total_credit"], 143.9)
        self.assertEqual(process_refund("booking-a")["status"], "completed")
        self.assertEqual(self.store.data("wallets", "customer-a")["balance"], 133.9)
        self.razorpay.payment.refund.assert_not_called()

    def test_existing_wallet_refund_marker_prevents_balance_increment(self):
        self.booking().update({"status": "cancelled", "payment_method": "wallet"})
        self.store.put("wallets", "customer-a", {"balance": 133.9})
        self.store.put("wallet_transactions", "refund_booking-a", {"amount": 123.9})
        self.assertEqual(process_refund("booking-a")["status"], "completed")
        self.assertEqual(self.store.data("wallets", "customer-a")["balance"], 133.9)

    def test_network_response_loss_retries_same_refund_key_and_original_amount(self):
        self.booking()["status"] = "cancelled"
        self.razorpay.payment.refund.side_effect = [TimeoutError("response lost"), self.razorpay.payment.refund.return_value]
        self.assertEqual(process_refund("booking-a")["status"], "failed")
        self.booking()["final_total"] = 900  # Original refund intent cannot change on retry.
        self.assertEqual(process_refund("booking-a")["status"], "completed")
        first, second = self.razorpay.payment.refund.call_args_list
        self.assertEqual(first, second)
        self.assertEqual(second.args[1]["amount"], 12390)
        self.assertTrue(second.kwargs["headers"]["X-Refund-Idempotency"].startswith("booking-refund-"))

    def test_pending_refund_is_submitted_and_later_fetched_without_second_create(self):
        self.booking()["status"] = "cancelled"
        pending = {**self.razorpay.payment.refund.return_value, "status": "pending"}
        self.razorpay.payment.refund.return_value = pending
        self.assertEqual(process_refund("booking-a")["status"], "submitted")
        self.assertEqual(self.booking()["payment_status"], "paid")
        self.assertEqual(process_refund("booking-a")["status"], "completed")
        self.razorpay.payment.refund.assert_called_once()
        self.razorpay.refund.fetch.assert_called_once_with("rfnd_a", timeout=30)

    def test_refund_requires_matching_capture_and_foreign_or_missing_intent_needs_review(self):
        self.booking()["status"] = "cancelled"
        self.store.data("payment_orders", "intent-a")["user_id"] = "other"
        self.assertEqual(process_refund("booking-a")["status"], "requires_review")
        self.razorpay.payment.refund.assert_not_called()
        self.booking().pop("refund_status")
        self.store.data("payment_orders", "intent-a")["user_id"] = "customer-a"
        self.razorpay.payment.fetch.return_value["amount"] = 1
        self.assertEqual(process_refund("booking-a")["status"], "requires_review")
        self.razorpay.payment.refund.assert_not_called()

    def test_stale_refund_worker_cannot_overwrite_newer_lease_result(self):
        self.booking()["status"] = "cancelled"
        def newer_worker(*args, **kwargs):
            self.booking().update({"refund_lease_token": "newer-worker", "refund_status": "submitted", "refund_id": "rfnd_newer"})
            raise TimeoutError("Old worker failed after its lease expired")
        self.razorpay.payment.refund.side_effect = newer_worker
        result = process_refund("booking-a")
        self.assertEqual(result["status"], "submitted")
        self.assertEqual(self.booking()["refund_id"], "rfnd_newer")

    def test_refunds_only_cancelled_paid_bookings_and_legacy_ambiguity_needs_review(self):
        self.assertEqual(process_refund("booking-a")["status"], "ineligible")
        self.booking().update({"status": "cancelled", "refund_status": "processing"})
        self.assertEqual(process_refund("booking-a")["status"], "requires_review")
        self.razorpay.payment.refund.assert_not_called()


if __name__ == "__main__":
    unittest.main()
