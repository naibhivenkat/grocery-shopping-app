import calendar
import logging
import razorpay
import uuid
from datetime import datetime
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List
from werkzeug.security import generate_password_hash, check_password_hash

import firebase_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("service")

db = firebase_db.db

RAZORPAY_KEY_ID = "rzp_test_RKK3DuGSaxK9fR"
RAZORPAY_KEY_SECRET = "VgVc96Pdn3t5T8ieX0nb2ajt"
razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
IST = timezone(timedelta(hours=5, minutes=30))
# ==========================
# COLLECTIONS
# ==========================
COLL_PROVIDERS = "service_providers"
COLL_REQUESTERS = "service_requesters"
COLL_PROVIDER_SERVICES = "provider_services"
COLL_AVAILABILITY = "provider_availability"
COLL_BOOKINGS = "service_bookings"
COLL_EARNINGS = "provider_earnings"
COLL_REVIEWS = "provider_reviews"
COLL_SERVICE_WALLETS = "service_wallets"
COLL_SERVICE_WALLET_TX = "service_wallet_transactions"


def _id() -> str:
    return uuid.uuid4().hex


# =================================================
# 👷 PROVIDERS
# =================================================
def provider_by_email(email: str):
    q = db.collection(COLL_PROVIDERS).where("email", "==", email).limit(1).stream()
    for doc in q:
        d = doc.to_dict()
        d["uid"] = doc.id
        return d
    return None


def create_service_provider(payload: Dict[str, Any]) -> Dict[str, Any]:
    if provider_by_email(payload["email"]):
        raise ValueError("Email already registered")

    uid = _id()
    password_hash = generate_password_hash(payload["password"])

    doc = {
        "role": "service_provider",
        "name": payload["name"],
        "mobile": payload["mobile"],
        "email": payload["email"],
        "password_hash": password_hash,
        "location": payload.get("location"),
        "photo_base64": payload.get("photo_base64"),
        "service_category_ids": payload.get("service_category_ids", []),
        "bank": payload.get("bank"),
        "working_schedule": payload.get("working_schedule"),
        "created_at": datetime.now(IST).replace(microsecond=0).isoformat(),
        "updated_at": datetime.now(IST).replace(microsecond=0).isoformat(),
    }

    db.collection(COLL_PROVIDERS).document(uid).set(doc)

    # AUTO CREATE SERVICE ENTRIES
    for category in payload.get("service_category_ids", []):
        sid = _id()

        db.collection(COLL_PROVIDER_SERVICES).document(sid).set({
            "provider_id": uid,
            "service_category_id": category,
            "title": category.capitalize(),
            "description": "",
            "fixed_price": 0,
            "pricing_unit": "fixed",
            "min_price": None,

            "pricing_type": "fixed",
            "hourly_price": 0,
            "per_30min_price": 0,
            "minimum_charge": 0,
            "inspection_charge": 0,

            "is_active": True,
            "is_deleted": False,
            "created_at": datetime.now(IST).replace(microsecond=0).isoformat(),
            "updated_at": datetime.now(IST).replace(microsecond=0).isoformat(),
        })

    return {
        "uid": uid,
        "role": "service_provider",
        "name": doc["name"],
        "email": doc["email"],
        "mobile": doc["mobile"],
        "location": doc.get("location"),
        "service_category_ids": doc.get("service_category_ids"),
    }


def login_service_user(email: str, password: str) -> Dict[str, Any]:
    u = provider_by_email(email)

    if not u:
        raise ValueError("Invalid email/password")

    if not check_password_hash(u.get("password_hash", ""), password):
        raise ValueError("Invalid email/password")

    return {
        "uid": u["uid"],
        "role": "service_provider",
        "name": u.get("name", ""),
        "email": u.get("email", ""),
        "mobile": u.get("mobile", ""),
        "location": u.get("location", ""),
        "photo_base64": u.get("photo_base64"),
        "service_category_ids": u.get("service_category_ids", []),
    }


def update_password(email: str, new_password: str):
    u = provider_by_email(email)
    if not u:
        raise ValueError("User not found")

    db.collection(COLL_PROVIDERS).document(u["uid"]).update({
        "password_hash": generate_password_hash(new_password),
        "updated_at": datetime.now(IST).replace(microsecond=0).isoformat()
    })


