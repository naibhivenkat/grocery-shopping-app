"""Vendor-confirmed khata balances, updated atomically with their ledger entries."""

import hashlib
import json
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from firebase_admin import firestore
from flask import Blueprint, g, jsonify, request
from google.cloud.firestore_v1.base_query import FieldFilter

from auth_utils import require_role
from db import KHATA_LEDGERS, KHATA_TRANSACTIONS, NOTIFICATIONS, USERS, col, db, doc, now_iso, to_dict
from notification_delivery import notification_data, deliver_push

khata_bp = Blueprint("khata_v2", __name__)
_MAX_PAISE = 1_000_000_000


class KhataError(ValueError):
    def __init__(self, detail, status=422):
        self.detail, self.status = detail, status
        super().__init__(detail)


@khata_bp.errorhandler(KhataError)
def _khata_error(error):
    return jsonify({"detail": error.detail}), error.status


def _money_paise(value, *, allow_zero=False):
    """Validate finite INR amounts and calculate with integer paise."""
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise KhataError("amount must be a finite number")
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0 or amount > Decimal("10000000"):
            raise KhataError("amount must be between 0 and 10000000 INR")
        paise = int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError, OverflowError):
        raise KhataError("amount must be a finite number") from None
    if not allow_zero and paise <= 0:
        raise KhataError("amount must be at least 0.01 INR")
    return paise


def _identifier(value, label):
    if not isinstance(value, str) or not value.strip() or "/" in value or len(value) > 200:
        raise KhataError(f"{label} must be a valid identifier")
    return value.strip()


def _payload():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise KhataError("JSON object required")
    return payload


def _text(value, label, limit):
    if value is None:
        return ""
    if not isinstance(value, str) or len(value) > limit:
        raise KhataError(f"{label} must be text of at most {limit} characters")
    return value.strip()


def _ledger_id(vendor_id, customer_id):
    return "pair_" + hashlib.sha256(json.dumps([vendor_id, customer_id]).encode()).hexdigest()


def lookup_ledger_txn(transaction, vendor_id, customer_id):
    """Read only: call before any transaction writes, including order writes.

    New ledgers have a deterministic pair ID to serialize concurrent creation.
    Existing ledgers retain their IDs and opening balances. Duplicate legacy
    ledgers require reconciliation instead of silently picking one balance.
    """
    canonical = doc(KHATA_LEDGERS, _ledger_id(vendor_id, customer_id))
    snapshot = canonical.get(transaction=transaction)
    query = col(KHATA_LEDGERS).where(filter=FieldFilter("vendor_id", "==", vendor_id)).where(
        filter=FieldFilter("customer_id", "==", customer_id)
    )
    matches = list(transaction.get(query))
    if len(matches) > 1:
        raise KhataError("Duplicate customer ledgers require reconciliation", 409)
    if snapshot.exists:
        data = snapshot.to_dict() or {}
        if data.get("vendor_id") != vendor_id or data.get("customer_id") != customer_id:
            raise KhataError("Ledger parties do not match", 409)
        return canonical, data, True
    if matches:
        return matches[0].reference, matches[0].to_dict() or {}, True
    return canonical, {}, False


def _parties_txn(transaction, vendor_id, customer_id):
    vendor_id = _identifier(vendor_id, "vendor_id")
    customer_id = _identifier(customer_id, "customer_id")
    if vendor_id == customer_id:
        raise KhataError("A customer ledger requires a different shop owner", 404)
    vendor = doc(USERS, vendor_id).get(transaction=transaction)
    customer = doc(USERS, customer_id).get(transaction=transaction)
    if not vendor.exists or (vendor.to_dict() or {}).get("role") != "vendor":
        raise KhataError("Vendor account not found", 404)
    if not customer.exists or (customer.to_dict() or {}).get("role") not in {"customer", "vendor", "service"}:
        raise KhataError("Customer account not found", 404)
    vendor_data, customer_data = vendor.to_dict() or {}, customer.to_dict() or {}
    if vendor_data.get("is_suspended") or customer_data.get("is_suspended"):
        raise KhataError("Ledger party account is suspended", 403)
    return vendor_data, customer_data


def _name(data, *, vendor=False):
    return (data.get("shop_name") if vendor else None) or data.get("full_name") or data.get("username") or ("Shop" if vendor else "Customer")


