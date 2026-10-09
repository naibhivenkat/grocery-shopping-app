"""`/notifications/*` endpoints consumed by `NotificationRemoteDataSource`."""

from flask import Blueprint, g, jsonify, request
from firebase_admin import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from auth_utils import require_auth
from db import NOTIFICATIONS, USERS, col, doc, db, to_dict, now_iso
from notification_delivery import device_token_id


notifications_bp = Blueprint("notifications", __name__)


@notifications_bp.route("/notifications/device-token", methods=["POST", "DELETE"])
@require_auth
def device_token():
    payload = request.get_json(silent=True)
    token = payload.get("token") if isinstance(payload, dict) else None
    if not isinstance(token, str) or not 10 <= len(token.strip()) <= 4096:
        return jsonify({"detail": "Valid device token required"}), 422
    token = token.strip()
    ref = doc(USERS, g.user_id)
    ownership_ref = doc("device_tokens", device_token_id(token))
    remove = request.method == "DELETE"

    @firestore.transactional
    def save(tx):
        snap = ref.get(transaction=tx)
        user = snap.to_dict() or {}
        if not snap.exists or user.get("is_suspended"):
            return False
        ownership = ownership_ref.get(transaction=tx)
        previous = user.get("fcm_tokens") or []
        previous = [item for item in previous if isinstance(item, str) and item != token] if isinstance(previous, list) else []
        # Bound obsolete devices while allowing several signed-in devices.
        tokens = previous[-9:] if remove else (previous + [token])[-10:]
        tx.set(ref, {"fcm_tokens": tokens, "notification_token_updated_at": now_iso()}, merge=True)
        if not remove:
            # Transfer ownership even when logout on the old account failed.
            tx.set(ownership_ref, {"user_id": g.user_id, "updated_at": now_iso()})
        elif ownership.exists and (ownership.to_dict() or {}).get("user_id") == g.user_id:
            tx.set(ownership_ref, {"user_id": None, "updated_at": now_iso()})
        return True

    if not save(db().transaction()):
        return jsonify({"detail": "Account unavailable"}), 403
    return jsonify({"ok": True})


@notifications_bp.get("/notifications")
@require_auth
def list_notifications():
    query = col(NOTIFICATIONS).where(
        filter=FieldFilter("user_id", "==", g.user_id)
    )
    items = [to_dict(d) for d in query.stream()]
    items.sort(key=lambda n: n.get("created_at") or "", reverse=True)
    return jsonify(items)


@notifications_bp.post("/notifications/<notification_id>/read")
@require_auth
def mark_read(notification_id):
    ref = doc(NOTIFICATIONS, notification_id)
    snap = ref.get()
    if not snap.exists:
        return jsonify({"detail": "Notification not found"}), 404
    if (snap.to_dict() or {}).get("user_id") != g.user_id:
        return jsonify({"detail": "Not your notification"}), 403
    ref.update({"is_read": True})
    return jsonify({"ok": True})


@notifications_bp.post("/notifications/read-all")
@require_auth
def mark_all_read():
    query = col(NOTIFICATIONS).where(
        filter=FieldFilter("user_id", "==", g.user_id)
    )
    batch = db().batch()
    count = 0
    for d in query.stream():
        if (d.to_dict() or {}).get("is_read"):
            continue
        batch.update(d.reference, {"is_read": True})
        count += 1
        # Firestore batches cap at 500 ops.
        if count % 450 == 0:
            batch.commit()
            batch = db().batch()
    if count % 450:
        batch.commit()
    return jsonify({"ok": True, "updated": count})