# =================================================
# 🛠 PROVIDER SERVICES
# =================================================
def upsert_provider_service(payload: Dict[str, Any]) -> Dict[str, Any]:
    sid = payload.get("id") or _id()

    doc = {
        "provider_id": payload["provider_id"],
        "service_category_id": payload["service_category_id"],
        "title": payload["title"],
        "description": payload.get("description", ""),

        # ⭐ SAFE PRICE HANDLING
        "fixed_price": float(payload["fixed_price"]) if payload.get("fixed_price") not in [None,
                                                                                           ""] else 0,
        "pricing_unit": payload.get("pricing_unit", "fixed"),
        "min_price": float(payload["min_price"]) if payload.get("min_price") not in [None,
                                                                                     ""] else None,

        "pricing_type": payload.get("pricing_type", "fixed"),
        "hourly_price": float(payload["hourly_price"]) if payload.get("hourly_price") not in [None,
                                                                                              ""] else 0,
        "per_30min_price": float(payload.get("per_30min_price") or 0),
        "minimum_charge": float(payload["minimum_charge"]) if payload.get("minimum_charge") not in [
            None, ""] else 0,
        "inspection_charge": float(payload.get("inspection_charge") or 0),

        "working_schedule": payload.get("working_schedule"),
        "is_active": payload.get("is_active", True),
        "is_deleted": payload.get("is_deleted", False),
        "updated_at": datetime.now(IST).replace(microsecond=0).isoformat(),
        "created_at": payload.get("created_at") or datetime.now(IST).replace(
            microsecond=0).isoformat(),
    }

    db.collection(COLL_PROVIDER_SERVICES).document(sid).set(doc, merge=True)
    return {"id": sid, **doc}


def get_provider_services(provider_id: str):
    stream = (
        db.collection(COLL_PROVIDER_SERVICES)
        .where("provider_id", "==", provider_id)
        .where("is_deleted", "==", False)
        .stream()
    )

    out = []
    for doc in stream:
        d = doc.to_dict()
        d["id"] = doc.id
        out.append(d)
    return out


def get_provider_service(service_id: str) -> Dict[str, Any]:
    snap = db.collection(COLL_PROVIDER_SERVICES).document(service_id).get()
    if not snap.exists:
        raise ValueError("Service not found")
    d = snap.to_dict()
    d["id"] = service_id
    return d


# =================================================
# 💰 PRICING ENGINE (PRODUCTION SAFE)
# =================================================
def calculate_service_cost(service, duration_minutes: int):
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

    if per_30 > 0:
        cost = (duration_minutes / 30) * per_30
    else:
        cost = hours * hourly_price

    if cost < min_charge:
        cost = min_charge

    return round(cost, 2)


# =================================================
# 📅 AVAILABILITY
# =================================================
def _availability_doc_id(provider_id: str, date: str) -> str:
    return f"{provider_id}:{date}"


def _parse_time_12h(t: str):
    """'9:00 AM' -> datetime.time"""
    return datetime.strptime(t, "%I:%M %p")


def get_or_create_availability(provider_id: str, date: str):
    try:
        doc_id = f"{provider_id}:{date}"
        ref = db.collection(COLL_AVAILABILITY).document(doc_id)
        snap = ref.get()

        if snap.exists:
            return snap.to_dict()

        # ⭐ get provider service
        services = db.collection("provider_services") \
            .where("provider_id", "==", provider_id) \
            .where("is_deleted", "==", False) \
            .limit(1).stream()

        service = None
        for s in services:
            service = s.to_dict()
            break

        # If provider has no service → return empty slots
        if not service:
            return {
                "provider_id": provider_id,
                "date": date,
                "slot_size": 30,
                "slots": [],
            }

        # ⭐ safe schedule read
        schedule = service.get("working_schedule") or {}

        weekday = datetime.strptime(date, "%Y-%m-%d").strftime("%a")
        day_schedule = schedule.get(weekday)

        if not day_schedule or day_schedule.get("closed"):
            slots = []
        else:
            start = _parse_time_12h(day_schedule["from"])
            end = _parse_time_12h(day_schedule["to"])

            slots = []
            current = start

            while current < end:
                slots.append({
                    "time": current.strftime("%H:%M"),
                    "status": "available"
                })
                current += timedelta(minutes=30)

        doc = {
            "provider_id": provider_id,
            "date": date,
            "slot_size": 30,
            "slots": slots,
            "created_at": datetime.now(IST).replace(microsecond=0).isoformat(),
            "updated_at": datetime.now(IST).replace(microsecond=0).isoformat(),
        }

        ref.set(doc)
        return doc

    except Exception as e:
        logger.exception("CRASH in get_or_create_availability")
        raise e


