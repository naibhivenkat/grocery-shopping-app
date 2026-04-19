"""`/payments/*` endpoints consumed by `PaymentRemoteDataSource`."""

from flask import Blueprint, g, jsonify, request
from google.cloud.firestore_v1.base_query import FieldFilter

from auth_utils import require_auth, require_role
from db import (
    NOTIFICATIONS,
    SUBSCRIPTION_PAYMENTS,
    VENDOR_SUBSCRIPTIONS,
    col,
    doc,
    now_iso,
    to_dict,
)


payments_bp = Blueprint("payments", __name__)


@payments_bp.post("/payments")
@require_auth
def submit_payment():
    payload = request.get_json(silent=True) or {}
    subscription_id = payload.get("subscription_id")
    amount = payload.get("amount")
    transaction_id = payload.get("transaction_id")
    if not subscription_id or amount is None or not transaction_id:
        return jsonify(
            {"detail": "subscription_id, amount, transaction_id required"}
        ), 422

    ref = col(SUBSCRIPTION_PAYMENTS).document()
    ref.set({
        "vendor_id": g.user_id,
        "subscription_id": subscription_id,
        "amount": float(amount),
        "method": payload.get("method") or "upi",
        "transaction_id": transaction_id,
        "upi_screenshot_url": payload.get("upi_screenshot_url"),
        "status": "pending",
        "created_at": now_iso(),
    })
    return jsonify(to_dict(ref.get())), 201


@payments_bp.get("/payments")
@require_auth
def list_my_payments():
    query = col(SUBSCRIPTION_PAYMENTS).where(
        filter=FieldFilter("vendor_id", "==", g.user_id)
    )
    items = [to_dict(d) for d in query.stream()]
    items.sort(key=lambda p: p.get("created_at") or "", reverse=True)
    return jsonify(items)


@payments_bp.get("/payments/all")
@require_role("admin", "super_admin")
def list_all_payments():
    query = col(SUBSCRIPTION_PAYMENTS).where(
        filter=FieldFilter("status", "==", "pending")
    )
    items = [to_dict(d) for d in query.stream()]
    items.sort(key=lambda p: p.get("created_at") or "", reverse=True)
    return jsonify(items)


def _notify(user_id: str, title: str, body: str, reference_id: str) -> None:
    col(NOTIFICATIONS).document().set({
        "user_id": user_id,
        "type": "payment_approved",
        "title": title,
        "body": body,
        "is_read": False,
        "reference_id": reference_id,
        "created_at": now_iso(),
    })


@payments_bp.post("/payments/<payment_id>/verify")
@require_role("admin", "super_admin")
def verify_payment(payment_id):
    ref = doc(SUBSCRIPTION_PAYMENTS, payment_id)
    snap = ref.get()
    if not snap.exists:
        return jsonify({"detail": "Payment not found"}), 404
    data = snap.to_dict() or {}

    ref.update({
        "status": "verified",
        "verified_at": now_iso(),
    })

    subscription_id = data.get("subscription_id")
    if subscription_id:
        doc(VENDOR_SUBSCRIPTIONS, subscription_id).set(
            {"status": "active", "activated_at": now_iso()}, merge=True
        )

    vendor_id = data.get("vendor_id")
    if vendor_id:
        _notify(vendor_id, "Payment verified", "Your subscription is now active.", payment_id)
    return jsonify({"ok": True})


@payments_bp.post("/payments/<payment_id>/reject")
@require_role("admin", "super_admin")
def reject_payment(payment_id):
    ref = doc(SUBSCRIPTION_PAYMENTS, payment_id)
    snap = ref.get()
    if not snap.exists:
        return jsonify({"detail": "Payment not found"}), 404
    data = snap.to_dict() or {}
    ref.update({
        "status": "rejected",
        "rejected_at": now_iso(),
    })
    vendor_id = data.get("vendor_id")
    if vendor_id:
        _notify(vendor_id, "Payment rejected", "Please retry with a valid transaction.", payment_id)
    return jsonify({"ok": True})
