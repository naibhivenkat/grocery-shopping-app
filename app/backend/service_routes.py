import calendar
import logging
import razorpay
from datetime import datetime, timedelta, timezone
from flask import Blueprint, request, jsonify
from google.cloud import firestore
from service_notifications_helper import  register_fcm_token
from service_firebase_db import (
    # AUTH
    create_service_provider,
    login_service_user,
    update_password,

    # SERVICES
    upsert_provider_service,
    get_provider_services,
    get_provider_service,
    soft_delete_provider_service,

    # AVAILABILITY
    get_or_create_availability,
    update_slots,

    # BOOKINGS
    provider_bookings,
    booking_detail,
    create_booking,
    provider_earnings_dashboard,

    # FIRESTORE
    db,
    initiate_refund,

    # PRICING
    calculate_service_cost,
    credit_provider_wallet,
    release_locked_slots,

    notify_customer,
    notify_provider
)

service_bp = Blueprint("service_bp", __name__)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("service_api")

# 🔹 Razorpay
RAZORPAY_KEY_ID = "rzp_test_RKK3DuGSaxK9fR"
RAZORPAY_KEY_SECRET = "VgVc96Pdn3t5T8ieX0nb2ajt"
razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

COLL_SERVICE_BOOKINGS = "service_bookings"
# cOLL_SERVICE_PENDING = "service_pending_bookings"
COLL_SERVICE_WALLETS = "service_wallets"
COLL_SERVICE_WALLET_TX = "service_wallet_transactions"

bookings_db = {}
IST = timezone(timedelta(hours=5, minutes=30))


# =================================================
# HELPERS
# =================================================
def ok(data=None, code=200):
    return jsonify(data or {"success": True}), code


def err(msg, code=400):
    return jsonify({"error": msg}), code


# =================================================
# AUTH
# =================================================
@service_bp.route("/auth/register", methods=["POST"])
def register():
    body = request.get_json(force=True)

    required = ["name", "mobile", "email", "password"]
    for k in required:
        if not body.get(k):
            return err(f"{k} is required", 400)

    try:
        user = create_service_provider(body)
        return ok({"success": True, "user": user})
    except Exception as e:
        return err(str(e), 400)


@service_bp.route("/auth/login", methods=["POST"])
def login():
    body = request.get_json(force=True)

    email = (body.get("email") or "").strip()
    password = body.get("password") or ""

    if not email or not password:
        return err("email and password required", 400)

    try:
        user = login_service_user(email, password)
        return ok({"success": True, "user": user})
    except Exception as e:
        return err(str(e), 401)


@service_bp.route("/auth/forgot_password", methods=["POST"])
def forgot_password():
    body = request.get_json(force=True)

    try:
        update_password(email=body["email"], new_password=body["new_password"])
        return ok({"success": True})
    except Exception as e:
        return err(str(e), 400)


# =================================================
# PROVIDER SERVICES
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

    if "provider_id" not in body:
        return err("provider_id required")

    try:
        service = upsert_provider_service(body)
        return ok({"success": True, "service": service})
    except Exception as e:
        return err(str(e), 400)


@service_bp.route("/provider/services/<service_id>", methods=["DELETE"])
def delete_service(service_id):
    try:
        soft_delete_provider_service(service_id)
        return ok({"success": True})
    except Exception as e:
        return err(str(e), 400)


# =================================================
# AVAILABLE SERVICES (USER SIDE)
# =================================================

@service_bp.route("/available", methods=["GET"])
def get_available_services():
    category_id = request.args.get("category_id")
    requester_id = str(request.args.get("requester_id") or "")

    if not category_id:
        return err("category_id required", 400)

    query = db.collection("provider_services") \
        .where("service_category_id", "==", category_id) \
        .where("is_deleted", "==", False)

    services = query.stream()
    result = []

    for s in services:
        data = s.to_dict()
        provider_id = str(data.get("provider_id"))

        # 🚫 hide own services
        if requester_id and provider_id == requester_id:
            continue

        # ✅ pull from correct collection
        provider = db.collection("service_providers").document(provider_id).get().to_dict() or {}

        result.append({
            "id": s.id,
            "service_name": data.get("title"),
            "provider_id": provider_id,

            "provider_name": provider.get("name"),
            "location": provider.get("location"),
            "photo_base64": provider.get("photo_base64"),

            "fixed_price": data.get("fixed_price"),
            "min_price": data.get("min_price"),
            "pricing_unit": data.get("pricing_unit"),

            "rating": provider.get("rating"),
            "completed_jobs": provider.get("completed_jobs", 0),
            "verified": provider.get("verified", False),
            "available_today": provider.get("available_today", True),
        })

    result.sort(key=lambda x: (
        not x.get("available_today", True),
        -(x.get("rating") or 0)
    ))

    return ok(result)