def _generate_slot_times(start_time: str, duration_min: int):
    slots = []
    t = datetime.strptime(start_time, "%H:%M")
    for _ in range(0, duration_min, 30):
        slots.append(t.strftime("%H:%M"))
        t += timedelta(minutes=30)
    return slots


def check_slot_available(provider_id: str, date: str, start_time: str, duration: int):
    doc = get_or_create_availability(provider_id, date)
    slot_times = _generate_slot_times(start_time, duration)

    for s in doc["slots"]:
        if s["time"] in slot_times and s["status"] != "available":
            return False

    return True


def lock_slots_after_booking(provider_id: str, date: str, start_time: str, duration: int):
    doc = get_or_create_availability(provider_id, date)
    slot_times = _generate_slot_times(start_time, duration)

    slots = {s["time"]: s for s in doc["slots"]}

    for t in slot_times:
        if t in slots:
            slots[t]["status"] = "booked"

    db.collection(COLL_AVAILABILITY).document(
        _availability_doc_id(provider_id, date)
    ).update({
        "slots": list(slots.values()),
        "updated_at": datetime.now(IST).replace(microsecond=0).isoformat(),
    })


def create_confirmed_booking_from_pending(pending_doc: Dict[str, Any]):
    booking_id = _id()

    available = check_slot_available(
        pending_doc["provider_id"],
        pending_doc["slot_date"],
        pending_doc["slot_time"],
        pending_doc["duration"]
    )

    if not available:
        raise ValueError("Slot already booked")

    total_paid = float(pending_doc["amount"])

    commission = round(total_paid * 0.10, 2)

    doc = {
        "provider_id": pending_doc["provider_id"],
        "requester_id": pending_doc["requester_id"],
        "service_id": pending_doc["service_id"],

        "slot_date": pending_doc["slot_date"],
        "slot_time": pending_doc["slot_time"],
        "duration": pending_doc["duration"],

        "amount_paid": total_paid,
        "service_cost": pending_doc.get("service_cost"),
        "platform_fee": pending_doc.get("platform_fee"),
        "tax": pending_doc.get("tax"),
        "pricing_type": pending_doc.get("pricing_type"),
        "payment_method": pending_doc.get("payment_method", "wallet"),
        "status": "confirmed",
        "commission": commission,

        "created_at": datetime.now(IST).replace(microsecond=0).isoformat(),
        "updated_at": datetime.now(IST).replace(microsecond=0).isoformat(),
    }

    db.collection(COLL_BOOKINGS).document(booking_id).set(doc)

    lock_slots_after_booking(
        pending_doc["provider_id"],
        pending_doc["slot_date"],
        pending_doc["slot_time"],
        pending_doc["duration"]
    )

    return {"id": booking_id, **doc}


def soft_delete_provider_service(service_id: str):
    db.collection(COLL_PROVIDER_SERVICES).document(service_id).update({
        "is_deleted": True,
        "updated_at": datetime.now(IST).replace(microsecond=0).isoformat()
    })


def update_slots(provider_id: str, date: str, updates: List[Dict[str, str]]):
    doc = get_or_create_availability(provider_id, date)
    slots = {s["time"]: s for s in doc["slots"]}

    for u in updates:
        if u["time"] in slots:
            slots[u["time"]]["status"] = u["status"]

    db.collection(COLL_AVAILABILITY).document(
        _availability_doc_id(provider_id, date)
    ).update({
        "slots": list(slots.values()),
        "updated_at": datetime.now(IST).replace(microsecond=0).isoformat(),
    })


