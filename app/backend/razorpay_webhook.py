"""Idempotent Razorpay webhook handling for legacy backend payment flows."""

from datetime import datetime, timezone
import os

from flask import Blueprint, jsonify, request

from db import db as get_db
from razorpay_config import verify_webhook_signature
from routes.razorpay_api import fail_payment_order, settle_payment_order


razorpay_webhook_bp = Blueprint("razorpay_webhook", __name__)


def _find_payment_order(razorpay_order_id):
    store = get_db()
    current_base = store.collection("localshop").document("v1")
    for collection in (
        "payment_orders",
        "service_payment_orders",
        "wallet_orders",
        "khata_pay_orders",
    ):
        matches = current_base.collection(collection).where(
            "razorpay_order_id", "==", razorpay_order_id
        ).limit(1).get()
        if matches:
            return collection, matches[0], current_base

    # Older service clients used root-level collections. Keep this migration
    # fallback lazy so a normal V2 Cloud Run boot never requires the legacy
    # credential loader or its old schema.
    if os.getenv("ENABLE_LEGACY_ROUTES", "0") == "1":
        from firebase_db import db as legacy_store

        for collection in (
            "payment_orders",
            "service_payment_orders",
            "wallet_orders",
            "khata_pay_orders",
        ):
            matches = legacy_store.collection(collection).where(
                "razorpay_order_id", "==", razorpay_order_id
            ).limit(1).get()
            if matches:
                return collection, matches[0], legacy_store
    return None, None, None


@razorpay_webhook_bp.route("/webhooks/razorpay", methods=["POST"])
def razorpay_webhook():
    signature = request.headers.get("X-Razorpay-Signature", "")
    if not verify_webhook_signature(request.get_data(), signature):
        return jsonify({"error": "Invalid webhook signature"}), 401

    payload = request.get_json(silent=True) or {}
    event = payload.get("event", "")
    payment = payload.get("payload", {}).get("payment", {}).get("entity", {})
    order_id = payment.get("order_id")
    if not order_id:
        order_id = payload.get("payload", {}).get("order", {}).get("entity", {}).get("id")
    if not order_id:
        return jsonify({"received": True}), 200

    collection, snapshot, store = _find_payment_order(order_id)
    if not snapshot:
        return jsonify({"received": True}), 200

    ref = snapshot.reference
    current = snapshot.to_dict() or {}
    if collection == "payment_orders":
        if event in ("payment.captured", "order.paid"):
            settle_payment_order(
                snapshot.id,
                payment.get("id"),
                request.headers.get("X-Razorpay-Event-Id"),
            )
        elif event == "payment.failed":
            fail_payment_order(
                snapshot.id,
                payment.get("id"),
                request.headers.get("X-Razorpay-Event-Id"),
                payment.get("error_description"),
            )
        return jsonify({"received": True, "collection": collection}), 200

    if event in ("payment.captured", "order.paid"):
        if current.get("status") != "paid":
            ref.update({
                "status": "paid",
                "payment_id": payment.get("id"),
                "paid_at": datetime.now(timezone.utc).isoformat(),
                "webhook_event": event,
            })
        booking_id = current.get("booking_id")
        if booking_id:
            booking_ref = store.collection("service_bookings").document(booking_id)
            booking = booking_ref.get()
            if booking.exists and (booking.to_dict() or {}).get("status") in (
                "pending",
                "payment_pending",
            ):
                booking_ref.update({
                    "status": "confirmed",
                    "payment_status": "paid",
                    "payment_id": payment.get("id"),
                })
    elif event == "payment.failed" and current.get("status") != "paid":
        ref.update({
            "status": "failed",
            "failure_reason": payment.get("error_description"),
            "webhook_event": event,
        })

    return jsonify({"received": True, "collection": collection}), 200
