"""Provider calendars and transaction-safe, booking-owned 30-minute slots."""

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from flask import Blueprint, g, jsonify, request
from google.cloud import firestore

from auth_utils import require_auth
from db import db, doc, now_iso

availability_bp = Blueprint("availability", __name__)
COLL_AVAILABILITY = "provider_availability"
COLL_PROFILES = "provider_profiles"
SERVICE_TIMEZONE = ZoneInfo("Asia/Kolkata")


def validate_date(date):
    if not isinstance(date, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        raise ValueError("date must be YYYY-MM-DD")
    try:
        return datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise ValueError("Invalid calendar date")


def get_slot_times(start_time, duration):
    """Return no slots for invalid, fractional, unaligned or overnight requests."""
    if isinstance(duration, bool) or not isinstance(duration, int) or not 30 <= duration <= 480 or duration % 30:
        return []
    if not isinstance(start_time, str) or not re.fullmatch(r"\d{2}:\d{2}", start_time):
        return []
    try:
        start = datetime.strptime(start_time, "%H:%M")
    except ValueError:
        return []
    if start.minute not in (0, 30) or start.hour * 60 + start.minute + duration > 1440:
        return []
    return [(start + timedelta(minutes=offset)).strftime("%H:%M") for offset in range(0, duration, 30)]


def validate_selection(date, start_time, duration, *, future=True):
    day = validate_date(date)
    slots = get_slot_times(start_time, duration)
    if not slots:
        raise ValueError("Select aligned 30-minute slots, a duration up to 8 hours, and no overnight booking")
    start = datetime.combine(day.date(), datetime.strptime(start_time, "%H:%M").time(), SERVICE_TIMEZONE)
    if future and start <= datetime.now(SERVICE_TIMEZONE):
        raise ValueError("Booking time must be in the future (Asia/Kolkata)")
    return slots


def _generate_default_slots(transaction, provider_id, date):
    weekday = validate_date(date).strftime("%a")
    snapshot = doc(COLL_PROFILES, provider_id).get(transaction=transaction)
    profile = snapshot.to_dict() or {} if snapshot.exists else {}
    schedule = profile.get("working_schedule") or {}
    day = schedule.get(weekday) if isinstance(schedule, dict) else None
    if not isinstance(day, dict) or day.get("closed"):
        return []
    try:
        start = datetime.strptime(day["from"], "%I:%M %p")
        end = datetime.strptime(day["to"], "%I:%M %p")
    except (KeyError, TypeError, ValueError):
        return []
    if start >= end or start.minute not in (0, 30) or end.minute not in (0, 30):
        return []
    slots = []
    while start + timedelta(minutes=30) <= end:
        slots.append({"time": start.strftime("%H:%M"), "status": "available"})
        start += timedelta(minutes=30)
    return slots


def _load_availability(transaction, provider_id, date):
    """Reads only: callers finish validation/other reads before scheduling writes."""
    validate_date(date)
    ref = doc(COLL_AVAILABILITY, f"{provider_id}:{date}")
    snapshot = ref.get(transaction=transaction)
    if snapshot.exists:
        return ref, snapshot.to_dict() or {}, True
    timestamp = now_iso()
    return ref, {
        "provider_id": provider_id, "date": date, "slot_size": 30,
        "slots": _generate_default_slots(transaction, provider_id, date),
        "created_at": timestamp, "updated_at": timestamp,
    }, False


def _save_availability(transaction, ref, data, exists):
    data["updated_at"] = now_iso()
    if exists:
        transaction.update(ref, {"slots": data["slots"], "updated_at": data["updated_at"]})
    else:
        transaction.set(ref, data)


def get_or_create_availability_txn(transaction, provider_id, date):
    ref, data, exists = _load_availability(transaction, provider_id, date)
    if not exists:
        transaction.set(ref, data)
    return data


def lock_slots_txn(transaction, provider_id, date, start_time, duration, booking_id=None):
    try:
        times = validate_selection(date, start_time, duration)
    except ValueError:
        return False
    ref, data, exists = _load_availability(transaction, provider_id, date)
    slots = {slot["time"]: slot for slot in data.get("slots", [])}
    if any(time not in slots or slots[time].get("status") != "available" for time in times):
        return False
    for time in times:
        slots[time]["status"] = "booked"
        if booking_id:
            slots[time]["booking_id"] = booking_id
    data["slots"] = list(slots.values())
    _save_availability(transaction, ref, data, exists)
    return True


def release_slots_txn(transaction, provider_id, date, start_time, duration, booking_id=None):
    times = validate_selection(date, start_time, duration, future=False)
    ref = doc(COLL_AVAILABILITY, f"{provider_id}:{date}")
    snapshot = ref.get(transaction=transaction)
    if not snapshot.exists:
        return
    data = snapshot.to_dict() or {}
    changed = False
    for slot in data.get("slots", []):
        if slot.get("time") in times and slot.get("status") == "booked":
            # Legacy slots have no booking_id. New slots can only be freed by their owner.
            if slot.get("booking_id") and slot["booking_id"] != booking_id:
                continue
            slot["status"] = "available"
            slot.pop("booking_id", None)
            changed = True
    if changed:
        _save_availability(transaction, ref, data, True)


@availability_bp.get("/provider/availability")
@require_auth
def get_own_availability():
    date = request.args.get("date")
    try:
        validate_date(date)
    except ValueError as error:
        return jsonify({"detail": str(error)}), 422

    @firestore.transactional
    def read(transaction):
        # Reads must not create calendar documents; saving/booking persists them.
        return _load_availability(transaction, g.user_id, date)[1]

    return jsonify(read(db().transaction()))


@availability_bp.put("/provider/availability")
@require_auth
def update_own_availability():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"detail": "Request body must be a JSON object"}), 422
    date, updates = payload.get("date"), payload.get("updates")
    try:
        validate_date(date)
        if not isinstance(updates, list) or not 1 <= len(updates) <= 48:
            raise ValueError("updates must contain 1 to 48 slots")
        times = set()
        for update in updates:
            if not isinstance(update, dict) or not get_slot_times(update.get("time"), 30):
                raise ValueError("Each update must specify an aligned HH:MM time")
            if update.get("status") not in ("available", "blocked", "booked"):
                raise ValueError("Only available or blocked statuses may be set; booked rows can only be retained")
            if update["time"] in times:
                raise ValueError("Duplicate slot updates are not allowed")
            times.add(update["time"])
    except ValueError as error:
        return jsonify({"detail": str(error)}), 422

    @firestore.transactional
    def update(transaction):
        ref, data, exists = _load_availability(transaction, g.user_id, date)
        slots = {slot["time"]: slot for slot in data.get("slots", [])}
        for change in updates:
            slot = slots.get(change["time"])
            if slot is None:
                raise ValueError("Slot is outside the provider's schedule")
            if slot.get("status") == "booked" or slot.get("booking_id"):
                if change["status"] != "booked":
                    raise PermissionError("Booked slots can only be released by cancelling their booking")
            elif change["status"] == "booked":
                raise ValueError("Only booking confirmation can mark a slot booked")
        for change in updates:
            if change["status"] != "booked":
                slots[change["time"]]["status"] = change["status"]
        data["slots"] = list(slots.values())
        _save_availability(transaction, ref, data, exists)

    try:
        update(db().transaction())
    except PermissionError as error:
        return jsonify({"detail": str(error)}), 409
    except ValueError as error:
        return jsonify({"detail": str(error)}), 422
    return jsonify({"success": True, "detail": "Availability updated"})


@availability_bp.get("/providers/<provider_id>/availability")
def get_target_availability(provider_id):
    if not isinstance(provider_id, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", provider_id) or provider_id in (".", ".."):
        return jsonify({"detail": "Invalid provider ID"}), 422
    date = request.args.get("date")
    try:
        validate_date(date)
    except ValueError as error:
        return jsonify({"detail": str(error)}), 422

    @firestore.transactional
    def read(transaction):
        user = doc("users", provider_id).get(transaction=transaction)
        profile = doc(COLL_PROFILES, provider_id).get(transaction=transaction)
        user_data = user.to_dict() or {} if user.exists else {}
        profile_data = profile.to_dict() or {} if profile.exists else {}
        if not user.exists or not profile.exists or user_data.get("is_suspended") or profile_data.get("is_active") is False:
            raise ValueError("Provider not available")
        return _load_availability(transaction, provider_id, date)[1]

    try:
        data = read(db().transaction())
    except ValueError as error:
        return jsonify({"detail": str(error)}), 404
    data["slots"] = [{"time": slot.get("time"), "status": slot.get("status")} for slot in data.get("slots", [])]
    return jsonify(data)
