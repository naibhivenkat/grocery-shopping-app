"""`/auth/*` endpoints consumed by `AuthRemoteDataSource` (Flutter)."""

from flask import Blueprint, g, jsonify, request
from google.cloud.firestore_v1.base_query import FieldFilter

from auth_utils import create_token, hash_password, require_auth, verify_password
from db import USERS, col, doc, now_iso, safe_delete_fields, to_dict


auth_bp = Blueprint("auth", __name__)

_ALLOWED_ROLES = {"customer", "vendor", "admin", "super_admin"}


def _find_user_by_email(email: str):
    email = (email or "").strip().lower()
    if not email:
        return None
    query = (
        col(USERS)
        .where(filter=FieldFilter("email", "==", email))
        .limit(1)
        .stream()
    )
    return next(iter(query), None)


@auth_bp.post("/auth/login")
def login():
    payload = request.get_json(silent=True) or {}
    email = payload.get("email") or ""
    password = payload.get("password") or ""
    if not email or not password:
        return jsonify({"detail": "Email and password are required"}), 422

    snapshot = _find_user_by_email(email)
    if snapshot is None:
        return jsonify({"detail": "Invalid credentials"}), 401

    data = snapshot.to_dict() or {}
    if data.get("is_suspended"):
        return jsonify({"detail": "Account is suspended"}), 403
    if not verify_password(password, data.get("password_hash") or ""):
        return jsonify({"detail": "Invalid credentials"}), 401

    user = safe_delete_fields(to_dict(snapshot), "password_hash")
    token = create_token(snapshot.id, data.get("role") or "customer")
    return jsonify({"access_token": token, "user": user})


@auth_bp.post("/auth/register")
def register():
    payload = request.get_json(silent=True) or {}
    email = (payload.get("email") or "").strip().lower()
    password = payload.get("password") or ""
    full_name = payload.get("full_name") or ""
    role = payload.get("role") or "customer"
    phone = payload.get("phone") or ""

    if not email or not password:
        return jsonify({"detail": "Email and password are required"}), 422
    if role not in _ALLOWED_ROLES:
        role = "customer"

    if _find_user_by_email(email) is not None:
        return jsonify({"detail": "Email already registered"}), 422

    ref = col(USERS).document()
    ref.set({
        "email": email,
        "password_hash": hash_password(password),
        "full_name": full_name,
        "role": role,
        "phone": phone,
        "city_id": payload.get("city_id"),
        "is_suspended": False,
        "created_at": now_iso(),
    })

    user = safe_delete_fields(to_dict(ref.get()), "password_hash")
    token = create_token(ref.id, role)
    return jsonify({"access_token": token, "user": user}), 201


@auth_bp.post("/auth/logout")
@require_auth
def logout():
    # Stateless JWT — client discards the token. Endpoint exists for the
    # Flutter client contract and future server-side revocation.
    return jsonify({"ok": True})


@auth_bp.get("/auth/me")
@require_auth
def me():
    snapshot = doc(USERS, g.user_id).get()
    if not snapshot.exists:
        return jsonify({"detail": "User not found"}), 404
    return jsonify(safe_delete_fields(to_dict(snapshot), "password_hash"))


@auth_bp.get("/auth/role")
@require_auth
def role():
    snapshot = doc(USERS, g.user_id).get()
    stored_role = (snapshot.to_dict() or {}).get("role") if snapshot.exists else None
    return jsonify({"role": stored_role or g.user_role or "customer"})
