"""`/service-wallet` endpoints and idempotent financial processors for LocalShop V2."""

from flask import Blueprint, g, jsonify, request
from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from auth_utils import require_auth
from db import db, col, doc, now_iso, to_dict
from razorpay_config import get_razorpay_client

service_wallet_bp = Blueprint("service_wallet", __name__)

COLL_BOOKINGS = "service_bookings"


def _refund_paise(value):
    from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or not 0 < amount <= 10_000_000:
            raise ValueError("Invalid refund amount")
        paise = int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        if paise <= 0:
            raise ValueError("Invalid refund amount")
        return paise
    except InvalidOperation:
        raise ValueError("Invalid refund amount")


def process_refund(booking_id: str):
    """Refund only cancelled/rejected paid bookings, with durable retry identity.

    X-Refund-Idempotency is reused after ambiguous network failures. A five-minute
    lease prevents simultaneous workers; no external call occurs in a Firestore
    transaction. Historical wallet refunds retain an atomic, once-only credit.
    Razorpay 'pending' refunds remain submitted until the provider confirms them.
    """
    import hashlib
    import uuid
    from datetime import datetime, timedelta, timezone
    from routes.razorpay_api import captured_payment_matches

    b_ref = doc(COLL_BOOKINGS, booking_id)
    lease_token = uuid.uuid4().hex

    @firestore.transactional
    def acquire(transaction):
        snapshot = b_ref.get(transaction=transaction)
        if not snapshot.exists:
            return {"skip": True, "status": "missing"}
        booking = snapshot.to_dict() or {}
        status = booking.get("refund_status")
        if status == "completed":
            return {"skip": True, "status": "completed"}
        if booking.get("status") not in ("cancelled", "rejected") or booking.get("payment_status") != "paid":
            return {"skip": True, "status": "ineligible"}
        refund_request = booking.get("refund_request")
        if status in ("processing", "submitted") and not refund_request:
            transaction.update(b_ref, {
                "refund_status": "requires_review", "refund_error": "Legacy refund must be reconciled before retry",
            })
            return {"skip": True, "status": "requires_review"}
        if status == "requires_review":
            return {"skip": True, "status": "requires_review"}
        if status == "processing":
            try:
                started = datetime.fromisoformat(booking.get("refund_started_at", ""))
                if started > datetime.now(timezone.utc) - timedelta(minutes=5):
                    return {"skip": True, "status": "processing"}
            except (ValueError, TypeError):
                return {"skip": True, "status": "requires_review"}
        if not refund_request:
            try:
                amount_paise = _refund_paise(booking.get("final_total") or booking.get("amount_paid"))
            except ValueError:
                transaction.update(b_ref, {"refund_status": "requires_review", "refund_error": "Invalid refund amount"})
                return {"skip": True, "status": "requires_review"}
            method = booking.get("payment_method", "wallet")
            customer_id = booking.get("requester_id")
            payment_id = booking.get("razorpay_payment_id")
            if (method not in ("wallet", "razorpay") or not isinstance(customer_id, str)
                or not customer_id or "/" in customer_id or (method == "razorpay" and not payment_id)):
                transaction.update(b_ref, {"refund_status": "requires_review", "refund_error": "Invalid original payment metadata"})
                return {"skip": True, "status": "requires_review"}
            refund_request = {
                "amount_paise": amount_paise, "payment_method": method, "customer_id": customer_id,
                "payment_id": payment_id,
                "idempotency_key": "booking-refund-" + hashlib.sha256(booking_id.encode()).hexdigest()[:40],
            }
        if refund_request.get("payment_method") == "razorpay":
            intent_id = refund_request.get("payment_intent_id") or booking.get("payment_intent_id")
            if not isinstance(intent_id, str) or not intent_id or "/" in intent_id:
                transaction.update(b_ref, {"refund_status": "requires_review", "refund_error": "Original payment intent is required"})
                return {"skip": True, "status": "requires_review"}
            intent_snapshot = doc("payment_orders", intent_id).get(transaction=transaction)
            intent = intent_snapshot.to_dict() or {} if intent_snapshot.exists else {}
            if (not intent_snapshot.exists or intent.get("status") != "paid" or intent.get("purpose") != "service"
                or intent.get("user_id") != refund_request.get("customer_id") or intent.get("reference_id") != booking_id
                or intent.get("payment_id") != refund_request.get("payment_id") or intent.get("currency") != "INR"
                or type(intent.get("amount_paise")) is not int or intent.get("amount_paise") != refund_request.get("amount_paise")
                or not isinstance(intent.get("razorpay_order_id"), str) or not intent["razorpay_order_id"]):
                transaction.update(b_ref, {"refund_status": "requires_review", "refund_error": "Original capture does not match booking refund"})
                return {"skip": True, "status": "requires_review"}
            refund_request.update({"payment_intent_id": intent_id, "razorpay_order_id": intent["razorpay_order_id"], "currency": "INR"})
        transaction.update(b_ref, {
            "refund_status": "processing", "refund_request": refund_request,
            "refund_started_at": now_iso(), "refund_lease_token": lease_token, "updated_at": now_iso(),
        })
        return {"request": refund_request, "refund_id": booking.get("refund_id")}

    acquired = acquire(db().transaction())
    if acquired.get("skip"):
        return {"status": acquired["status"]}
    original = acquired["request"]
    method = original["payment_method"]
    refund_id = acquired.get("refund_id")
    provider_status = "processed"
    if method == "razorpay":
        try:
            client = get_razorpay_client()
            if refund_id:
                refund = client.refund.fetch(refund_id, timeout=30)
            else:
                payment = client.payment.fetch(original["payment_id"], timeout=30)
                expected = {"razorpay_order_id": original["razorpay_order_id"], "amount_paise": original["amount_paise"], "currency": "INR"}
                if not captured_payment_matches(expected, payment) or payment.get("id") != original["payment_id"]:
                    raise ValueError("Captured payment does not match original refund intent")
                refund = client.payment.refund(original["payment_id"], {
                    "amount": original["amount_paise"], "speed": "normal",
                    "notes": {"booking_id": booking_id, "reason": "cancelled_booking"},
                }, headers={"X-Refund-Idempotency": original["idempotency_key"]}, timeout=30)
            refund_id = refund.get("id")
            provider_status = refund.get("status")
            if (not isinstance(refund_id, str) or not refund_id.startswith("rfnd_") or refund.get("payment_id") != original["payment_id"]
                or type(refund.get("amount")) is not int or refund.get("amount") != original["amount_paise"]
                or refund.get("currency") != "INR" or provider_status not in ("pending", "processed", "failed")):
                raise ValueError("Refund response does not match the original payment")
        except Exception as error:
            # Response loss may mean Razorpay accepted the refund. Retrying uses
            # the exact same durable key/body and cannot issue a second refund.
            @firestore.transactional
            def record_failure(transaction):
                snapshot = b_ref.get(transaction=transaction)
                current = snapshot.to_dict() or {} if snapshot.exists else {}
                if (current.get("refund_status") == "processing" and current.get("refund_request") == original
                    and current.get("refund_lease_token") == lease_token):
                    failure_status = "requires_review" if isinstance(error, ValueError) else "failed"
                    transaction.update(b_ref, {
                        "refund_status": failure_status,
                        "refund_error": "Refund could not be confirmed; retry with the same refund request",
                    })
                    return {"status": failure_status}
                return {"status": current.get("refund_status", "requires_review"), "refund_id": current.get("refund_id")}
            return record_failure(db().transaction())

    @firestore.transactional
    def finalize(transaction):
        snapshot = b_ref.get(transaction=transaction)
        current = snapshot.to_dict() or {} if snapshot.exists else {}
        if current.get("refund_status") == "completed":
            return {"status": "completed", "refund_id": current.get("refund_id")}
        if current.get("refund_request") != original or current.get("refund_lease_token") != lease_token:
            return {"status": current.get("refund_status", "requires_review"), "refund_id": current.get("refund_id")}
        marker_ref = wallet_ref = None
        wallet = {}
        marker_exists = False
        if method == "wallet":
            marker_ref = doc("wallet_transactions", f"refund_{booking_id}")
            marker_exists = marker_ref.get(transaction=transaction).exists
            wallet_ref = doc("wallets", original["customer_id"])
            wallet_snapshot = wallet_ref.get(transaction=transaction)
            wallet = wallet_snapshot.to_dict() or {} if wallet_snapshot.exists else {}
        # All reads precede every write, including the idempotency marker.
        timestamp = now_iso()
        if method == "wallet" and not marker_exists:
            amount = original["amount_paise"] / 100
            transaction.set(wallet_ref, {
                "balance": round(float(wallet.get("balance") or 0) + amount, 2),
                "total_credit": round(float(wallet.get("total_credit") or 0) + amount, 2),
                "last_updated": timestamp,
            }, merge=True)
            transaction.set(marker_ref, {
                "wallet_id": original["customer_id"], "user_id": original["customer_id"],
                "type": "refund", "amount": amount,
                "description": f"Refund for cancelled service booking {booking_id}",
                "order_id": booking_id, "created_at": timestamp,
            })
        status = {"processed": "completed", "pending": "submitted", "failed": "requires_review"}[provider_status]
        updates = {
            "refund_status": status, "refund_id": refund_id,
            "refund_error": None if status != "requires_review" else "Provider reports refund failed",
            "updated_at": timestamp,
        }
        if status == "completed":
            updates.update({"payment_status": "refunded", "refunded_at": timestamp})
        transaction.update(b_ref, updates)
        return {"status": status, "refund_id": refund_id}

    return finalize(db().transaction())


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