def _with_party_names(ledger):
    for party in ("vendor", "customer"):
        if ledger.get(f"{party}_id") and not ledger.get(f"{party}_name"):
            snapshot = doc(USERS, ledger[f"{party}_id"]).get()
            if snapshot.exists:
                ledger[f"{party}_name"] = _name(snapshot.to_dict() or {}, vendor=party == "vendor")
    return ledger


def _owned_ledger(ledger_id):
    snapshot = doc(KHATA_LEDGERS, _identifier(ledger_id, "ledger_id")).get()
    if not snapshot.exists:
        raise KhataError("Ledger not found", 404)
    ledger = to_dict(snapshot)
    if g.user_id not in {ledger.get("vendor_id"), ledger.get("customer_id")}:
        raise KhataError("Not your ledger", 403)
    return ledger


@khata_bp.get("/khata/ledgers")
@require_role("vendor", "customer", "service")
def list_ledgers():
    fields = ("vendor_id", "customer_id") if g.user_role == "vendor" else ("customer_id",)
    selected = {}
    for field in fields:
        for snapshot in col(KHATA_LEDGERS).where(filter=FieldFilter(field, "==", g.user_id)).stream():
            selected[snapshot.id] = _with_party_names(to_dict(snapshot))
    items = list(selected.values())
    items.sort(key=lambda item: item.get("updated_at") or "", reverse=True)
    return jsonify(items)


@khata_bp.get("/khata/ledgers/<ledger_id>")
@require_role("vendor", "customer", "service")
def get_ledger(ledger_id):
    return jsonify(_with_party_names(_owned_ledger(ledger_id)))


@khata_bp.post("/khata/ledgers")
@require_role("vendor")
def create_ledger():
    payload = _payload()
    customer_id = _identifier(payload.get("customer_id"), "customer_id")
    _text(payload.get("customer_name"), "customer_name", 200)

    @firestore.transactional
    def _create(transaction):
        vendor, customer = _parties_txn(transaction, g.user_id, customer_id)
        ref, data, exists = lookup_ledger_txn(transaction, g.user_id, customer_id)
        if exists:
            if data.get("status") == "settled":
                data = {**data, "status": "active", "updated_at": now_iso()}
                transaction.set(ref, {"status": "active", "updated_at": data["updated_at"]}, merge=True)
            return {**data, "uid": ref.id}, 200
        timestamp = now_iso()
        data = {"vendor_id": g.user_id, "vendor_name": _name(vendor, vendor=True),
                "customer_id": customer_id, "customer_name": _name(customer),
                "balance": 0.0, "status": "active", "created_at": timestamp, "updated_at": timestamp}
        transaction.set(ref, data)
        return {**data, "uid": ref.id}, 201

    body, status = _create(db().transaction())
    return jsonify(body), status


@khata_bp.get("/khata/customers/search")
@require_role("vendor")
def search_customers():
    query = (request.args.get("q") or "").strip().lower()
    if len(query) < 2:
        return jsonify([])
    matches = []
    users = (snapshot for role in ("customer", "vendor", "service")
             for snapshot in col(USERS).where(filter=FieldFilter("role", "==", role)).stream())
    for snap in users:
        customer = to_dict(snap)
        if customer.get("is_suspended"):
            continue
        haystack = " ".join(str(customer.get(field) or "").lower() for field in ("full_name", "username", "email", "phone"))
        if query in haystack:
            matches.append({"uid": snap.id, "id": snap.id, "full_name": _name(customer),
                            "email": customer.get("email") or "", "phone": customer.get("phone") or ""})
        if len(matches) >= 20:
            break
    return jsonify(matches)


@khata_bp.get("/khata/ledgers/<ledger_id>/transactions")
@require_role("vendor", "customer", "service")
def list_ledger_transactions(ledger_id):
    _owned_ledger(ledger_id)
    items = [to_dict(d) for d in col(KHATA_TRANSACTIONS).where(filter=FieldFilter("ledger_id", "==", ledger_id)).stream()]
    items.sort(key=lambda item: item.get("created_at") or "")
    return jsonify(items)


