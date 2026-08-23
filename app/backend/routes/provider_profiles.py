"""`/provider/profile` endpoints for LocalShop V2 Provider Capability."""

from flask import Blueprint, g, jsonify, request

from auth_utils import require_auth
from db import col, doc, now_iso, to_dict

provider_profiles_bp = Blueprint("provider_profiles", __name__)

PROVIDER_PROFILES = "provider_profiles"


@provider_profiles_bp.get("/provider/profile")
@require_auth
def get_provider_profile():
    """Retrieve the authenticated user's provider capability profile."""
    snap = doc(PROVIDER_PROFILES, g.user_id).get()

    if not snap.exists:
        return jsonify({"detail": "Provider profile not found"}), 404

    return jsonify(to_dict(snap))


@provider_profiles_bp.put("/provider/profile")
@require_auth
def update_provider_profile():
    """Create or update the authenticated user's provider capability profile."""
    payload = request.get_json(silent=True) or {}

    allowed_fields = {"location", "service_category_ids", "bank", "working_schedule"}
    data = {k: v for k, v in payload.items() if k in allowed_fields}

    # Safely handle boolean deactivation/activation
    if "is_active" in payload:
        data["is_active"] = bool(payload.get("is_active"))

    ref = doc(PROVIDER_PROFILES, g.user_id)
    snap = ref.get()

    if not snap.exists:
        # Initial provider activation
        data["created_at"] = now_iso()
        data.setdefault("is_active", True)

    data["updated_at"] = now_iso()

    ref.set(data, merge=True)

    return jsonify(to_dict(ref.get())), 200