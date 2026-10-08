"""Authentication helpers: password hashing, JWT tokens, Flask decorators."""

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps

import jwt
from flask import g, jsonify, request

from db import col, now_iso
from firebase_admin import auth as firebase_auth
from google.cloud.firestore_v1.base_query import FieldFilter

_configured_jwt_secret = os.getenv("JWT_SECRET")
if os.getenv("FLASK_ENV", "").lower() == "production":
    if not _configured_jwt_secret or len(_configured_jwt_secret) < 32:
        raise RuntimeError(
            "JWT_SECRET must be configured with at least 32 characters in production"
        )
JWT_SECRET = _configured_jwt_secret or "localshop-dev-secret-change-me"
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_DAYS = int(os.getenv("JWT_EXPIRE_DAYS", "30"))
_PBKDF2_ITER = 120_000

AUDIT_LOGS = "audit_logs"


def log_admin_action(
    admin_id: str,
    admin_email: str,
    action: str,
    target_id: str,
    target_type: str,
):
    """Write a minimal audit record for privileged administrative actions."""
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
    """Decorator that populates g.user_id, g.user_role and user metadata."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        token = _extract_token()

        if not token:
            return jsonify({
                "detail": "Missing authentication token"
            }), 401

        firebase_identity = False
        try:
            payload = decode_token(token)
        except jwt.ExpiredSignatureError:
            return jsonify({"detail": "Token expired"}), 401
        except jwt.InvalidTokenError:
            # Some installed checkout clients send a Firebase ID token. Verify
            # it with Firebase; never trust decoded claims or client roles.
            try:
                payload = firebase_auth.verify_id_token(token, check_revoked=True)
                firebase_identity = True
            except Exception:
                return jsonify({"detail": "Invalid token"}), 401

        subject = payload.get("uid") if firebase_identity else payload.get("sub")
        if not isinstance(subject, str) or not subject or "/" in subject:
            return jsonify({"detail": "Invalid token subject"}), 401
        try:
            from db import USERS, doc
            if firebase_identity:
                user_snapshot = next(iter(col(USERS).where(
                    filter=FieldFilter("firebase_id", "==", subject)
                ).limit(1).stream()), None)
                if user_snapshot is None:
                    user_snapshot = doc(USERS, subject).get()
            else:
                user_snapshot = doc(USERS, subject).get()
        except Exception:
            return jsonify({"detail": "Authentication service temporarily unavailable"}), 503

        if user_snapshot is None or not user_snapshot.exists:
            return jsonify({"detail": "Account no longer exists"}), 401
        user_data = user_snapshot.to_dict() or {}
        if user_data.get("is_suspended"):
            return jsonify({"detail": "Account is suspended"}), 403
        if not firebase_identity and user_data.get("password_reset_at"):
            try:
                reset_at = datetime.fromisoformat(user_data["password_reset_at"]).timestamp()
                if float(payload.get("iat") or 0) < int(reset_at):
                    return jsonify({"detail": "Session expired; sign in again"}), 401
            except (ValueError, TypeError):
                return jsonify({"detail": "Session expired; sign in again"}), 401
        g.user_id = user_snapshot.id
        g.user_role = user_data.get("role") or "customer"
        g.user_email = user_data.get("email", "")
        g.user_name = user_data.get("full_name") or user_data.get("username", "")
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


def require_webhook_secret(fn):
    """Protect non-Razorpay webhook endpoints with a shared secret."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        expected = os.getenv("WEBHOOK_SECRET")
        provided = request.headers.get("X-Webhook-Secret") or request.args.get("secret")
        if not expected:
            return jsonify({"detail": "Webhook secret not configured on server"}), 503
        if not provided or not hmac.compare_digest(provided, expected):
            return jsonify({"detail": "Invalid or missing webhook secret"}), 401
        return fn(*args, **kwargs)

    return wrapper
