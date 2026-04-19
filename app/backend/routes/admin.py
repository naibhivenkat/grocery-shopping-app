"""`/admin/*` endpoints consumed by `AdminRemoteDataSource`."""

from flask import Blueprint, jsonify
from google.cloud.firestore_v1.base_query import FieldFilter

from auth_utils import require_role
from db import (
    CUSTOMER_ORDERS,
    USERS,
    VENDOR_SUBSCRIPTIONS,
    col,
    doc,
    now_iso,
    to_dict,
)


admin_bp = Blueprint("admin", __name__)


def _users_by_role(role: str):
    query = col(USERS).where(filter=FieldFilter("role", "==", role))
    return [to_dict(d) for d in query.stream()]


@admin_bp.get("/admin/stats")
@require_role("admin", "super_admin")
def get_stats():
    vendors = list(col(USERS).where(filter=FieldFilter("role", "==", "vendor")).stream())
    customers = list(col(USERS).where(filter=FieldFilter("role", "==", "customer")).stream())
    active_subs = list(
        col(VENDOR_SUBSCRIPTIONS).where(filter=FieldFilter("status", "==", "active")).stream()
    )
    total_revenue = 0.0
    for d in col(CUSTOMER_ORDERS).stream():
        data = d.to_dict() or {}
        if data.get("status") in {"completed", "delivered", "paid"}:
            try:
                total_revenue += float(data.get("total_price") or 0)
            except (TypeError, ValueError):
                pass
    return jsonify({
        "vendor_count": len(vendors),
        "customer_count": len(customers),
        "active_subscriptions": len(active_subs),
        "total_revenue": total_revenue,
    })


@admin_bp.get("/admin/vendors")
@require_role("admin", "super_admin")
def list_vendors():
    vendors = _users_by_role("vendor")
    for v in vendors:
        v.pop("password_hash", None)
        v["id"] = v.get("uid")
    return jsonify(vendors)


@admin_bp.get("/admin/customers")
@require_role("admin", "super_admin")
def list_customers():
    customers = _users_by_role("customer")
    for c in customers:
        c.pop("password_hash", None)
        c["id"] = c.get("uid")
        # Compute lightweight orders_count; safe for small datasets.
        orders_query = col(CUSTOMER_ORDERS).where(
            filter=FieldFilter("customer_id", "==", c["id"])
        )
        c["orders_count"] = sum(1 for _ in orders_query.stream())
    return jsonify(customers)


@admin_bp.post("/admin/users/<user_id>/suspend")
@require_role("admin", "super_admin")
def suspend_user(user_id):
    doc(USERS, user_id).set(
        {"is_suspended": True, "suspended_at": now_iso()}, merge=True
    )
    return jsonify({"ok": True})


@admin_bp.post("/admin/users/<user_id>/unsuspend")
@require_role("admin", "super_admin")
def unsuspend_user(user_id):
    doc(USERS, user_id).set(
        {"is_suspended": False, "suspended_at": None}, merge=True
    )
    return jsonify({"ok": True})
