"""`/bookings` and `/provider/bookings` endpoints for LocalShop V2."""

from datetime import datetime, timedelta, timezone
from flask import Blueprint, g, jsonify, request
from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from auth_utils import require_auth
from db import db, col, doc, now_iso
from routes.availability import lock_slots_txn, release_slots_txn

bookings_bp = Blueprint("bookings", __name__)

COLL_BOOKINGS = "service_bookings"
COLL_SERVICES = "provider_services"
USERS = "users"

def _calculate_service_cost(service: dict, duration_minutes: int) -> float:
    pricing_type = service.get("pricing_type", "fixed")
    fixed_price = float(service.get("fixed_price", 0))
    hourly_price = float(service.get("hourly_price", 0))
    per_30 = float(service.get("per_30min_price", 0))
    min_charge = float(service.get("minimum_charge", 0))
    visit_charge = float(service.get("inspection_charge", 0))

    if pricing_type == "fixed":
        return fixed_price
    if pricing_type == "visit":
        return visit_charge

    hours = duration_minutes / 60
    cost = (duration_minutes / 30) * per_30 if per_30 > 0 else hours * hourly_price
    return round(max(cost, min_charge), 2)


def _get_trusted_user_info(transaction, uid: str) -> dict:
    snap = doc(USERS, uid).get(transaction=transaction)
    data = snap.to_dict() or {} if snap.exists else {}
    return {
        "name": data.get("full_name") or data.get("username") or "User",
        "phone": data.get("phone", ""),
        "email": data.get("email", ""),
        "photo": data.get("avatar_url") or data.get("photo_base64", "")
    }

# =====================================================================
# V2 BOOKING ENDPOINTS
# =====================================================================

@bookings_bp.post("/bookings/create-pending")
@require_auth
def create_pending_booking():
    payload = request.get_json(silent=True) or {}
    provider_id = payload.get("provider_id")
    service_id = payload.get("service_id")
    requester_id = g.user_id

    if not provider_id or not service_id:
        return jsonify({"detail": "provider_id and service_id required"}), 400

    if provider_id == requester_id:
        return jsonify({"detail": "Cannot book your own service"}), 403

    svc_snap = doc(COLL_SERVICES, service_id).get()
    if not svc_snap.exists:
        return jsonify({"detail": "Service not found"}), 404

    svc_data = svc_snap.to_dict() or {}
    if svc_data.get("provider_id") != provider_id:
        return jsonify({"detail": "Service mismatch with target provider"}), 400

    duration = int(payload.get("duration", 60))
    booking_id = datetime.utcnow().strftime("%Y%m%d%H%M%S")

    booking_data = {
        "booking_id": booking_id,
        "service_id": service_id,
        "provider_id": provider_id,
        "requester_id": requester_id,
        "slot_date": payload.get("slot_date"),
        "slot_time": payload.get("slot_time"),
        "duration": duration,
        "pricing_type": svc_data.get("pricing_type", "fixed"),
        "status": "pending_payment",
        "created_at": now_iso()
    }

    doc(COLL_BOOKINGS, booking_id).set(booking_data)
    return jsonify({"booking_id": booking_id, "detail": "Pending booking created"}), 201


