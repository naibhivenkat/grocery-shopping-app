"""`/khata/*` endpoints consumed by `KhataRemoteDataSource`.

Implements the vendor-side khata (credit-book) ledger: each vendor can have
multiple customer ledgers tracking outstanding balance via typed
transactions (credit, debit, settlement).
"""

from flask import Blueprint, g, jsonify, request
from google.cloud.firestore_v1.base_query import FieldFilter

from auth_utils import require_auth, require_role
from db import (
    KHATA_LEDGERS,
    KHATA_TRANSACTIONS,
    USERS,
    col,
    doc,
    now_iso,
    to_dict,
)


khata_bp = Blueprint("khata_v2", __name__)


def _recompute_balance(ledger_id: str, ledger_ref) -> float:
    balance = 0.0
    for d in (
        col(KHATA_TRANSACTIONS)
        .where(filter=FieldFilter("ledger_id", "==", ledger_id))
        .stream()
    ):
        data = d.to_dict() or {}
        try:
            amount = float(data.get("amount") or 0)
        except (TypeError, ValueError):
            amount = 0.0
        t = data.get("type")
        if t == "credit":
            balance += amount
        elif t in ("debit", "settlement"):
            balance -= amount
    ledger_ref.set({"balance": balance, "updated_at": now_iso()}, merge=True)
    return balance


@khata_bp.get("/khata/ledgers")
@require_auth
def list_ledgers():
    field = "vendor_id" if g.user_role == "vendor" else "customer_id"
    query = col(KHATA_LEDGERS).where(filter=FieldFilter(field, "==", g.user_id))
    items = [_with_party_names(to_dict(d)) for d in query.stream()]
    items.sort(key=lambda item: item.get("updated_at") or "", reverse=True)
    return jsonify(items)


@khata_bp.post("/khata/ledgers")
@require_role("vendor")
def create_ledger():
    payload = request.get_json(silent=True) or {}
    customer_id = payload.get("customer_id")
    customer_name = payload.get("customer_name") or ""
    if not customer_id:
        return jsonify({"detail": "customer_id is required"}), 422

    ref = col(KHATA_LEDGERS).document()
    vendor = doc(USERS, g.user_id).get()
    vendor_data = vendor.to_dict() or {}
    ref.set({
        "vendor_id": g.user_id,
        "vendor_name": vendor_data.get("shop_name")
            or vendor_data.get("full_name")
            or vendor_data.get("username")
            or "Shop",
        "customer_id": customer_id,
        "customer_name": customer_name,
        "balance": 0.0,
        "status": "active",
        "created_at": now_iso(),
        "updated_at": now_iso(),
    })
    return jsonify(to_dict(ref.get())), 201


def _with_party_names(ledger: dict) -> dict:
    vendor_id = ledger.get("vendor_id")
    if vendor_id and not ledger.get("vendor_name"):
        vendor = doc(USERS, vendor_id).get()
        if vendor.exists:
            data = vendor.to_dict() or {}
            ledger["vendor_name"] = (
                data.get("shop_name")
                or data.get("full_name")
                or data.get("username")
                or "Shop"
            )
    return ledger


@khata_bp.get("/khata/ledgers/<ledger_id>/transactions")
@require_auth
def list_ledger_transactions(ledger_id):
    ledger_snap = doc(KHATA_LEDGERS, ledger_id).get()
    if not ledger_snap.exists:
        return jsonify({"detail": "Ledger not found"}), 404
    data = ledger_snap.to_dict() or {}
    if g.user_id not in {data.get("vendor_id"), data.get("customer_id")}:
        return jsonify({"detail": "Not your ledger"}), 403

    query = col(KHATA_TRANSACTIONS).where(
        filter=FieldFilter("ledger_id", "==", ledger_id)
    )
    items = [to_dict(d) for d in query.stream()]
    items.sort(key=lambda t: t.get("created_at") or "")
    return jsonify(items)


@khata_bp.post("/khata/transactions")
@require_auth
def record_transaction():
    payload = request.get_json(silent=True) or {}
    ledger_id = payload.get("ledger_id")
    txn_type = payload.get("type")
    try:
        amount = float(payload.get("amount"))
    except (TypeError, ValueError):
        return jsonify({"detail": "amount is required"}), 422
    description = payload.get("description") or ""

    if not ledger_id or txn_type not in {"credit", "debit", "settlement"}:
        return jsonify({"detail": "ledger_id and valid type required"}), 422

    ledger_ref = doc(KHATA_LEDGERS, ledger_id)
    ledger_snap = ledger_ref.get()
    if not ledger_snap.exists:
        return jsonify({"detail": "Ledger not found"}), 404
    ledger = ledger_snap.to_dict() or {}
    if g.user_id not in {ledger.get("vendor_id"), ledger.get("customer_id")}:
        return jsonify({"detail": "Not your ledger"}), 403

    txn_ref = col(KHATA_TRANSACTIONS).document()
    txn_ref.set({
        "ledger_id": ledger_id,
        "vendor_id": ledger.get("vendor_id"),
        "customer_id": ledger.get("customer_id"),
        "type": txn_type,
        "amount": amount,
        "description": description,
        "payment_method": payload.get("payment_method"),
        "created_at": now_iso(),
    })
    _recompute_balance(ledger_id, ledger_ref)
    return jsonify(to_dict(txn_ref.get())), 201


@khata_bp.post("/khata/ledgers/<ledger_id>/settle")
@require_auth
def settle_ledger(ledger_id):
    ledger_ref = doc(KHATA_LEDGERS, ledger_id)
    ledger_snap = ledger_ref.get()
    if not ledger_snap.exists:
        return jsonify({"detail": "Ledger not found"}), 404
    ledger = ledger_snap.to_dict() or {}
    if g.user_id not in {ledger.get("vendor_id"), ledger.get("customer_id")}:
        return jsonify({"detail": "Not your ledger"}), 403

    balance = float(ledger.get("balance") or 0)
    if balance > 0:
        col(KHATA_TRANSACTIONS).document().set({
            "ledger_id": ledger_id,
            "vendor_id": ledger.get("vendor_id"),
            "customer_id": ledger.get("customer_id"),
            "type": "settlement",
            "amount": balance,
            "description": "Ledger settled",
            "payment_method": None,
            "created_at": now_iso(),
        })
    ledger_ref.set({
        "balance": 0.0,
        "status": "settled",
        "updated_at": now_iso(),
    }, merge=True)
    return jsonify({"ok": True})
