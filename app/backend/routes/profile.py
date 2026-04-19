"""`/profile` endpoints consumed by `ProfileRemoteDataSource`."""

from flask import Blueprint, g, jsonify, request

from auth_utils import require_auth
from db import USERS, doc, now_iso, safe_delete_fields, to_dict


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
    return jsonify({"ok": True})
