import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from werkzeug.security import generate_password_hash, check_password_hash

# ✅ Use your existing firebase_db.py connection
# Example: firebase_db.db is Firestore client
import firebase_db


db = firebase_db.db

# ✅ REQUIRED COLLECTIONS
COLL_PROVIDERS = "service_providers"
COLL_PROVIDER_SERVICES = "provider_services"
COLL_AVAILABILITY = "provider_availability"
COLL_BOOKINGS = "service_bookings"
COLL_EARNINGS = "provider_earnings"
COLL_REVIEWS = "provider_reviews"


def _id() -> str:
    return uuid.uuid4().hex


# ==========================
# ✅ PROVIDERS AUTH
# ==========================

def provider_by_email(email: str):
    q = (
        db.collection(COLL_PROVIDERS)
        .where("email", "==", email)
        .limit(1)
        .stream()
    )

    for doc in q:
        data = doc.to_dict()
        data["uid"] = doc.id   # ✅ CRITICAL FIX
        return data

    return None


# def create_provider(payload: Dict[str, Any]) -> Dict[str, Any]:
#     existing = provider_by_email(payload["email"])
#     if existing:
#         raise ValueError("Email already registered")
#
#     uid = _id()
#     password_hash = generate_password_hash(payload["password"])
#
#     # ✅ SAFE DEFAULTS
#     service_category_ids = payload.get("service_category_ids", [])
#     bank = payload.get("bank")
#     working_schedule = payload.get("working_schedule")
#
#     doc = {
#         "role": payload.get("role", "provider"),  # provider / requester
#         "name": payload["name"],
#         "mobile": payload["mobile"],
#         "email": payload["email"],
#         "password_hash": password_hash,
#
#         # ✅ MULTI SERVICE (OPTIONAL)
#         "service_category_ids": service_category_ids,
#
#         # ✅ OPTIONAL FIELDS
#         "location": payload.get("location"),
#         "photo_base64": payload.get("photo_base64"),
#
#         "bank": bank,  # may be None
#
#         # ✅ OPTIONAL SCHEDULE
#         "working_schedule": working_schedule,  # may be None
#
#         # system / limits
#         "cancel_count": 0,
#         "blocked_until": None,
#
#         "created_at": datetime.utcnow().isoformat(),
#         "updated_at": datetime.utcnow().isoformat(),
#     }
#
#     db.collection(COLL_PROVIDERS).document(uid).set(doc)
#
#     return {
#         "uid": uid,
#         "role": doc["role"],
#         "name": doc["name"],
#         "mobile": doc["mobile"],
#         "email": doc["email"],
#         "service_category_ids": doc["service_category_ids"],
#         "location": doc["location"],
#     }
def create_provider(payload: Dict[str, Any]) -> Dict[str, Any]:
    existing = provider_by_email(payload["email"])
    if existing:
        raise ValueError("Email already registered")

    uid = _id()
    password_hash = generate_password_hash(payload["password"])

    service_category_ids = payload.get("service_category_ids", [])

    doc = {
        "role": payload.get("role", "provider"),
        "name": payload["name"],
        "mobile": payload["mobile"],
        "email": payload["email"],
        "password_hash": password_hash,

        "service_category_ids": service_category_ids,
        "location": payload.get("location"),
        "photo_base64": payload.get("photo_base64"),

        "bank": payload.get("bank"),
        "working_schedule": payload.get("working_schedule"),

        "cancel_count": 0,
        "blocked_until": None,
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
    }

    # ✅ Save provider
    db.collection(COLL_PROVIDERS).document(uid).set(doc)

    # ✅ AUTO-CREATE SERVICES (THIS IS THE FIX)
    for cid in service_category_ids:
        db.collection(COLL_PROVIDER_SERVICES).document(_id()).set({
            "provider_id": uid,
            "service_category_id": cid,
            "title": cid.replace("_", " ").title(),
            "description": "",
            "fixed_price": 0,
            "pricing_unit": "fixed",
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
        })

    return {
        "uid": uid,
        "role": doc["role"],
        "name": doc["name"],
        "email": doc["email"],
        "mobile": doc["mobile"],
        "service_category_ids": service_category_ids,
        "location": doc["location"],
    }


