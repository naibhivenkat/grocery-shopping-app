"""`/chat/*` endpoints consumed by `ChatRemoteDataSource`."""

from flask import Blueprint, g, jsonify, request
from google.cloud.firestore_v1.base_query import FieldFilter

from auth_utils import require_auth
from db import (
    CHAT_ROOMS,
    MESSAGES,
    NOTIFICATIONS,
    USERS,
    col,
    doc,
    now_iso,
    to_dict,
)


chat_bp = Blueprint("chat", __name__)


def _other_party(room_data: dict, user_id: str) -> str | None:
    customer = room_data.get("customer_id")
    vendor = room_data.get("vendor_id")
    if user_id == customer:
        return vendor
    if user_id == vendor:
        return customer
    return None


@chat_bp.get("/chat/rooms")
@require_auth
def list_rooms():
    rooms_as_customer = col(CHAT_ROOMS).where(
        filter=FieldFilter("customer_id", "==", g.user_id)
    )
    rooms_as_vendor = col(CHAT_ROOMS).where(
        filter=FieldFilter("vendor_id", "==", g.user_id)
    )
    rooms = {d.id: to_dict(d) for d in rooms_as_customer.stream()}
    rooms.update({d.id: to_dict(d) for d in rooms_as_vendor.stream()})
    return jsonify(list(rooms.values()))


@chat_bp.post("/chat/rooms")
@require_auth
def get_or_create_room():
    payload = request.get_json(silent=True) or {}
    vendor_id = payload.get("vendor_id")
    if not vendor_id:
        return jsonify({"detail": "vendor_id is required"}), 422

    customer_id = g.user_id
    # Deterministic room id so repeated calls return the same document.
    room_id = f"{customer_id}__{vendor_id}"
    ref = doc(CHAT_ROOMS, room_id)
    snap = ref.get()
    if not snap.exists:
        customer_doc = doc(USERS, customer_id).get().to_dict() or {}
        vendor_doc = doc(USERS, vendor_id).get().to_dict() or {}
        ref.set({
            "customer_id": customer_id,
            "vendor_id": vendor_id,
            "customer_name": customer_doc.get("full_name"),
            "vendor_name": vendor_doc.get("full_name") or vendor_doc.get("shop_name"),
            "last_message": None,
            "last_message_at": None,
            "created_at": now_iso(),
        })
        snap = ref.get()
    return jsonify(to_dict(snap))


@chat_bp.get("/chat/rooms/<room_id>/messages")
@require_auth
def list_messages(room_id):
    room_snap = doc(CHAT_ROOMS, room_id).get()
    if not room_snap.exists:
        return jsonify({"detail": "Chat room not found"}), 404
    data = room_snap.to_dict() or {}
    if g.user_id not in {data.get("customer_id"), data.get("vendor_id")}:
        return jsonify({"detail": "Not a participant"}), 403

    query = col(MESSAGES).where(filter=FieldFilter("chat_room_id", "==", room_id))
    messages = [to_dict(d) for d in query.stream()]
    messages.sort(key=lambda m: m.get("created_at") or "")
    return jsonify(messages)


@chat_bp.post("/chat/rooms/<room_id>/messages")
@require_auth
def send_message(room_id):
    payload = request.get_json(silent=True) or {}
    text = (payload.get("text") or "").strip()
    if not text:
        return jsonify({"detail": "text is required"}), 422

    room_ref = doc(CHAT_ROOMS, room_id)
    room_snap = room_ref.get()
    if not room_snap.exists:
        return jsonify({"detail": "Chat room not found"}), 404
    room = room_snap.to_dict() or {}
    if g.user_id not in {room.get("customer_id"), room.get("vendor_id")}:
        return jsonify({"detail": "Not a participant"}), 403

    msg_ref = col(MESSAGES).document()
    msg_ref.set({
        "chat_room_id": room_id,
        "sender_id": g.user_id,
        "text": text,
        "created_at": now_iso(),
    })

    room_ref.set(
        {"last_message": text, "last_message_at": now_iso()}, merge=True
    )

    recipient = _other_party(room, g.user_id)
    if recipient:
        col(NOTIFICATIONS).document().set({
            "user_id": recipient,
            "type": "chat_message",
            "title": "New message",
            "body": text[:140],
            "is_read": False,
            "reference_id": room_id,
            "created_at": now_iso(),
        })

    return jsonify(to_dict(msg_ref.get())), 201
