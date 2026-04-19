"""`/cities/*` endpoints consumed by `CityRemoteDataSource` and AdminRemoteDataSource."""

from flask import Blueprint, g, jsonify, request

from auth_utils import require_auth, require_role
from db import CITIES, USERS, col, doc, now_iso, to_dict


cities_bp = Blueprint("cities", __name__)


def _city_payload_sans_immutable(payload: dict) -> dict:
    cleaned = {k: v for k, v in payload.items() if k not in {"id", "uid", "created_at"}}
    return cleaned


@cities_bp.get("/cities")
def list_cities():
    cities = [to_dict(d) for d in col(CITIES).stream()]
    cities.sort(key=lambda c: (c.get("name") or "").lower())
    return jsonify(cities)


@cities_bp.get("/cities/current/<user_id>")
def get_current_city(user_id):
    snap = doc(USERS, user_id).get()
    if not snap.exists:
        return jsonify({"city_id": None})
    return jsonify({"city_id": (snap.to_dict() or {}).get("city_id")})


@cities_bp.put("/cities/current")
@require_auth
def set_current_city():
    payload = request.get_json(silent=True) or {}
    city_id = payload.get("city_id")
    doc(USERS, g.user_id).set({"city_id": city_id}, merge=True)
    return jsonify({"ok": True})


@cities_bp.post("/cities")
@require_role("admin", "super_admin")
def create_city():
    payload = request.get_json(silent=True) or {}
    data = _city_payload_sans_immutable(payload)
    data.setdefault("is_active", True)
    data["created_at"] = now_iso()
    ref = col(CITIES).document()
    ref.set(data)
    body = to_dict(ref.get())
    body["id"] = ref.id  # Flutter admin datasource reads `id` before `uid`
    return jsonify(body), 201


@cities_bp.get("/cities/<city_id>")
def get_city(city_id):
    snap = doc(CITIES, city_id).get()
    if not snap.exists:
        return jsonify({"detail": "City not found"}), 404
    body = to_dict(snap)
    body["id"] = snap.id
    return jsonify(body)


@cities_bp.put("/cities/<city_id>")
@require_role("admin", "super_admin")
def update_city(city_id):
    payload = request.get_json(silent=True) or {}
    data = _city_payload_sans_immutable(payload)
    data["updated_at"] = now_iso()
    doc(CITIES, city_id).set(data, merge=True)
    return jsonify({"ok": True})