def login_provider(email: str, password: str) -> Dict[str, Any]:
    u = provider_by_email(email)
    if not u:
        raise ValueError("Invalid email/password")

    blocked_until = u.get("blocked_until")
    if blocked_until:
        if datetime.utcnow() < datetime.fromisoformat(blocked_until):
            raise ValueError(f"Account blocked until {blocked_until}")

    if not check_password_hash(u.get("password_hash", ""), password):
        raise ValueError("Invalid email/password")

    return {
        "uid": u["uid"],
        "role": u.get("role", "provider"),
        "name": u.get("name", ""),
        "email": u.get("email", ""),
        "mobile": u.get("mobile", ""),
        "location": u.get("location", ""),

        # ✅ NEW
        "service_category_ids": u.get("service_category_ids", []),

        # 🛡️ backward compatibility (optional)
        "service_category_id": (
            u.get("service_category_ids", [None])[0]
            if u.get("service_category_ids")
            else None
        ),
    }



def update_password(email: str, new_password: str) -> None:
    u = provider_by_email(email)
    if not u:
        raise ValueError("User not found")
    uid = u["uid"]
    db.collection(COLL_PROVIDERS).document(uid).update({
        "password_hash": generate_password_hash(new_password),
        "updated_at": datetime.utcnow().isoformat()
    })


# def upsert_provider_service(payload: Dict[str, Any]) -> Dict[str, Any]:
#     sid = payload.get("id") or _id()
#
#     doc = {
#         "provider_id": payload["provider_id"],
#         "service_category_id": payload["service_category_id"],
#         "title": payload["title"],
#         "description": payload.get("description", ""),
#         "fixed_price": float(payload.get("fixed_price", 0)),
#         "pricing_unit": payload.get("pricing_unit", "fixed"),
#         "min_price": payload.get("min_price"),
#         "is_active": payload.get("is_active", True),
#         "is_deleted": payload.get("is_deleted", False),  # ✅ NEW
#         "updated_at": datetime.utcnow().isoformat(),
#         "created_at": payload.get("created_at") or datetime.utcnow().isoformat(),
#     }
#
#     db.collection(COLL_PROVIDER_SERVICES).document(sid).set(doc, merge=True)
#     return {"id": sid, **doc}
def upsert_provider_service(payload: Dict[str, Any]) -> Dict[str, Any]:
    sid = payload.get("id") or _id()

    doc = {
        "provider_id": payload["provider_id"],
        "service_category_id": payload["service_category_id"],
        "title": payload["title"],
        "description": payload.get("description", ""),
        "fixed_price": float(payload.get("fixed_price", 0)),
        "pricing_unit": payload.get("pricing_unit", "fixed"),
        "min_price": payload.get("min_price"),
        "is_active": payload.get("is_active", True),
        "is_deleted": payload.get("is_deleted", False),
        "updated_at": datetime.utcnow().isoformat(),
        "created_at": payload.get("created_at") or datetime.utcnow().isoformat(),
    }

    # ✅ SAFE: only update if provided
    if "working_schedule" in payload:
        doc["working_schedule"] = normalize_schedule(
            payload.get("working_schedule", {})
        )

    db.collection(COLL_PROVIDER_SERVICES).document(sid).set(doc, merge=True)

    return {"id": sid, **doc}




def get_provider_services(provider_id: str):
    q = (
        db.collection(COLL_PROVIDER_SERVICES)
        .where("provider_id", "==", provider_id)
        .where("is_deleted", "==", False)
        .stream()
    )

    services = []
    for doc in q:
        d = doc.to_dict()
        d["id"] = doc.id

        # ✅ NORMALIZE OLD DATA
        if "is_active" not in d:
            d["is_active"] = True

        services.append(d)

    return services



