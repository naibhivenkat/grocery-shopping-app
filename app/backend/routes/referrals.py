"""Stable reusable invite codes and one atomic application per referee.

Referral rewards remain disabled while wallet is disabled; no balances change.
Existing issued and applied referral records remain valid without a migration.
"""
import hashlib
import re
import secrets
import string
from datetime import datetime, timezone

from firebase_admin import firestore
from flask import Blueprint, g, jsonify
from google.cloud.firestore_v1.base_query import FieldFilter

from auth_utils import require_role
from db import REFERRALS, USERS, col, db, doc, now_iso, to_dict
from routes.khata import KhataError, _payload, _text, _identifier

referrals_bp = Blueprint("referrals", __name__)
_CODE_PATTERN = re.compile(r"[A-Z0-9]{8,10}")


class ReferralError(KhataError):
    def __init__(self, detail, status=422, code="referral_invalid_code"):
        super().__init__(detail, status)
        self.code = code


@referrals_bp.errorhandler(KhataError)
def referral_error(error):
    # Add a machine-readable reason while preserving existing detail/status.
    return jsonify({"detail": error.detail,
                    "code": getattr(error, "code", "referral_invalid_code")}), error.status


def _generate_code(length=8):
    return "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(length))


def _owner_id(user_id):
    return "owner_" + hashlib.sha256(user_id.encode()).hexdigest()


def _account(user_id, tx):
    try:
        user_id = _identifier(user_id, "user_id")
    except KhataError:
        raise ReferralError("Referral account is unavailable", 403,
                            "referral_account_unavailable") from None
    snap = doc(USERS, user_id).get(transaction=tx)
    data = snap.to_dict() or {}
    if (not snap.exists or data.get("role") not in {"customer", "vendor", "service"}
            or data.get("is_suspended")):
        raise ReferralError("Referral account is unavailable", 403,
                            "referral_account_unavailable")
    return data


