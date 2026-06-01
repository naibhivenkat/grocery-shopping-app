"""Authentication helpers: password hashing, JWT tokens, Flask decorators."""

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps

import jwt
from flask import g, jsonify, request

from app.backend.db import col, now_iso

JWT_SECRET = os.getenv("JWT_SECRET", "localshop-dev-secret-change-me")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_DAYS = int(os.getenv("JWT_EXPIRE_DAYS", "30"))
_PBKDF2_ITER = 120_000

AUDIT_LOGS = "audit_logs"

def log_admin_action(
    admin_id,
    admin_email,
    action,
    target_id,
    target_type,
):
    col(AUDIT_LOGS).document().set({
        "admin_id": admin_id,
        "admin_email": admin_email,
        "action": action,
        "target_id": target_id,
        "target_type": target_type,
        "created_at": now_iso(),
    })
def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _PBKDF2_ITER)
    return f"{salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    if not stored or "$" not in stored:
        return False
    salt, expected = stored.split("$", 1)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _PBKDF2_ITER)
    return hmac.compare_digest(digest.hex(), expected)


def create_token(user_id: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "role": role,
        "iat": now,
        "exp": now + timedelta(days=JWT_EXPIRE_DAYS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])


def _extract_token() -> str | None:
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return header[7:].strip() or None
    return None


def require_auth(fn):
    """Decorator that populates g.user_id and g.user_role, or returns 401."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        token = _extract_token()
        if not token:
            return jsonify({"detail": "Missing authentication token"}), 401
        try:
            payload = decode_token(token)
        except jwt.ExpiredSignatureError:
            return jsonify({"detail": "Token expired"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"detail": "Invalid token"}), 401
        g.user_id = payload["sub"]
        try:
            from db import USERS, doc

            user_snapshot = doc(USERS, g.user_id).get()
        except Exception:
            user_snapshot = None
        if user_snapshot is not None and user_snapshot.exists:
            user_data = user_snapshot.to_dict() or {}
            if user_data.get("is_suspended"):
                return jsonify({"detail": "Account is suspended"}), 403
            g.user_role = user_data.get("role") or payload.get("role", "customer")
        else:
            g.user_role = payload.get("role", "customer")
        return fn(*args, **kwargs)

    return wrapper


def require_role(*roles: str):
    """Decorator that enforces both auth and role membership."""

    def decorator(fn):
        @wraps(fn)
        @require_auth
        def wrapper(*args, **kwargs):
            if g.user_role not in roles:
                return jsonify({"detail": "Insufficient permissions"}), 403
            return fn(*args, **kwargs)

        return wrapper

    return decorator