# =================================================
# PRICE CALCULATION (SOURCE OF TRUTH)
# =================================================
@service_bp.route("/calculate-price", methods=["POST"])
def calculate_price():
    body = request.get_json(force=True)

    service_id = body.get("service_id")
    duration = int(body.get("duration", 60))

    svc = get_provider_service(service_id)

    base = calculate_service_cost(svc, duration)

    platform_fee = base * 0.05
    tax = base * 0.18
    total = base + platform_fee + tax

    return ok({
        "service_cost": round(base, 2),
        "platform_fee": round(platform_fee, 2),
        "tax": round(tax, 2),
        "total_cost": round(total, 2),

        "pricing_type": svc.get("pricing_type", "fixed"),
        "visit_charge": float(svc.get("inspection_charge", 0)),
        "hourly_price": float(svc.get("hourly_price", 0)),
        "per_30min_price": float(svc.get("per_30min_price", 0)),
        "minimum_charge": float(svc.get("minimum_charge", 0))
    })


@service_bp.route("/booking/create-pending", methods=["POST"])
def create_pending_booking():
    body = request.json

    # 🚫 BLOCK SELF BOOKING AT ENTRY
    if body["provider_id"] == body["requester_id"]:
        return err("You cannot book your own service", 400)

    booking_id = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    IST = timezone(timedelta(hours=5, minutes=30))
    time_of_update = datetime.now(IST).replace(microsecond=0).isoformat()
    doc = {
        "booking_id": booking_id,
        "service_id": body["service_id"],
        "provider_id": body["provider_id"],
        "requester_id": body["requester_id"],
        "slot_date": body["slot_date"],
        "slot_time": body["slot_time"],
        "duration": body["duration"],
        "amount": body["amount"],
        "service_cost": body.get("service_cost"),
        "platform_fee": body.get("platform_fee"),
        "tax": body.get("tax"),
        "pricing_type": body.get("pricing_type"),
        "status": "pending_payment",
        "created_at": time_of_update
    }

    db.collection(COLL_SERVICE_BOOKINGS).document(booking_id).set(doc)

    return ok({"booking_id": booking_id})


# =================================================
# CONFIRM BOOKING AFTER PAYMENT
# =================================================

@service_bp.route("/booking/confirm", methods=["POST"])
def confirm_booking():
    body = request.json
    booking_id = body["booking_id"]

    ref = db.collection(COLL_SERVICE_BOOKINGS).document(booking_id)
    snap = ref.get()

    if not snap.exists:
        return err("Booking not found")

    pending = snap.to_dict()

    if pending["status"] != "pending_payment":
        return err("Booking already processed")

    # 🚫 PREVENT PROVIDER BOOKING OWN SERVICE
    if pending["provider_id"] == pending["requester_id"]:
        return err("You cannot book your own service", 400)

    try:
        # ⭐ CALL MAIN BOOKING ENGINE
        booking = create_booking({
            "service_id": pending["service_id"],
            "provider_id": pending["provider_id"],
            "requester_id": pending["requester_id"],
            "slot_date": pending["slot_date"],
            "slot_time": pending["slot_time"],
            "duration": pending.get("duration", 60),
        })

        # ⭐ mark pending as confirmed
        ref.update({
            "status": "confirmed",
            "payment_status": "paid",
            "confirmed_at": datetime.utcnow().isoformat(),
            "final_booking_id": booking["id"]
        })

        return ok({
            "success": True,
            "booking": booking
        })

    except Exception as e:
        logger.exception("Booking confirm failed", exc_info=True)
        return err(f"Confirm failed: {str(e)}", 400)


