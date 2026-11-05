"""Legacy service inbox unavailable without verified recipient provenance.

Legacy provider and authenticated user IDs are independently generated; matching
strings alone do not establish ownership.
"""
from flask import Blueprint, jsonify
from auth_utils import require_auth

service_notifications_bp = Blueprint("service_notifications", __name__)


def _unverified_recipient():
    return jsonify({"error": "Legacy recipient identity cannot be verified"}), 403


@service_notifications_bp.route("/service/notifications", methods=["GET"])
@require_auth
def fetch_service_notifications():
    return _unverified_recipient()


@service_notifications_bp.route("/service/notifications/mark-read", methods=["POST"])
@require_auth
def mark_read():
    return _unverified_recipient()


@service_notifications_bp.route("/service/notifications/mark-all-read", methods=["POST"])
@require_auth
def mark_all():
    return _unverified_recipient()


@service_notifications_bp.route("/service/notifications/unread-count", methods=["GET"])
@require_auth
def unread_count():
    return _unverified_recipient()