def get_provider_service(service_id: str) -> Dict[str, Any]:
    snap = db.collection(COLL_PROVIDER_SERVICES).document(service_id).get()
    if not snap.exists:
        raise ValueError("Service not found")
    d = snap.to_dict()
    d["id"] = service_id
    return d


# ==========================
# ✅ AVAILABILITY (SLOTS)
# ==========================
def _availability_doc_id(provider_id: str, date: str) -> str:
    return f"{provider_id}:{date}"


def get_provider(provider_id: str) -> Dict[str, Any]:
    snap = db.collection(COLL_PROVIDERS).document(provider_id).get()
    if not snap.exists:
        raise ValueError("Provider not found")
    d = snap.to_dict()
    d["uid"] = provider_id
    return d


def get_or_create_availability(provider_id: str, date: str) -> Dict[str, Any]:
    doc_id = _availability_doc_id(provider_id, date)
    ref = db.collection(COLL_AVAILABILITY).document(doc_id)
    snap = ref.get()

    if snap.exists:
        return snap.to_dict()

    p = get_provider(provider_id)
    slot_size = int(p.get("slot_size", 30))
    hours = p.get("working_hours", {"from": "09:00", "to": "18:00"})

    start_h, start_m = [int(x) for x in hours["from"].split(":")]
    end_h, end_m = [int(x) for x in hours["to"].split(":")]

    start = start_h * 60 + start_m
    end = end_h * 60 + end_m

    slots = []
    t = start
    while t + slot_size <= end:
        hh = str(t // 60).zfill(2)
        mm = str(t % 60).zfill(2)
        slots.append({"time": f"{hh}:{mm}", "status": "available"})
        t += slot_size

    doc = {
        "provider_id": provider_id,
        "date": date,
        "slot_size": slot_size,
        "slots": slots,
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
    }
    ref.set(doc)
    return doc


def update_slots(provider_id: str, date: str, updates: List[Dict[str, str]]) -> None:
    doc = get_or_create_availability(provider_id, date)
    slots = doc.get("slots", [])
    slot_map = {s["time"]: s for s in slots}

    for u in updates:
        time = u.get("time")
        new_status = u.get("status")
        if not time or not new_status:
            continue
        if time not in slot_map:
            continue

        current = slot_map[time].get("status", "available")
        # ✅ booked/locked cannot be edited manually
        if current in ["booked", "locked"]:
            continue

        # allow toggle between available/unavailable
        slot_map[time]["status"] = new_status

    new_slots = [slot_map[s["time"]] for s in slots]

    doc_id = _availability_doc_id(provider_id, date)
    db.collection(COLL_AVAILABILITY).document(doc_id).update({
        "slots": new_slots,
        "updated_at": datetime.utcnow().isoformat(),
    })


def _set_slot_status(provider_id: str, date: str, time: str, status: str) -> None:
    doc = get_or_create_availability(provider_id, date)
    slots = doc.get("slots", [])
    for s in slots:
        if s["time"] == time:
            s["status"] = status
            break
    doc_id = _availability_doc_id(provider_id, date)
    db.collection(COLL_AVAILABILITY).document(doc_id).update({
        "slots": slots,
        "updated_at": datetime.utcnow().isoformat()
    })


# ==========================
# ✅ BOOKINGS + RULES
# ==========================
def create_booking(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Requester creates booking request.
    Provider cannot change price after accept.
    """
    booking_id = _id()

    svc = get_provider_service(payload["service_id"])
    fixed_price = float(svc.get("fixed_price", 0))

    # ✅ Commission calculation (example 10%)
    commission = round(fixed_price * 0.10, 2)
    discount = float(payload.get("discount", 0))
    total = max(fixed_price - discount, 0.0)

    doc = {
        "provider_id": payload["provider_id"],
        "requester_id": payload["requester_id"],
        "service_id": payload["service_id"],
        "slot_date": payload["slot_date"],
        "slot_time": payload["slot_time"],

        "status": "incoming",
        "reject_reason": None,

        "total_cost": total,
        "commission": commission,
        "discount": discount,

        "refund_initiated": False,
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
    }

    db.collection(COLL_BOOKINGS).document(booking_id).set(doc)
    return {"id": booking_id, **doc}


def booking_detail(booking_id: str) -> Dict[str, Any]:
    snap = db.collection(COLL_BOOKINGS).document(booking_id).get()
    if not snap.exists:
        raise ValueError("Booking not found")
    d = snap.to_dict()
    d["id"] = booking_id
    return d


def provider_bookings(provider_id: str, group: str) -> List[Dict[str, Any]]:
    """
    Tabs:
    incoming, upcoming, completed, rejected/cancelled
    """
    stream = db.collection(COLL_BOOKINGS).where("provider_id", "==", provider_id).stream()
    items = []
    for doc in stream:
        d = doc.to_dict()
        d["id"] = doc.id
        items.append(d)

    def in_group(st: str) -> bool:
        if group == "incoming":
            return st == "incoming"
        if group == "upcoming":
            return st in ["accepted"]
        if group == "completed":
            return st == "completed"
        if group == "rejected":
            return st in ["rejected", "cancelled"]
        return False

    out = [x for x in items if in_group(x.get("status", "incoming"))]
    out.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return out


def accept_booking(booking_id: str, provider_id: str) -> None:
    b = booking_detail(booking_id)

    if b["provider_id"] != provider_id:
        raise ValueError("Unauthorized")
    if b["status"] != "incoming":
        raise ValueError("Only incoming booking can be accepted")

    # ✅ Accept -> Slot locked
    _set_slot_status(provider_id, b["slot_date"], b["slot_time"], "locked")

    db.collection(COLL_BOOKINGS).document(booking_id).update({
        "status": "accepted",
        "accepted_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
    })

    # ✅ Notification hook (use your existing notification system)
    # send_notification_to_user(b["requester_id"], "Booking Accepted", "...")



def reject_booking(booking_id: str, provider_id: str, reason: str) -> None:
    b = booking_detail(booking_id)

    if b["provider_id"] != provider_id:
        raise ValueError("Unauthorized")
    if b["status"] != "incoming":
        raise ValueError("Only incoming booking can be rejected")
    if not reason.strip():
        raise ValueError("Reason required")

    # ✅ Reject -> refund triggered (do not expose wallet)
    _set_slot_status(provider_id, b["slot_date"], b["slot_time"], "rejected")

    db.collection(COLL_BOOKINGS).document(booking_id).update({
        "status": "rejected",
        "reject_reason": reason,
        "refund_initiated": True,
        "rejected_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
    })

    # ✅ cancellation counter + block logic
    prov_ref = db.collection(COLL_PROVIDERS).document(provider_id)
    prov = prov_ref.get().to_dict()

    cancel_count = int(prov.get("cancel_count", 0)) + 1
    updates = {
        "cancel_count": cancel_count,
        "updated_at": datetime.utcnow().isoformat()
    }

    # Example rule:
    # 5 rejections -> block 3 days
    if cancel_count >= 5:
        updates["blocked_until"] = (datetime.utcnow() + timedelta(days=3)).isoformat()

    prov_ref.update(updates)

    # ✅ Notification hook
    # send_notification_to_user(b["requester_id"], "Booking Rejected", reason)



def start_service(booking_id: str, provider_id: str) -> None:
    b = booking_detail(booking_id)
    if b["provider_id"] != provider_id:
        raise ValueError("Unauthorized")
    if b["status"] != "accepted":
        raise ValueError("Service can start only after accepted")

    # locked -> booked when started
    _set_slot_status(provider_id, b["slot_date"], b["slot_time"], "booked")

    db.collection(COLL_BOOKINGS).document(booking_id).update({
        "status": "started",
        "started_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
    })


def complete_service(booking_id: str, provider_id: str) -> None:
    b = booking_detail(booking_id)
    if b["provider_id"] != provider_id:
        raise ValueError("Unauthorized")
    if b["status"] != "started":
        raise ValueError("Complete allowed only after started")

    db.collection(COLL_BOOKINGS).document(booking_id).update({
        "status": "completed",
        "completed_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
    })

    # ✅ Earnings record
    earn_id = _id()

    provider_earning = float(b.get("total_cost", 0)) - float(b.get("commission", 0))
    provider_earning = max(provider_earning, 0)

    db.collection(COLL_EARNINGS).document(earn_id).set({
        "provider_id": provider_id,
        "booking_id": booking_id,
        "amount": round(provider_earning, 2),
        "commission": float(b.get("commission", 0)),
        "total_cost": float(b.get("total_cost", 0)),
        "discount": float(b.get("discount", 0)),
        "status": "pending",
        "payout_cycle": "weekly",
        "created_at": datetime.utcnow().isoformat(),
    })


# ==========================
# ✅ EARNINGS
# ==========================
def earnings_summary(provider_id: str) -> Dict[str, Any]:
    completed = provider_bookings(provider_id, "completed")
    incoming = provider_bookings(provider_id, "incoming")

    stream = db.collection(COLL_EARNINGS).where("provider_id", "==", provider_id).stream()

    pending_amount = 0.0
    paid_total = 0.0
    completed_jobs = len(completed)

    for doc in stream:
        d = doc.to_dict()
        amt = float(d.get("amount", 0))
        if d.get("status") == "paid":
            paid_total += amt
        else:
            pending_amount += amt

    return {
        "provider_id": provider_id,
        "completed_jobs": completed_jobs,
        "incoming_count": len(incoming),
        "pending_amount": round(pending_amount, 2),
        "paid_total": round(paid_total, 2),
        "payout_mode": "weekly",
    }


# ==========================
# ✅ RATINGS (READONLY)
# ==========================
def ratings(provider_id: str) -> Dict[str, Any]:
    stream = db.collection(COLL_REVIEWS).where("provider_id", "==", provider_id).stream()
    items = []
    total = 0.0
    count = 0

    for doc in stream:
        d = doc.to_dict()
        d["id"] = doc.id
        items.append(d)
        total += float(d.get("rating", 0))
        count += 1

    overall = round(total / count, 2) if count else 0.0
    items.sort(key=lambda x: x.get("created_at", ""), reverse=True)

    return {"overall_rating": overall, "reviews": items}


def soft_delete_provider_service(service_id: str) -> None:
    ref = db.collection(COLL_PROVIDER_SERVICES).document(service_id)
    snap = ref.get()

    if not snap.exists:
        raise ValueError("Service not found")

    ref.set(
        {
            "is_deleted": True,
            "updated_at": datetime.utcnow().isoformat(),
        },
        merge=True,
    )


def normalize_time(t: str | None):
    if not t:
        return None

    t = t.strip().upper()

    try:
        # Handles "9:00 AM", "09:00"
        dt = datetime.strptime(t, "%I:%M %p")
    except ValueError:
        try:
            dt = datetime.strptime(t, "%H:%M")
        except ValueError:
            return None

    return dt.strftime("%H:%M")  # ALWAYS 24h


def normalize_schedule(raw: dict) -> dict:
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    clean = {}

    for day in days:
        d = raw.get(day)
        if not isinstance(d, dict):
            continue

        closed = str(d.get("closed", "false")).lower() == "true"

        clean[day] = {
            "closed": closed,
            "from": normalize_time(d.get("from")),
            "to": normalize_time(d.get("to")),
            "lunch_from": normalize_time(d.get("lunch_from")),
            "lunch_to": normalize_time(d.get("lunch_to")),
        }

    return clean

