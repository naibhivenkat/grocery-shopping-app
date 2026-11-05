"""Legacy service inbox, scoped to the authenticated recipient ID.

Legacy provider IDs are not mapped to current users by this module. Access is
available only when the stored provider_id is exactly the authenticated user ID.
"""
from flask import Blueprint, g, jsonify, request
from firebase_admin import firestore

from auth_utils import require_auth
from service_notifications_helper import (
    COLL_SERVICE_NOTIFICATIONS, db, get_service_notifications,
    get_unread_service_notification_count,
)

service_notifications_bp = Blueprint("service_notifications", __name__)


def _recipient(value):
    if not isinstance(value, str) or not value or "/" in value:
        return jsonify({"error": "provider_id required"}), 400
    if value != g.user_id:
        return jsonify({"error": "Not your notifications"}), 403
    return None


@service_notifications_bp.route("/service/notifications", methods=["GET"])
@require_auth
def fetch_service_notifications():
    provider_id = request.args.get("provider_id")
    error = _recipient(provider_id)
    if error:
        return error
    return jsonify(get_service_notifications(provider_id))


@service_notifications_bp.route("/service/notifications/mark-read", methods=["POST"])
@require_auth
def mark_read():
    body = request.get_json(silent=True)
    notif_id = body.get("notification_id") if isinstance(body, dict) else None
    if not isinstance(notif_id, str) or not notif_id or "/" in notif_id:
        return jsonify({"error": "notification_id required"}), 400
    ref = db.collection(COLL_SERVICE_NOTIFICATIONS).document(notif_id)

    @firestore.transactional
    def mark_if_owned(transaction):
        snap = ref.get(transaction=transaction)
        if not snap.exists:
            return 404
        if (snap.to_dict() or {}).get("provider_id") != g.user_id:
            return 403
        transaction.update(ref, {"is_read": True})
        return 200

    status = mark_if_owned(db.transaction())
    if status != 200:
        return jsonify({"error": "Notification not found" if status == 404 else "Not your notification"}), status
    return jsonify({"message": "marked"})


@service_notifications_bp.route("/service/notifications/mark-all-read", methods=["POST"])
@require_auth
def mark_all():
    body = request.get_json(silent=True)
    provider_id = body.get("provider_id") if isinstance(body, dict) else None
    error = _recipient(provider_id)
    if error:
        return error
    # Recheck ownership in each transaction: a queried document may have been
    # reassigned between the query and its update.
    documents = db.collection(COLL_SERVICE_NOTIFICATIONS).where(
        "provider_id", "==", provider_id
    ).where("is_read", "==", False).stream()
    for document in documents:
        @firestore.transactional
        def mark_if_still_owned(transaction):
            snap = document.reference.get(transaction=transaction)
            data = snap.to_dict() or {} if snap.exists else {}
            if data.get("provider_id") == provider_id and data.get("is_read") is False:
                transaction.update(document.reference, {"is_read": True})
        mark_if_still_owned(db.transaction())
    return jsonify({"message": "all marked"})


@service_notifications_bp.route("/service/notifications/unread-count", methods=["GET"])
@require_auth
def unread_count():
    provider_id = request.args.get("provider_id")
    error = _recipient(provider_id)
    if error:
        return error
    return jsonify({"unread": get_unread_service_notification_count(provider_id)})