def provider_bookings(provider_id: str, status: str):
    from datetime import datetime

    docs = (
        db.collection("service_bookings")
        .where("provider_id", "==", provider_id)
        .stream()
    )

    today = datetime.utcnow().date()
    result = []
    dedupe = {}

    for d in docs:
        b = d.to_dict()
        booking_id = d.id

        if b.get("is_active") is False:
            continue

        if b.get("payment_status") != "paid":
            continue

        slot_date = b.get("slot_date")
        slot_time = b.get("slot_time")
        if not slot_date or not slot_time:
            continue

        booking_status = b.get("status", "incoming")
        slot_dt = datetime.fromisoformat(slot_date).date()

        # ───────── TAB FILTER ─────────

        if status == "confirmed":
            if booking_status not in ["incoming", "confirmed"]:
                continue

        elif status == "upcoming":
            if slot_dt < today:
                continue

        elif status == "completed":
            if booking_status != "completed":
                continue

        elif status == "rejected":
            if booking_status != "rejected":
                continue

        # ⭐ provider earning only
        provider_amount = (
                b.get("provider_earning")
                or b.get("service_price")
                or b.get("total_cost")
        )

        if not provider_amount:
            continue  # remove 0 entries

        # ───────── DEDUPE KEY ─────────
        key = (
            b.get("provider_id"),
            b.get("requester_id"),
            b.get("service_id"),
            slot_date,
            slot_time,
        )

        existing = dedupe.get(key)

        # keep only ONE booking per request
        # choose the higher earning (parent record)
        if existing:
            if provider_amount > existing["amount"]:
                dedupe[key] = {
                    "doc": d,
                    "data": b,
                    "amount": provider_amount
                }
        else:
            dedupe[key] = {
                "doc": d,
                "data": b,
                "amount": provider_amount
            }

    # ───────── BUILD FINAL RESPONSE ─────────

    for item in dedupe.values():
        d = item["doc"]
        b = item["data"]
        booking_id = d.id
        provider_amount = item["amount"]

        # SERVICE
        svc_doc = db.collection("provider_services").document(b["service_id"]).get()
        service_data = svc_doc.to_dict() if svc_doc.exists else {}

        # CUSTOMER
        user_doc = db.collection("service_providers").document(b["requester_id"]).get()
        user_data = user_doc.to_dict() if user_doc.exists else {}

        result.append({
            "id": booking_id,
            "service_title": service_data.get("title", "Service"),
            "customer_name": user_data.get("name", "Unknown"),
            "customer_phone": user_data.get("mobile", ""),
            "slot_date": b.get("slot_date"),
            "slot_time": b.get("slot_time"),
            "status": b.get("status", "incoming"),
            "amount": provider_amount,
            "payment_status": b.get("payment_status"),
        })

    result.sort(
        key=lambda x: (
            x.get("slot_date") or "",
            x.get("slot_time") or ""
        )
    )

    return result


def get_user(user_id: str):
    try:
        doc = db.collection("service_providers").document(user_id).get()
        return doc.to_dict() if doc.exists else {}
    except Exception as e:
        logger.info(f"User Not found: {str(e)}")
        return {}



def create_booking(payload: Dict[str, Any]) -> Dict[str, Any]:
    if payload["provider_id"] == payload["requester_id"]:
        raise ValueError("You cannot book your own service")

    booking_id = _id()

    svc_doc = db.collection(COLL_PROVIDER_SERVICES).document(payload["service_id"]).get()
    svc = svc_doc.to_dict() if svc_doc.exists else {}

    user_doc = db.collection("service_providers").document(payload["requester_id"]).get()
    user = user_doc.to_dict() if user_doc.exists else {}

    duration = int(payload.get("duration", 60))

    available = check_slot_available(
        payload["provider_id"],
        payload["slot_date"],
        payload["slot_time"],
        duration
    )

    if not available:
        raise ValueError("Selected slot not available anymore")

    # pricing engine
    service_price = calculate_service_cost(svc, duration)
    platform_fee = round(service_price * 0.05, 2)
    tax = round((service_price + platform_fee) * 0.18, 2)
    final_total = round(service_price + platform_fee + tax, 2)

    provider_earning = service_price
    platform_earning = round(final_total - provider_earning, 2)

    doc = {
        "provider_id": payload["provider_id"],
        "requester_id": payload["requester_id"],
        "service_id": payload["service_id"],

        "service_title": svc.get("title", "Service"),
        "customer_name": user.get("name", "Unknown"),
        "customer_phone": user.get("mobile", ""),

        "slot_date": payload["slot_date"],
        "slot_time": payload["slot_time"],
        "duration": duration,
        "pricing_type": svc.get("pricing_type"),

        "service_price": service_price,
        "provider_earning": provider_earning,
        "platform_fee": platform_fee,
        "tax": tax,
        "final_total": final_total,
        "platform_earning": platform_earning,

        "payment_status": "paid",
        "payment_method": payload.get("payment_method", "wallet"),

        "status": "confirmed",

        "created_at": datetime.now(IST).replace(microsecond=0).isoformat(),
        "updated_at": datetime.now(IST).replace(microsecond=0).isoformat(),
    }

    logger.info(f"DATA-PAYLOAD : {doc}")

    # 🔹 SAVE BOOKING
    db.collection("service_bookings").document(booking_id).set(doc)

    # 🔹 LOCK SLOTS
    lock_slots_after_booking(
        payload["provider_id"],
        payload["slot_date"],
        payload["slot_time"],
        duration
    )

    # 🟢 CREATE CHAT FOR THIS BOOKING
    create_chat_for_booking(
        booking_id,
        payload["provider_id"],
        payload["requester_id"]
    )

    # 🚫 NO WALLET CREDIT HERE (credit only after completion)

    return {"id": booking_id, **doc}