# =================================================
# FAIL BOOKING
# =================================================
@service_bp.route("/booking/fail", methods=["POST"])
def fail_booking():
    body = request.json
    booking_id = body["booking_id"]

    db.collection(COLL_SERVICE_BOOKINGS).document(booking_id).update({
        "status": "failed",
        "failed_at": datetime.utcnow().isoformat()
    })

    return ok({"success": True})


@service_bp.route("/payment/create-order", methods=["POST"])
def create_payment_order():
    body = request.get_json(force=True)

    amount = float(body.get("amount"))

    order = razorpay_client.order.create({
        "amount": int(amount * 100),
        "currency": "INR",
        "payment_capture": 1
    })
    IST = timezone(timedelta(hours=5, minutes=30))
    time_of_update = datetime.now(IST).replace(microsecond=0).isoformat()
    backend_id = datetime.utcnow().strftime("%Y%m%d%H%M%S")

    db.collection("payment_orders").document(backend_id).set({
        "razorpay_order_id": order["id"],
        "amount": amount,
        "status": "created",
        "created_at": time_of_update
    })

    return ok({
        "razorpay_order_id": order["id"],
        "backend_order_id": backend_id
    })


@service_bp.route("/payment/verify", methods=["POST"])
def verify_payment():
    body = request.json

    razorpay_order_id = body["order_id"]
    payment_id = body["payment_id"]
    signature = body["signature"]
    backend_order_id = body["backend_order_id"]

    try:
        razorpay_client.utility.verify_payment_signature({
            "razorpay_order_id": razorpay_order_id,
            "razorpay_payment_id": payment_id,
            "razorpay_signature": signature
        })

        # mark payment success
        db.collection("payment_orders").document(backend_order_id).update({
            "status": "paid",
            "paid_at": datetime.utcnow().isoformat()
        })

        return ok({
            "success": True,
            "backend_order_id": backend_order_id
        })

    except Exception as e:
        return err(str(e), 400)


# =================================================
# WALLET
# =================================================
@service_bp.route("/wallet/create-order", methods=["POST"])
def wallet_create_order():
    body = request.json

    user_id = body["user_id"]
    amount = float(body["amount"])

    try:
        # 1️⃣ Create Razorpay order
        razorpay_order = razorpay_client.order.create({
            "amount": int(amount * 100),  # paisa
            "currency": "INR",
            "payment_capture": 1
        })
        IST = timezone(timedelta(hours=5, minutes=30))
        time_of_update = datetime.now(IST).replace(microsecond=0).isoformat()
        backend_order_id = datetime.utcnow().strftime("%Y%m%d%H%M%S")

        # 2️⃣ Store backend order
        db.collection("service_payment_orders").document(backend_order_id).set({
            "user_id": user_id,
            "amount": amount,
            "razorpay_order_id": razorpay_order["id"],
            "status": "created",
            "created_at": time_of_update
        })

        return ok({
            "backend_order_id": backend_order_id,
            "razorpay_order_id": razorpay_order["id"]
        })

    except Exception as e:
        return err(str(e), 500)


@service_bp.route("/wallet/<user_id>/balance", methods=["GET"])
def wallet_balance(user_id):
    snap = db.collection(COLL_SERVICE_WALLETS).document(user_id).get()

    if not snap.exists:
        IST = timezone(timedelta(hours=5, minutes=30))
        time_of_update = datetime.now(IST).replace(microsecond=0).isoformat()
        db.collection(COLL_SERVICE_WALLETS).document(user_id).set({
            "balance": 0,
            "updated_at": time_of_update
        })
        return ok({"balance": 0})

    return ok({"balance": snap.to_dict().get("balance", 0)})