@bookings_bp.post("/bookings/<booking_id>/confirm")
@require_auth
def confirm_booking(booking_id):
    payload = request.get_json(silent=True) or {}
    payment_method = payload.get("payment_method", "wallet")

    @firestore.transactional
    def _confirm_tx(transaction):
        ref = doc(COLL_BOOKINGS, booking_id)
        snap = ref.get(transaction=transaction)

        if not snap.exists:
            raise ValueError("Booking not found")

        booking = snap.to_dict() or {}

        if booking.get("requester_id") != g.user_id:
            raise PermissionError("Forbidden: Not your booking")

        if booking.get("status") != "pending_payment":
            raise ValueError("Booking already processed or invalid state")

        # 1. ATOMIC SLOT LOCKING
        locked = lock_slots_txn(
            transaction,
            booking["provider_id"],
            booking["slot_date"],
            booking["slot_time"],
            booking["duration"]
        )
        if not locked:
            raise ValueError("Slot conflict: Selected time is no longer available")

        # 2. FINAL PRICING EXTRACTION (Server-Side Trust Only)
        svc_snap = doc(COLL_SERVICES, booking["service_id"]).get(transaction=transaction)
        svc = svc_snap.to_dict() or {} if svc_snap.exists else {}

        service_price = _calculate_service_cost(svc, booking["duration"])
        platform_fee = round(service_price * 0.05, 2)
        tax = round((service_price + platform_fee) * 0.18, 2)
        final_total = round(service_price + platform_fee + tax, 2)

        # 3. ATOMIC SHOPPING WALLET DEDUCTION
        if payment_method == "wallet":
            c_wallet_ref = doc("wallets", g.user_id)
            c_snap = c_wallet_ref.get(transaction=transaction)
            c_bal = float((c_snap.to_dict() or {}).get("balance", 0.0)) if c_snap.exists else 0.0

            if c_bal < final_total:
                raise ValueError("Insufficient shopping wallet balance")

            transaction.set(c_wallet_ref, {"balance": c_bal - final_total, "last_updated": now_iso()}, merge=True)

            c_tx_ref = doc("wallet_transactions", f"debit_{booking_id}")
            if not c_tx_ref.get(transaction=transaction).exists:
                transaction.set(c_tx_ref, {
                    "wallet_id": g.user_id,
                    "user_id": g.user_id,
                    "type": "debit",
                    "amount": final_total,
                    "description": f"Service booking {booking_id}",
                    "order_id": booking_id,
                    "created_at": now_iso()
                })

        # 4. FINAL STATE & METADATA COMMIT
        requester_info = _get_trusted_user_info(transaction, g.user_id)

        updates = {
            "status": "confirmed",
            "payment_status": "paid",
            "payment_method": payment_method,
            "confirmed_at": now_iso(),
            "service_title": svc.get("title", "Service"),
            "customer_name": requester_info["name"],
            "customer_phone": requester_info["phone"],
            "service_price": service_price,
            "provider_earning": service_price,
            "platform_fee": platform_fee,
            "tax": tax,
            "final_total": final_total,
            "platform_earning": round(final_total - service_price, 2),
            "commission": round(final_total * 0.10, 2),
            "updated_at": now_iso()
        }
        transaction.update(ref, updates)

    try:
        _confirm_tx(db().transaction())
        return jsonify({"success": True, "detail": "Booking confirmed"}), 200
    except PermissionError as e:
        return jsonify({"detail": str(e)}), 403
    except ValueError as e:
        err_msg = str(e)
        if "not found" in err_msg:
            return jsonify({"detail": err_msg}), 404
        if "conflict" in err_msg:
            return jsonify({"detail": err_msg}), 409
        return jsonify({"detail": err_msg}), 400


@bookings_bp.post("/bookings/<booking_id>/accept")
@require_auth
def accept_booking(booking_id):
    @firestore.transactional
    def _accept_tx(transaction):
        ref = doc(COLL_BOOKINGS, booking_id)
        snap = ref.get(transaction=transaction)
        if not snap.exists:
            raise ValueError("Booking not found")

        booking = snap.to_dict() or {}
        if booking.get("provider_id") != g.user_id:
            raise PermissionError("Forbidden: You are not the provider for this booking")

        if booking.get("status") not in ["confirmed", "incoming"]:
            raise ValueError("Invalid booking state for acceptance")

        transaction.update(ref, {
            "status": "accepted",
            "accepted_at": now_iso(),
            "updated_at": now_iso()
        })

    try:
        _accept_tx(db().transaction())
        return jsonify({"success": True, "detail": "Booking accepted"}), 200
    except PermissionError as e:
        return jsonify({"detail": str(e)}), 403
    except ValueError as e:
        err_msg = str(e)
        return jsonify({"detail": err_msg}), 404 if "not found" in err_msg else 400


