"""`/service-wallet` endpoints and idempotent financial processors for LocalShop V2."""

import os
from flask import Blueprint, g, jsonify, request
from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from auth_utils import require_auth
from db import db, col, doc, now_iso, to_dict

service_wallet_bp = Blueprint("service_wallet", __name__)

COLL_BOOKINGS = "service_bookings"


def process_refund(booking_id: str):
    """
    Idempotent refund handler executing asynchronously from the booking state machine.
    Safely orchestrates external API calls and subsequent internal Firestore ledger balancing.
    """

    # 1. Start transaction to verify refund eligibility and lock processing state
    @firestore.transactional
    def check_and_lock(txn):
        b_ref = doc(COLL_BOOKINGS, booking_id)
        b_snap = b_ref.get(transaction=txn)
        if not b_snap.exists:
            return None
        b_data = b_snap.to_dict() or {}

        if b_data.get("payment_status") != "paid" or b_data.get("refund_status") in ["completed", "processing"]:
            return None

        txn.update(b_ref, {"refund_status": "processing", "updated_at": now_iso()})
        return b_data

    booking = check_and_lock(db().transaction())
    if not booking:
        return

    payment_method = booking.get("payment_method", "wallet")
    customer_id = booking.get("requester_id")
    customer_refund_amount = float(booking.get("final_total") or booking.get("amount_paid") or 0)

    refund_id = None
    # 2. External API Processing (Non-transactional to prevent duplicate HTTP calls on retry)
    if payment_method == "razorpay":
        payment_id = booking.get("razorpay_payment_id")
        if payment_id:
            try:
                import razorpay
                # Maintained identical hardcoded dev keys from legacy service_firebase_db.py to avoid breaking test environments
                client = razorpay.Client(auth=("rzp_test_RKK3DuGSaxK9fR", "VgVc96Pdn3t5T8ieX0nb2ajt"))
                refund = client.payment.refund(payment_id, {
                    "amount": int(customer_refund_amount * 100),
                    "notes": {"booking_id": booking_id, "reason": "cancelled_booking"}
                })
                refund_id = refund.get("id")
            except Exception as e:
                doc(COLL_BOOKINGS, booking_id).set({"refund_status": "failed", "refund_error": str(e)}, merge=True)
                return

    # 3. Final Internal Settlement
    @firestore.transactional
    def finalize_refund(txn):
        # NOTE: In V2, we strictly DO NOT debit the provider wallet on refund/cancellation
        # because the provider is only credited AFTER 'completed'. Since cancellation
        # happens prior to completion, the provider has not received funds yet.
        # This fixes a major legacy logic flaw.

        # Credit Customer Shopping Wallet (if they paid using Shopping Wallet)
        if payment_method == "wallet" and customer_refund_amount > 0:
            c_wallet_ref = doc("wallets", customer_id)
            c_snap = c_wallet_ref.get(transaction=txn)
            c_bal = float((c_snap.to_dict() or {}).get("balance", 0)) if c_snap.exists else 0.0
            txn.set(c_wallet_ref, {"balance": c_bal + customer_refund_amount, "last_updated": now_iso()}, merge=True)

            # Idempotent Transaction Record
            c_tx_ref = doc("wallet_transactions", f"refund_{booking_id}")
            if not c_tx_ref.get(transaction=txn).exists:
                txn.set(c_tx_ref, {
                    "wallet_id": customer_id,
                    "user_id": customer_id,
                    "type": "refund",
                    "amount": customer_refund_amount,
                    "description": f"Refund for cancelled service booking {booking_id}",
                    "order_id": booking_id,
                    "created_at": now_iso()
                })

        # Mark Booking Fully Refunded
        txn.update(doc(COLL_BOOKINGS, booking_id), {
            "refund_status": "completed",
            "refund_id": refund_id,
            "refunded_at": now_iso()
        })

    finalize_refund(db().transaction())


# =====================================================================
# SECURE V2 ENDPOINTS
# =====================================================================

@service_wallet_bp.get("/service-wallet")
@require_auth
def get_service_wallet():
    """Retrieve the authenticated provider's service wallet balance and lifetime earnings."""
    w_snap = doc("service_wallets", g.user_id).get()
    balance = float((w_snap.to_dict() or {}).get("balance", 0.0)) if w_snap.exists else 0.0

    e_snap = doc("provider_earnings", g.user_id).get()
    lifetime_total = float((e_snap.to_dict() or {}).get("lifetime_total", 0.0)) if e_snap.exists else 0.0

    return jsonify({
        "balance": balance,
        "lifetime_total": lifetime_total,
        "uid": g.user_id
    }), 200


@service_wallet_bp.get("/service-wallet/transactions")
@require_auth
def get_service_wallet_transactions():
    """Retrieve the authenticated provider's transaction ledger."""
    query = col("service_wallet_transactions").where(filter=FieldFilter("user_id", "==", g.user_id))
    results = [to_dict(d) for d in query.stream()]
    results.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return jsonify(results), 200


@service_wallet_bp.post("/service-wallet/withdraw")
@require_auth
def withdraw_funds():
    """Safely deducts funds from the provider's service wallet for payout."""
    payload = request.get_json(silent=True) or {}
    try:
        amount = float(payload.get("amount", 0))
    except (TypeError, ValueError):
        return jsonify({"detail": "Invalid amount"}), 400

    if amount <= 0:
        return jsonify({"detail": "Amount must be positive"}), 400

    @firestore.transactional
    def _withdraw_tx(txn):
        w_ref = doc("service_wallets", g.user_id)
        w_snap = w_ref.get(transaction=txn)
        balance = float((w_snap.to_dict() or {}).get("balance", 0.0)) if w_snap.exists else 0.0

        if balance < amount:
            raise ValueError("Insufficient balance")

        txn.set(w_ref, {"balance": balance - amount, "updated_at": now_iso()}, merge=True)

        tx_id = col("service_wallet_transactions").document().id
        txn.set(doc("service_wallet_transactions", tx_id), {
            "user_id": g.user_id,
            "type": "withdrawal",
            "amount": amount,
            "status": "pending",
            "created_at": now_iso()
        })
        return tx_id

    try:
        tx_id = _withdraw_tx(db().transaction())
        return jsonify({"success": True, "detail": "Withdrawal initiated", "transaction_id": tx_id}), 200
    except ValueError as e:
        return jsonify({"detail": str(e)}), 400