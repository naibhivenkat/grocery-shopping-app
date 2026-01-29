from flask import request, jsonify

from flask import Blueprint


from service_firebase_db import (
    create_provider,
    login_provider,
    update_password,

    upsert_provider_service,
    get_provider_services,

    get_or_create_availability,
    update_slots,

    create_booking,
    provider_bookings,
    booking_detail,

    accept_booking,
    reject_booking,
    start_service,
    complete_service,

    earnings_summary,
    ratings, soft_delete_provider_service
)
service_bp = Blueprint("service_bp", __name__)

def ok(data=None, code=200):
    return jsonify(data or {"success": True}), code


def err(msg, code=400):
    return jsonify({"error": msg}), code


# =================================================
# ✅ AUTH (OTP handled by your existing /send_otp and /verify_otp)
# =================================================
@service_bp.route("/auth/register", methods=["POST"])
def register():
    body = request.get_json(force=True)

    # 🔹 REQUIRED (minimal & realistic)
    required = ["name", "mobile", "email", "password"]
    for k in required:
        if not body.get(k):
            return err(f"{k} is required", 400)

    # 🔹 OPTIONAL FIELDS (SAFE DEFAULTS)
    role = body.get("role", "provider")  # default provider
    service_category_ids = body.get("service_category_ids", [])
    location = body.get("location")
    photo_base64 = body.get("photo_base64")

    bank = body.get("bank")              # may be None
    working_schedule = body.get("working_schedule")  # may be None

    try:
        user = create_provider({
            "role": role,
            "name": body["name"],
            "mobile": body["mobile"],
            "email": body["email"],
            "password": body["password"],

            "service_category_ids": service_category_ids,
            "location": location,
            "photo_base64": photo_base64,

            "bank": bank,
            "working_schedule": working_schedule,
        })

        return ok({
            "success": True,
            "user": user
        })

    except Exception as e:
        return err(str(e), 400)


@service_bp.route("/auth/login", methods=["POST"])
def login():
    body = request.get_json(force=True)
    email = (body.get("email") or "").strip()
    password = body.get("password") or ""

    if not email or not password:
        return err("email and password required")

    try:
        user = login_provider(email=email, password=password)
        return ok({"success": True, "user": user})
    except Exception as e:
        return err(str(e), 401)


@service_bp.route("/auth/forgot_password", methods=["POST"])
def forgot_password():
    body = request.get_json(force=True)
    email = (body.get("email") or "").strip()
    new_password = body.get("new_password") or ""

    if not email or not new_password:
        return err("email and new_password required")

    try:
        update_password(email=email, new_password=new_password)
        return ok({"success": True, "message": "Password updated"})
    except Exception as e:
        return err(str(e), 400)


# =================================================
# ✅ PROVIDER SERVICES
# =================================================
@service_bp.route("/provider/<provider_id>/services", methods=["GET"])
def my_services(provider_id):
    try:
        services = get_provider_services(provider_id)
        return ok({"services": services})
    except Exception as e:
        return err(str(e), 400)



@service_bp.route("/provider/services/upsert", methods=["POST"])
def upsert_service():
    body = request.get_json(force=True)
    required = ["provider_id"]


    for k in required:
        if k not in body:
            return err(f"{k} required")

    try:
        service = upsert_provider_service(body)
        return ok({"success": True, "service": service})
    except Exception as e:
        return err(str(e), 400)


# =================================================
# ✅ AVAILABILITY
# =================================================
@service_bp.route("/provider/<provider_id>/availability", methods=["GET"])
def get_availability(provider_id):
    date = request.args.get("date", "").strip()
    if not date:
        return err("date required (YYYY-MM-DD)")

    try:
        doc = get_or_create_availability(provider_id, date)
        return ok({
            "provider_id": provider_id,
            "date": date,
            "slot_size": doc.get("slot_size", 30),
            "slots": doc.get("slots", [])
        })
    except Exception as e:
        return err(str(e), 400)


