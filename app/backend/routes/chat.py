"""Private customer/shop/provider chat with atomic messages and notifications."""
import hashlib
import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from firebase_admin import firestore
from flask import Blueprint, g, jsonify, request
from google.cloud.firestore_v1.base_query import FieldFilter
from auth_utils import require_role
from db import CHAT_ROOMS, MESSAGES, NOTIFICATIONS, USERS, col, db, doc, now_iso, to_dict
from routes.khata import KhataError, _khata_error, _payload, _identifier, _text
from notification_delivery import notification_data, deliver_push

chat_bp = Blueprint("chat", __name__)
chat_bp.register_error_handler(KhataError, _khata_error)
_ROOM_FIELDS = {"uid", "customer_id", "vendor_id", "customer_name", "vendor_name", "last_message", "last_message_at", "created_at"}
_MESSAGE_FIELDS = {"uid", "chat_room_id", "sender_id", "text", "created_at"}


def _room_identifier(value):
    # Legacy room IDs concatenate two account IDs and can exceed 200 chars.
    if not isinstance(value, str) or not value or "/" in value or len(value) > 500:
        raise KhataError("room_id must be a valid identifier")
    return value


def _public(snapshot, fields):
    return {key: value for key, value in to_dict(snapshot).items() if key in fields}


def _parties(room, tx=None):
    if room.get("customer_id") == room.get("vendor_id"):
        raise KhataError("A chat requires two different participants")
    parties = []
    # Every ordinary account can buy; customer accounts can also activate a
    # provider capability without changing their primary account role.
    for field, roles in (("customer_id", {"customer", "vendor", "service"}), ("vendor_id", {"vendor", "service", "customer"})):
        identifier = _identifier(room.get(field), field)
        snap = doc(USERS, identifier).get(transaction=tx) if tx else doc(USERS, identifier).get()
        data = snap.to_dict() or {}
        if not snap.exists or data.get("role") not in roles or data.get("is_suspended"):
            raise KhataError("Chat participant is unavailable", 403)
        if field == "vendor_id" and data.get("role") == "customer":
            profile = doc("provider_profiles", identifier).get(transaction=tx) if tx else doc("provider_profiles", identifier).get()
            if not profile.exists or (profile.to_dict() or {}).get("is_active") is False:
                raise KhataError("Provider capability is unavailable", 403)
        parties.append(data)
    return parties


def _owned_room(room_id, tx=None):
    ref = doc(CHAT_ROOMS, _room_identifier(room_id))
    snap = ref.get(transaction=tx) if tx else ref.get()
    if not snap.exists:
        raise KhataError("Chat room not found", 404)
    room = snap.to_dict() or {}
    if g.user_id not in {room.get("customer_id"), room.get("vendor_id")}:
        raise KhataError("Not a participant", 403)
    _parties(room, tx)
    return ref, snap


@chat_bp.get("/chat/rooms")
@require_role("customer", "vendor", "service")
def list_rooms():
    fields = ("vendor_id", "customer_id")
    selected = {}
    for field in fields:
        for snap in col(CHAT_ROOMS).where(filter=FieldFilter(field, "==", g.user_id)).stream():
            try:
                _parties(snap.to_dict() or {})
            except KhataError:
                continue
            selected[snap.id] = _public(snap, _ROOM_FIELDS)
    rooms = list(selected.values())
    rooms.sort(key=lambda item: item.get("last_message_at") or item.get("created_at") or "", reverse=True)
    return jsonify(rooms)