def _idempotency_ref(ledger_id, payload):
    key = request.headers.get("Idempotency-Key") or payload.get("idempotency_key")
    if key is None:
        return col(KHATA_TRANSACTIONS).document()
    key = _text(key, "idempotency_key", 200)
    if not key:
        raise KhataError("idempotency_key must not be empty")
    digest = hashlib.sha256(json.dumps([ledger_id, key]).encode()).hexdigest()
    return doc(KHATA_TRANSACTIONS, "request_" + digest)


@khata_bp.post("/khata/transactions")
@require_role("vendor", "customer", "service")
def record_transaction():
    payload = _payload()
    ledger_id = _identifier(payload.get("ledger_id"), "ledger_id")
    txn_type = payload.get("type")
    if not isinstance(txn_type, str) or txn_type not in {"credit", "debit", "settlement"}:
        raise KhataError("Valid transaction type required")
    amount = _money_paise(payload.get("amount"))
    description = _text(payload.get("description"), "description", 1000)
    payment_method = _text(payload.get("payment_method"), "payment_method", 40) or None
    payment_reference = _text(payload.get("payment_reference"), "payment_reference", 200) or None
    ledger_ref, txn_ref = doc(KHATA_LEDGERS, ledger_id), _idempotency_ref(ledger_id, payload)
    notification_ref = col(NOTIFICATIONS).document()

    @firestore.transactional
    def _record(transaction):
        snapshot = ledger_ref.get(transaction=transaction)
        if not snapshot.exists:
            raise KhataError("Ledger not found", 404)
        ledger = snapshot.to_dict() or {}
        is_vendor = ledger.get("vendor_id") == g.user_id
        if not is_vendor and ledger.get("customer_id") != g.user_id:
            raise KhataError("Not your ledger", 403)
        if not is_vendor and (txn_type != "debit" or payment_method not in {"cash", "upi"}):
            raise KhataError("Customers can submit Cash or UPI payment requests only", 403)
        _parties_txn(transaction, ledger.get("vendor_id"), ledger.get("customer_id"))
        previous = txn_ref.get(transaction=transaction)
        data = {"ledger_id": ledger_id, "vendor_id": ledger.get("vendor_id"),
                "customer_id": ledger.get("customer_id"), "type": txn_type, "amount": amount / 100,
                "description": description, "payment_method": payment_method, "recorded_by": g.user_id,
                "payment_reference": payment_reference}
        if previous.exists:
            existing = previous.to_dict() or {}
            if any(existing.get(key) != value for key, value in data.items()):
                raise KhataError("Idempotency key already used for a different transaction", 409)
            return {**existing, "uid": txn_ref.id}, 200, None
        balance = _money_paise(ledger.get("balance", 0), allow_zero=True)
        pending = 0
        if not is_vendor:
            if ledger.get("status") != "active":
                raise KhataError("This ledger is not active", 409)
            entries = transaction.get(col(KHATA_TRANSACTIONS).where(filter=FieldFilter("ledger_id", "==", ledger_id)))
            pending = sum(_money_paise((entry.to_dict() or {}).get("amount")) for entry in entries
                          if (entry.to_dict() or {}).get("status") == "pending")
            if amount + pending > balance:
                raise KhataError("Payment requests exceed outstanding balance")
        updated = balance + amount if txn_type == "credit" else balance - amount
        if updated < 0:
            raise KhataError("Payment exceeds outstanding balance")
        if updated > _MAX_PAISE:
            raise KhataError("Outstanding balance exceeds supported limit")
        timestamp = now_iso()
        data["created_at"] = timestamp
        data["status"] = "confirmed" if is_vendor else "pending"
        transaction.set(txn_ref, data)
        if is_vendor:
            transaction.set(ledger_ref, {"balance": updated / 100, "status": "active", "updated_at": timestamp}, merge=True)
        else:
            # All pending submissions write the same ledger document as well,
            # forcing retries to re-read pending totals under concurrent requests.
            transaction.set(ledger_ref, {"updated_at": timestamp}, merge=True)
        event = notification_data(ledger["customer_id"] if is_vendor else ledger["vendor_id"],
            "khata_transaction" if is_vendor else "khata_payment_pending",
            "Khata updated" if is_vendor else "Payment approval requested",
            f"INR {amount / 100:.2f} {payment_method or txn_type}", ledger_id)
        transaction.set(notification_ref, event)
        return {**data, "uid": txn_ref.id}, 201, event

    body, status, event = _record(db().transaction())
    deliver_push(event, lookup=doc)
    return jsonify(body), status