@service_bp.route("/wallet/verify", methods=["POST"])
def wallet_verify():
    body = request.json
    logger.info(f"VERIFY BODY: {body}")

    try:
        razorpay_client.utility.verify_payment_signature({
            "razorpay_order_id": body["order_id"],
            "razorpay_payment_id": body["payment_id"],
            "razorpay_signature": body["signature"]
        })

        logger.info("SIGNATURE VERIFIED")

        backend_order_id = body["backend_order_id"]

        order_doc = db.collection("service_payment_orders").document(backend_order_id).get()

        if not order_doc.exists:
            logger.info(f"ORDER NOT FOUND:{backend_order_id}")
            return err("Backend order not found", 400)

        order = order_doc.to_dict()
        logger.info(f"ORDER DATA:{order}")

        user_id = order["user_id"]
        amount = order["amount"]

        ref = db.collection(COLL_SERVICE_WALLETS).document(user_id)
        snap = ref.get()

        balance = snap.to_dict().get("balance", 0) if snap.exists else 0
        new_balance = balance + amount
        IST = timezone(timedelta(hours=5, minutes=30))
        time_of_update = datetime.now(IST).replace(microsecond=0).isoformat()
        ref.set({
            "balance": new_balance,
            "updated_at": time_of_update
        })

        db.collection(COLL_SERVICE_WALLET_TX).add({
            "user_id": user_id,
            "type": "deposit",
            "amount": amount,
            "created_at": time_of_update
        })

        logger.info("WALLET UPDATED")

        return ok({"success": True})

    except Exception as e:
        logger.info("VERIFY ERROR:", str(e))
        return err(str(e), 400)


@service_bp.route("/wallet/deduct", methods=["POST"])
def wallet_deduct():
    body = request.json

    user_id = body["user_id"]
    amount = float(body["amount"])

    ref = db.collection(COLL_SERVICE_WALLETS).document(user_id)
    snap = ref.get()

    if not snap.exists:
        return err("Wallet not found")

    balance = snap.to_dict().get("balance", 0)

    if balance < amount:
        return err("Insufficient balance")
    IST = timezone(timedelta(hours=5, minutes=30))
    time_of_update = datetime.now(IST).replace(microsecond=0).isoformat()

    ref.update({
        "balance": balance - amount,
        "updated_at": time_of_update
    })

    db.collection(COLL_SERVICE_WALLET_TX).add({
        "user_id": user_id,
        "type": "service_payment",
        "amount": amount,
        "created_at": time_of_update
    })

    return ok({"success": True})


@service_bp.route("/provider/<provider_id>/availability", methods=["GET"])
def get_availability(provider_id):
    logger.info("availability ---> hit")

    date = request.args.get("date")

    if not date:
        return err("date required", 400)

    try:
        doc = get_or_create_availability(provider_id, date)
        return ok(doc)
    except Exception as e:
        logger.exception("availability error")
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
        return ok({"success": True})
    except Exception as e:
        logger.exception("update slots error")
        return err(str(e), 400)


@service_bp.route("/wallet/<user_id>/transactions", methods=["GET"])
def wallet_transactions(user_id):
    stream = db.collection(COLL_SERVICE_WALLET_TX) \
        .where("user_id", "==", user_id).stream()

    out = []
    for doc in stream:
        d = doc.to_dict()
        d["id"] = doc.id
        out.append(d)

    return jsonify(out)


@service_bp.route("/provider/<provider_id>/service/<service_id>", methods=["GET"])
def provider_service_detail(provider_id, service_id):
    try:
        svc = get_provider_service(service_id)

        if svc.get("provider_id") != provider_id:
            return err("Unauthorized access")

        return ok({"service": svc})
    except Exception as e:
        return err(str(e), 400)


@service_bp.route("/provider/<provider_id>/bookings", methods=["GET"])
def provider_bookings_route(provider_id):
    status = request.args.get("status", "incoming")

    try:
        items = provider_bookings(provider_id, status)
        return ok({"bookings": items})
    except Exception as e:
        return err(str(e), 400)


@service_bp.route("/bookings/<booking_id>", methods=["GET"])
def booking_detail_route(booking_id):
    try:
        b = booking_detail(booking_id)
        return ok({"booking": b})
    except Exception as e:
        return err(str(e), 404)


@service_bp.route("/bookings/<booking_id>/accept", methods=["POST"])
def accept_booking(booking_id):
    data = request.json
    provider_id = data.get("provider_id")

    if not provider_id:
        return jsonify({"error": "provider_id required"}), 400

    db_ref = db.collection("service_bookings").document(booking_id)

    @firestore.transactional
    def accept_tx(transaction, ref):
        snap = ref.get(transaction=transaction)

        if not snap.exists:
            raise Exception("Booking not found")

        booking = snap.to_dict()
        status = booking.get("status")

        # 🔥 allow new lifecycle statuses
        if status in ["incoming", "confirmed", "accepted", "started", "completed", "rejected"]:
            pass

        IST = timezone(timedelta(hours=5, minutes=30))
        time_of_update = datetime.now(IST).replace(microsecond=0).isoformat()
        transaction.update(ref, {
            "provider_id": provider_id,
            "status": "accepted",
            "accepted_at": time_of_update
        })

    transaction = db.transaction()

    try:
        accept_tx(transaction, db_ref)
        return jsonify({"message": "Booking accepted"})
    except Exception as e:
        return jsonify({"error": str(e)}), 400



