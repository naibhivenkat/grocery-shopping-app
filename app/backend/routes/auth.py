"""`/auth/*` endpoints consumed by `AuthRemoteDataSource` (Flutter)."""

import hashlib
import json
import logging
import os
import random
import re
import smtplib
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from flask import Blueprint, g, jsonify, request
from firebase_admin import auth as firebase_auth
from google.cloud.firestore_v1.base_query import FieldFilter
from google.cloud import firestore

from auth_utils import create_token, hash_password, require_auth, verify_password
from db import USERS, col, doc, db, now_iso, safe_delete_fields, to_dict

auth_bp = Blueprint("auth", __name__)
log = logging.getLogger(__name__)

@auth_bp.before_request
def _validate_auth_json():
    if request.method != "POST":
        return None
    payload = request.get_json(silent=True)
    if payload is None:
        return None
    if not isinstance(payload, dict):
        return jsonify({"detail": "JSON object required"}), 422
    fields = {"email", "username", "password", "new_password", "full_name",
              "role", "phone", "city_id", "otp", "id_token"}
    if any(value is not None and (not isinstance(value, str) or len(value) > 4096)
           for key, value in payload.items() if key in fields):
        return jsonify({"detail": "Authentication fields must be strings"}), 422
    return None


_ALLOWED_ROLES = {"customer", "vendor", "service"}
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



class RegistrationError(ValueError):
    def __init__(self, detail, status=422, field=None):
        self.detail, self.status, self.field = detail, status, field
        super().__init__(detail)


@auth_bp.errorhandler(RegistrationError)
def _registration_error(error):
    return jsonify({"detail": error.detail}), error.status


def _registration_email(value):
    if not isinstance(value, str):
        raise RegistrationError("A valid email is required")
    email = value.strip().lower()
    if len(email) > 254 or email.count("@") != 1:
        raise RegistrationError("A valid email is required")
    local, domain = email.split("@")
    if (not 1 <= len(local) <= 64 or local.startswith(".") or local.endswith(".") or ".." in local
        or not re.fullmatch(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+", local)
        or len(domain) > 253 or "." not in domain):
        raise RegistrationError("A valid email is required")
    labels = domain.split(".")
    if any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels):
        raise RegistrationError("A valid email is required")
    if len(labels[-1]) < 2:
        raise RegistrationError("A valid email is required")
    return email


def _registration_username(value, email):
    if value in (None, ""):
        username = re.sub(r"[^a-z0-9_.-]", "_", email.split("@", 1)[0])
        if len(username) < 3:
            username += "_user"
    elif isinstance(value, str):
        username = value.strip().lower()
    else:
        raise RegistrationError("username must be text")
    if not re.fullmatch(r"[a-z0-9_.-]{3,64}", username) or not any(char.isalnum() for char in username):
        raise RegistrationError("username must contain 3 to 64 letters, numbers, dots, hyphens or underscores")
    return username


def _registration_text(value, field, maximum):
    if value is None:
        return ""
    if not isinstance(value, str) or len(value) > maximum:
        raise RegistrationError(f"{field} must be text of at most {maximum} characters")
    return value.strip()


def _identifier_reservation(field, value):
    return doc("auth_identifiers", field + "_" + hashlib.sha256(value.encode()).hexdigest())


def _create_account_atomic(data, *, requires_otp=False):
    """Reserve unique identifiers and consume signup OTP with the new account.

    Legacy users are queried without rewriting them. Reservation documents also
    protect concurrent empty-query results, including Google signup. Stale
    reservations can be reused after their account is deleted or identifier is
    changed by a separately authorized administrative operation.
    """
    ref = col(USERS).document()
    reservations = [(field, data[field], _identifier_reservation(field, data[field])) for field in ("email", "username")]
    otp_ref = _otp_ref(data["email"]) if requires_otp else None

    @firestore.transactional
    def create(tx):
        reserved = [(field, value, reservation, reservation.get(transaction=tx)) for field, value, reservation in reservations]
        existing = [(field, list(tx.get(col(USERS).where(filter=FieldFilter(field, "==", value)))))
                    for field, value, _ in reservations]
        owners = []
        for field, value, _, snap in reserved:
            if not snap.exists:
                continue
            owner_id = (snap.to_dict() or {}).get("user_id")
            if not isinstance(owner_id, str) or not owner_id or "/" in owner_id:
                raise RegistrationError("Account identifier reservation needs reconciliation", 409)
            owners.append((field, value, doc(USERS, owner_id).get(transaction=tx)))
        otp_snapshot = otp_ref.get(transaction=tx) if otp_ref else None
        for field, matches in existing:
            if matches:
                raise RegistrationError(f"{field.title()} already registered", field=field)
        for field, value, owner in owners:
            if owner.exists and (owner.to_dict() or {}).get(field) == value:
                raise RegistrationError(f"{field.title()} already registered", field=field)
        if otp_ref:
            otp_data = otp_snapshot.to_dict() or {}
            expires = _parse_iso(otp_data.get("expires_at"))
            if (not otp_snapshot.exists or otp_data.get("verified") is not True or expires is None or expires <= _utcnow()
                or otp_data.get("purpose") not in (None, "registration") or otp_data.get("email") != data["email"]):
                raise RegistrationError("Please verify OTP before registering", 400)
        from subscription_service import vendor_activation_plan
        activate_subscription = vendor_activation_plan(tx, ref.id, ref.id, lookup=doc) if data.get("role") == "vendor" else (lambda: None)
        timestamp = now_iso()
        created = {**data, "created_at": timestamp, "updated_at": timestamp}
        tx.set(ref, created)
        activate_subscription()
        for field, value, reservation in reservations:
            tx.set(reservation, {"kind": field, "value": value, "user_id": ref.id, "created_at": timestamp})
        if otp_ref:
            tx.delete(otp_ref)
        return {**created, "uid": ref.id}
    return create(db().transaction())