def booking_detail(booking_id: str) -> Dict[str, Any]:
    snap = db.collection(COLL_BOOKINGS).document(booking_id).get()
    if not snap.exists:
        raise ValueError("Booking not found")

    b = snap.to_dict()
    logger.info(f"booking data : {b}")
    b["id"] = booking_id

    # ───────── SERVICE INFO ─────────
    svc_doc = db.collection("provider_services").document(b["service_id"]).get()
    if svc_doc.exists:
        svc = svc_doc.to_dict()
        b["service_title"] = svc.get("title", "Service")

    # ───────── CUSTOMER INFO ─────────
    user_doc = db.collection("service_providers").document(b["requester_id"]).get()
    if user_doc.exists:
        user = user_doc.to_dict()
        b["customer_name"] = user.get("name", "Customer")
        b["customer_phone"] = user.get("mobile", "")

    # ───────── PROVIDER PRICE LOGIC (IMPORTANT FIX) ─────────

    provider_amount = (
            b.get("provider_earning")
            or b.get("service_price")
            or b.get("total_cost")
            or b.get("amount")
            or 0
    )

    # provider should NOT see platform fee or tax
    b["total_cost"] = provider_amount
    b["discount"] = 0
    b["commission"] = 0
    b["payment_status"] = b.get("payment_status") or "unpaid"

    return b


def debit_provider_wallet(provider_id, amount, booking_id=None):
    ref = db.collection(COLL_SERVICE_WALLETS).document(provider_id)
    snap = ref.get()

    balance = snap.to_dict().get("balance", 0) if snap.exists else 0

    new_balance = max(balance - amount, 0)

    ref.set({
        "balance": new_balance,
        "updated_at": datetime.now(IST).replace(microsecond=0).isoformat()
    }, merge=True)

    db.collection(COLL_SERVICE_WALLET_TX).add({
        "user_id": provider_id,
        "type": "refund_debit",
        "amount": amount,
        "booking_id": booking_id,
        "created_at": datetime.now(IST).replace(microsecond=0).isoformat()
    })


def initiate_refund(booking):
    try:
        payment_method = booking.get("payment_method", "wallet")

        if payment_method == "razorpay":
            refund_razorpay_payment(booking)

        elif payment_method == "wallet":
            refund_wallet_payment(booking)

        else:
            logger.info("Unknown payment method — refund skipped")

    except Exception as e:
        logger.exception("REFUND CRASH")


def refund_razorpay_payment(booking):
    payment_id = booking.get("razorpay_payment_id")

    if not payment_id:
        raise Exception("Missing Razorpay payment ID")

    customer_refund_amount = float(
        booking.get("final_total")
        or booking.get("amount_paid")
        or 0
    )

    provider_debit_amount = float(
        booking.get("provider_earning")
        or booking.get("service_price")
        or 0
    )

    refund = razorpay_client.payment.refund(payment_id, {
        "amount": int(customer_refund_amount * 100),
        "speed": "optimum",
        "notes": {
            "booking_id": booking["id"],
            "reason": "provider_rejected"
        }
    })

    booking["refund_status"] = "initiated"
    booking["refund_id"] = refund["id"]

    # debit ONLY provider earning
    debit_provider_wallet(
        booking["provider_id"],
        provider_debit_amount,
        booking["id"]
    )

    logger.info(f"Razorpay refund started: {refund['id']}")


