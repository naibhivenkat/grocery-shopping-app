"""`/provider/availability` endpoints and atomic lock mechanisms for LocalShop V2."""

from datetime import datetime, timedelta
from flask import Blueprint, g, jsonify, request
from google.cloud import firestore

from auth_utils import require_auth
from db import db, col, doc, now_iso

availability_bp = Blueprint("availability", __name__)

COLL_AVAILABILITY = "provider_availability"
COLL_PROFILES = "provider_profiles"


def _get_provider_schedule(transaction, provider_id: str) -> dict:
    """Safely extracts the provider's working schedule from the capability profile."""
    snap = doc(COLL_PROFILES, provider_id).get(transaction=transaction)
    if snap.exists:
        return (snap.to_dict() or {}).get("working_schedule", {})
    return {}


def _generate_default_slots(transaction, provider_id: str, date: str) -> list:
    """Generates standard 30-min slots strictly bounded by the provider's schedule."""
    schedule = _get_provider_schedule(transaction, provider_id)
    try:
        weekday = datetime.strptime(date, "%Y-%m-%d").strftime("%a")
    except ValueError:
        return []

    day_schedule = schedule.get(weekday)
    if not day_schedule or day_schedule.get("closed"):
        return []

    try:
        start = datetime.strptime(day_schedule["from"], "%I:%M %p")
        end = datetime.strptime(day_schedule["to"], "%I:%M %p")
    except ValueError:
        return []

    slots = []
    current = start
    while current < end:
        slots.append({
            "time": current.strftime("%H:%M"),
            "status": "available"
        })
        current += timedelta(minutes=30)
    return slots


def get_or_create_availability_txn(transaction, provider_id: str, date: str) -> dict:
    """Atomic read-or-create for daily availability documents."""
    doc_id = f"{provider_id}:{date}"
    ref = doc(COLL_AVAILABILITY, doc_id)
    snap = ref.get(transaction=transaction)

    if snap.exists:
        return snap.to_dict() or {}

    slots = _generate_default_slots(transaction, provider_id, date)
    data = {
        "provider_id": provider_id,
        "date": date,
        "slot_size": 30,
        "slots": slots,
        "created_at": now_iso(),
        "updated_at": now_iso()
    }
    transaction.set(ref, data)
    return data


def get_slot_times(start_time: str, duration: int) -> list:
    """Mathematical projection of 30-minute intervals for a booking duration."""
    slots = []
    try:
        t = datetime.strptime(start_time, "%H:%M")
    except ValueError:
        return []
    for _ in range(0, duration, 30):
        slots.append(t.strftime("%H:%M"))
        t += timedelta(minutes=30)
    return slots


def lock_slots_txn(transaction, provider_id: str, date: str, start_time: str, duration: int) -> bool:
    """
    Atomically verifies and locks time slots to prevent race conditions.
    Fixes legacy vulnerability where missing slots bypassed booking validation.
    """
    avail = get_or_create_availability_txn(transaction, provider_id, date)
    slot_times = get_slot_times(start_time, duration)

    slots_map = {s["time"]: s for s in avail.get("slots", [])}

    # 1. Verification Phase
    for t in slot_times:
        if t not in slots_map or slots_map[t].get("status") != "available":
            return False  # Target slot is missing, locked, or outside working hours.

    # 2. Locking Phase
    for t in slot_times:
        slots_map[t]["status"] = "booked"

    ref = doc(COLL_AVAILABILITY, f"{provider_id}:{date}")
    transaction.update(ref, {
        "slots": list(slots_map.values()),
        "updated_at": now_iso()
    })
    return True


def release_slots_txn(transaction, provider_id: str, date: str, start_time: str, duration: int):
    """Atomically frees previously locked slots back into the scheduling pool."""
    avail = get_or_create_availability_txn(transaction, provider_id, date)
    slot_times = get_slot_times(start_time, duration)

    slots_map = {s["time"]: s for s in avail.get("slots", [])}

    for t in slot_times:
        if t in slots_map:
            slots_map[t]["status"] = "available"

    ref = doc(COLL_AVAILABILITY, f"{provider_id}:{date}")
    transaction.update(ref, {
        "slots": list(slots_map.values()),
        "updated_at": now_iso()
    })


# =====================================================================
# V2 AVAILABILITY ENDPOINTS
# =====================================================================

@availability_bp.get("/provider/availability")
@require_auth
def get_own_availability():
    """Reads the authenticated provider's availability matrix."""
    date = request.args.get("date")
    if not date:
        return jsonify({"detail": "date required"}), 400

    @firestore.transactional
    def _read(txn):
        return get_or_create_availability_txn(txn, g.user_id, date)

    try:
        data = _read(db().transaction())
        return jsonify(data), 200
    except Exception as e:
        return jsonify({"detail": str(e)}), 500


@availability_bp.put("/provider/availability")
@require_auth
def update_own_availability():
    """Allows providers to manually block/free specific slots."""
    payload = request.get_json(silent=True) or {}
    date = payload.get("date")
    updates = payload.get("updates")

    if not date or not isinstance(updates, list):
        return jsonify({"detail": "date and updates array required"}), 400

    @firestore.transactional
    def _update(txn):
        avail = get_or_create_availability_txn(txn, g.user_id, date)
        slots_map = {s["time"]: s for s in avail.get("slots", [])}

        for u in updates:
            time_val = u.get("time")
            if time_val in slots_map:
                slots_map[time_val]["status"] = u.get("status", "available")

        ref = doc(COLL_AVAILABILITY, f"{g.user_id}:{date}")
        txn.update(ref, {
            "slots": list(slots_map.values()),
            "updated_at": now_iso()
        })

    try:
        _update(db().transaction())
        return jsonify({"success": True, "detail": "Availability updated"}), 200
    except Exception as e:
        return jsonify({"detail": str(e)}), 500


@availability_bp.get("/providers/<provider_id>/availability")
def get_target_availability(provider_id):
    """Public discovery endpoint for a target provider's slots."""
    date = request.args.get("date")
    if not date:
        return jsonify({"detail": "date required"}), 400

    @firestore.transactional
    def _read(txn):
        return get_or_create_availability_txn(txn, provider_id, date)

    try:
        data = _read(db().transaction())
        return jsonify(data), 200
    except Exception as e:
        return jsonify({"detail": str(e)}), 500