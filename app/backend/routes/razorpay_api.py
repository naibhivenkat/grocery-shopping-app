"""Server-side Razorpay order and settlement API for the installed app."""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import uuid

from flask import Blueprint, g, jsonify, request
from google.cloud import firestore

from auth_utils import require_auth
from db import WALLET_TRANSACTIONS, WALLETS, col, db, doc, now_iso
from razorpay_config import get_razorpay_client, get_razorpay_key_id


razorpay_api_bp = Blueprint("razorpay_api", __name__)
PAYMENT_ORDERS = "payment_orders"
ALLOWED_PURPOSES = {"order", "wallet", "subscription", "service"}


def _amount_paise(value):
    try:
        amount = Decimal(str(value))
        paise = (amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not amount.is_finite() or paise <= 0 or paise > 10_000_000_00:
        return None
    return int(paise)


def settle_payment_order(intent_id, payment_id, event_id=None):
    """Settle exactly once, crediting wallet recharge within the same transaction."""
    intent_ref = doc(PAYMENT_ORDERS, intent_id)
    wallet_tx_ref = doc(WALLET_TRANSACTIONS, f"razorpay_{intent_id}")

    @firestore.transactional
    def _settle(transaction):
        intent_snap = intent_ref.get(transaction=transaction)
        if not intent_snap.exists:
            return {"status": "missing"}
        intent = intent_snap.to_dict() or {}
        if intent.get("status") == "paid":
            return {"status": "already_paid"}
        if intent.get("status") == "failed":
            return {"status": "failed"}

        if intent.get("purpose") == "wallet":
            wallet = doc(WALLETS, intent["user_id"])
            wallet_snap = wallet.get(transaction=transaction)
            current = wallet_snap.to_dict() or {}
            wallet_tx = wallet_tx_ref.get(transaction=transaction)
            if wallet_tx.exists:
                return {"status": "already_paid"}
            amount = float(intent.get("amount") or 0)
            transaction.set(wallet, {
                "user_id": intent["user_id"],
                "balance": float(current.get("balance") or 0) + amount,
                "total_credit": float(current.get("total_credit") or 0) + amount,
                "last_updated": now_iso(),
            }, merge=True)
            transaction.create(wallet_tx_ref, {
                "wallet_id": intent["user_id"],
                "user_id": intent["user_id"],
                "type": "credit",
                "amount": amount,
                "description": "Razorpay wallet recharge",
                "payment_intent_id": intent_id,
                "payment_id": payment_id,
                "created_at": now_iso(),
            })

        transaction.update(intent_ref, {
            "status": "paid",
            "payment_id": payment_id,
            "settled_at": now_iso(),
            **({"last_webhook_event_id": event_id} if event_id else {}),
        })
        return {"status": "paid", "purpose": intent.get("purpose")}

    return _settle(db().transaction())


def fail_payment_order(intent_id, payment_id=None, event_id=None, reason=None):
    ref = doc(PAYMENT_ORDERS, intent_id)

    @firestore.transactional
    def _fail(transaction):
        snap = ref.get(transaction=transaction)
        if not snap.exists:
            return {"status": "missing"}
        data = snap.to_dict() or {}
        if data.get("status") in ("paid", "failed"):
            return {"status": data["status"]}
        transaction.update(ref, {
            "status": "failed",
            "payment_id": payment_id,
            "failure_reason": reason or "Payment failed",
            "failed_at": now_iso(),
            **({"last_webhook_event_id": event_id} if event_id else {}),
        })
        return {"status": "failed"}

    return _fail(db().transaction())


@razorpay_api_bp.post("/razorpayApi/orders")
@require_auth
def create_razorpay_order():
    payload = request.get_json(silent=True) or {}
    amount_paise = _amount_paise(payload.get("amount"))
    purpose = str(payload.get("purpose") or "order")
    reference_id = str(payload.get("reference_id") or "").strip()
    if amount_paise is None or purpose not in ALLOWED_PURPOSES:
        return jsonify({"detail": "Valid amount and purpose are required"}), 422
    if len(reference_id) > 128:
        return jsonify({"detail": "reference_id is too long"}), 422
    try:
        client = get_razorpay_client()
        order = client.order.create({
            "amount": amount_paise,
            "currency": "INR",
            "receipt": f"ls_{g.user_id[:12]}_{uuid.uuid4().hex[:12]}",
            "notes": {
                "user_id": g.user_id,
                "purpose": purpose,
                "reference_id": reference_id,
            },
        })
        intent_ref = col(PAYMENT_ORDERS).document()
        intent_ref.set({
            "user_id": g.user_id,
            "amount": amount_paise / 100,
            "amount_paise": amount_paise,
            "currency": "INR",
            "purpose": purpose,
            "reference_id": reference_id or None,
            "razorpay_order_id": order["id"],
            "status": "created",
            "created_at": now_iso(),
        })
        return jsonify({
            "backend_order_id": intent_ref.id,
            "razorpay_order_id": order["id"],
            "key_id": get_razorpay_key_id(),
            "amount": amount_paise,
            "currency": "INR",
        }), 201
    except Exception as exc:
        print(f"Razorpay order creation failed: {type(exc).__name__}")
        return jsonify({"detail": "Payment service temporarily unavailable"}), 503


@razorpay_api_bp.post("/razorpayApi/verify")
@require_auth
def verify_razorpay_payment():
    payload = request.get_json(silent=True) or {}
    intent_id = str(payload.get("backend_order_id") or "")
    order_id = str(payload.get("order_id") or "")
    payment_id = str(payload.get("payment_id") or "")
    signature = str(payload.get("signature") or "")
    if not all((intent_id, order_id, payment_id, signature)):
        return jsonify({"detail": "Payment verification fields are required"}), 422

    intent_snap = doc(PAYMENT_ORDERS, intent_id).get()
    intent = intent_snap.to_dict() or {} if intent_snap.exists else {}
    if not intent_snap.exists or intent.get("user_id") != g.user_id:
        return jsonify({"detail": "Payment intent not found"}), 404
    if intent.get("razorpay_order_id") != order_id:
        return jsonify({"detail": "Razorpay order mismatch"}), 422
    try:
        get_razorpay_client().utility.verify_payment_signature({
            "razorpay_order_id": order_id,
            "razorpay_payment_id": payment_id,
            "razorpay_signature": signature,
        })
    except Exception:
        return jsonify({"detail": "Invalid Razorpay payment signature"}), 400

    result = settle_payment_order(intent_id, payment_id)
    if result["status"] not in ("paid", "already_paid"):
        return jsonify({"detail": "Payment could not be settled"}), 409
    return jsonify({"success": True, **result, "backend_order_id": intent_id})
