"""`/profile` endpoints consumed by `ProfileRemoteDataSource`."""

from flask import Blueprint, g, jsonify, request
from google.cloud.firestore_v1.base_query import FieldFilter

from auth_utils import require_auth
from db import SHOP_ITEMS, USERS, col, doc, now_iso, safe_delete_fields, to_dict


profile_bp = Blueprint("profile", __name__)

_IMMUTABLE_FIELDS = {"uid", "id", "email", "role", "created_at", "password_hash"}


@profile_bp.get("/profile")
@require_auth
def get_profile():
    snap = doc(USERS, g.user_id).get()
    if not snap.exists:
        return jsonify({"detail": "Profile not found"}), 404
    return jsonify(safe_delete_fields(to_dict(snap), "password_hash"))


@profile_bp.put("/profile")
@require_auth
def update_profile():
    payload = request.get_json(silent=True) or {}
    cleaned = {k: v for k, v in payload.items() if k not in _IMMUTABLE_FIELDS}
    cleaned["updated_at"] = now_iso()
    doc(USERS, g.user_id).set(cleaned, merge=True)
    item_updates = {}
    if "full_name" in cleaned or "shop_name" in cleaned:
        item_updates["vendor_name"] = cleaned.get("shop_name") or cleaned.get("full_name")
    if "phone" in cleaned:
        item_updates["vendor_phone"] = cleaned.get("phone")
    if "email" in cleaned:
        item_updates["vendor_email"] = cleaned.get("email")
    if "city_id" in cleaned:
        item_updates["city_id"] = cleaned.get("city_id")
    if "latitude" in cleaned:
        item_updates["vendor_latitude"] = cleaned.get("latitude")
    if "longitude" in cleaned:
        item_updates["vendor_longitude"] = cleaned.get("longitude")
    if "shop_address" in cleaned:
        item_updates["vendor_shop_description"] = cleaned.get("shop_address")
    if item_updates:
        item_updates["updated_at"] = now_iso()
        query = col(SHOP_ITEMS).where(filter=FieldFilter("vendor_id", "==", g.user_id))
        for item in query.stream():
            item.reference.set(item_updates, merge=True)
    return jsonify({"ok": True})
