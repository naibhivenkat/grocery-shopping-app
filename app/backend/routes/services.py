"""`/services` and `/provider/services` endpoints for LocalShop V2."""

from flask import Blueprint, g, jsonify, request, current_app
from google.cloud.firestore_v1.base_query import FieldFilter

from auth_utils import require_auth
from db import USERS, USER_FAVORITES, col, doc, now_iso, to_dict
from routes.provider_profiles import ValidationError, validation_response, valid_id, json_object, text, finite_number, schedule
from routes.bookings import _calculate_service_cost

services_bp = Blueprint("services", __name__)

services_bp.register_error_handler(ValidationError, validation_response)

PROVIDER_SERVICES = "provider_services"
PROVIDER_PROFILES = "provider_profiles"


SERVICE_FIELDS = {
    "title", "description", "service_category_id", "pricing_unit", "pricing_type", "fixed_price", "min_price",
    "hourly_price", "per_30min_price", "minimum_charge", "inspection_charge", "working_schedule", "is_active",
}


def _provider_data(user_id):
    valid_id(user_id, "provider_id")
    user = doc(USERS, user_id).get()
    profile = doc(PROVIDER_PROFILES, user_id).get()
    user_data = user.to_dict() or {} if user.exists else {}
    profile_data = profile.to_dict() or {} if profile.exists else {}
    if not user.exists or not profile.exists or user_data.get("is_suspended") or profile_data.get("is_active") is False:
        return None
    return user_data, profile_data


def _service_content(payload, current=None):
    data = dict(current or {})
    data.update(payload)
    data["title"] = text(data.get("title"), "title", 120, True)
    data["description"] = text(data.get("description"), "description", 2000)
    category = data.get("service_category_id")
    if category in (None, ""):
        category = ""
    else:
        valid_id(category, "service_category_id")
    data["service_category_id"] = category
    pricing_type = data.get("pricing_type", "fixed")
    if pricing_type not in ("fixed", "visit", "hourly", "per_30min", "time_based"):
        raise ValidationError("Invalid pricing_type")
    data["pricing_type"] = pricing_type
    data["pricing_unit"] = text(data.get("pricing_unit", pricing_type), "pricing_unit", 30, True)
    for field in ("fixed_price", "hourly_price", "per_30min_price", "minimum_charge", "inspection_charge"):
        data[field] = finite_number(data.get(field) if data.get(field) not in (None, "") else 0, field)
    data["min_price"] = None if data.get("min_price") in (None, "") else finite_number(data["min_price"], "min_price")
    if not isinstance(data.get("is_active", True), bool):
        raise ValidationError("is_active must be true or false")
    data["is_active"] = data.get("is_active", True)
    if data.get("working_schedule") is not None:
        data["working_schedule"] = schedule(data["working_schedule"])
    try:
        _calculate_service_cost(data, 30)
    except ValueError as error:
        raise ValidationError(str(error))
    return {field: data.get(field) for field in SERVICE_FIELDS}


@services_bp.post("/provider/services")
@require_auth
def create_service():
    if not _provider_data(g.user_id):
        raise ValidationError("An active provider profile is required", 403)
    data = _service_content(json_object(SERVICE_FIELDS))
    ref = col(PROVIDER_SERVICES).document()
    timestamp = now_iso()
    data.update({"provider_id": g.user_id, "is_deleted": False, "created_at": timestamp, "updated_at": timestamp})
    ref.set(data)
    return jsonify({**data, "id": ref.id}), 201


@services_bp.put("/provider/services/<service_id>")
@require_auth
def update_service(service_id):
    valid_id(service_id, "service_id")
    ref = doc(PROVIDER_SERVICES, service_id)
    snapshot = ref.get()
    if not snapshot.exists:
        raise ValidationError("Service not found", 404)
    current = snapshot.to_dict() or {}
    if current.get("provider_id") != g.user_id:
        raise ValidationError("You do not own this service", 403)
    if current.get("is_deleted"):
        raise ValidationError("Service not found", 404)
    if not _provider_data(g.user_id):
        raise ValidationError("An active provider profile is required", 403)
    payload = json_object(SERVICE_FIELDS)
    if not payload:
        raise ValidationError("At least one service field is required")
    data = _service_content(payload, current)
    data["updated_at"] = now_iso()
    ref.update(data)
    return jsonify({**(ref.get().to_dict() or {}), "id": service_id})


