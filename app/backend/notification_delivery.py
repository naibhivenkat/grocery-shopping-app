"""Modern-schema push delivery; durable inbox records are committed by callers.

FCM is a post-commit best-effort signal. A provider failure never rolls back a
confirmed order/payment or the inbox event and never encourages duplicate writes.
"""
import logging
import hashlib

from firebase_admin import messaging
import db as storage
from db import now_iso

logger = logging.getLogger(__name__)


def device_token_id(token):
    return hashlib.sha256(token.encode()).hexdigest()


def notification_data(user_id, kind, title, body, reference_id):
    return {"user_id": user_id, "type": kind, "title": title, "body": body,
            "reference_id": reference_id, "is_read": False, "created_at": now_iso()}


def deliver_push(event, *, lookup=None):
    """Read tokens from localshop/v1/users, rather than the old root users path."""
    if not event:
        return
    try:
        snapshot = (lookup or storage.doc)(storage.USERS, event["user_id"]).get()
        user = snapshot.to_dict() or {}
        if not snapshot.exists or user.get("is_suspended"):
            return
        tokens = user.get("fcm_tokens") or []
        if not isinstance(tokens, list):
            return
        for token in dict.fromkeys(item for item in tokens if isinstance(item, str) and item):
            try:
                # The same installation can switch accounts while offline, so
                # an old per-user token array is not evidence of current ownership.
                ownership = (lookup or storage.doc)("device_tokens", device_token_id(token)).get()
                if not ownership.exists or (ownership.to_dict() or {}).get("user_id") != event["user_id"]:
                    continue
                messaging.send(messaging.Message(token=token,
                    notification=messaging.Notification(title=event["title"], body=event["body"]),
                    data={field: str(event[field]) for field in ("user_id", "type", "reference_id")},
                    android=messaging.AndroidConfig(priority="high")))
            except Exception:
                # Do not log token values or let push failures affect the business action.
                logger.warning("Notification push delivery failed", exc_info=False)
    except Exception:
        logger.warning("Notification token lookup failed", exc_info=False)
