"""Provider capability profiles and bounded request validation."""

import math
import re
from datetime import datetime

from flask import Blueprint, g, jsonify, request

from auth_utils import require_auth
from db import doc, now_iso, to_dict

provider_profiles_bp = Blueprint("provider_profiles", __name__)
PROVIDER_PROFILES = "provider_profiles"


class ValidationError(Exception):
    def __init__(self, detail, status=422):
        self.detail, self.status = detail, status


def validation_response(error):
    return jsonify({"detail": error.detail}), error.status


provider_profiles_bp.register_error_handler(ValidationError, validation_response)


def valid_id(value, field="id"):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", value) or value in (".", ".."):
        raise ValidationError(f"{field} must be a valid document ID")
    return value


def json_object(allowed=None):
    if len(request.get_data(cache=True)) > 65536:
        raise ValidationError("Request body exceeds 64 KiB", 413)
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise ValidationError("Request body must be a JSON object")
    if allowed is not None and set(payload) - allowed:
        raise ValidationError("Unknown or read-only fields: " + ", ".join(sorted(set(payload) - allowed)))
    return payload


def text(value, field, maximum, required=False):
    if value is None and not required:
        return ""
    if not isinstance(value, str) or len(value.strip()) > maximum or (required and not value.strip()):
        raise ValidationError(f"{field} must be text {'with a value ' if required else ''}up to {maximum} characters")
    return value.strip()


def finite_number(value, field, low=0, high=10_000_000):
    if isinstance(value, bool):
        raise ValidationError(f"{field} must be a finite number")
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValidationError(f"{field} must be a finite number")
    if not math.isfinite(value) or not low <= value <= high:
        raise ValidationError(f"{field} must be between {low} and {high}")
    return value


def schedule(value):
    if not isinstance(value, dict) or set(value) - {"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"}:
        raise ValidationError("working_schedule must map Mon through Sun to daily schedules")
    result = {}
    for weekday, day in value.items():
        if not isinstance(day, dict) or set(day) - {"from", "to", "closed"}:
            raise ValidationError("Each schedule day accepts from, to and closed")
        if "closed" in day and not isinstance(day["closed"], bool):
            raise ValidationError("closed must be true or false")
        if day.get("closed"):
            result[weekday] = {"closed": True}
            continue
        try:
            start = datetime.strptime(day["from"], "%I:%M %p")
            end = datetime.strptime(day["to"], "%I:%M %p")
        except (KeyError, TypeError, ValueError):
            raise ValidationError("Open days require from and to in hh:mm AM/PM format")
        if start >= end or start.minute not in (0, 30) or end.minute not in (0, 30):
            raise ValidationError("Schedule must contain aligned 30-minute intervals within one day")
        result[weekday] = {"from": start.strftime("%I:%M %p"), "to": end.strftime("%I:%M %p"), "closed": False}
    return result


@provider_profiles_bp.get("/provider/profile")
@require_auth
def get_provider_profile():
    snap = doc(PROVIDER_PROFILES, g.user_id).get()
    if not snap.exists:
        return jsonify({"detail": "Provider profile not found"}), 404
    return jsonify(to_dict(snap))


@provider_profiles_bp.put("/provider/profile")
@require_auth
def update_provider_profile():
    payload = json_object({"location", "service_category_ids", "bank", "working_schedule", "is_active"})
    data = {}
    if "location" in payload:
        location = payload["location"]
        if isinstance(location, str):
            data["location"] = text(location, "location", 500)
        elif isinstance(location, dict) and set(location) <= {"latitude", "longitude", "address"}:
            data["location"] = {
                "latitude": finite_number(location.get("latitude"), "latitude", -90, 90),
                "longitude": finite_number(location.get("longitude"), "longitude", -180, 180),
            }
            if "address" in location:
                data["location"]["address"] = text(location["address"], "address", 500)
        else:
            raise ValidationError("location must be text or latitude/longitude coordinates")
    if "service_category_ids" in payload:
        values = payload["service_category_ids"]
        if not isinstance(values, list) or len(values) > 30:
            raise ValidationError("service_category_ids must be a list of at most 30 IDs")
        values = [valid_id(value, "service_category_id") for value in values]
        if len(set(values)) != len(values):
            raise ValidationError("Duplicate service categories are not allowed")
        data["service_category_ids"] = values
    if "working_schedule" in payload:
        data["working_schedule"] = schedule(payload["working_schedule"])
    if "bank" in payload:
        bank = payload["bank"]
        if not isinstance(bank, dict) or len(bank) > 10:
            raise ValidationError("bank must be an object of at most 10 text fields")
        data["bank"] = {text(key, "bank field", 50, True): text(value, "bank value", 150) for key, value in bank.items()}
    if "is_active" in payload:
        if not isinstance(payload["is_active"], bool):
            raise ValidationError("is_active must be true or false")
        data["is_active"] = payload["is_active"]
    if not data:
        raise ValidationError("At least one profile field is required")
    ref = doc(PROVIDER_PROFILES, g.user_id)
    snap = ref.get()
    if not snap.exists:
        data["created_at"] = now_iso()
        data.setdefault("is_active", True)
    data["updated_at"] = now_iso()
    ref.set(data, merge=True)
    return jsonify(to_dict(ref.get()))