@bookings_bp.post("/bookings/<booking_id>/reject")
@require_auth
def reject_booking(booking_id):
    payload = request.get_json(silent=True) or {}
    reason = payload.get("reason", "No reason provided")
    booking_data_for_refund = {}

    @firestore.transactional
    def _reject_tx(transaction):
        nonlocal booking_data_for_refund
        ref = doc(COLL_BOOKINGS, booking_id)
        snap = ref.get(transaction=transaction)
        if not snap.exists:
            raise ValueError("Booking not found")

        booking = snap.to_dict() or {}
        booking_data_for_refund = booking

        if booking.get("provider_id") != g.user_id:
            raise PermissionError("Forbidden: You are not the provider")

        if booking.get("status") not in ["pending", "incoming", "confirmed", "accepted"]:
            raise ValueError("Already processed")

        transaction.update(ref, {
            "status": "rejected",
            "reject_reason": reason,
            "updated_at": now_iso()
        })

        release_slots_txn(
            transaction,
            booking["provider_id"],
            booking["slot_date"],
            booking["slot_time"],
            booking.get("duration", 60)
        )

    try:
        _reject_tx(db().transaction())
    except PermissionError as e:
        return jsonify({"detail": str(e)}), 403
    except ValueError as e:
        err_msg = str(e)
        return jsonify({"detail": err_msg}), 404 if "not found" in err_msg else 400

    if booking_data_for_refund.get("payment_status") == "paid":
        from routes.service_wallet import process_refund
        process_refund(booking_id)

    return jsonify({"success": True, "detail": "Booking rejected"}), 200


@bookings_bp.post("/bookings/<booking_id>/start")
@require_auth
def start_booking(booking_id):
    @firestore.transactional
    def _start_tx(transaction):
        ref = doc(COLL_BOOKINGS, booking_id)
        snap = ref.get(transaction=transaction)
        if not snap.exists:
            raise ValueError("Booking not found")

        booking = snap.to_dict() or {}
        if booking.get("provider_id") != g.user_id:
            raise PermissionError("Forbidden: You are not the provider")

        if booking.get("status") != "accepted":
            raise ValueError("Booking must be accepted before starting")

        transaction.update(ref, {
            "status": "started",
            "started_at": now_iso(),
            "updated_at": now_iso()
        })

    try:
        _start_tx(db().transaction())
        return jsonify({"success": True, "detail": "Service started"}), 200
    except PermissionError as e:
        return jsonify({"detail": str(e)}), 403
    except ValueError as e:
        err_msg = str(e)
        return jsonify({"detail": err_msg}), 404 if "not found" in err_msg else 400


@bookings_bp.post("/bookings/<booking_id>/complete")
@require_auth
def complete_booking(booking_id):
    @firestore.transactional
    def _complete_tx(transaction):
        ref = doc(COLL_BOOKINGS, booking_id)
        snap = ref.get(transaction=transaction)
        if not snap.exists:
            raise ValueError("Booking not found")

        booking = snap.to_dict() or {}
        if booking.get("provider_id") != g.user_id:
            raise PermissionError("Forbidden: You are not the provider")

        if booking.get("status") != "started":
            raise ValueError("Service must be started before completion")

        transaction.update(ref, {
            "status": "completed",
            "completed_at": now_iso(),
            "updated_at": now_iso()
        })

        # ATOMIC FINANCIAL SETTLEMENT INSIDE THE SAME TRANSACTION
        provider_earning = float(booking.get("provider_earning") or booking.get("service_price") or 0)
        if provider_earning > 0:
            tx_ref = doc("service_wallet_transactions", f"credit_{booking_id}")
            if not tx_ref.get(transaction=transaction).exists:
                # Credit Service Wallet
                w_ref = doc("service_wallets", g.user_id)
                w_snap = w_ref.get(transaction=transaction)
                w_bal = float((w_snap.to_dict() or {}).get("balance", 0)) if w_snap.exists else 0.0
                transaction.set(w_ref, {"balance": w_bal + provider_earning, "updated_at": now_iso()}, merge=True)

                # Record Transaction
                transaction.set(tx_ref, {
                    "user_id": g.user_id,
                    "type": "service_income",
                    "amount": provider_earning,
                    "booking_id": booking_id,
                    "created_at": now_iso()
                })

                # Credit Earnings Dashboard Ledger
                e_ref = doc("provider_earnings", g.user_id)
                e_snap = e_ref.get(transaction=transaction)
                e_total = float((e_snap.to_dict() or {}).get("lifetime_total", 0)) if e_snap.exists else 0.0
                transaction.set(e_ref, {"lifetime_total": e_total + provider_earning, "updated_at": now_iso()}, merge=True)
        return booking

    try:
        _complete_tx(db().transaction())
        return jsonify({"success": True, "detail": "Service completed & earnings settled"}), 200
    except PermissionError as e:
        return jsonify({"detail": str(e)}), 403
    except ValueError as e:
        err_msg = str(e)
        return jsonify({"detail": err_msg}), 404 if "not found" in err_msg else 400