@service_bp.route("/provider/availability/update_slots", methods=["POST"])
def update_availability():
    body = request.get_json(force=True)

    required = ["provider_id", "date", "updates"]
    for k in required:
        if k not in body:
            return err(f"{k} required")

    try:
        update_slots(body["provider_id"], body["date"], body["updates"])
        return ok({"success": True, "message": "Slots updated"})
    except Exception as e:
        return err(str(e), 400)


# =================================================
# ✅ BOOKINGS (Requester creates booking)
# =================================================
@service_bp.route("/bookings/create", methods=["POST"])
def create_booking_route():
    body = request.get_json(force=True)

    required = ["provider_id", "requester_id", "service_id", "slot_date", "slot_time"]
    for k in required:
        if k not in body:
            return err(f"{k} required")

    try:
        b = create_booking(body)
        return ok({"success": True, "booking": b})
    except Exception as e:
        return err(str(e), 400)


@service_bp.route("/provider/<provider_id>/bookings", methods=["GET"])
def provider_bookings_route(provider_id):
    status = request.args.get("status", "incoming").strip()
    try:
        items = provider_bookings(provider_id, status)
        return ok({"success": True, "bookings": items})
    except Exception as e:
        return err(str(e), 400)


@service_bp.route("/bookings/<booking_id>", methods=["GET"])
def booking_detail_route(booking_id):
    try:
        b = booking_detail(booking_id)
        return ok({"success": True, "booking": b})
    except Exception as e:
        return err(str(e), 404)


@service_bp.route("/bookings/<booking_id>/accept", methods=["POST"])
def accept_booking_route(booking_id):
    body = request.get_json(force=True)
    provider_id = body.get("provider_id")
    if not provider_id:
        return err("provider_id required")

    try:
        accept_booking(booking_id, provider_id)
        return ok({"success": True, "message": "Booking accepted"})
    except Exception as e:
        return err(str(e), 400)


@service_bp.route("/bookings/<booking_id>/reject", methods=["POST"])
def reject_booking_route(booking_id):
    body = request.get_json(force=True)
    provider_id = body.get("provider_id")
    reason = (body.get("reason") or "").strip()

    if not provider_id or not reason:
        return err("provider_id and reason required")

    try:
        reject_booking(booking_id, provider_id, reason)
        return ok({"success": True, "message": "Booking rejected + refund initiated"})
    except Exception as e:
        return err(str(e), 400)


@service_bp.route("/bookings/<booking_id>/start", methods=["POST"])
def start_service_route(booking_id):
    body = request.get_json(force=True)
    provider_id = body.get("provider_id")
    if not provider_id:
        return err("provider_id required")

    try:
        start_service(booking_id, provider_id)
        return ok({"success": True, "message": "Service started"})
    except Exception as e:
        return err(str(e), 400)


@service_bp.route("/bookings/<booking_id>/complete", methods=["POST"])
def complete_service_route(booking_id):
    body = request.get_json(force=True)
    provider_id = body.get("provider_id")
    if not provider_id:
        return err("provider_id required")

    try:
        complete_service(booking_id, provider_id)
        return ok({"success": True, "message": "Service completed"})
    except Exception as e:
        return err(str(e), 400)


# =================================================
# ✅ EARNINGS
# =================================================
@service_bp.route("/provider/<provider_id>/earnings/summary", methods=["GET"])
def earnings_summary_route(provider_id):
    try:
        data = earnings_summary(provider_id)
        return ok({"success": True, **data})
    except Exception as e:
        return err(str(e), 400)


# =================================================
# ✅ RATINGS (READONLY)
# =================================================
@service_bp.route("/provider/<provider_id>/ratings", methods=["GET"])
def ratings_route(provider_id):
    try:
        data = ratings(provider_id)
        return ok({"success": True, **data})
    except Exception as e:
        return err(str(e), 400)

@service_bp.route("/provider/services/<service_id>", methods=["DELETE"])
def delete_service(service_id):
    try:
        soft_delete_provider_service(service_id)
        return ok({"success": True})
    except ValueError as e:
        return err(str(e), 404)
    except Exception as e:
        return err(str(e), 400)
