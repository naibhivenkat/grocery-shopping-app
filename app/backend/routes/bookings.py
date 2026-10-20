"""`/bookings` and `/provider/bookings` endpoints for LocalShop V2."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re
import uuid
from flask import Blueprint, g, jsonify, request
from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from auth_utils import require_auth
from db import db, col, doc, now_iso, NOTIFICATIONS
from notification_delivery import notification_data, deliver_push
from routes.availability import lock_slots_txn, release_slots_txn, validate_selection, _load_availability

bookings_bp = Blueprint("bookings", __name__)

COLL_BOOKINGS = "service_bookings"
COLL_SERVICES = "provider_services"
USERS = "users"

def _booking_notice(transaction, booking_id, booking, state):
    recipient = booking.get('provider_id') if g.user_id == booking.get('requester_id') else booking.get('requester_id')
    if not _valid_id(recipient):
        return None
    event = notification_data(recipient, 'service_booking', 'Service booking ' + state,
                              'Open your booking to view the latest details.', booking_id)
    transaction.set(doc(NOTIFICATIONS, f'booking_{booking_id}_{state}_{recipient}'), event)
    return event


def _calculate_service_cost(service: dict, duration_minutes: int) -> float:
    pricing_type = service.get("pricing_type", "fixed")
    try:
        values = {key: Decimal(str(service.get(key) or 0)) for key in (
            "fixed_price", "hourly_price", "per_30min_price", "minimum_charge", "inspection_charge",
        )}
        if any(not value.is_finite() or value < 0 for value in values.values()):
            raise ValueError("Service pricing is invalid")
        if pricing_type == "fixed":
            cost = values["fixed_price"]
        elif pricing_type == "visit":
            cost = values["inspection_charge"]
        elif pricing_type in ("hourly", "per_30min", "time_based"):
            per_30 = values["per_30min_price"]
            cost = Decimal(duration_minutes) / 30 * per_30 if per_30 > 0 else Decimal(duration_minutes) / 60 * values["hourly_price"]
            cost = max(cost, values["minimum_charge"])
        else:
            raise ValueError("Unsupported service pricing type")
        if not 0 < cost <= 10_000_000:
            raise ValueError("Service must have a positive price within the supported limit")
        cost = cost.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if cost <= 0:
            raise ValueError("Service price must be at least one paisa")
        return float(cost)
    except InvalidOperation:
        raise ValueError("Service pricing is invalid")


def _valid_id(value):
    return isinstance(value, str) and bool(re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", value)) and value not in (".", "..")


def _paise(value):
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount <= 0 or amount > 10_000_000:
            raise ValueError("Invalid booking amount")
        paise = int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        if paise <= 0:
            raise ValueError("Invalid booking amount")
        return paise
    except (InvalidOperation, TypeError):
        raise ValueError("Invalid booking amount")


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
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"detail": "Request body must be a JSON object"}), 422
    provider_id = payload.get("provider_id")
    service_id = payload.get("service_id")
    requester_id = g.user_id

    if not _valid_id(provider_id) or not _valid_id(service_id):
        return jsonify({"detail": "provider_id and service_id required"}), 400

    if provider_id == requester_id:
        return jsonify({"detail": "Cannot book your own service"}), 403

    svc_snap = doc(COLL_SERVICES, service_id).get()
    if not svc_snap.exists:
        return jsonify({"detail": "Service not found"}), 404

    svc_data = svc_snap.to_dict() or {}
    if svc_data.get("provider_id") != provider_id:
        return jsonify({"detail": "Service mismatch with target provider"}), 400
    if svc_data.get("is_deleted") or svc_data.get("is_active") is False:
        return jsonify({"detail": "Service is not available"}), 409

    try:
        raw_duration = payload.get("duration", 60)
        if isinstance(raw_duration, bool) or isinstance(raw_duration, float):
            raise ValueError("fractional duration")
        duration = int(raw_duration)
    except (TypeError, ValueError):
        return jsonify({"detail": "duration must be a number"}), 422
    if duration <= 0 or duration % 30 != 0 or duration > 480:
        return jsonify({"detail": "duration must be 30-minute intervals up to 8 hours"}), 422
    if not payload.get("slot_date") or not payload.get("slot_time"):
        return jsonify({"detail": "slot_date and slot_time are required"}), 422
    try:
        times = validate_selection(payload["slot_date"], payload["slot_time"], duration)
    except ValueError as error:
        return jsonify({"detail": str(error)}), 422
    booking_id = uuid.uuid4().hex

    # Calculate financials for the pending snapshot
    try:
        service_price = _calculate_service_cost(svc_data, duration)
    except ValueError as error:
        return jsonify({"detail": str(error)}), 422
    platform_fee = round(service_price * 0.05, 2)
    tax = round((service_price + platform_fee) * 0.18, 2)
    final_total = round(service_price + platform_fee + tax, 2)
    if final_total > 10_000_000:
        return jsonify({"detail": "Booking quote exceeds the payment limit"}), 422

    booking_data = {
        "booking_id": booking_id,
        "service_id": service_id,
        "service_title": svc_data.get("title", "Service"),
        "provider_id": provider_id,
        "requester_id": requester_id,
        "slot_date": payload.get("slot_date"),
        "slot_time": payload.get("slot_time"),
        "duration": duration,
        "pricing_type": svc_data.get("pricing_type", "fixed"),
        "status": "pending_payment",
        "service_price": service_price,
        "provider_earning": service_price,
        "platform_fee": platform_fee,
        "tax": tax,
        "final_total": final_total,
        "platform_earning": round(final_total - service_price, 2),
        "commission": round(final_total * 0.10, 2),
        "created_at": now_iso()
    }

    @firestore.transactional
    def create(transaction):
        # Verify the quote and current schedule before creating a payable booking.
        provider = doc(USERS, provider_id).get(transaction=transaction)
        provider_data = provider.to_dict() or {} if provider.exists else {}
        profile = doc("provider_profiles", provider_id).get(transaction=transaction)
        profile_data = profile.to_dict() or {} if profile.exists else {}
        if not provider.exists or provider_data.get("is_suspended") or not profile.exists or profile_data.get("is_active") is False:
            raise ValueError("Provider is unavailable")
        service = doc(COLL_SERVICES, service_id).get(transaction=transaction)
        current = service.to_dict() or {} if service.exists else {}
        if (not service.exists or current.get("provider_id") != provider_id
            or current.get("is_deleted") or current.get("is_active") is False
            or _calculate_service_cost(current, duration) != service_price):
            raise ValueError("Service or price changed; refresh the quote")
        _, calendar, _ = _load_availability(transaction, provider_id, payload["slot_date"])
        slots = {slot["time"]: slot for slot in calendar.get("slots", [])}
        if any(time not in slots or slots[time].get("status") != "available" for time in times):
            raise ValueError("Selected slots are unavailable")
        transaction.set(doc(COLL_BOOKINGS, booking_id), booking_data)

    try:
        create(db().transaction())
    except ValueError as error:
        return jsonify({"detail": str(error)}), 409
    return jsonify({
        **booking_data,
        "id": booking_id,
        "detail": "Pending booking created",
    }), 201


@bookings_bp.post("/bookings/<booking_id>/confirm")
@require_auth
def confirm_booking(booking_id):
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"detail": "Request body must be a JSON object"}), 422
    payment_method = payload.get("payment_method", "razorpay")
    if payment_method == "wallet":
        return jsonify({"detail": "Wallet is temporarily disabled", "code": "WALLET_DISABLED"}), 410
    if payment_method != "razorpay":
        return jsonify({"detail": "Razorpay payment is required"}), 422

    @firestore.transactional
    def _confirm_tx(transaction):
        ref = doc(COLL_BOOKINGS, booking_id)
        snap = ref.get(transaction=transaction)

        if not snap.exists:
            raise ValueError("Booking not found")

        booking = snap.to_dict() or {}

        if booking.get("requester_id") != g.user_id:
            raise PermissionError("Forbidden: Not your booking")

        if booking.get("status") in {"confirmed", "incoming", "accepted", "started", "completed"} and booking.get("payment_status") == "paid":
            return
        if booking.get("status") != "pending_payment":
            raise ValueError("Booking already processed or invalid state")

        payment_intent_id = payload.get("payment_intent_id") or booking.get("payment_intent_id")
        payment_id = booking.get("razorpay_payment_id")
        if payment_method == "razorpay":
            if not _valid_id(payment_intent_id):
                raise ValueError("A settled Razorpay payment intent is required")
            intent_snap = doc("payment_orders", str(payment_intent_id)).get(transaction=transaction)
            intent = intent_snap.to_dict() or {} if intent_snap.exists else {}
            if (
                not intent_snap.exists
                or intent.get("status") != "paid"
                or intent.get("purpose") != "service"
                or intent.get("user_id") != g.user_id
                or intent.get("reference_id") != booking_id
                or intent.get("settlement_status", "settled") != "settled"
            ):
                raise ValueError("Razorpay payment is not settled for this booking")
            payment_id = intent.get("payment_id")
            if not payment_id:
                raise ValueError("Payment has no captured payment ID")
        elif payment_method != "wallet":
            raise ValueError("Unsupported booking payment method")

        # 2. FINAL PRICING EXTRACTION (Server-Side Trust Only)
        svc_snap = doc(COLL_SERVICES, booking["service_id"]).get(transaction=transaction)
        svc = svc_snap.to_dict() or {} if svc_snap.exists else {}
        if (not svc_snap.exists or svc.get("provider_id") != booking["provider_id"]
            or svc.get("is_deleted") or svc.get("is_active") is False):
            raise ValueError("Service is unavailable; cancel the booking to request a refund")
        provider = doc(USERS, booking["provider_id"]).get(transaction=transaction)
        provider_data = provider.to_dict() or {} if provider.exists else {}
        profile = doc("provider_profiles", booking["provider_id"]).get(transaction=transaction)
        profile_data = profile.to_dict() or {} if profile.exists else {}
        if not provider.exists or provider_data.get("is_suspended") or not profile.exists or profile_data.get("is_active") is False:
            raise ValueError("Provider is unavailable; cancel the booking to request a refund")

        # Honor the server quote that the captured payment covered.
        service_price = float(booking["service_price"])
        platform_fee = float(booking["platform_fee"])
        tax = float(booking["tax"])
        final_total = float(booking["final_total"])
        paid_paise = intent.get("amount_paise") if intent.get("amount_paise") is not None else _paise(intent.get("amount", 0))
        if isinstance(paid_paise, bool) or paid_paise != _paise(final_total):
            raise ValueError("Payment amount does not match booking quote")
        requester_info = _get_trusted_user_info(transaction, g.user_id)
        # Complete every read before locking slots, which schedules writes.
        if not lock_slots_txn(transaction, booking["provider_id"], booking["slot_date"],
                              booking["slot_time"], booking["duration"], booking_id):
            raise ValueError("Slot conflict: Selected time is no longer available")

        # 4. FINAL STATE & METADATA COMMIT
        updates = {
            "status": "confirmed",
            "payment_status": "paid",
            "payment_method": payment_method,
            "payment_intent_id": payment_intent_id,
            "razorpay_payment_id": payment_id,
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
        return _booking_notice(transaction, booking_id, booking, "confirmed")

    try:
        event = _confirm_tx(db().transaction())
        if event:
            deliver_push(event, lookup=doc)
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
        return _booking_notice(transaction, booking_id, booking, "accepted")

    try:
        event = _accept_tx(db().transaction())
        if event:
            deliver_push(event, lookup=doc)
        return jsonify({"success": True, "detail": "Booking accepted"}), 200
    except PermissionError as e:
        return jsonify({"detail": str(e)}), 403
    except ValueError as e:
        err_msg = str(e)
        return jsonify({"detail": err_msg}), 404 if "not found" in err_msg else 400


@bookings_bp.post("/bookings/<booking_id>/reject")
@require_auth
def reject_booking(booking_id):
    payload = request.get_json(silent=True)
    if payload is None and not request.get_data(cache=True):
        payload = {}  # Existing APK booking actions send no JSON body.
    if not isinstance(payload, dict):
        return jsonify({"detail": "Request body must be a JSON object"}), 422
    reason = payload.get("reason", "No reason provided")
    if not isinstance(reason, str) or len(reason) > 500:
        return jsonify({"detail": "reason must be text up to 500 characters"}), 422
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

        if booking.get("status") == "rejected":
            return
        if booking.get("status") not in ["pending", "incoming", "confirmed", "accepted"]:
            raise ValueError("Already processed")

        release_slots_txn(
            transaction,
            booking["provider_id"],
            booking["slot_date"],
            booking["slot_time"],
            booking.get("duration", 60), booking_id,
        )
        transaction.update(ref, {
            "status": "rejected", "reject_reason": reason, "updated_at": now_iso(),
        })

        return _booking_notice(transaction, booking_id, booking, "rejected")

    try:
        event = _reject_tx(db().transaction())
        if event:
            deliver_push(event, lookup=doc)
    except PermissionError as e:
        return jsonify({"detail": str(e)}), 403
    except ValueError as e:
        err_msg = str(e)
        return jsonify({"detail": err_msg}), 404 if "not found" in err_msg else 400

    refund = None
    if booking_data_for_refund.get("payment_status") == "paid":
        from routes.service_wallet import process_refund
        refund = process_refund(booking_id)

    return jsonify({"success": True, "detail": "Booking rejected", "refund": refund}), 200


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
        return _booking_notice(transaction, booking_id, booking, "started")

    try:
        event = _start_tx(db().transaction())
        if event:
            deliver_push(event, lookup=doc)
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

        if booking.get("status") == "completed":
            return None
        if booking.get("status") != "started" or booking.get("payment_status") != "paid":
            raise ValueError("Service must be started before completion")

        # ATOMIC FINANCIAL SETTLEMENT INSIDE THE SAME TRANSACTION
        provider_earning = _paise(booking.get("provider_earning") or booking.get("service_price") or 0) / 100
        if provider_earning > 0:
            tx_ref = doc("service_wallet_transactions", f"credit_{booking_id}")
            if not tx_ref.get(transaction=transaction).exists:
                # Credit Service Wallet
                w_ref = doc("service_wallets", g.user_id)
                w_snap = w_ref.get(transaction=transaction)
                w_bal = float((w_snap.to_dict() or {}).get("balance", 0)) if w_snap.exists else 0.0
                # Credit Earnings Dashboard Ledger
                e_ref = doc("provider_earnings", g.user_id)
                e_snap = e_ref.get(transaction=transaction)
                e_total = float((e_snap.to_dict() or {}).get("lifetime_total", 0)) if e_snap.exists else 0.0
                transaction.set(w_ref, {"balance": round(w_bal + provider_earning, 2), "updated_at": now_iso()}, merge=True)
                transaction.set(tx_ref, {
                    "user_id": g.user_id, "type": "service_income", "amount": provider_earning,
                    "booking_id": booking_id, "created_at": now_iso(),
                })
                transaction.set(e_ref, {"lifetime_total": e_total + provider_earning, "updated_at": now_iso()}, merge=True)
        transaction.update(ref, {"status": "completed", "completed_at": now_iso(), "updated_at": now_iso()})
        return _booking_notice(transaction, booking_id, booking, "completed")

    try:
        event = _complete_tx(db().transaction())
        if event:
            deliver_push(event, lookup=doc)
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

        if booking.get("status") == "cancelled":
            return
        if booking.get("status") not in ["pending_payment", "confirmed", "accepted"]:
            raise ValueError("Booking cannot be cancelled from current state")

        if booking.get("status") != "pending_payment":
            release_slots_txn(
                transaction, booking["provider_id"], booking["slot_date"],
                booking["slot_time"], booking.get("duration", 60), booking_id,
            )
        transaction.update(ref, {"status": "cancelled", "cancelled_by": g.user_id, "updated_at": now_iso()})

        return _booking_notice(transaction, booking_id, booking, "cancelled")

    try:
        event = _cancel_tx(db().transaction())
        if event:
            deliver_push(event, lookup=doc)
    except PermissionError as e:
        return jsonify({"detail": str(e)}), 403
    except ValueError as e:
        err_msg = str(e)
        return jsonify({"detail": err_msg}), 404 if "not found" in err_msg else 400

    refund = None
    if booking_data_for_refund.get("payment_status") == "paid":
        from routes.service_wallet import process_refund
        refund = process_refund(booking_id)

    return jsonify({"success": True, "detail": "Booking cancelled", "refund": refund}), 200


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


@bookings_bp.get("/services/dashboard/<provider_id>")
@require_auth
def get_legacy_provider_dashboard(provider_id):
    # Enforce Auth
    if provider_id != g.user_id:
        return jsonify({"detail": "Forbidden"}), 403

    e_snap = doc("provider_earnings", g.user_id).get()
    lifetime = float((e_snap.to_dict() or {}).get("lifetime_total", 0.0)) if e_snap.exists else 0.0

    return jsonify({
        "dashboard": {
            "total_earnings": lifetime,
            "jobs_completed": len(list(
                col(COLL_BOOKINGS).where(filter=FieldFilter("provider_id", "==", g.user_id)).where(
                    filter=FieldFilter("status", "==", "completed")).stream()))
        }
    })
