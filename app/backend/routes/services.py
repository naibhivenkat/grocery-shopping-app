"""`/services` and `/provider/services` endpoints for LocalShop V2."""

from flask import Blueprint, g, jsonify, request
from google.cloud.firestore_v1.base_query import FieldFilter

from auth_utils import require_auth
from db import USERS, USER_FAVORITES, col, doc, now_iso, to_dict

services_bp = Blueprint("services", __name__)

PROVIDER_SERVICES = "provider_services"
PROVIDER_PROFILES = "provider_profiles"


def _check_provider_capability(user_id: str) -> bool:
    """Verifies the authenticated user has activated provider capability."""
    return doc(PROVIDER_PROFILES, user_id).get().exists


@services_bp.post("/provider/services")
@require_auth
def create_service():
    """Create a new service. Actor is strictly g.user_id."""
    if not _check_provider_capability(g.user_id):
        return jsonify({"detail": "Provider profile required to create services"}), 403

    payload = request.get_json(silent=True) or {}

    # Ignore any client-supplied provider_id
    # Enforce canonical identity mapping
    provider_id = g.user_id
    service_ref = col(PROVIDER_SERVICES).document()

    # Safe float extraction matching legacy pricing engine preservation
    try:
        fixed_price = float(payload.get("fixed_price")) if payload.get("fixed_price") not in [None, ""] else 0.0
        min_price = float(payload.get("min_price")) if payload.get("min_price") not in [None, ""] else None
        hourly_price = float(payload.get("hourly_price")) if payload.get("hourly_price") not in [None, ""] else 0.0
        per_30min_price = float(payload.get("per_30min_price") or 0.0)
        minimum_charge = float(payload.get("minimum_charge")) if payload.get("minimum_charge") not in [None,
                                                                                                       ""] else 0.0
        inspection_charge = float(payload.get("inspection_charge") or 0.0)
    except (TypeError, ValueError):
        return jsonify({"detail": "Invalid pricing format"}), 400

    service_data = {
        "provider_id": provider_id,
        "service_category_id": payload.get("service_category_id", ""),
        "title": payload.get("title", ""),
        "description": payload.get("description", ""),

        "fixed_price": fixed_price,
        "pricing_unit": payload.get("pricing_unit", "fixed"),
        "min_price": min_price,

        "pricing_type": payload.get("pricing_type", "fixed"),
        "hourly_price": hourly_price,
        "per_30min_price": per_30min_price,
        "minimum_charge": minimum_charge,
        "inspection_charge": inspection_charge,

        "working_schedule": payload.get("working_schedule"),
        "is_active": bool(payload.get("is_active", True)),
        "is_deleted": False,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }

    service_ref.set(service_data)

    return jsonify({**service_data, "id": service_ref.id}), 201


@services_bp.put("/provider/services/<service_id>")
@require_auth
def update_service(service_id):
    """Update an existing service. Verifies ownership."""
    snap = doc(PROVIDER_SERVICES, service_id).get()
    if not snap.exists:
        return jsonify({"detail": "Service not found"}), 404

    current_data = snap.to_dict() or {}

    # Ownership Check
    if current_data.get("provider_id") != g.user_id:
        return jsonify({"detail": "Forbidden: You do not own this service"}), 403

    payload = request.get_json(silent=True) or {}
    updates = {"updated_at": now_iso()}

    # Safe updates mapping
    if "title" in payload:
        updates["title"] = payload["title"]
    if "description" in payload:
        updates["description"] = payload["description"]
    if "service_category_id" in payload:
        updates["service_category_id"] = payload["service_category_id"]
    if "pricing_unit" in payload:
        updates["pricing_unit"] = payload["pricing_unit"]
    if "pricing_type" in payload:
        updates["pricing_type"] = payload["pricing_type"]
    if "working_schedule" in payload:
        updates["working_schedule"] = payload["working_schedule"]
    if "is_active" in payload:
        updates["is_active"] = bool(payload["is_active"])

    try:
        if "fixed_price" in payload:
            updates["fixed_price"] = float(payload["fixed_price"]) if payload["fixed_price"] not in [None, ""] else 0.0
        if "min_price" in payload:
            updates["min_price"] = float(payload["min_price"]) if payload["min_price"] not in [None, ""] else None
        if "hourly_price" in payload:
            updates["hourly_price"] = float(payload["hourly_price"]) if payload["hourly_price"] not in [None,
                                                                                                        ""] else 0.0
        if "per_30min_price" in payload:
            updates["per_30min_price"] = float(payload.get("per_30min_price") or 0.0)
        if "minimum_charge" in payload:
            updates["minimum_charge"] = float(payload["minimum_charge"]) if payload["minimum_charge"] not in [None,
                                                                                                              ""] else 0.0
        if "inspection_charge" in payload:
            updates["inspection_charge"] = float(payload.get("inspection_charge") or 0.0)
    except (TypeError, ValueError):
        return jsonify({"detail": "Invalid pricing format"}), 400

    doc(PROVIDER_SERVICES, service_id).set(updates, merge=True)

    updated_snap = doc(PROVIDER_SERVICES, service_id).get()
    return jsonify({**updated_snap.to_dict(), "id": service_id}), 200


