"""`/wallet/*` endpoints consumed by `WalletRemoteDataSource` and LocalShop UI.

Wallet credits for customers require a two-step recharge intent:
  1. POST /wallet/recharge/initiate  → one-time payment_id
  2. POST /wallet/recharge/confirm   → credits after client payment UI

Direct POST /wallet/credit is restricted to admin (or a valid unused payment_id).
"""

from datetime import datetime, timedelta, timezone

from flask import Blueprint, g, jsonify, request
from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from auth_utils import require_auth
from db import WALLETS, WALLET_TRANSACTIONS, col, db, doc, now_iso, to_dict


wallet_bp = Blueprint("wallet_v2", __name__)

# Pending recharge intents live under wallets/{uid}/recharge_intents/{id}
# (subcollection) so we don't need a new top-level collection constant.
RECHARGE_TTL_MINUTES = 15
MAX_RECHARGE_AMOUNT = 100_000.0


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


def _intent_col(user_id: str):
    return doc(WALLETS, user_id).collection("recharge_intents")


def _parse_iso(value: str | None):
    if not value:
        return None
    try:
        # Accept both Z and +00:00
        cleaned = value.replace("Z", "+00:00")
        return datetime.fromisoformat(cleaned)
    except (TypeError, ValueError):
        return None


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
    """Create a one-time recharge intent. Client must confirm after payment UI."""
    payload = request.get_json(silent=True) or {}
    try:
        amount = float(payload.get("amount"))
    except (TypeError, ValueError):
        return jsonify({"detail": "amount must be numeric"}), 422
    if amount <= 0:
        return jsonify({"detail": "amount must be positive"}), 422
    if amount > MAX_RECHARGE_AMOUNT:
        return jsonify({"detail": f"amount exceeds max ₹{MAX_RECHARGE_AMOUNT:,.0f}"}), 422

    _get_or_create_wallet()
    created = now_iso()
    expires_at = (
        datetime.now(timezone.utc) + timedelta(minutes=RECHARGE_TTL_MINUTES)
    ).isoformat()
    ref = _intent_col(g.user_id).document()
    ref.set({
        "user_id": g.user_id,
        "amount": amount,
        "status": "pending",
        "description": payload.get("description") or "Wallet recharge",
        "created_at": created,
        "expires_at": expires_at,
        "completed_at": None,
    })
    return jsonify({
        "payment_id": ref.id,
        "amount": amount,
        "status": "pending",
        "expires_at": expires_at,
    }), 201


@wallet_bp.post("/wallet/recharge/confirm")
@require_auth
def confirm_recharge():
    """Complete a pending recharge intent (one-time). Simulates verified payment."""
    payload = request.get_json(silent=True) or {}
    payment_id = (payload.get("payment_id") or "").strip()
    if not payment_id:
        return jsonify({"detail": "payment_id is required"}), 422

    intent_ref = _intent_col(g.user_id).document(payment_id)
    snap = intent_ref.get()
    if not snap.exists:
        return jsonify({"detail": "Payment intent not found"}), 404
    intent = snap.to_dict() or {}
    if intent.get("user_id") != g.user_id:
        return jsonify({"detail": "Not your payment intent"}), 403
    if intent.get("status") != "pending":
        return jsonify({"detail": f"Intent already {intent.get('status')}"}), 409

    expires = _parse_iso(intent.get("expires_at"))
    if expires is not None:
        now = datetime.now(timezone.utc)
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if now > expires:
            intent_ref.set({"status": "expired"}, merge=True)
            return jsonify({"detail": "Payment intent expired"}), 410

    amount = float(intent.get("amount") or 0)
    if amount <= 0:
        return jsonify({"detail": "Invalid intent amount"}), 422

    # Mark completed first to prevent double-credit races (best-effort).
    # Use a conditional update via transaction when possible.
    @firestore.transactional
    def _claim(transaction):
        s = intent_ref.get(transaction=transaction)
        if not s.exists:
            raise ValueError("not_found")
        data = s.to_dict() or {}
        if data.get("status") != "pending":
            raise ValueError("already_used")
        transaction.set(
            intent_ref,
            {"status": "processing", "claimed_at": now_iso()},
            merge=True,
        )
        return float(data.get("amount") or 0), data.get("description") or "Wallet recharge"

    try:
        txn = db().transaction()
        amount, description = _claim(txn)
    except ValueError as exc:
        code = str(exc)
        if code == "not_found":
            return jsonify({"detail": "Payment intent not found"}), 404
        return jsonify({"detail": "Payment intent already used"}), 409
    except Exception as exc:
        return jsonify({"detail": f"Failed to claim intent: {exc}"}), 500

    wallet, txn_id, err = _apply_mutation("credit", amount, description, None)
    if err:
        intent_ref.set({"status": "pending", "claim_error": True}, merge=True)
        return err

    intent_ref.set({
        "status": "completed",
        "completed_at": now_iso(),
        "transaction_id": txn_id,
    }, merge=True)

    return jsonify({
        "ok": True,
        "payment_id": payment_id,
        "transaction_id": txn_id,
        "wallet": {**wallet, "uid": g.user_id},
    }), 201


@wallet_bp.post("/wallet/credit")
@require_auth
def credit():
    """Admin free-credit, OR customer credit via a valid pending payment_id.

    Open free credit for arbitrary customers is intentionally blocked.
    """
    payload = request.get_json(silent=True) or {}
    payment_id = (payload.get("payment_id") or "").strip()
    role = getattr(g, "user_role", None) or ""

    # Path A: customer confirms via payment_id (same as /recharge/confirm)
    if payment_id:
        # Reuse confirm logic by rewriting request is awkward; call same body flow.
        # Inline: claim intent + credit.
        intent_ref = _intent_col(g.user_id).document(payment_id)
        snap = intent_ref.get()
        if not snap.exists:
            return jsonify({"detail": "Payment intent not found"}), 404
        intent = snap.to_dict() or {}
        if intent.get("status") != "pending":
            return jsonify({"detail": "Payment intent already used"}), 409
        expires = _parse_iso(intent.get("expires_at"))
        if expires is not None:
            now = datetime.now(timezone.utc)
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            if now > expires:
                intent_ref.set({"status": "expired"}, merge=True)
                return jsonify({"detail": "Payment intent expired"}), 410
        amount = float(intent.get("amount") or 0)
        if amount <= 0:
            return jsonify({"detail": "Invalid intent amount"}), 422
        intent_ref.set({"status": "processing"}, merge=True)
        wallet, txn_id, err = _apply_mutation(
            "credit", amount, intent.get("description") or "Wallet recharge", None
        )
        if err:
            intent_ref.set({"status": "pending"}, merge=True)
            return err
        intent_ref.set({
            "status": "completed",
            "completed_at": now_iso(),
            "transaction_id": txn_id,
        }, merge=True)
        return jsonify({
            "ok": True,
            "transaction_id": txn_id,
            "wallet": {**wallet, "uid": g.user_id},
        }), 201

    # Path B: admin free credit only
    if role not in {"admin", "super_admin"}:
        return jsonify({
            "detail": "Direct wallet credit is disabled. "
            "Use /wallet/recharge/initiate then /wallet/recharge/confirm."
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