def _moderate_payment(transaction_id, approve):
    txn_ref = doc(KHATA_TRANSACTIONS, _identifier(transaction_id, "transaction_id"))
    notification_ref = col(NOTIFICATIONS).document()

    @firestore.transactional
    def moderate(tx):
        snap = txn_ref.get(transaction=tx)
        if not snap.exists:
            raise KhataError("Payment request not found", 404)
        payment = snap.to_dict() or {}
        ledger_ref = doc(KHATA_LEDGERS, _identifier(payment.get("ledger_id"), "ledger_id"))
        ledger_snap = ledger_ref.get(transaction=tx)
        ledger = ledger_snap.to_dict() or {}
        if not ledger_snap.exists:
            raise KhataError("Ledger not found", 404)
        if ledger.get("vendor_id") != g.user_id:
            raise KhataError("Only this shop owner can approve payments", 403)
        _parties_txn(tx, ledger.get("vendor_id"), ledger.get("customer_id"))
        if (payment.get("vendor_id") != ledger.get("vendor_id")
                or payment.get("customer_id") != ledger.get("customer_id")
                or payment.get("recorded_by") != ledger.get("customer_id") or payment.get("type") != "debit"):
            raise KhataError("Transaction is not a customer payment request", 409)
        wanted = "confirmed" if approve else "rejected"
        if payment.get("status") == wanted:
            return {**payment, "uid": txn_ref.id}, None
        if payment.get("status") != "pending":
            raise KhataError("Payment request has already been reviewed", 409)
        amount = _money_paise(payment.get("amount"))
        balance = _money_paise(ledger.get("balance", 0), allow_zero=True)
        if approve and amount > balance:
            raise KhataError("Payment exceeds current outstanding balance", 409)
        timestamp = now_iso()
        changes = {"status": wanted, "reviewed_by": g.user_id, "reviewed_at": timestamp}
        tx.set(txn_ref, changes, merge=True)
        if approve:
            tx.set(ledger_ref, {"balance": (balance - amount) / 100, "status": "active", "updated_at": timestamp}, merge=True)
        event = notification_data(ledger["customer_id"], "khata_payment_approved" if approve else "khata_payment_rejected",
            "Payment approved" if approve else "Payment rejected", f"INR {amount / 100:.2f}", ledger_ref.id)
        tx.set(notification_ref, event)
        return {**payment, **changes, "uid": txn_ref.id}, event

    body, event = moderate(db().transaction())
    deliver_push(event, lookup=doc)
    return jsonify(body)


@khata_bp.post("/khata/transactions/<transaction_id>/approve")
@require_role("vendor")
def approve_payment(transaction_id):
    return _moderate_payment(transaction_id, True)


@khata_bp.post("/khata/transactions/<transaction_id>/reject")
@require_role("vendor")
def reject_payment(transaction_id):
    return _moderate_payment(transaction_id, False)


@khata_bp.post("/khata/ledgers/<ledger_id>/settle")
@require_role("vendor")
def settle_ledger(ledger_id):
    ledger_ref = doc(KHATA_LEDGERS, _identifier(ledger_id, "ledger_id"))
    txn_ref = col(KHATA_TRANSACTIONS).document()

    @firestore.transactional
    def _settle(transaction):
        snapshot = ledger_ref.get(transaction=transaction)
        if not snapshot.exists:
            raise KhataError("Ledger not found", 404)
        ledger = snapshot.to_dict() or {}
        if ledger.get("vendor_id") != g.user_id:
            raise KhataError("Only the ledger vendor can settle it", 403)
        _parties_txn(transaction, ledger.get("vendor_id"), ledger.get("customer_id"))
        balance = _money_paise(ledger.get("balance", 0), allow_zero=True)
        timestamp = now_iso()
        if balance:
            transaction.set(txn_ref, {"ledger_id": ledger_id, "vendor_id": ledger.get("vendor_id"),
                "customer_id": ledger.get("customer_id"), "type": "settlement", "amount": balance / 100,
                "description": "Ledger settled", "payment_method": None, "recorded_by": g.user_id, "created_at": timestamp})
        transaction.set(ledger_ref, {"balance": 0.0, "status": "settled", "updated_at": timestamp}, merge=True)
        return {"ok": True}

    return jsonify(_settle(db().transaction()))