@services_bp.delete("/provider/services/<service_id>")
@require_auth
def delete_service(service_id):
    """Soft-delete an existing service. Verifies ownership."""
    snap = doc(PROVIDER_SERVICES, service_id).get()
    if not snap.exists:
        return jsonify({"detail": "Service not found"}), 404

    if (snap.to_dict() or {}).get("provider_id") != g.user_id:
        return jsonify({"detail": "Forbidden: You do not own this service"}), 403

    doc(PROVIDER_SERVICES, service_id).update({
        "is_deleted": True,
        "updated_at": now_iso()
    })

    return jsonify({"detail": "Service successfully deleted"}), 200


@services_bp.get("/provider/services")
@require_auth
def list_own_services():
    """List services belonging to the authenticated provider."""
    query = col(PROVIDER_SERVICES).where(
        filter=FieldFilter("provider_id", "==", g.user_id)
    ).where(filter=FieldFilter("is_deleted", "==", False))

    services = []
    for s in query.stream():
        data = s.to_dict() or {}
        data["id"] = s.id
        services.append(data)

    return jsonify(services), 200


@services_bp.get("/providers/<provider_id>/services")
def list_target_provider_services(provider_id):
    """List public services belonging to a specific provider."""
    query = col(PROVIDER_SERVICES).where(
        filter=FieldFilter("provider_id", "==", provider_id)
    ).where(filter=FieldFilter("is_deleted", "==", False))

    services = []
    for s in query.stream():
        data = s.to_dict() or {}
        data["id"] = s.id
        services.append(data)

    return jsonify(services), 200


@services_bp.get("/services/available")
def discover_available_services():
    """Public discovery of available services. Filters out own services if JWT is passed."""
    category_id = request.args.get("category_id")
    if not category_id:
        return jsonify({"detail": "category_id required"}), 400

    # Optional Auth check to exclude self-booking listings seamlessly
    actor_id = None
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        try:
            from auth_utils import decode_token
            payload = decode_token(token)
            actor_id = payload.get("sub")
        except Exception:
            pass  # Fail silently for public endpoint; it's optional

    query = col(PROVIDER_SERVICES).where(
        filter=FieldFilter("service_category_id", "==", category_id)
    ).where(filter=FieldFilter("is_deleted", "==", False))

    result = []
    for s in query.stream():
        data = s.to_dict() or {}
        provider_id = data.get("provider_id")

        # Exclude own services to prevent self-booking visibility
        if actor_id and provider_id == actor_id:
            continue

        # Look up canonical user and provider profile
        user_snap = doc(USERS, provider_id).get()
        prof_snap = doc(PROVIDER_PROFILES, provider_id).get()

        user_data = user_snap.to_dict() or {} if user_snap.exists else {}
        prof_data = prof_snap.to_dict() or {} if prof_snap.exists else {}

        # Preserve legacy Flutter contract output fields
        result.append({
            "id": s.id,
            "service_name": data.get("title"),
            "provider_id": provider_id,
            "provider_name": user_data.get("full_name") or user_data.get("username") or "Provider",
            "location": prof_data.get("location"),
            "photo_base64": user_data.get("avatar_url") or user_data.get("photo_base64"),
            "fixed_price": data.get("fixed_price"),
            "min_price": data.get("min_price"),
            "pricing_unit": data.get("pricing_unit"),
            "rating": user_data.get("rating") or prof_data.get("rating"),
            "completed_jobs": prof_data.get("completed_jobs", 0),
            "verified": prof_data.get("is_verified", False),
            "available_today": prof_data.get("is_active", True),
        })

    # Sort logic matching legacy system
    result.sort(key=lambda x: (
        not x.get("available_today", True),
        -(x.get("rating") or 0)
    ))

    return jsonify(result), 200


@services_bp.get("/services/<service_id>")
def get_service_detail(service_id):
    """Get details of a specific service."""
    snap = doc(PROVIDER_SERVICES, service_id).get()
    if not snap.exists or snap.to_dict().get("is_deleted"):
        return jsonify({"detail": "Service not found"}), 404

    data = snap.to_dict() or {}
    data["id"] = snap.id

    provider_id = data.get("provider_id")
    if provider_id:
        user_snap = doc(USERS, provider_id).get()
        prof_snap = doc(PROVIDER_PROFILES, provider_id).get()

        user_data = user_snap.to_dict() or {} if user_snap.exists else {}
        prof_data = prof_snap.to_dict() or {} if prof_snap.exists else {}

        # Merge canonical identity presentation
        data["provider_name"] = user_data.get("full_name") or user_data.get("username") or "Provider"
        data["location"] = prof_data.get("location")
        data["photo_base64"] = user_data.get("avatar_url") or user_data.get("photo_base64")

    return jsonify(data), 200


