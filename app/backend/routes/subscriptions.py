"""`/subscriptions/*` endpoints consumed by `SubscriptionRemoteDataSource`."""

from datetime import datetime, timedelta, timezone

from flask import Blueprint, g, jsonify, request
from google.cloud.firestore_v1.base_query import FieldFilter

from auth_utils import require_auth, require_role
from db import (
    SUBSCRIPTION_PLANS,
    VENDOR_SUBSCRIPTIONS,
    col,
    doc,
    now_iso,
    to_dict,
)


subscriptions_bp = Blueprint("subscriptions", __name__)


@subscriptions_bp.get("/subscriptions/plans")
def list_plans():
    plans = [to_dict(d) for d in col(SUBSCRIPTION_PLANS).stream()]
    return jsonify(plans)


@subscriptions_bp.get("/subscriptions/me")
@require_auth
def my_subscription():
    query = (
        col(VENDOR_SUBSCRIPTIONS)
        .where(filter=FieldFilter("vendor_id", "==", g.user_id))
        .where(filter=FieldFilter("status", "==", "active"))
        .limit(1)
        .stream()
    )
    snap = next(iter(query), None)
    if snap is None:
        return jsonify({"detail": "No active subscription"}), 404
    return jsonify(to_dict(snap))


@subscriptions_bp.post("/subscriptions/subscribe")
@require_role("vendor")
def subscribe():
    payload = request.get_json(silent=True) or {}
    plan_id = payload.get("plan_id")
    if not plan_id:
        return jsonify({"detail": "plan_id is required"}), 422

    plan_snap = doc(SUBSCRIPTION_PLANS, plan_id).get()
    if not plan_snap.exists:
        return jsonify({"detail": "Plan not found"}), 404
    plan = plan_snap.to_dict() or {}

    duration_days = int(plan.get("duration_days") or 30)
    now = datetime.now(timezone.utc)
    end = now + timedelta(days=duration_days)

    ref = col(VENDOR_SUBSCRIPTIONS).document()
    ref.set({
        "vendor_id": g.user_id,
        "plan_id": plan_id,
        "plan": plan.get("name") or "basic",
        "max_items": plan.get("max_items") or 10,
        # Start as pending until a payment is verified; the Flutter client
        # confirms activation via the payments flow.
        "status": "pending",
        "start_date": now.isoformat(),
        "end_date": end.isoformat(),
        "created_at": now_iso(),
    })
    return jsonify(to_dict(ref.get())), 201
