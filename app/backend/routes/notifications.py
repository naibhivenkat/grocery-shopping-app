"""`/notifications/*` endpoints consumed by `NotificationRemoteDataSource`."""

from flask import Blueprint, g, jsonify
from google.cloud.firestore_v1.base_query import FieldFilter

from auth_utils import require_auth
from db import NOTIFICATIONS, col, doc, to_dict


notifications_bp = Blueprint("notifications", __name__)


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
    batch = col(NOTIFICATIONS)._client.batch()
    count = 0
    for d in query.stream():
        if (d.to_dict() or {}).get("is_read"):
            continue
        batch.update(d.reference, {"is_read": True})
        count += 1
        # Firestore batches cap at 500 ops.
        if count % 450 == 0:
            batch.commit()
            batch = col(NOTIFICATIONS)._client.batch()
    if count % 450:
        batch.commit()
    return jsonify({"ok": True, "updated": count})
