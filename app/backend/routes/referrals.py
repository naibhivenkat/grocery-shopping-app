"""One referral code per account and one atomic application per referee.

Referral rewards remain disabled while wallet is disabled; no balances change.
"""
import hashlib
import secrets
import string
import re
from firebase_admin import firestore
from flask import Blueprint, g, jsonify
from google.cloud.firestore_v1.base_query import FieldFilter
from auth_utils import require_role
from db import REFERRALS, USERS, col, db, doc, now_iso, to_dict
from routes.khata import KhataError, _khata_error, _payload, _text, _identifier

referrals_bp = Blueprint("referrals", __name__)
referrals_bp.register_error_handler(KhataError, _khata_error)


def _generate_code(length=8):
    return "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(length))


def _account(user_id, tx):
    snap = doc(USERS, _identifier(user_id, "user_id")).get(transaction=tx)
    data = snap.to_dict() or {}
    if not snap.exists or data.get("role") not in {"customer", "vendor", "service"} or data.get("is_suspended"):
        raise KhataError("Referral account is unavailable", 403)
    return data


@referrals_bp.post("/referrals/generate")
@require_role("customer", "vendor", "service")
def generate_code():
    owner_ref = doc(REFERRALS, "owner_" + hashlib.sha256(g.user_id.encode()).hexdigest())
    for _ in range(10):
        candidate = _generate_code()

        @firestore.transactional
        def generate(tx):
            owner = owner_ref.get(transaction=tx)
            account = _account(g.user_id, tx)
            legacy = list(tx.get(col(REFERRALS).where(filter=FieldFilter("referrer_id", "==", g.user_id))))
            if owner.exists:
                return {"code": (owner.to_dict() or {}).get("code", "")}
            if legacy:
                # Keep the original issued code even after consumption.
                legacy.sort(key=lambda snap: (snap.to_dict() or {}).get("created_at") or "")
                return {"code": (legacy[0].to_dict() or {}).get("code", "")}
            reservation_ref = doc("referral_codes", candidate)
            reservation = reservation_ref.get(transaction=tx)
            collision = list(tx.get(col(REFERRALS).where(filter=FieldFilter("code", "==", candidate))))
            if reservation.exists or collision:
                raise KhataError("Referral code collision", 409)
            timestamp = now_iso()
            tx.set(owner_ref, {"referrer_id": g.user_id, "referee_id": "", "referrer_name": account.get("full_name") or account.get("username"),
                              "referee_name": None, "code": candidate, "status": "pending", "created_at": timestamp})
            tx.set(reservation_ref, {"referrer_id": g.user_id, "referral_id": owner_ref.id, "created_at": timestamp})
            return {"code": candidate}
        try:
            return jsonify(generate(db().transaction()))
        except KhataError as exc:
            if exc.detail != "Referral code collision":
                raise
    raise KhataError("Unable to allocate a referral code; retry later", 503)


@referrals_bp.post("/referrals/apply")
@require_role("customer", "vendor", "service")
def apply_code():
    code = _text(_payload().get("code"), "code", 10).upper()
    if not re.fullmatch(r"[A-Z0-9]{8,10}", code):
        raise KhataError("A valid referral code is required")
    marker_ref = doc("referral_applications", g.user_id)

    @firestore.transactional
    def apply(tx):
        referee = _account(g.user_id, tx)
        marker = marker_ref.get(transaction=tx)
        matches = list(tx.get(col(REFERRALS).where(filter=FieldFilter("code", "==", code))))
        used = list(tx.get(col(REFERRALS).where(filter=FieldFilter("referee_id", "==", g.user_id))))
        if not matches:
            raise KhataError("Invalid referral code", 404)
        if len(matches) != 1:
            raise KhataError("Duplicate referral codes require reconciliation", 409)
        referral_snap = matches[0]
        data = referral_snap.to_dict() or {}
        if data.get("referrer_id") == g.user_id:
            raise KhataError("Cannot apply your own referral")
        _account(data.get("referrer_id"), tx)
        if marker.exists or used:
            applied_code = (marker.to_dict() or {}).get("code") if marker.exists else (used[0].to_dict() or {}).get("code")
            if applied_code == code and data.get("referee_id") == g.user_id:
                return {"ok": True, "reward_credited": False}
            raise KhataError("An account can apply only one referral", 409)
        if data.get("referee_id"):
            raise KhataError("Referral code already used", 409)
        timestamp = now_iso()
        tx.update(referral_snap.reference, {"referee_id": g.user_id, "referee_name": referee.get("full_name") or referee.get("username"),
                                           "status": "applied", "applied_at": timestamp, "reward_status": "disabled"})
        tx.set(marker_ref, {"code": code, "referral_id": referral_snap.id, "referrer_id": data["referrer_id"], "created_at": timestamp})
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