def refund_wallet_payment(booking):
    user_id = booking.get("requester_id")

    customer_refund_amount = float(
        booking.get("final_total")
        or booking.get("amount_paid")
        or 0
    )

    provider_debit_amount = float(
        booking.get("provider_earning")
        or booking.get("service_price")
        or 0
    )

    wallet_ref = db.collection(COLL_SERVICE_WALLETS).document(user_id)
    snap = wallet_ref.get()

    IST = timezone(timedelta(hours=5, minutes=30))
    now = datetime.now(IST).replace(microsecond=0).isoformat()

    if not snap.exists:
        wallet_ref.set({
            "balance": customer_refund_amount,
            "updated_at": now
        })
    else:
        balance = snap.to_dict().get("balance", 0)
        wallet_ref.update({
            "balance": balance + customer_refund_amount,
            "updated_at": now
        })

    db.collection(COLL_SERVICE_WALLET_TX).add({
        "user_id": user_id,
        "type": "refund",
        "amount": customer_refund_amount,
        "booking_id": booking["id"],
        "created_at": now
    })

    # debit provider wallet ONLY earning
    debit_provider_wallet(
        booking["provider_id"],
        provider_debit_amount,
        booking["id"]
    )

    logger.info("Wallet refund completed")


def get_provider_name(provider_id: str):
    doc = db.collection("service_providers").document(provider_id).get()
    return doc.to_dict().get("name") if doc.exists else "Provider"


def get_provider_location(provider_id: str):
    doc = db.collection("service_providers").document(provider_id).get()
    return doc.to_dict().get("location") if doc.exists else ""


def get_provider_photo(provider_id: str):
    doc = db.collection("service_providers").document(provider_id).get()
    return doc.to_dict().get("photo_base64") if doc.exists else None


def mark_missed_bookings():
    now = datetime.utcnow()

    docs = db.collection("service_bookings") \
        .where("status", "==", "incoming") \
        .stream()

    for d in docs:
        b = d.to_dict()
        slot_date = b.get("slot_date")
        slot_time = b.get("slot_time")

        if not slot_date or not slot_time:
            continue

        dt = datetime.fromisoformat(slot_date)

        # slot expired more than 30 mins
        if now > dt + timedelta(minutes=30):
            d.reference.update({
                "status": "missed",
                "updated_at": now.isoformat()
            })


def mark_urgent_bookings():
    now = datetime.utcnow()

    docs = db.collection("service_bookings") \
        .where("status", "==", "incoming") \
        .stream()

    for d in docs:
        b = d.to_dict()
        slot_date = b.get("slot_date")

        if not slot_date:
            continue

        dt = datetime.fromisoformat(slot_date)
        diff = (dt - now).total_seconds() / 60

        urgent = diff > 0 and diff <= 120

        d.reference.update({
            "is_urgent": urgent
        })


def accept_booking(booking_id, provider_id):
    ref = db.collection("service_bookings").document(booking_id)
    booking = ref.get().to_dict()

    ref.update({
        "status": "accepted",
        "updated_at": datetime.now(IST).replace(microsecond=0).isoformat()
    })

    # lock slot
    db.collection("provider_availability").document(
        f"{provider_id}_{booking['slot_date']}_{booking['slot_time']}"
    ).update({
        "status": "locked"
    })


def calculate_daily_earnings():
    today = datetime.utcnow().date()

    docs = db.collection("service_bookings") \
        .where("status", "==", "completed") \
        .stream()

    earnings = {}

    for d in docs:
        b = d.to_dict()
        provider = b["provider_id"]
        amount = b.get("total_cost", 0)

        earnings.setdefault(provider, 0)
        earnings[provider] += amount

    for provider, total in earnings.items():
        db.collection("provider_earnings").document(provider).set({
            "daily_total": total,
            "updated_at": datetime.now(IST).replace(microsecond=0).isoformat()
        }, merge=True)



def release_locked_slots(provider_id: str, date: str, start_time: str, duration: int):
    doc = get_or_create_availability(provider_id, date)

    slot_times = _generate_slot_times(start_time, duration)
    slots = {s["time"]: s for s in doc["slots"]}

    for t in slot_times:
        if t in slots:
            slots[t]["status"] = "available"

    db.collection(COLL_AVAILABILITY).document(
        _availability_doc_id(provider_id, date)
    ).update({
        "slots": list(slots.values()),
        "updated_at": datetime.now(IST).replace(microsecond=0).isoformat(),
    })


