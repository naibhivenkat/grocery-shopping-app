import logging
from datetime import datetime
from firebase_admin import firestore
from firebase_admin import messaging
from typing import List

logger = logging.getLogger(__name__)
db = firestore.client()

COLL_SERVICE_NOTIFICATIONS = "service_notifications"

COLL_FCM_TOKENS = "fcm_tokens"
############################################################
# CREATE SERVICE NOTIFICATION
############################################################

############################################################
# CREATE SERVICE NOTIFICATION
############################################################

def create_service_notification(user_id, title, body, notif_type, data=None):

    doc = {
        "provider_id": user_id,
        "title": title,
        "body": body,
        "type": notif_type,
        "is_read": False,
        "created_at": datetime.utcnow().isoformat(),
        "data": data or {}
    }

    db.collection(COLL_SERVICE_NOTIFICATIONS).add(doc)

    logger.info(f"📥 Service notification stored for {user_id}")

    # PUSH
    tokens = get_fcm_tokens_for_user(user_id)

    send_fcm_notification_to_tokens(
        tokens,
        title,
        body,
        data_payload=data
    )


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


def get_unread_service_notification_count(provider_id: str):
    docs = db.collection("service_notifications") \
        .where("provider_id", "==", provider_id) \
        .where("is_read", "==", False) \
        .stream()

    count = 0
    for _ in docs:
        count += 1

    return count


############################################################
# REGISTER TOKEN
############################################################

def register_fcm_token(user_id: str, role: str, token: str):
    """
    Stores FCM token for any user role.
    """

    if not user_id or not token:
        return

    # Prevent duplicate token
    docs = db.collection(COLL_FCM_TOKENS) \
        .where("token", "==", token) \
        .stream()

    for d in docs:
        d.reference.delete()

    db.collection(COLL_FCM_TOKENS).add({
        "user_id": user_id,
        "role": role,
        "token": token,
        "created_at": datetime.utcnow().isoformat()
    })

    logger.info(f"✅ FCM token saved for {user_id}")


############################################################
# FETCH TOKENS
############################################################

def get_fcm_tokens_for_user(user_id: str) -> List[str]:
    """
    Returns all FCM tokens for a user.
    """

    docs = db.collection(COLL_FCM_TOKENS) \
        .where("user_id", "==", user_id) \
        .stream()

    tokens = [d.to_dict().get("token") for d in docs]

    logger.info(f"🔵 FCM tokens fetched for {user_id}: {len(tokens)}")

    return tokens


############################################################
# SEND PUSH
############################################################

def send_fcm_notification_to_tokens(tokens, title, body, data_payload=None):
    """
    Sends push to tokens.
    """

    if not tokens:
        logger.info("⚠️ No tokens to send notification")
        return {"success": 0, "failure": 0}

    success = 0
    failure = 0

    for token in tokens:
        try:
            message = messaging.Message(
                notification=messaging.Notification(
                    title=title,
                    body=body
                ),
                token=token,
                data=data_payload or {}
            )

            messaging.send(message)
            success += 1

        except Exception as e:
            logger.info(f"❌ Push failed: {e}")
            failure += 1

    return {"success": success, "failure": failure}
