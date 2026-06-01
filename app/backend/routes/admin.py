from flask import Blueprint, jsonify, request, g
from google.cloud.firestore_v1.base_query import FieldFilter

from auth_utils import require_role
from db import (
    CUSTOMER_ORDERS,
    SHOP_ITEMS,
    USERS,
    VENDOR_SUBSCRIPTIONS,
    col,
    doc,
    now_iso,
    to_dict,
NOTIFICATIONS,
SUPPORT_TICKETS
)
#from werkzeug.security import check_password_hash, generate_password_hash



admin_bp = Blueprint("admin", __name__)


def _users_by_role(role: str, include_suspended: bool = False):
    query = col(USERS).where(filter=FieldFilter("role", "==", role))
    users = [to_dict(d) for d in query.stream()]
    if include_suspended and role == "vendor":
        suspended_query = col(USERS).where(
            filter=FieldFilter("suspended_role", "==", "vendor")
        )
        existing = {u.get("uid") for u in users}
        users.extend(
            to_dict(d)
            for d in suspended_query.stream()
            if d.id not in existing
        )
    return users


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
    vendors = _users_by_role("vendor", include_suspended=True)
    for v in vendors:
        v.pop("password_hash", None)
        v["id"] = v.get("uid")
        v["role"] = v.get("role") or "vendor"
        v["is_suspended"] = bool(v.get("is_suspended"))
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
    snap = doc(USERS, user_id).get()
    current_role = (snap.to_dict() or {}).get("role") if snap.exists else None
    doc(USERS, user_id).set({
        "is_suspended": True,
        "suspended_role": current_role,
        "suspended_at": now_iso(),
    }, merge=True)
    return jsonify({"ok": True})


@admin_bp.post("/admin/users/<user_id>/unsuspend")
@require_role("admin", "super_admin")
def unsuspend_user(user_id):
    doc(USERS, user_id).set(
        {"is_suspended": False, "suspended_at": None, "suspended_role": None},
        merge=True,
    )
    return jsonify({"ok": True})


@admin_bp.get("/admin/orders")
@require_role("admin", "super_admin")
def admin_orders():
    docs = col(CUSTOMER_ORDERS).stream()

    orders = []

    for doc_snap in docs:
        data = to_dict(doc_snap)

        orders.append(data)

    return jsonify(orders)


@admin_bp.get("/admin/products")
@require_role("admin", "super_admin")
def admin_products():
    docs = col(SHOP_ITEMS).stream()

    products = []

    for doc_snap in docs:
        data = to_dict(doc_snap)

        products.append(data)

    return jsonify(products)

@admin_bp.get("/admin/analytics")
@require_role("admin", "super_admin")
def analytics():
    vendors = list(
        col(USERS).where(
            filter=FieldFilter("role", "==", "vendor")
        ).stream()
    )

    customers = list(
        col(USERS).where(
            filter=FieldFilter("role", "==", "customer")
        ).stream()
    )

    orders = list(col(CUSTOMER_ORDERS).stream())

    revenue = 0.0

    for d in orders:
        data = d.to_dict() or {}

        try:
            revenue += float(
                data.get("total_price") or 0
            )
        except Exception:
            pass

    return jsonify({
        "vendors": len(vendors),
        "customers": len(customers),
        "orders": len(orders),
        "revenue": revenue,
    })


@admin_bp.post("/admin/notifications/send")
@require_role("admin", "super_admin")
def send_notification():
    data = request.get_json(force=True)

    notification = {
        "title": data.get("title", ""),
        "message": data.get("message", ""),
        "target": data.get("target", "all"),
        "created_at": now_iso(),
    }

    ref = col(NOTIFICATIONS).document()

    notification["uid"] = ref.id

    ref.set(notification)

    return jsonify({
        "success": True,
        "notification": notification,
    })


@admin_bp.get("/admin/notifications")
@require_role("admin", "super_admin")
def list_notifications():
    docs = col(NOTIFICATIONS).stream()

    notifications = []

    for d in docs:
        notifications.append(to_dict(d))

    return jsonify(notifications)


@admin_bp.get("/admin/support")
@require_role("admin", "super_admin")
def list_support_tickets():
    docs = col(SUPPORT_TICKETS).stream()

    tickets = []

    for d in docs:
        tickets.append(to_dict(d))

    return jsonify(tickets)


@admin_bp.post("/admin/support/reply")
@require_role("admin", "super_admin")
def reply_support_ticket():
    data = request.get_json(force=True)

    ticket_id = data.get("ticket_id")

    if not ticket_id:
        return jsonify({
            "error": "ticket_id required"
        }), 400

    update_data = {
        "admin_reply": data.get("reply", ""),
        "status": "resolved",
        "resolved_at": now_iso(),
    }

    doc(SUPPORT_TICKETS, ticket_id).set(
        update_data,
        merge=True,
    )

    return jsonify({
        "success": True,
    })


@admin_bp.post("/admin/support/create")
@require_role("admin", "super_admin")
def create_support_ticket():
    data = request.get_json(force=True)

    ref = col(SUPPORT_TICKETS).document()

    ticket = {
        "uid": ref.id,
        "user_name": data.get("user_name"),
        "message": data.get("message"),
        "status": "open",
        "created_at": now_iso(),
    }

    ref.set(ticket)

    return jsonify(ticket)


#
# @admin_bp.post("/auth/change-password")
# @require_role("admin", "super_admin")
# def change_password():
#     data = request.get_json(force=True)
#
#     current_password = data.get("current_password")
#     new_password = data.get("new_password")
#
#     if not current_password:
#         return jsonify({
#             "detail": "Current password required"
#         }), 400
#
#     if not new_password:
#         return jsonify({
#             "detail": "New password required"
#         }), 400
#
#     user_id = g.user_id
#
#     user_snapshot = doc(USERS, user_id).get()
#
#     if not user_snapshot.exists:
#         return jsonify({
#             "detail": "User not found"
#         }), 404
#
#     user = user_snapshot.to_dict() or {}
#
#     stored_hash = user.get("password_hash")
#
#     if not stored_hash:
#         return jsonify({
#             "detail": "Password not configured"
#         }), 400
#
#     if not check_password_hash(
#         stored_hash,
#         current_password,
#     ):
#         return jsonify({
#             "detail": "Current password incorrect"
#         }), 400
#
#     doc(USERS, user_id).set(
#         {
#             "password_hash":
#                 generate_password_hash(new_password)
#         },
#         merge=True,
#     )
#
#     return jsonify({
#         "success": True,
#         "message": "Password changed successfully"
#     })