@services_bp.delete("/provider/services/<service_id>")
@require_auth
def delete_service(service_id):
    """Soft-delete an existing service. Verifies ownership."""
    valid_id(service_id, "service_id")
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
    if not _provider_data(provider_id):
        return jsonify([])
    query = col(PROVIDER_SERVICES).where(
        filter=FieldFilter("provider_id", "==", provider_id)
    ).where(filter=FieldFilter("is_deleted", "==", False))

    services = []
    for s in query.stream():
        data = s.to_dict() or {}
        if data.get("is_active") is False:
            continue
        try:
            data.update(_service_content({}, data))
        except ValidationError:
            continue
        data["id"] = s.id
        services.append(data)

    return jsonify(services), 200


@services_bp.get("/services/available")
def discover_available_services():
    """Public discovery of available services.

    Without category_id:
        Returns all active, non-deleted provider services.

    With category_id:
        Returns only active, non-deleted services belonging to that category.

    If a valid JWT is supplied, the authenticated provider's own services
    are excluded to prevent self-booking.
    """
    category_id = request.args.get("category_id")
    if category_id:
        valid_id(category_id, "category_id")

    # Optional Auth check to exclude self-booking listings seamlessly.
    actor_id = None
    auth_header = request.headers.get("Authorization", "")

    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()

        try:
            from auth_utils import decode_token

            payload = decode_token(token)
            actor_id = payload.get("sub")
        except Exception:
            # Public endpoint: invalid/missing optional auth should not fail
            # the service discovery request.
            pass

    # Base query:
    # - service must not be deleted
    # - service must be active
    query = col(PROVIDER_SERVICES).where(
        filter=FieldFilter("is_deleted", "==", False)
    ).where(
        filter=FieldFilter("is_active", "==", True)
    )

    # Category is optional.
    # If provided, filter by category.
    if category_id:
        query = query.where(
            filter=FieldFilter(
                "service_category_id",
                "==",
                category_id,
            )
        )

    result = []

    for s in query.stream():
        data = s.to_dict() or {}
        provider_id = data.get("provider_id")

        # Skip malformed service documents without a provider.
        if not provider_id:
            continue
        try:
            available_provider = _provider_data(provider_id)
            data.update(_service_content({}, data))
        except (ValidationError, ValueError):
            continue
        if not available_provider:
            continue

        # Exclude own services to prevent self-booking visibility.
        if actor_id and provider_id == actor_id:
            continue

        # Look up canonical user and provider profile.
        user_data, prof_data = available_provider

        # Preserve the existing Flutter contract.
        result.append({
            "id": s.id,

            # Service information
            "service_name": data.get("title"),
            "description": data.get("description", ""),
            "service_category_id": data.get("service_category_id"),

            # Provider information
            "provider_id": provider_id,
            "provider_name": (
                user_data.get("full_name")
                or user_data.get("username")
                or "Provider"
            ),

            "location": prof_data.get("location"),

            "photo_base64": (
                user_data.get("avatar_url")
                or user_data.get("photo_base64")
            ),

            # Pricing
            "fixed_price": data.get("fixed_price"),
            "min_price": data.get("min_price"),
            "pricing_unit": data.get("pricing_unit"),
            "pricing_type": data.get("pricing_type", "fixed"),
            "hourly_price": data.get("hourly_price", 0),
            "per_30min_price": data.get("per_30min_price", 0),
            "minimum_charge": data.get("minimum_charge", 0),
            "inspection_charge": data.get("inspection_charge", 0),

            # Provider metadata
            "rating": _rating(
                user_data.get("rating")
                or prof_data.get("rating")
            ),

            "completed_jobs": prof_data.get(
                "completed_jobs",
                0,
            ),

            "verified": prof_data.get(
                "is_verified",
                False,
            ),

            # Provider availability
            "available_today": prof_data.get(
                "is_active",
                True,
            ),
        })

    # Sort:
    # 1. Available today first
    # 2. Higher-rated providers first
    result.sort(
        key=lambda x: (
            not x.get("available_today", True),
            -_rating(x.get("rating")),
        )
    )

    return jsonify(result), 200

def _rating(value):
    try:
        return finite_number(value or 0, "rating", 0, 5)
    except ValidationError:
        return 0


@services_bp.get("/services/<service_id>")
def get_service_detail(service_id):
    valid_id(service_id, "service_id")
    snap = doc(PROVIDER_SERVICES, service_id).get()
    data = snap.to_dict() or {} if snap.exists else {}
    if not snap.exists or data.get("is_deleted") or data.get("is_active") is False:
        raise ValidationError("Service not found", 404)
    provider = _provider_data(data.get("provider_id"))
    if not provider:
        raise ValidationError("Service not available", 404)
    user, profile = provider
    try:
        data.update(_service_content({}, data))
    except ValidationError:
        raise ValidationError("Service not available", 404)
    return jsonify({**data, "id": snap.id,
        "provider_name": user.get("full_name") or user.get("username") or "Provider",
        "location": profile.get("location"), "photo_base64": user.get("avatar_url") or user.get("photo_base64"),
    })