@service_bp.route("/bookings/<booking_id>/reject", methods=["POST"])
def reject_booking(booking_id):
    data = request.json
    provider_id = data.get("provider_id")
    reason = data.get("reason")

    if not provider_id:
        return jsonify({"error": "provider_id required"}), 400

    if not reason:
        return jsonify({"error": "reject reason required"}), 400

    ref = db.collection("service_bookings").document(booking_id)
    snap = ref.get()

    if not snap.exists:
        return jsonify({"error": "Booking not found"}), 404

    booking = snap.to_dict()
    booking["id"] = booking_id

    # allow only rejectable states
    if booking.get("status") not in ["pending", "incoming", "confirmed", "accepted"]:
        return jsonify({"error": "Already processed"}), 400

    IST = timezone(timedelta(hours=5, minutes=30))
    now = datetime.now(IST).replace(microsecond=0).isoformat()

    # 🔥 UPDATE STATUS
    ref.update({
        "status": "rejected",
        "provider_id": provider_id,
        "reject_reason": reason,
        "updated_at": now
    })

    # 🔥 RELEASE SLOT (THIS WAS MISSING)
    try:
        release_locked_slots(
            booking["provider_id"],
            booking["slot_date"],
            booking["slot_time"],
            booking.get("duration", 60)
        )
    except Exception as e:
        logger.error(f"SLOT RELEASE FAILED: {e}")

    # 🔥 REFUND
    if booking.get("payment_status") == "paid":
        try:
            initiate_refund(booking)
        except Exception as e:
            logger.error(f"Refund failed: {e}")

    notify_customer(
        booking["requester_id"],
        "Booking Rejected",
        "Provider rejected your booking. Refund initiated.",
        "booking",
        {"booking_id": booking_id, "type": "booking"}
    )


    return jsonify({"message": "Booking rejected, slot released, refund started"})


@firestore.transactional
def start_tx(transaction, ref, provider_id):
    snap = ref.get(transaction=transaction)

    if not snap.exists:
        raise Exception("Booking not found")

    booking = snap.to_dict()

    if booking.get("status") != "accepted":
        raise Exception("Service cannot be started")

    transaction.update(ref, {
        "status": "started",
        "started_at": datetime.utcnow().isoformat(),
        "provider_id": provider_id
    })


@service_bp.route("/bookings/<booking_id>/start", methods=["POST"])
def start_service(booking_id):
    data = request.json
    provider_id = data.get("provider_id")

    if not provider_id:
        return jsonify({"error": "provider_id required"}), 400

    ref = db.collection("service_bookings").document(booking_id)
    snap = ref.get()

    if not snap.exists:
        return jsonify({"error": "Booking not found"}), 404

    booking = snap.to_dict()

    # allow only accepted jobs
    if booking.get("status") != "accepted":
        return jsonify({"error": "Service cannot be started"}), 400

    ref.update({
        "status": "started",
        "started_at": datetime.utcnow().isoformat(),
        "provider_id": provider_id
    })

    notify_customer(
        booking["requester_id"],
        "Service Started",
        "Provider has started the service",
        "booking",
        {"booking_id": booking_id, "type": "booking"}
    )


    return jsonify({"message": "Service started"})



