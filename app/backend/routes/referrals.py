"""`/referrals/*` endpoints consumed by `ReferralRemoteDataSource`."""

import secrets
import string

from flask import Blueprint, g, jsonify, request
from google.cloud.firestore_v1.base_query import FieldFilter

from auth_utils import require_auth
from db import REFERRALS, USERS, col, doc, now_iso, to_dict


referrals_bp = Blueprint("referrals", __name__)


def _generate_code(length: int = 8) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _unique_code() -> str:
    for _ in range(10):
        code = _generate_code()
        existing = next(
            iter(
                col(REFERRALS)
                .where(filter=FieldFilter("code", "==", code))
                .limit(1)
                .stream()
            ),
            None,
        )
        if existing is None:
            return code
    return _generate_code(10)


@referrals_bp.post("/referrals/generate")
@require_auth
def generate_code():
    query = (
        col(REFERRALS)
        .where(filter=FieldFilter("referrer_id", "==", g.user_id))
        .where(filter=FieldFilter("referee_id", "==", ""))
        .limit(1)
        .stream()
    )
    existing = next(iter(query), None)
    if existing is not None:
        return jsonify({"code": (existing.to_dict() or {}).get("code", "")})

    code = _unique_code()
    referrer = doc(USERS, g.user_id).get().to_dict() or {}
    col(REFERRALS).document().set({
        "referrer_id": g.user_id,
        "referee_id": "",
        "referrer_name": referrer.get("full_name"),
        "referee_name": None,
        "code": code,
        "status": "pending",
        "created_at": now_iso(),
    })
    return jsonify({"code": code})


@referrals_bp.post("/referrals/apply")
@require_auth
def apply_code():
    payload = request.get_json(silent=True) or {}
    code = (payload.get("code") or "").strip().upper()
    if not code:
        return jsonify({"detail": "code is required"}), 422

    query = (
        col(REFERRALS)
        .where(filter=FieldFilter("code", "==", code))
        .limit(1)
        .stream()
    )
    referral_snap = next(iter(query), None)
    if referral_snap is None:
        return jsonify({"detail": "Invalid referral code"}), 404

    data = referral_snap.to_dict() or {}
    if data.get("referrer_id") == g.user_id:
        return jsonify({"detail": "Cannot apply your own referral"}), 422
    if data.get("referee_id"):
        return jsonify({"detail": "Referral code already used"}), 422

    referee = doc(USERS, g.user_id).get().to_dict() or {}
    referral_snap.reference.update({
        "referee_id": g.user_id,
        "referee_name": referee.get("full_name"),
        "status": "applied",
        "applied_at": now_iso(),
    })
    return jsonify({"ok": True})


@referrals_bp.get("/referrals")
@require_auth
def list_my_referrals():
    as_referrer = col(REFERRALS).where(
        filter=FieldFilter("referrer_id", "==", g.user_id)
    )
    as_referee = col(REFERRALS).where(
        filter=FieldFilter("referee_id", "==", g.user_id)
    )
    out = {d.id: to_dict(d) for d in as_referrer.stream()}
    out.update({d.id: to_dict(d) for d in as_referee.stream()})
    return jsonify(list(out.values()))