@bookings_bp.post("/bookings/<booking_id>/cancel")
@require_auth
def cancel_booking(booking_id):
    booking_data_for_refund = {}

    @firestore.transactional
    def _cancel_tx(transaction):
        nonlocal booking_data_for_refund
        ref = doc(COLL_BOOKINGS, booking_id)
        snap = ref.get(transaction=transaction)
        if not snap.exists:
            raise ValueError("Booking not found")

        booking = snap.to_dict() or {}
        booking_data_for_refund = booking

        if g.user_id not in [booking.get("requester_id"), booking.get("provider_id")]:
            raise PermissionError("Forbidden: You are not a participant")

        if booking.get("status") not in ["confirmed", "accepted"]:
            raise ValueError("Booking cannot be cancelled from current state")

        transaction.update(ref, {
            "status": "cancelled",
            "cancelled_by": g.user_id,
            "updated_at": now_iso()
        })

        release_slots_txn(
            transaction,
            booking["provider_id"],
            booking["slot_date"],
            booking["slot_time"],
            booking.get("duration", 60)
        )

    try:
        _cancel_tx(db().transaction())
    except PermissionError as e:
        return jsonify({"detail": str(e)}), 403
    except ValueError as e:
        err_msg = str(e)
        return jsonify({"detail": err_msg}), 404 if "not found" in err_msg else 400

    if booking_data_for_refund.get("payment_status") == "paid":
        from routes.service_wallet import process_refund
        process_refund(booking_id)

    return jsonify({"success": True, "detail": "Booking cancelled"}), 200


@bookings_bp.get("/bookings")
@require_auth
def list_requester_bookings():
    query = col(COLL_BOOKINGS).where(filter=FieldFilter("requester_id", "==", g.user_id))
    result = []
    for d in query.stream():
        b = d.to_dict() or {}
        b["id"] = d.id
        result.append(b)
    result.sort(key=lambda x: f"{x.get('slot_date', '')} {x.get('slot_time', '')}", reverse=True)
    return jsonify({"bookings": result}), 200


@bookings_bp.get("/provider/bookings")
@require_auth
def list_provider_bookings():
    status_filter = request.args.get("status")
    query = col(COLL_BOOKINGS).where(filter=FieldFilter("provider_id", "==", g.user_id))
    if status_filter:
        query = query.where(filter=FieldFilter("status", "==", status_filter))
    result = []
    for d in query.stream():
        b = d.to_dict() or {}
        b["id"] = d.id
        result.append(b)
    result.sort(key=lambda x: f"{x.get('slot_date', '')} {x.get('slot_time', '')}")
    return jsonify({"bookings": result}), 200


@bookings_bp.get("/bookings/<booking_id>")
@require_auth
def get_booking_detail(booking_id):
    snap = doc(COLL_BOOKINGS, booking_id).get()
    if not snap.exists:
        return jsonify({"detail": "Booking not found"}), 404
    b = snap.to_dict() or {}
    if g.user_id not in [b.get("requester_id"), b.get("provider_id")]:
        return jsonify({"detail": "Forbidden: Not authorized to view"}), 403
    b["id"] = booking_id
    return jsonify({"booking": b}), 200