def _otp_ref(email: str):
    key = hashlib.sha256(email.strip().lower().encode()).hexdigest()
    return col("auth_otps").document(key)


def _password_reset_otp_ref(email: str):
    key = hashlib.sha256(
        f"password-reset:{email.strip().lower()}".encode()
    ).hexdigest()
    return col("auth_otps").document(key)


def _check_otp(ref, otp, *, purpose=None, mark_verified=False):
    @firestore.transactional
    def verify(tx):
        snap = ref.get(transaction=tx)
        data = snap.to_dict() or {}
        if not snap.exists or (purpose and data.get("purpose") != purpose):
            return None, "Invalid or expired OTP", 400
        expires = _parse_iso(data.get("expires_at"))
        if expires is None or expires < _utcnow():
            tx.delete(ref)
            return None, "OTP expired", 400
        attempts = int(data.get("failed_attempts") or 0)
        if attempts >= 5:
            return None, "Too many OTP attempts; request a new code", 429
        if not verify_password(otp, data.get("otp_hash") or ""):
            tx.update(ref, {"failed_attempts": attempts + 1})
            return None, "Invalid OTP", 400
        if mark_verified:
            tx.update(ref, {"verified": True, "verified_at": now_iso()})
        return data, None, 200
    return verify(db().transaction())


def _save_otp(ref, data):
    @firestore.transactional
    def save(tx):
        snap = ref.get(transaction=tx)
        previous = snap.to_dict() or {}
        created = _parse_iso(previous.get("created_at"))
        if created and (_utcnow() - created).total_seconds() < 60:
            return False
        tx.set(ref, {**data, "failed_attempts": 0})
        return True
    return save(db().transaction())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo is not None else None
    except (TypeError, ValueError):
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
        if os.getenv("FLASK_ENV", "").lower() == "production":
            raise RuntimeError("OTP email delivery is not configured")
        log.info("OTP email delivery is not configured in development")
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
        return jsonify({
            "detail": "Email already registered"
        }), 422

    otp = f"{random.SystemRandom().randint(0, 999999):06d}"
    expires_at = _utcnow() + timedelta(minutes=_OTP_TTL_MINUTES)
    if not _save_otp(_otp_ref(email), {
        "email": email,
        "otp_hash": hash_password(otp),
        "verified": False,
        "created_at": now_iso(),
        "expires_at": expires_at.isoformat(),
    }):
        return jsonify({"detail": "Wait 60 seconds before requesting another OTP"}), 429

    try:
        _send_otp_email(email, otp)
    except Exception as exc:
        log.warning("Failed to send OTP email to %s: %s", email, exc)
        return jsonify({"detail": "Failed to send OTP"}), 500

    response = {"success": True, "message": "OTP sent to email"}
    if os.getenv("AUTH_OTP_DEBUG_RESPONSE") == "1" and os.getenv("FLASK_ENV", "").lower() != "production":
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
    _, error, status = _check_otp(ref, otp, mark_verified=True)
    if error:
        return jsonify({"detail": error}), status
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
    if not _save_otp(_password_reset_otp_ref(email), {
        "email": email,
        "otp_hash": hash_password(otp),
        "purpose": "password_reset",
        "created_at": now_iso(),
        "expires_at": expires_at.isoformat(),
    }):
        return jsonify({"detail": "Wait 60 seconds before requesting another OTP"}), 429

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

    if os.getenv("AUTH_OTP_DEBUG_RESPONSE") == "1" and os.getenv("FLASK_ENV", "").lower() != "production":
        response["otp"] = otp
    return jsonify(response)


