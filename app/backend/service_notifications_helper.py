from datetime import datetime
from firebase_admin import firestore
import logging

logger = logging.getLogger(__name__)
db = firestore.client()

############################################################
# CREATE SERVICE NOTIFICATION
############################################################

def create_service_notification(
        provider_id: str,
        title: str,
        body: str,
        notif_type: str,
        data_payload=None
):
    """
    Save notification in Firestore (service-only collection)
    """

    try:
        doc_ref = db.collection("service_notifications").document()

        doc_ref.set({
            "provider_id": provider_id,
            "title": title,
            "body": body,
            "type": notif_type,
            "is_read": False,
            "created_at": datetime.utcnow().isoformat(),
            "data": data_payload or {}
        })

        logger.info(f"📥 Service notification stored for {provider_id}")

    except Exception as e:
        logger.error(f"❌ Failed storing service notification: {e}")


############################################################
# FETCH NOTIFICATIONS
############################################################

def get_service_notifications(provider_id: str):

    docs = db.collection("service_notifications") \
        .where("provider_id", "==", provider_id) \
        .order_by("created_at", direction=firestore.Query.DESCENDING) \
        .stream()

    result = []

    for doc in docs:
        d = doc.to_dict()
        d["id"] = doc.id
        result.append(d)

    return result


############################################################
# MARK SINGLE READ
############################################################

def mark_service_notification_read(notification_id: str):
    db.collection("service_notifications") \
        .document(notification_id) \
        .update({"is_read": True})


############################################################
# MARK ALL READ
############################################################

def mark_all_service_notifications_read(provider_id: str):

    docs = db.collection("service_notifications") \
        .where("provider_id", "==", provider_id) \
        .where("is_read", "==", False) \
        .stream()

    for doc in docs:
        doc.reference.update({"is_read": True})
