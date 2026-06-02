"""Firestore access helpers for the `localshop/v1/*` schema."""

from datetime import datetime, timezone
from typing import Any

from firebase_admin import firestore


ROOT_COLLECTION = "localshop"
VERSION_DOC = "v1"

# Collection names (kept in sync with
# lib/core/constants/firebase_constants.dart).
USERS = "users"
CITIES = "cities"
SHOP_ITEMS = "shop_items"
CATEGORIES = "categories"
CUSTOMER_ORDERS = "customer_orders"
USER_FAVORITES = "user_favorites"
VENDOR_SUBSCRIPTIONS = "vendor_subscriptions"
REVIEWS = "reviews"
CHAT_ROOMS = "chat_rooms"
MESSAGES = "messages"
REFERRALS = "referrals"
SUBSCRIPTION_PLANS = "subscription_plans"
SUBSCRIPTION_PAYMENTS = "subscription_payments"
AI_SUMMARIES = "ai_summaries"
WALLETS = "wallets"
WALLET_TRANSACTIONS = "wallet_transactions"
NOTIFICATIONS = "notifications"
KHATA_LEDGERS = "khata_ledgers"
KHATA_TRANSACTIONS = "khata_transactions"
SUPPORT_TICKETS = "support_tickets"


def db():
    """Lazy Firestore client — avoids touching firebase_admin at import time."""
    return firestore.client()


def col(name: str):
    """Returns a CollectionReference at `localshop/v1/<name>`."""
    return db().collection(ROOT_COLLECTION).document(VERSION_DOC).collection(name)


def doc(name: str, doc_id: str):
    return col(name).document(doc_id)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _serialize(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _serialize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_serialize(v) for v in value]
    if isinstance(value, datetime):
        return value.isoformat()
    # Firestore DocumentReference → path string; GeoPoint → {lat, lng}
    if hasattr(value, "latitude") and hasattr(value, "longitude") and not isinstance(value, (int, float)):
        return {"latitude": value.latitude, "longitude": value.longitude}
    if hasattr(value, "path"):
        return value.path
    return value


def to_dict(snapshot) -> dict:
    """Serialize a DocumentSnapshot to JSON-safe dict, injecting `uid`."""
    if snapshot is None or not snapshot.exists:
        return {}
    data = snapshot.to_dict() or {}
    data = {**data, "uid": snapshot.id}
    return _serialize(data)


def safe_delete_fields(data: dict, *fields: str) -> dict:
    """Return a copy of `data` without the given keys."""
    return {k: v for k, v in data.items() if k not in fields}
