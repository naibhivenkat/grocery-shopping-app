"""City catalog and authenticated, private current-city preferences."""

from flask import Blueprint, g, jsonify, request

from auth_utils import require_auth, require_role
from db import CITIES, USERS, col, doc, now_iso, to_dict
from routes.provider_profiles import ValidationError, validation_response, valid_id, json_object, text, finite_number

cities_bp = Blueprint("cities", __name__)
cities_bp.register_error_handler(ValidationError, validation_response)
CITY_FIELDS = {"name", "state", "country", "latitude", "longitude", "is_active"}


def _city_payload(current=None):
    # Existing admin models send immutable presentation fields; ignore those.
    payload = json_object(CITY_FIELDS | {"id", "uid", "created_at", "updated_at"})
    content = {**(current or {}), **{key: value for key, value in payload.items() if key in CITY_FIELDS}}
    result = {"name": text(content.get("name"), "name", 100, True),
        "state": text(content.get("state"), "state", 100),
        "country": text(content.get("country", "India"), "country", 100),
        "latitude": finite_number(content.get("latitude", 0), "latitude", -90, 90),
        "longitude": finite_number(content.get("longitude", 0), "longitude", -180, 180),
        "is_active": content.get("is_active", True)}
    if not isinstance(result["is_active"], bool):
        raise ValidationError("is_active must be true or false")
    return result


@cities_bp.get("/cities")
def list_cities():
    include_inactive = request.args.get("include_inactive") == "true"
    cities = []
    for snapshot in col(CITIES).stream():
        city = to_dict(snapshot)
        if not include_inactive and city.get("is_active") is False:
            continue
        cities.append(city)
    cities.sort(key=lambda city: str(city.get("name") or "").lower())
    return jsonify(cities)


@cities_bp.get("/cities/current/<user_id>")
@require_auth
def get_current_city(user_id):
    valid_id(user_id, "user_id")
    if user_id != g.user_id and g.user_role not in ("admin", "super_admin"):
        raise ValidationError("You cannot view another user's city", 403)
    snapshot = doc(USERS, user_id).get()
    return jsonify({"city_id": (snapshot.to_dict() or {}).get("city_id") if snapshot.exists else None})


@cities_bp.put("/cities/current")
@require_auth
def set_current_city():
    payload = json_object({"city_id"})
    if "city_id" not in payload:
        raise ValidationError("city_id is required; use null to clear it")
    city_id = payload["city_id"]
    if city_id is not None:
        valid_id(city_id, "city_id")
        snapshot = doc(CITIES, city_id).get()
        if not snapshot.exists or (snapshot.to_dict() or {}).get("is_active") is False:
            raise ValidationError("City is not available", 404)
    doc(USERS, g.user_id).update({"city_id": city_id})
    return jsonify({"ok": True})


@cities_bp.post("/cities")
@require_role("admin", "super_admin")
def create_city():
    data = _city_payload()
    data["created_at"] = now_iso()
    ref = col(CITIES).document()
    ref.set(data)
    return jsonify({**to_dict(ref.get()), "id": ref.id}), 201


@cities_bp.get("/cities/<city_id>")
def get_city(city_id):
    valid_id(city_id, "city_id")
    snapshot = doc(CITIES, city_id).get()
    if not snapshot.exists:
        raise ValidationError("City not found", 404)
    return jsonify({**to_dict(snapshot), "id": snapshot.id})


@cities_bp.put("/cities/<city_id>")
@require_role("admin", "super_admin")
def update_city(city_id):
    valid_id(city_id, "city_id")
    ref = doc(CITIES, city_id)
    snapshot = ref.get()
    if not snapshot.exists:
        raise ValidationError("City not found", 404)
    data = _city_payload(snapshot.to_dict() or {})
    data["updated_at"] = now_iso()
    ref.update(data)
    return jsonify({"ok": True})