@chat_bp.post("/chat/rooms")
@require_role("customer", "vendor", "service")
def get_or_create_room():
    vendor_id = _identifier(_payload().get("vendor_id"), "vendor_id")
    customer_id = g.user_id
    ref = doc(CHAT_ROOMS, f"{customer_id}__{vendor_id}")

    @firestore.transactional
    def create(tx):
        snap = ref.get(transaction=tx)
        room = {"customer_id": customer_id, "vendor_id": vendor_id}
        customer, vendor = _parties(room, tx)
        if snap.exists:
            saved = snap.to_dict() or {}
            if any(saved.get(key) != value for key, value in room.items()):
                raise KhataError("Chat room participants do not match", 409)
            return {key: value for key, value in {**saved, "uid": ref.id}.items() if key in _ROOM_FIELDS}
        data = {**room, "customer_name": customer.get("full_name") or customer.get("username"),
                "vendor_name": vendor.get("shop_name") or vendor.get("full_name"),
                "last_message": None, "last_message_at": None, "created_at": now_iso()}
        tx.set(ref, data)
        return {**data, "uid": ref.id}
    return jsonify(create(db().transaction()))


@chat_bp.get("/chat/rooms/<room_id>/messages")
@require_role("customer", "vendor", "service")
def list_messages(room_id):
    _owned_room(room_id)
    query = col(MESSAGES).where(filter=FieldFilter("chat_room_id", "==", room_id))
    messages = [_public(snap, _MESSAGE_FIELDS) for snap in query.stream()]
    messages.sort(key=lambda item: item.get("created_at") or "")
    return jsonify(messages)


@chat_bp.post("/chat/rooms/<room_id>/messages")
@require_role("customer", "vendor", "service")
def send_message(room_id):
    payload = _payload()
    text = _text(payload.get("text"), "text", 4000)
    if not text:
        raise KhataError("text is required")
    room_id = _room_identifier(room_id)
    key = request.headers.get("Idempotency-Key") or payload.get("idempotency_key")
    if key is not None:
        key = _text(key, "idempotency_key", 200)
        if not key:
            raise KhataError("idempotency_key must not be empty")
        identifier = "message_" + hashlib.sha256(json.dumps([room_id, g.user_id, key]).encode()).hexdigest()
        msg_ref = doc(MESSAGES, identifier)
    else:
        msg_ref = col(MESSAGES).document()
    notification_ref = col(NOTIFICATIONS).document()
    # One canonical counter across rooms: concurrent messages cannot bypass the
    # customer-wide daily allowance. Calendar day follows the Indian market.
    day = datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Kolkata")).date().isoformat()
    quota_ref = doc("chat_daily_usage", hashlib.sha256(json.dumps([g.user_id, day]).encode()).hexdigest())

    @firestore.transactional
    def send(tx):
        room_ref, room_snap = _owned_room(room_id, tx)
        room = room_snap.to_dict() or {}
        previous = msg_ref.get(transaction=tx)
        if previous.exists:
            data = previous.to_dict() or {}
            if data.get("text") != text or data.get("sender_id") != g.user_id or data.get("chat_room_id") != room_id:
                raise KhataError("Idempotency key belongs to a different message", 409)
            return _public(previous, _MESSAGE_FIELDS), 200, None
        count = 0
        as_customer = g.user_id == room["customer_id"]
        if as_customer:
            quota = quota_ref.get(transaction=tx)
            count = (quota.to_dict() or {}).get("count", 0)
            if type(count) is not int or count < 0:
                raise KhataError("Message allowance needs reconciliation", 409)
            if count >= 3:
                raise KhataError("Customer message limit reached (3 messages per day)", 429)
        recipient = room["vendor_id"] if g.user_id == room["customer_id"] else room["customer_id"]
        timestamp = now_iso()
        data = {"chat_room_id": room_id, "sender_id": g.user_id, "text": text, "created_at": timestamp}
        event = notification_data(recipient, "chat_message", "New message", text[:140], room_id)
        tx.set(msg_ref, data)
        tx.update(room_ref, {"last_message": text, "last_message_at": timestamp})
        tx.set(notification_ref, event)
        if as_customer:
            tx.set(quota_ref, {"user_id": g.user_id, "day": day, "count": count + 1, "updated_at": timestamp})
        return {**data, "uid": msg_ref.id}, 201, event
    body, status, event = send(db().transaction())
    deliver_push(event, lookup=doc)
    return jsonify(body), status
