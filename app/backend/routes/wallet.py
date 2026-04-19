"""`/wallet/*` endpoints consumed by `WalletRemoteDataSource`."""

from flask import Blueprint, g, jsonify, request
from google.cloud.firestore_v1.base_query import FieldFilter

from auth_utils import require_auth
from db import WALLETS, WALLET_TRANSACTIONS, col, doc, now_iso, to_dict


wallet_bp = Blueprint("wallet_v2", __name__)


def _get_or_create_wallet():
    ref = doc(WALLETS, g.user_id)
    snap = ref.get()
    if not snap.exists:
        ref.set({
            "user_id": g.user_id,
            "balance": 0.0,
            "total_credit": 0.0,
            "total_debit": 0.0,
            "last_updated": now_iso(),
        })
        snap = ref.get()
    return ref, snap


@wallet_bp.get("/wallet")
@require_auth
def get_wallet():
    _, snap = _get_or_create_wallet()
    return jsonify(to_dict(snap))


@wallet_bp.get("/wallet/transactions")
@require_auth
def list_transactions():
    try:
        limit = int(request.args.get("limit") or 20)
    except ValueError:
        limit = 20
    query = col(WALLET_TRANSACTIONS).where(
        filter=FieldFilter("wallet_id", "==", g.user_id)
    )
    items = [to_dict(d) for d in query.stream()]
    items.sort(key=lambda t: t.get("created_at") or "", reverse=True)
    return jsonify(items[:limit])


def _apply_mutation(kind: str, amount: float, description: str, order_id: str | None) -> tuple:
    if amount <= 0:
        return None, (jsonify({"detail": "amount must be positive"}), 422)

    ref, snap = _get_or_create_wallet()
    current = snap.to_dict() or {}
    balance = float(current.get("balance") or 0)
    total_credit = float(current.get("total_credit") or 0)
    total_debit = float(current.get("total_debit") or 0)

    if kind == "credit":
        balance += amount
        total_credit += amount
    else:
        if balance < amount:
            return None, (jsonify({"detail": "Insufficient balance"}), 422)
        balance -= amount
        total_debit += amount

    ref.set({
        "balance": balance,
        "total_credit": total_credit,
        "total_debit": total_debit,
        "last_updated": now_iso(),
    }, merge=True)

    txn_ref = col(WALLET_TRANSACTIONS).document()
    txn_ref.set({
        "wallet_id": g.user_id,
        "user_id": g.user_id,
        "type": kind,
        "amount": amount,
        "description": description or "",
        "order_id": order_id,
        "created_at": now_iso(),
    })
    return txn_ref.id, None


@wallet_bp.post("/wallet/credit")
@require_auth
def credit():
    payload = request.get_json(silent=True) or {}
    try:
        amount = float(payload.get("amount"))
    except (TypeError, ValueError):
        return jsonify({"detail": "amount must be numeric"}), 422
    txn_id, err = _apply_mutation("credit", amount, payload.get("description") or "", None)
    if err:
        return err
    return jsonify({"ok": True, "transaction_id": txn_id}), 201


@wallet_bp.post("/wallet/deduct")
@require_auth
def deduct():
    payload = request.get_json(silent=True) or {}
    try:
        amount = float(payload.get("amount"))
    except (TypeError, ValueError):
        return jsonify({"detail": "amount must be numeric"}), 422
    txn_id, err = _apply_mutation(
        "debit", amount, payload.get("description") or "", payload.get("order_id")
    )
    if err:
        return err
    return jsonify({"ok": True, "transaction_id": txn_id}), 201