@service_bp.route("/bookings/<booking_id>/complete", methods=["POST"])
def complete_service(booking_id):
    data = request.json
    provider_id = data.get("provider_id")

    if not provider_id:
        return jsonify({"error": "provider_id required"}), 400

    ref = db.collection("service_bookings").document(booking_id)
    snap = ref.get()

    if not snap.exists:
        return jsonify({"error": "Booking not found"}), 404

    booking = snap.to_dict()

    # allow only started jobs
    if booking.get("status") != "started":
        return jsonify({"error": "Service not started"}), 400

    # ───────── MARK COMPLETED ─────────
    IST = timezone(timedelta(hours=5, minutes=30))
    time_of_update = datetime.now(IST).replace(microsecond=0).isoformat()

    ref.update({
        "status": "completed",
        "completed_at": time_of_update,
        "provider_id": provider_id
    })

    # ───────── CREDIT PROVIDER WALLET HERE ─────────
    provider_earning = (
            booking.get("provider_earning")
            or booking.get("service_price")
            or 0
    )

    if provider_earning > 0:
        credit_provider_wallet(
            provider_id,
            provider_earning,
            booking_id
        )
        logger.info(f"WALLET CREDITED: ₹{provider_earning}")

    else:
        logger.error("Provider earning missing — wallet credit skipped")

    notify_customer(
        booking["requester_id"],
        "Service Completed",
        "Service completed successfully",
        "booking",
        {"booking_id": booking_id, "type": "booking"}
        )

    notify_provider(
            provider_id,
            "Wallet Credited",
            f"₹{provider_earning} added to wallet",
            "payment",
            {"booking_id": booking_id, "type": "payment"}
        )


    return jsonify({"message": "Service completed & wallet credited"})


@service_bp.route("/provider/dashboard/earnings", methods=["GET"])
def provider_earnings_dashboard_api():
    provider_id = request.args.get("provider_id")

    if not provider_id:
        return jsonify({"error": "provider_id required"}), 400

    try:
        data = provider_earnings_dashboard(provider_id)
        return jsonify(data)

    except Exception as e:
        logger.exception("Earnings dashboard crash")
        return jsonify({"error": str(e)}), 500



@service_bp.route("/customer/bookings/<requester_id>", methods=["GET"])
def customer_bookings(requester_id):
    docs = db.collection("service_bookings") \
        .where("requester_id", "==", requester_id) \
        .where("payment_status", "==", "paid") \
        .stream()

    data = []

    for d in docs:
        b = d.to_dict()

        logger.info(f"Raw Firestore doc ID={d.id} -> {b}")

        amount = b.get("final_total") or 0
        service = b.get("service_title")

        # 🚫 skip invalid entries
        if amount <= 0:
            continue

        if not service:
            continue

        # 🔥 FETCH PROVIDER NAME USING provider_id
        provider_name = None
        provider_id = b.get("provider_id")

        if provider_id:
            try:
                provider_doc = db.collection("service_providers") \
                    .document(provider_id).get()

                if provider_doc.exists:
                    provider_name = provider_doc.to_dict().get("name")
            except Exception as e:
                logger.warning(f"Provider fetch failed for {provider_id}: {e}")

        data.append({
            "id": d.id,
            "service_title": service,
            "provider_name": provider_name,   # now real provider name
            "slot_date": b.get("slot_date"),
            "slot_time": b.get("slot_time"),
            "status": b.get("status"),
            "amount": amount,
            "payment_status": b.get("payment_status"),
        })

    # 🧠 SORT by slot date + time (latest first)
    data.sort(
        key=lambda x: f"{x.get('slot_date','')} {x.get('slot_time','')}",
        reverse=True
    )

    logger.info(f"Returning customer bookings -> {data}")

    return jsonify({"bookings": data})



@service_bp.route("/booking/<booking_id>/cancel", methods=["POST"])
def cancel_booking(booking_id):
    ref = db.collection("service_bookings").document(booking_id)
    snap = ref.get()

    if not snap.exists:
        return jsonify({"error": "Booking not found"}), 404

    booking = snap.to_dict()

    # only pending/confirmed bookings cancelable
    if booking.get("status") not in ["confirmed", "accepted"]:
        return jsonify({"error": "Booking cannot be cancelled"}), 400

    # update status
    ref.update({
        "status": "cancelled",
        "updated_at": datetime.now(IST).replace(microsecond=0).isoformat()
    })

    # release provider slot
    release_locked_slots(
        booking["provider_id"],
        booking["slot_date"],
        booking["slot_time"],
        booking.get("duration", 60)
    )

    # refund trigger
    initiate_refund({**booking, "id": booking_id})

    return jsonify({"success": True})


@service_bp.route("service/api/register_fcm_token", methods=["POST"])
def register_token():
    body = request.json

    user_id = body.get("user_id")
    role = body.get("role")
    token = body.get("token")

    if not user_id or not token:
        return jsonify({"error": "user_id and token required"}), 400

    register_fcm_token(user_id, role, token)

    return jsonify({"success": True})
