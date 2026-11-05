"""`/profile` endpoints consumed by `ProfileRemoteDataSource`."""

import re
from uuid import uuid4

from google.api_core.exceptions import NotFound
from flask import Blueprint, g, jsonify, request
from google.cloud.firestore_v1.base_query import FieldFilter

from auth_utils import require_auth
from db import SHOP_ITEMS, USERS, col, doc, now_iso, safe_delete_fields, to_dict


profile_bp = Blueprint("profile", __name__)

_PROFILE_FIELDS = {"full_name", "username", "phone", "city_id", "city_name",
                   "latitude", "longitude", "shop_name", "shop_address",
                   "address", "avatar_url", "photo_base64", "language"}


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
    if not isinstance(payload, dict) or set(payload) - _PROFILE_FIELDS:
        return jsonify({"detail": "Only editable profile fields are allowed"}), 422
    cleaned = dict(payload)
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


# Saved addresses are separate documents: legacy profile fields and responses
# remain unchanged, and editing one address cannot overwrite another address.
_ADDRESS_ID = re.compile(r"[0-9a-f]{32}")
_ADDRESS_FIELDS = {"label": 80, "address": 1000}


def _saved_addresses():
    return doc(USERS, g.user_id).collection("saved_addresses")


def _address_payload():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or set(payload) != set(_ADDRESS_FIELDS):
        return None
    cleaned = {}
    for field, limit in _ADDRESS_FIELDS.items():
        value = payload[field]
        if not isinstance(value, str) or len(value) > limit or not value.strip():
            return None
        cleaned[field] = value.strip()
    return cleaned


def _address_json(snapshot):
    data = snapshot.to_dict() or {}
    return {"id": snapshot.id, **{key: data.get(key) for key in
            ("label", "address", "created_at", "updated_at")}}


@profile_bp.get("/profile/addresses")
@require_auth
def list_saved_addresses():
    addresses = [_address_json(snap) for snap in _saved_addresses().stream()]
    return jsonify({"addresses": sorted(addresses, key=lambda value: value["id"])})


@profile_bp.post("/profile/addresses")
@require_auth
def create_saved_address():
    payload = _address_payload()
    if payload is None:
        return jsonify({"detail": "Provide only nonempty label (max 80) and address (max 1000) strings"}), 422
    timestamp = now_iso()
    data = {**payload, "created_at": timestamp, "updated_at": timestamp}
    identifier = uuid4().hex
    _saved_addresses().document(identifier).create(data)
    return jsonify({"id": identifier, **data}), 201


@profile_bp.route("/profile/addresses/<address_id>", methods=["GET", "PUT", "DELETE"])
@require_auth
def saved_address(address_id):
    if not _ADDRESS_ID.fullmatch(address_id):
        return jsonify({"detail": "Invalid address ID"}), 422
    ref = _saved_addresses().document(address_id)
    snapshot = ref.get()
    if not snapshot.exists:
        # Foreign IDs are intentionally indistinguishable from missing IDs.
        return jsonify({"detail": "Address not found"}), 404
    if request.method == "GET":
        return jsonify(_address_json(snapshot))
    if request.method == "DELETE":
        ref.delete()
        return jsonify({"ok": True})
    payload = _address_payload()
    if payload is None:
        return jsonify({"detail": "Provide only nonempty label (max 80) and address (max 1000) strings"}), 422
    changes = {**payload, "updated_at": now_iso()}
    try:
        # update requires the document to still exist, unlike set(merge=True).
        ref.update(changes)
    except NotFound:
        return jsonify({"detail": "Address not found"}), 404
    return jsonify({**_address_json(snapshot), **changes})