@auth_bp.post("/auth/reset_password")
@auth_bp.post("/reset_password")
def reset_password():
    payload = request.get_json(silent=True) or {}

    email = (payload.get("email") or "").strip().lower()
    otp = (payload.get("otp") or "").strip()
    new_password = payload.get("new_password") or payload.get("password") or ""


    if not email or not otp or len(new_password) < 8:
        return jsonify({"detail": "Email, OTP and password of at least 8 characters are required"}), 422

    ref = _password_reset_otp_ref(email)

    otp_snapshot = ref.get()


    if not otp_snapshot.exists:
        return jsonify({"detail": "Invalid or expired OTP"}), 400

    otp_data = otp_snapshot.to_dict() or {}

    if otp_data.get("purpose") != "password_reset":
        return jsonify({"detail": "Invalid or expired OTP"}), 400
    expires_at = _parse_iso(otp_data.get("expires_at"))


    if expires_at is None or expires_at < _utcnow():
        ref.delete()
        return jsonify({"detail": "OTP expired"}), 400

    otp_data, error, status = _check_otp(ref, otp, purpose="password_reset")
    if error:
        return jsonify({"detail": error}), status

    user_snapshot = _find_user_by_email(email)


    if user_snapshot is None:
        return jsonify({"detail": "User not found"}), 404

    new_hash = hash_password(new_password)
    user_ref = doc(USERS, user_snapshot.id)
    @firestore.transactional
    def _reset(tx):
        # Consume the OTP in the same transaction as the password update.
        current = ref.get(transaction=tx)
        user = user_ref.get(transaction=tx)
        current_data = current.to_dict() or {}
        if (not current.exists or not user.exists
            or current_data.get("purpose") != "password_reset"
            or current_data.get("otp_hash") != otp_data.get("otp_hash")):
            return False
        expires = _parse_iso(current_data.get("expires_at"))
        if expires is None or expires < _utcnow() or (user.to_dict() or {}).get("is_suspended"):
            return False
        tx.update(user_ref, {"password_hash": new_hash, "updated_at": now_iso(),
            "password_reset_at": now_iso()})
        tx.delete(ref)
        return True
    if not _reset(db().transaction()):
        return jsonify({"detail": "Invalid or expired OTP"}), 400

    return jsonify({
        "success": True,
        "message": "Password reset successfully"
    })


@auth_bp.post("/auth/verify_reset_otp")
@auth_bp.post("/verify_reset_otp")
def verify_reset_otp():
    payload = request.get_json(silent=True) or {}

    email = (payload.get("email") or "").strip().lower()
    otp = (payload.get("otp") or "").strip()


    if not email or not otp:
        return jsonify({"detail": "Email and OTP are required"}), 422

    ref = _password_reset_otp_ref(email)

    _, error, status = _check_otp(ref, otp, purpose="password_reset", mark_verified=True)
    if error:
        return jsonify({"detail": error}), status

    return jsonify({
        "success": True,
        "message": "OTP verified",
    })

@auth_bp.post("/auth/google")
def google_login():
    payload = request.get_json(silent=True) or {}
    id_token = payload.get("id_token") or ""
    requested_role = _normalize_role(payload.get("role") or "customer")
    if not id_token:
        return jsonify({"detail": "Google id_token is required"}), 422

    try:
        decoded = firebase_auth.verify_id_token(id_token, check_revoked=True)
    except Exception:
        return jsonify({"detail": "Invalid Google token"}), 401

    email = (decoded.get("email") or "").strip().lower()
    if not email or decoded.get("email_verified") is not True:
        return jsonify({"detail": "A verified Google account email is required"}), 422

    snapshot = _find_user_by_email(email)
    if snapshot is None:
        email = _registration_email(email)
        base_username = _registration_username(None, email)
        data = {"email": email, "full_name": _registration_text(decoded.get("name") or email.split("@")[0], "full_name", 200),
                "role": requested_role, "phone": "", "avatar_url": decoded.get("picture"), "firebase_id": decoded.get("uid"),
                "auth_provider": "google", "is_suspended": False}
        for suffix in range(1, 101):
            username = base_username if suffix == 1 else base_username[:64 - len(str(suffix))] + str(suffix)
            try:
                created = _create_account_atomic({**data, "username": username})
                snapshot = doc(USERS, created["uid"]).get()
                break
            except RegistrationError as exc:
                if exc.field == "email":
                    snapshot = _find_user_by_email(email)
                    if snapshot is None:
                        raise RegistrationError("Account creation is temporarily unavailable", 503) from None
                    break
                if exc.field != "username":
                    raise
        else:
            raise RegistrationError("Unable to allocate a username; retry later", 503)
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
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise RegistrationError("JSON object required")
    email = _registration_email(payload.get("email"))
    password = payload.get("password")
    if not isinstance(password, str) or not 8 <= len(password) <= 128:
        raise RegistrationError("password must contain 8 to 128 characters")
    # Passwords are hashed verbatim, including intentional surrounding spaces.
    username = _registration_username(payload.get("username"), email)
    city_id = payload.get("city_id")
    if city_id is not None and (not isinstance(city_id, str) or len(city_id) > 200 or "/" in city_id):
        raise RegistrationError("city_id must be a valid identifier")
    role = _normalize_role(payload.get("role") or "customer")
    data = {"email": email, "username": username, "password_hash": hash_password(password),
            "full_name": _registration_text(payload.get("full_name"), "full_name", 200), "role": role,
            "phone": _registration_text(payload.get("phone"), "phone", 40), "city_id": city_id, "is_suspended": False}
    user = safe_delete_fields(_create_account_atomic(data, requires_otp=request.path.endswith("register_after_otp")), "password_hash")
    token = create_token(user["uid"], role)
    return jsonify({"success": True, "access_token": token, "token": token, "user": user}), 201


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