@services_bp.post("/services/calculate-price")
def calculate_price():
    """Preserved legacy pricing logic wrapped in V2 endpoint."""
    body = request.get_json(silent=True) or {}
    service_id = body.get("service_id")

    try:
        duration = int(body.get("duration", 60))
    except (TypeError, ValueError):
        duration = 60

    if not service_id:
        return jsonify({"detail": "service_id required"}), 400

    snap = doc(PROVIDER_SERVICES, service_id).get()
    if not snap.exists:
        return jsonify({"detail": "Service not found"}), 404

    svc = snap.to_dict() or {}

    pricing_type = svc.get("pricing_type", "fixed")
    fixed_price = float(svc.get("fixed_price", 0))
    hourly_price = float(svc.get("hourly_price", 0))
    per_30 = float(svc.get("per_30min_price", 0))
    min_charge = float(svc.get("minimum_charge", 0))
    visit_charge = float(svc.get("inspection_charge", 0))

    if pricing_type == "fixed":
        base = fixed_price
    elif pricing_type == "visit":
        base = visit_charge
    else:
        hours = duration / 60
        if per_30 > 0:
            cost = (duration / 30) * per_30
        else:
            cost = hours * hourly_price

        if cost < min_charge:
            cost = min_charge

        base = round(cost, 2)

    platform_fee = base * 0.05
    tax = base * 0.18
    total = base + platform_fee + tax

    return jsonify({
        "service_cost": round(base, 2),
        "platform_fee": round(platform_fee, 2),
        "tax": round(tax, 2),
        "total_cost": round(total, 2),
        "pricing_type": pricing_type,
        "visit_charge": visit_charge,
        "hourly_price": hourly_price,
        "per_30min_price": per_30,
        "minimum_charge": min_charge
    }), 200


@services_bp.get("/services/favourites")
@require_auth
def get_favourites():
    """Get the authenticated user's favourite providers."""
    # Fetch all favourites for the authenticated user
    query = col(USER_FAVORITES).where(filter=FieldFilter("user_id", "==", g.user_id))

    providers = []
    for fav_snap in query.stream():
        fav_data = fav_snap.to_dict() or {}
        provider_id = fav_data.get("provider_id")

        # Skip if this is a shop item favourite (which would have an item_id instead)
        if not provider_id:
            continue

        # Look up provider details
        user_snap = doc(USERS, provider_id).get()
        prof_snap = doc(PROVIDER_PROFILES, provider_id).get()

        if not user_snap.exists:
            continue

        user_data = user_snap.to_dict() or {}
        prof_data = prof_snap.to_dict() or {} if prof_snap.exists else {}

        # Preserve the ProviderEntity-compatible fields expected by Flutter
        providers.append({
            "id": provider_id,
            "provider_id": provider_id,
            "provider_name": user_data.get("full_name") or user_data.get("username") or "Provider",
            "location": prof_data.get("location"),
            "photo_base64": user_data.get("avatar_url") or user_data.get("photo_base64"),
            "rating": user_data.get("rating") or prof_data.get("rating"),
            "completed_jobs": prof_data.get("completed_jobs", 0),
            "verified": prof_data.get("is_verified", False),
            "available_today": prof_data.get("is_active", True),
        })

    return jsonify({"providers": providers}), 200


@services_bp.post("/services/favourites/add")
@require_auth
def add_favourite():
    """Add a provider to the authenticated user's favourites."""
    payload = request.get_json(silent=True) or {}
    provider_id = payload.get("provider_id")

    if not provider_id:
        return jsonify({"detail": "provider_id is required"}), 400

    # Idempotent document ID merging user and provider
    fav_id = f"{g.user_id}_{provider_id}"

    doc(USER_FAVORITES, fav_id).set({
        "user_id": g.user_id,
        "provider_id": provider_id,
        "type": "provider",
        "created_at": now_iso()
    }, merge=True)

    return jsonify({"success": True, "detail": "Provider added to favourites"}), 200


@services_bp.post("/services/favourites/remove")
@require_auth
def remove_favourite():
    """Remove a provider from the authenticated user's favourites."""
    payload = request.get_json(silent=True) or {}
    provider_id = payload.get("provider_id")

    if not provider_id:
        return jsonify({"detail": "provider_id is required"}), 400

    fav_id = f"{g.user_id}_{provider_id}"

    # Deleting a non-existent document in Firestore does not throw an error, making this idempotent
    doc(USER_FAVORITES, fav_id).delete()

    return jsonify({"success": True, "detail": "Provider removed from favourites"}), 200