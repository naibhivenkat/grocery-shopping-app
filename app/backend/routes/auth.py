"""`/auth/*` endpoints consumed by `AuthRemoteDataSource` (Flutter)."""

import hashlib
import json
import logging
import os
import random
import smtplib
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from flask import Blueprint, g, jsonify, request
from firebase_admin import auth as firebase_auth
from google.cloud.firestore_v1.base_query import FieldFilter

from auth_utils import create_token, hash_password, require_auth, verify_password
from db import USERS, col, doc, now_iso, safe_delete_fields, to_dict


auth_bp = Blueprint("auth", __name__)
log = logging.getLogger(__name__)

_ALLOWED_ROLES = {"customer", "vendor", "admin", "super_admin"}
_OTP_TTL_MINUTES = int(os.getenv("AUTH_OTP_TTL_MINUTES", "10"))


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


def _find_user_by_username(username: str):
    username = (username or "").strip().lower()
    if not username:
        return None
    query = (
        col(USERS)
        .where(filter=FieldFilter("username", "==", username))
        .limit(1)
        .stream()
    )
    return next(iter(query), None)


def _normalize_role(role: str) -> str:
    role = (role or "customer").strip().lower()
    if role in {"shopowner", "shopkeeper"}:
        return "vendor"
    return role if role in _ALLOWED_ROLES else "customer"


def _otp_ref(email: str):
    key = hashlib.sha256(email.strip().lower().encode()).hexdigest()
    return col("auth_otps").document(key)