def credit_provider_wallet(provider_id, amount, booking_id=None):
    # 🔴 SAFETY: prevent wrong credits
    if amount is None or amount <= 0:
        return

    ref = db.collection(COLL_SERVICE_WALLETS).document(provider_id)
    snap = ref.get()

    balance = snap.to_dict().get("balance", 0) if snap.exists else 0

    IST = timezone(timedelta(hours=5, minutes=30))
    time_of_update = datetime.now(IST).replace(microsecond=0).isoformat()

    # update wallet
    ref.set({
        "balance": balance + amount,
        "updated_at": time_of_update
    }, merge=True)

    # transaction log
    db.collection(COLL_SERVICE_WALLET_TX).add({
        "user_id": provider_id,
        "type": "service_income",
        "amount": amount,
        "booking_id": booking_id,
        "created_at": time_of_update
    })


def provider_earnings_dashboard(provider_id: str):



    docs = db.collection("service_bookings") \
        .where("provider_id", "==", provider_id) \
        .stream()

    today = datetime.utcnow().date()
    week_start = today - timedelta(days=7)
    month_start = today.replace(day=1)

    # ───────── METRICS ─────────

    today_total = 0
    week_total = 0
    month_total = 0
    lifetime_total = 0

    completed_jobs = 0
    refund_total = 0
    platform_total = 0
    tax_total = 0

    daily_chart = {}
    weekly_chart = {}
    category_map = {}

    highest_day = {"date": None, "amount": 0}

    for d in docs:
        b = d.to_dict()

        if b.get("status") != "completed":
            continue

        earning = (
                b.get("provider_earning")
                or b.get("service_price")
                or 0
        )

        if earning <= 0:
            continue

        completed_jobs += 1
        lifetime_total += earning

        platform_total += b.get("platform_fee", 0)
        tax_total += b.get("tax", 0)

        slot_date = b.get("slot_date")
        if not slot_date:
            continue

        dt = datetime.fromisoformat(slot_date).date()

        # TODAY
        if dt == today:
            today_total += earning

        # WEEK
        if dt >= week_start:
            week_total += earning

        # MONTH
        if dt >= month_start:
            month_total += earning

        # DAILY CHART
        daily_chart.setdefault(slot_date, 0)
        daily_chart[slot_date] += earning

        # WEEKLY CHART
        week_day = calendar.day_name[dt.weekday()]
        weekly_chart.setdefault(week_day, 0)
        weekly_chart[week_day] += earning

        # CATEGORY
        cat = b.get("service_title", "Other")
        category_map.setdefault(cat, 0)
        category_map[cat] += earning

        # HIGHEST DAY
        if daily_chart[slot_date] > highest_day["amount"]:
            highest_day = {
                "date": slot_date,
                "amount": daily_chart[slot_date]
            }

    avg_per_job = lifetime_total / completed_jobs if completed_jobs else 0

    return {
        "cards": {
            "today": round(today_total, 2),
            "week": round(week_total, 2),
            "month": round(month_total, 2),
            "lifetime": round(lifetime_total, 2),
        },

        "stats": {
            "completed_jobs": completed_jobs,
            "avg_per_job": round(avg_per_job, 2),
            "highest_day": highest_day,
        },

        "financial": {
            "gross_earnings": round(lifetime_total, 2),
            "platform_fee": round(platform_total, 2),
            "tax": round(tax_total, 2),
            "refund_loss": round(refund_total, 2),
            "net_payout": round(lifetime_total, 2)
        },

        "charts": {
            "daily": daily_chart,
            "weekly": weekly_chart,
            "category": category_map
        }
    }


def create_chat_for_booking(booking_id, provider_id, requester_id):
    chat_ref = db.collection("service_chats").document(booking_id)

    if chat_ref.get().exists:
        return

    chat_ref.set({
        "provider_id": provider_id,
        "requester_id": requester_id,
        "last_message": "",
        "last_sender": "",
        "last_time": datetime.now(IST).isoformat(),
        "unread_provider": 0,
        "unread_requester": 0,
        "created_at": datetime.now(IST).isoformat()
    })

def customer_bookings(requester_id):
    docs = db.collection("service_bookings") \
        .where("requester_id", "==", requester_id).stream()

    result = []
    for d in docs:
        b = d.to_dict()
        b["id"] = d.id
        result.append(b)

    return result