def _legacy_order(snapshot):
    """Compare legacy Firestore timestamps and ISO strings without TypeError."""
    value = (snapshot.to_dict() or {}).get("created_at")
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(
            str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return (1, parsed.timestamp(), snapshot.id)
    except (ValueError, TypeError, OverflowError):
        # Old records without timestamps preceded the timestamped schema.
        return (0, 0, snapshot.id)


def _checked_saved_code(snapshot, owner_id, tx):
    data = snapshot.to_dict() or {}
    code = data.get("code")
    if not isinstance(code, str) or not _CODE_PATTERN.fullmatch(code):
        raise ReferralError("Saved referral code requires reconciliation", 409,
                            "referral_saved_code_invalid")
    matches = list(tx.get(col(REFERRALS).where(filter=FieldFilter("code", "==", code))))
    reservation = doc("referral_codes", code).get(transaction=tx)
    if (data.get("referrer_id") != owner_id
            or any((item.to_dict() or {}).get("referrer_id") != owner_id for item in matches)
            or (reservation.exists and (reservation.to_dict() or {}).get("referrer_id") != owner_id)):
        raise ReferralError("Duplicate referral codes require reconciliation", 409,
                            "referral_ambiguous_code")
    return code


@referrals_bp.post("/referrals/generate")
@require_role("customer", "vendor", "service")
def generate_code():
    owner_ref = doc(REFERRALS, _owner_id(g.user_id))
    for _ in range(10):
        candidate = _generate_code()

        @firestore.transactional
        def generate(tx):
            owner = owner_ref.get(transaction=tx)
            account = _account(g.user_id, tx)
            legacy = list(tx.get(col(REFERRALS).where(filter=FieldFilter("referrer_id", "==", g.user_id))))
            if owner.exists:
                return {"code": _checked_saved_code(owner, g.user_id, tx)}
            if legacy:
                # Applications share the code: prefer the original issued row.
                legacy.sort(key=_legacy_order)
                return {"code": _checked_saved_code(legacy[0], g.user_id, tx)}
            reservation_ref = doc("referral_codes", candidate)
            reservation = reservation_ref.get(transaction=tx)
            collision = list(tx.get(col(REFERRALS).where(filter=FieldFilter("code", "==", candidate))))
            if reservation.exists or collision:
                raise ReferralError("Referral code collision", 409,
                                    "referral_code_collision")
            timestamp = now_iso()
            tx.set(owner_ref, {"referrer_id": g.user_id, "referee_id": "", "referrer_name": account.get("full_name") or account.get("username"),
                              "referee_name": None, "code": candidate, "status": "pending", "created_at": timestamp})
            tx.set(reservation_ref, {"referrer_id": g.user_id, "referral_id": owner_ref.id, "created_at": timestamp})
            return {"code": candidate}
        try:
            return jsonify(generate(db().transaction()))
        except ReferralError as exc:
            if exc.code != "referral_code_collision":
                raise
    raise ReferralError("Unable to allocate a referral code; retry later", 503,
                        "referral_code_exhausted")


@referrals_bp.post("/referrals/apply")
@require_role("customer", "vendor", "service")
def apply_code():
    # Trim before length validation so copied codes with surrounding whitespace work.
    code = _text(_payload().get("code"), "code", 64).upper()
    if not _CODE_PATTERN.fullmatch(code):
        raise ReferralError("A valid referral code is required")
    marker_ref = doc("referral_applications", g.user_id)
    application_ref = doc(REFERRALS, "application_" + hashlib.sha256(g.user_id.encode()).hexdigest())

    @firestore.transactional
    def apply(tx):
        referee = _account(g.user_id, tx)
        marker = marker_ref.get(transaction=tx)
        matches = list(tx.get(col(REFERRALS).where(filter=FieldFilter("code", "==", code))))
        used = list(tx.get(col(REFERRALS).where(filter=FieldFilter("referee_id", "==", g.user_id))))
        application = application_ref.get(transaction=tx)
        reservation = doc("referral_codes", code).get(transaction=tx)
        if not matches:
            raise ReferralError("Invalid referral code", 404)
        owner_values = [(item.to_dict() or {}).get("referrer_id") for item in matches]
        owners = {value for value in owner_values if isinstance(value, str) and value}
        if len(owners) != 1 or len(owner_values) != sum(isinstance(value, str) and bool(value) for value in owner_values):
            raise ReferralError("Duplicate referral codes require reconciliation", 409,
                                "referral_ambiguous_code")
        referrer_id = next(iter(owners))
        if reservation.exists and (reservation.to_dict() or {}).get("referrer_id") != referrer_id:
            raise ReferralError("Duplicate referral codes require reconciliation", 409,
                                "referral_ambiguous_code")
        if referrer_id == g.user_id:
            raise ReferralError("Cannot apply your own referral", 422,
                                "referral_self_referral")
        referrer = _account(referrer_id, tx)
        if marker.exists:
            applied = marker.to_dict() or {}
            if applied.get("code") == code and applied.get("referrer_id") == referrer_id:
                return {"ok": True, "reward_credited": False}
            raise ReferralError("An account can apply only one referral", 409,
                                "referral_already_applied")
        if used:
            if all((item.to_dict() or {}).get("code") == code
                   and (item.to_dict() or {}).get("referrer_id") == referrer_id for item in used):
                return {"ok": True, "reward_credited": False}
            raise ReferralError("An account can apply only one referral", 409,
                                "referral_already_applied")
        if application.exists:
            raise ReferralError("Referral application requires reconciliation", 409,
                                "referral_application_conflict")
        timestamp = now_iso()
        changes = {"referee_id": g.user_id, "referee_name": referee.get("full_name") or referee.get("username"),
                   "status": "applied", "applied_at": timestamp, "reward_status": "disabled"}
        pending = [item for item in matches if not (item.to_dict() or {}).get("referee_id")]
        if pending:
            # Preserve the original first-application shape for existing clients.
            pending.sort(key=lambda item: (item.id != _owner_id(referrer_id), _legacy_order(item)))
            referral_ref = pending[0].reference
            tx.update(referral_ref, changes)
        else:
            # A reusable code has one history row per referee; never overwrite history.
            referral_ref = application_ref
            tx.create(referral_ref, {"referrer_id": referrer_id,
                                    "referrer_name": referrer.get("full_name") or referrer.get("username"),
                                    "code": code, "created_at": timestamp, **changes})
        tx.set(marker_ref, {"code": code, "referral_id": referral_ref.id,
                            "referrer_id": referrer_id, "created_at": timestamp})
        return {"ok": True, "reward_credited": False}
    return jsonify(apply(db().transaction()))


@referrals_bp.get("/referrals")
@require_role("customer", "vendor", "service")
def list_my_referrals():
    fields = {"uid", "referrer_id", "referee_id", "referrer_name", "referee_name", "code", "status", "created_at", "applied_at", "reward_status"}
    matches = {}
    for field in ("referrer_id", "referee_id"):
        for snap in col(REFERRALS).where(filter=FieldFilter(field, "==", g.user_id)).stream():
            matches[snap.id] = {key: value for key, value in to_dict(snap).items() if key in fields}
    return jsonify(list(matches.values()))
