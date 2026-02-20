from flask import Blueprint, request, jsonify

from service_notifications_helper import (
    get_service_notifications,
    mark_service_notification_read,
    mark_all_service_notifications_read
)

service_notifications_bp = Blueprint("service_notifications", __name__)

############################################################
# FETCH
############################################################

@service_notifications_bp.route("/service/notifications", methods=["GET"])
def fetch_service_notifications():
    provider_id = request.args.get("provider_id")

    if not provider_id:
        return jsonify({"error": "provider_id required"}), 400

    data = get_service_notifications(provider_id)
    return jsonify(data)


############################################################
# MARK SINGLE
############################################################

@service_notifications_bp.route("/service/notifications/mark-read", methods=["POST"])
def mark_read():
    notif_id = request.json.get("notification_id")
    mark_service_notification_read(notif_id)
    return jsonify({"message": "marked"})


############################################################
# MARK ALL
############################################################

@service_notifications_bp.route("/service/notifications/mark-all-read", methods=["POST"])
def mark_all():
    provider_id = request.json.get("provider_id")
    mark_all_service_notifications_read(provider_id)
    return jsonify({"message": "all marked"})