def _password_reset_otp_ref(email: str):
    key = hashlib.sha256(
        f"password-reset:{email.strip().lower()}".encode()
    ).hexdigest()
    return col("auth_otps").document(key)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _send_otp_email(
    email: str,
    otp: str,
    *,
    subject: str = "Your LocalShop Finder verification code",
    message_prefix: str = "Your LocalShop Finder verification code",
) -> None:
    """Send OTP email when Brevo/Sendinblue or SMTP env vars are configured."""
    sendinblue_key = os.getenv("SENDINBLUE_API_KEY")
    from_email = os.getenv("FROM_EMAIL")
    message_text = (
        f"{message_prefix} is {otp}. "
        f"It expires in {_OTP_TTL_MINUTES} minutes."
    )
    if sendinblue_key and from_email:
        payload = json.dumps({
            "sender": {
                "email": from_email,
                "name": "LocalShop Finder",
            },
            "to": [{"email": email}],
            "subject": subject,
            "textContent": message_text,
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://api.sendinblue.com/v3/smtp/email",
            data=payload,
            headers={
                "api-key": sendinblue_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                response.read()
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            raise RuntimeError(
                f"Brevo email API failed with {exc.code}: {body}"
            ) from exc
        return

    host = os.getenv("SMTP_HOST")
    username = os.getenv("SMTP_USERNAME")
    password = os.getenv("SMTP_PASSWORD")
    sender = os.getenv("SMTP_SENDER") or username
    if not host or not username or not password or not sender:
        log.info("%s for %s is %s", subject, email, otp)
        return

    port = int(os.getenv("SMTP_PORT", "587"))
    message = EmailMessage()
    message["From"] = sender
    message["To"] = email
    message["Subject"] = subject
    message.set_content(message_text)
    with smtplib.SMTP(host, port, timeout=10) as smtp:
        smtp.starttls()
        smtp.login(username, password)
        smtp.send_message(message)


def _login_response(snapshot):
    data = snapshot.to_dict() or {}
    user = safe_delete_fields(to_dict(snapshot), "password_hash")
    token = create_token(snapshot.id, data.get("role") or "customer")
    return jsonify({
        "success": True,
        "access_token": token,
        "token": token,
        "user": user,
    })


@auth_bp.post("/auth/send_otp")
@auth_bp.post("/send_otp")
def send_otp():
    payload = request.get_json(silent=True) or {}
    email = (payload.get("email") or "").strip().lower()
    if not email:
        return jsonify({"detail": "Email is required"}), 422
    if _find_user_by_email(email) is not None:
        return jsonify({"detail": "Email already registered"}), 422

    otp = f"{random.SystemRandom().randint(0, 999999):06d}"
    expires_at = _utcnow() + timedelta(minutes=_OTP_TTL_MINUTES)
    _otp_ref(email).set({
        "email": email,
        "otp_hash": hash_password(otp),
        "verified": False,
        "created_at": now_iso(),
        "expires_at": expires_at.isoformat(),
    })

    try:
        _send_otp_email(email, otp)
    except Exception as exc:
        log.warning("Failed to send OTP email to %s: %s", email, exc)
        return jsonify({"detail": "Failed to send OTP"}), 500

    response = {"success": True, "message": "OTP sent to email"}
    if os.getenv("AUTH_OTP_DEBUG_RESPONSE") == "1":
        response["otp"] = otp
    return jsonify(response)


@auth_bp.post("/auth/verify_otp")
@auth_bp.post("/verify_otp")
def verify_otp():
    payload = request.get_json(silent=True) or {}
    email = (payload.get("email") or "").strip().lower()
    otp = (payload.get("otp") or "").strip()
    if not email or not otp:
        return jsonify({"detail": "Email and OTP are required"}), 422

    ref = _otp_ref(email)
    snapshot = ref.get()
    if not snapshot.exists:
        return jsonify({"detail": "OTP not found or expired"}), 400

    data = snapshot.to_dict() or {}
    expires_at = _parse_iso(data.get("expires_at"))
    if expires_at is None or expires_at < _utcnow():
        ref.delete()
        return jsonify({"detail": "OTP expired"}), 400
    if not verify_password(otp, data.get("otp_hash") or ""):
        return jsonify({"detail": "Invalid OTP"}), 400

    ref.update({"verified": True, "verified_at": now_iso()})
    return jsonify({"success": True, "status": "success", "message": "OTP verified"})


@auth_bp.post("/auth/login")
@auth_bp.post("/login")
def login():
    payload = request.get_json(silent=True) or {}
    email = payload.get("email") or payload.get("username") or ""
    password = payload.get("password") or ""
    if not email or not password:
        return jsonify({"detail": "Email/username and password are required"}), 422

    snapshot = _find_user_by_email(email)
    if snapshot is None:
        snapshot = _find_user_by_username(email)
    if snapshot is None:
        return jsonify({"detail": "Invalid credentials"}), 401

    data = snapshot.to_dict() or {}
    if data.get("is_suspended"):
        return jsonify({"detail": "Account is suspended"}), 403
    if not verify_password(password, data.get("password_hash") or ""):
        return jsonify({"detail": "Invalid credentials"}), 401

    return _login_response(snapshot)


@auth_bp.post("/auth/forgot_password")
@auth_bp.post("/forgot_password")
def forgot_password():
    payload = request.get_json(silent=True) or {}
    email = (payload.get("email") or "").strip().lower()
    if not email:
        return jsonify({"detail": "Email is required"}), 422

    snapshot = _find_user_by_email(email)
    response = {
        "success": True,
        "message": "If an account exists, a reset OTP has been sent",
    }
    if snapshot is None:
        return jsonify(response)

    data = snapshot.to_dict() or {}
    if data.get("is_suspended"):
        return jsonify(response)

    otp = f"{random.SystemRandom().randint(0, 999999):06d}"
    expires_at = _utcnow() + timedelta(minutes=_OTP_TTL_MINUTES)
    _password_reset_otp_ref(email).set({
        "email": email,
        "otp_hash": hash_password(otp),
        "purpose": "password_reset",
        "created_at": now_iso(),
        "expires_at": expires_at.isoformat(),
    })

    try:
        _send_otp_email(
            email,
            otp,
            subject="Reset your LocalShop Finder password",
            message_prefix="Your LocalShop Finder password reset code",
        )
    except Exception as exc:
        log.warning(
            "Failed to send password reset OTP email to %s: %s",
            email,
            exc,
        )
        return jsonify({"detail": "Failed to send password reset OTP"}), 500

    if os.getenv("AUTH_OTP_DEBUG_RESPONSE") == "1":
        response["otp"] = otp
    return jsonify(response)


@auth_bp.post("/auth/reset_password")
@auth_bp.post("/reset_password")
def reset_password():
    payload = request.get_json(silent=True) or {}
    email = (payload.get("email") or "").strip().lower()
    otp = (payload.get("otp") or "").strip()
    new_password = payload.get("new_password") or payload.get("password") or ""
    if not email or not otp or not new_password:
        return jsonify({"detail": "Email, OTP, and new password are required"}), 422
    if len(new_password) < 6:
        return jsonify({"detail": "Password must be at least 6 characters"}), 422

    ref = _password_reset_otp_ref(email)
    otp_snapshot = ref.get()
    if not otp_snapshot.exists:
        return jsonify({"detail": "Invalid or expired OTP"}), 400

    otp_data = otp_snapshot.to_dict() or {}
    expires_at = _parse_iso(otp_data.get("expires_at"))
    if expires_at is None or expires_at < _utcnow():
        ref.delete()
        return jsonify({"detail": "OTP expired"}), 400
    if not verify_password(otp, otp_data.get("otp_hash") or ""):
        return jsonify({"detail": "Invalid OTP"}), 400

    user_snapshot = _find_user_by_email(email)
    if user_snapshot is None:
        ref.delete()
        return jsonify({"detail": "Invalid or expired OTP"}), 400

    user_data = user_snapshot.to_dict() or {}
    if user_data.get("is_suspended"):
        return jsonify({"detail": "Account is suspended"}), 403

    reset_at = now_iso()
    doc(USERS, user_snapshot.id).update({
        "password_hash": hash_password(new_password),
        "updated_at": reset_at,
        "password_reset_at": reset_at,
    })
    ref.delete()
    return jsonify({"success": True, "message": "Password reset successfully"})


@auth_bp.post("/auth/google")
def google_login():
    payload = request.get_json(silent=True) or {}
    id_token = payload.get("id_token") or ""
    requested_role = _normalize_role(payload.get("role") or "customer")
    if not id_token:
        return jsonify({"detail": "Google id_token is required"}), 422

    try:
        decoded = firebase_auth.verify_id_token(id_token)
    except Exception:
        return jsonify({"detail": "Invalid Google token"}), 401

    email = (decoded.get("email") or "").strip().lower()
    if not email:
        return jsonify({"detail": "Google account email is required"}), 422

    snapshot = _find_user_by_email(email)
    if snapshot is None:
        full_name = decoded.get("name") or email.split("@")[0]
        username = email.split("@")[0].strip().lower()
        base_username = username
        suffix = 1
        while _find_user_by_username(username) is not None:
            suffix += 1
            username = f"{base_username}{suffix}"

        ref = col(USERS).document()
        ref.set({
            "email": email,
            "username": username,
            "full_name": full_name,
            "role": requested_role,
            "phone": "",
            "avatar_url": decoded.get("picture"),
            "firebase_id": decoded.get("uid"),
            "auth_provider": "google",
            "is_suspended": False,
            "created_at": now_iso(),
            "updated_at": now_iso(),
        })
        snapshot = ref.get()
    else:
        # Keep Google identity fields fresh for existing accounts.
        updates = {}
        data_existing = snapshot.to_dict() or {}
        firebase_uid = decoded.get("uid")
        if firebase_uid and data_existing.get("firebase_id") != firebase_uid:
            updates["firebase_id"] = firebase_uid
        picture = decoded.get("picture")
        if picture and not data_existing.get("avatar_url"):
            updates["avatar_url"] = picture
        if not data_existing.get("auth_provider"):
            updates["auth_provider"] = "google"
        if updates:
            updates["updated_at"] = now_iso()
            doc(USERS, snapshot.id).update(updates)
            snapshot = doc(USERS, snapshot.id).get()

    data = snapshot.to_dict() or {}
    if data.get("is_suspended"):
        return jsonify({"detail": "Account is suspended"}), 403
    return _login_response(snapshot)


@auth_bp.post("/auth/register")
@auth_bp.post("/auth/register_after_otp")
@auth_bp.post("/register_after_otp")
def register():
    payload = request.get_json(silent=True) or {}
    email = (payload.get("email") or "").strip().lower()
    password = payload.get("password") or ""
    full_name = payload.get("full_name") or ""
    role = _normalize_role(payload.get("role") or "customer")
    phone = payload.get("phone") or ""
    username = (payload.get("username") or email.split("@")[0]).strip().lower()
    requires_otp = request.path.endswith("register_after_otp")

    if not email or not password:
        return jsonify({"detail": "Email and password are required"}), 422

    if _find_user_by_email(email) is not None:
        return jsonify({"detail": "Email already registered"}), 422
    if username and _find_user_by_username(username) is not None:
        return jsonify({"detail": "Username already registered"}), 422

    if requires_otp:
        otp_snapshot = _otp_ref(email).get()
        if not otp_snapshot.exists:
            return jsonify({"detail": "Please verify OTP before registering"}), 400
        otp_data = otp_snapshot.to_dict() or {}
        expires_at = _parse_iso(otp_data.get("expires_at"))
        if not otp_data.get("verified") or expires_at is None or expires_at < _utcnow():
            return jsonify({"detail": "Please verify OTP before registering"}), 400

    ref = col(USERS).document()
    ref.set({
        "email": email,
        "username": username,
        "password_hash": hash_password(password),
        "full_name": full_name,
        "role": role,
        "phone": phone,
        "city_id": payload.get("city_id"),
        "is_suspended": False,
        "created_at": now_iso(),
    })

    if requires_otp:
        _otp_ref(email).delete()

    user = safe_delete_fields(to_dict(ref.get()), "password_hash")
    token = create_token(ref.id, role)
    return jsonify({
        "success": True,
        "access_token": token,
        "token": token,
        "user": user,
    }), 201


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
