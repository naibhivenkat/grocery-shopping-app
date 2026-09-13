"""Authenticated wallet reads and internal wallet mutations.

Customer wallet recharge is owned by the Firebase Razorpay Function. The
deprecated Flask recharge aliases remain as explicit 410 responses so an old
client cannot turn a locally-created intent into free wallet credit.
"""

from flask import Blueprint, g, jsonify, request
from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from auth_utils import require_auth
from db import WALLETS, WALLET_TRANSACTIONS, col, db, doc, now_iso, to_dict


wallet_bp = Blueprint("wallet_v2", __name__)

def _empty_wallet_fields():
    return {
        "user_id": g.user_id,
        "balance": 0.0,
        "total_credit": 0.0,
        "total_debit": 0.0,
        "last_updated": now_iso(),
    }


def _get_or_create_wallet():
    ref = doc(WALLETS, g.user_id)
    snap = ref.get()
    if not snap.exists:
        ref.set(_empty_wallet_fields())
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
    limit = max(1, min(limit, 100))

    # Ensure wallet exists so first-time users get a consistent empty history.
    _get_or_create_wallet()

    query = col(WALLET_TRANSACTIONS).where(
        filter=FieldFilter("wallet_id", "==", g.user_id)
    )
    items = [to_dict(d) for d in query.stream()]
    items.sort(key=lambda t: t.get("created_at") or "", reverse=True)
    return jsonify(items[:limit])


def _apply_mutation(kind: str, amount: float, description: str, order_id: str | None):
    """Atomically update wallet balance and write a transaction ledger entry."""
    if amount <= 0:
        return None, None, (jsonify({"detail": "amount must be positive"}), 422)

    wallet_ref = doc(WALLETS, g.user_id)
    txn_ref = col(WALLET_TRANSACTIONS).document()
    created_at = now_iso()

    @firestore.transactional
    def _run(transaction):
        snap = wallet_ref.get(transaction=transaction)
        current = snap.to_dict() if snap.exists else None
        if not current:
            current = {
                "user_id": g.user_id,
                "balance": 0.0,
                "total_credit": 0.0,
                "total_debit": 0.0,
            }

        balance = float(current.get("balance") or 0)
        total_credit = float(current.get("total_credit") or 0)
        total_debit = float(current.get("total_debit") or 0)

        if kind == "credit":
            balance += amount
            total_credit += amount
        else:
            if balance < amount:
                raise ValueError("Insufficient balance")
            balance -= amount
            total_debit += amount

        wallet_payload = {
            "user_id": g.user_id,
            "balance": balance,
            "total_credit": total_credit,
            "total_debit": total_debit,
            "last_updated": created_at,
        }
        transaction.set(wallet_ref, wallet_payload, merge=True)

        txn_payload = {
            "wallet_id": g.user_id,
            "user_id": g.user_id,
            "type": kind,
            "amount": amount,
            "description": description or "",
            "order_id": order_id,
            "created_at": created_at,
        }
        transaction.set(txn_ref, txn_payload)

        return wallet_payload, txn_ref.id

    try:
        transaction = db().transaction()
        wallet_payload, txn_id = _run(transaction)
        return wallet_payload, txn_id, None
    except ValueError as exc:
        if str(exc) == "Insufficient balance":
            return None, None, (jsonify({"detail": "Insufficient balance"}), 422)
        return None, None, (jsonify({"detail": str(exc)}), 422)
    except Exception as exc:  # pragma: no cover - surfaced to client for debugging
        return None, None, (
            jsonify({"detail": f"Wallet mutation failed: {exc}"}),
            500,
        )


@wallet_bp.post("/wallet/recharge/initiate")
@require_auth
def initiate_recharge():
    return jsonify({
        "detail": "Wallet recharge moved to the Razorpay payment function"
    }), 410


@wallet_bp.post("/wallet/recharge/confirm")
@require_auth
def confirm_recharge():
    return jsonify({
        "detail": "Wallet recharge moved to the Razorpay payment function"
    }), 410


@wallet_bp.post("/wallet/credit")
@require_auth
def credit():
    """Admin-only operational credit; customer funds settle through Razorpay."""
    payload = request.get_json(silent=True) or {}
    role = getattr(g, "user_role", None) or ""

    # Admin free credit only; customer funds arrive through Razorpay settlement.
    if role not in {"admin", "super_admin"}:
        return jsonify({
            "detail": "Direct wallet credit is disabled"
        }), 403

    try:
        amount = float(payload.get("amount"))
    except (TypeError, ValueError):
        return jsonify({"detail": "amount must be numeric"}), 422
    wallet, txn_id, err = _apply_mutation(
        "credit", amount, payload.get("description") or "Admin credit", None
    )
    if err:
        return err
    return jsonify({
        "ok": True,
        "transaction_id": txn_id,
        "wallet": {**wallet, "uid": g.user_id},
    }), 201


@wallet_bp.post("/wallet/deduct")
@require_auth
def deduct():
    payload = request.get_json(silent=True) or {}
    try:
        amount = float(payload.get("amount"))
    except (TypeError, ValueError):
        return jsonify({"detail": "amount must be numeric"}), 422
    wallet, txn_id, err = _apply_mutation(
        "debit",
        amount,
        payload.get("description") or "",
        payload.get("order_id"),
    )
    if err:
        return err
    return jsonify({
        "ok": True,
        "transaction_id": txn_id,
        "wallet": {**wallet, "uid": g.user_id},
    }), 201