@services_bp.post("/services/calculate-price")
def calculate_price():
    body = json_object({"service_id", "duration"})
    service_id = valid_id(body.get("service_id"), "service_id")
    duration = body.get("duration", 60)
    if isinstance(duration, bool) or not isinstance(duration, int) or not 30 <= duration <= 480 or duration % 30:
        raise ValidationError("duration must be 30-minute intervals up to 8 hours")
    snap = doc(PROVIDER_SERVICES, service_id).get()
    svc = snap.to_dict() or {} if snap.exists else {}
    if not snap.exists or svc.get("is_deleted") or svc.get("is_active") is False or not _provider_data(svc.get("provider_id")):
        raise ValidationError("Service not available", 404)
    try:
        base = _calculate_service_cost(svc, duration)
    except ValueError as error:
        raise ValidationError(str(error))
    fee = round(base * 0.05, 2)
    tax = round((base + fee) * 0.18, 2)
    total = round(base + fee + tax, 2)
    if total > 10_000_000:
        raise ValidationError("Quote exceeds the payment limit")
    return jsonify({"service_cost": base, "platform_fee": fee, "tax": tax,
        "total_cost": total, "pricing_type": svc.get("pricing_type", "fixed"),
        "visit_charge": svc.get("inspection_charge", 0), "hourly_price": svc.get("hourly_price", 0),
        "per_30min_price": svc.get("per_30min_price", 0), "minimum_charge": svc.get("minimum_charge", 0),
    })


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

        if not user_snap.exists or not prof_snap.exists:
            continue

        user_data = user_snap.to_dict() or {}
        prof_data = prof_snap.to_dict() or {} if prof_snap.exists else {}

        if user_data.get("is_suspended") or prof_data.get("is_active") is False:
            continue
        # Preserve the ProviderEntity-compatible fields expected by Flutter
        providers.append({
            "id": provider_id,
            "provider_id": provider_id,
            "provider_name": user_data.get("full_name") or user_data.get("username") or "Provider",
            "location": prof_data.get("location"),
            "photo_base64": user_data.get("avatar_url") or user_data.get("photo_base64"),
            "rating": _rating(user_data.get("rating") or prof_data.get("rating")),
            "completed_jobs": prof_data.get("completed_jobs", 0),
            "verified": prof_data.get("is_verified", False),
            "available_today": prof_data.get("is_active", True),
        })

    return jsonify({"providers": providers}), 200


@services_bp.post("/services/favourites/add")
@require_auth
def add_favourite():
    """Add a provider to the authenticated user's favourites."""
    payload = json_object({"provider_id"})
    provider_id = valid_id(payload.get("provider_id"), "provider_id")

    if not provider_id:
        return jsonify({"detail": "provider_id is required"}), 400

    if not _provider_data(provider_id):
        raise ValidationError("Provider not available", 404)
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
    payload = json_object({"provider_id"})
    provider_id = valid_id(payload.get("provider_id"), "provider_id")

    if not provider_id:
        return jsonify({"detail": "provider_id is required"}), 400

    fav_id = f"{g.user_id}_{provider_id}"

    # Deleting a non-existent document in Firestore does not throw an error, making this idempotent
    doc(USER_FAVORITES, fav_id).delete()

    return jsonify({"success": True, "detail": "Provider removed from favourites"}), 200

@services_bp.get("/services/addresses")
@require_auth
def get_customer_addresses():
    """Return saved addresses for a customer."""
    customer_id = valid_id(request.args.get("customer_id"), "customer_id")
    if customer_id != g.user_id and g.user_role not in ("admin", "super_admin"):
        raise ValidationError("You cannot view another customer's addresses", 403)

    if not customer_id:
        return jsonify({
            "detail": "customer_id is required"
        }), 400

    try:
        customer_snap = doc(USERS, customer_id).get()

        if not customer_snap.exists:
            return jsonify({
                "addresses": []
            }), 200

        customer_data = customer_snap.to_dict() or {}

        addresses = customer_data.get("addresses", [])

        if not isinstance(addresses, list):
            addresses = []

        return jsonify({
            "addresses": addresses
        }), 200

    except Exception as e:
        current_app.logger.exception(
            "Failed to get addresses for customer %s",
            customer_id,
        )

        return jsonify({
            "detail": "Failed to retrieve customer addresses"
        }), 500
