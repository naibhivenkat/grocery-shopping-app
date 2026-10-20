from auth_utils import (
    require_role,
    verify_password,
    hash_password,
    log_admin_action, AUDIT_LOGS
)
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
    SUPPORT_TICKETS,
    SHOP_ITEMS,
    APP_SETTINGS
)
from notification_delivery import deliver_push
from flask import Blueprint, jsonify, request, g
from firebase_admin import firestore
from db import db
from routes.khata import KhataError, _khata_error, _payload, _identifier, _text, _money_paise
from routes.vendors import _item_patch, _stock
import subscription_service as subscriptions
from routes.subscriptions import subscription_error
from routes.measurement import metadata, acknowledge
from google.cloud.firestore_v1.base_query import FieldFilter

admin_bp = Blueprint("admin", __name__)
admin_bp.register_error_handler(KhataError, _khata_error)
admin_bp.register_error_handler(subscriptions.SubscriptionError, subscription_error)
_ROLES = {"customer", "vendor", "service", "admin", "super_admin"}


def _user_changes(body, vendor_only=False):
    allowed = {"full_name", "email", "phone", "is_suspended"} | (set() if vendor_only else {"role"})
    if set(body) - allowed or not body:
        raise KhataError("Unsupported or missing user fields")
    changes = {}
    for field, maximum in (("full_name", 200), ("email", 254), ("phone", 40)):
        if field in body:
            changes[field] = _text(body[field], field, maximum)
            if not changes[field]:
                raise KhataError(f"{field} must not be empty")
            if field == "email":
                if "@" not in changes[field] or " " in changes[field]:
                    raise KhataError("A valid email is required")
                changes[field] = changes[field].lower()
    if "role" in body:
        if not isinstance(body["role"], str) or body["role"] not in _ROLES:
            raise KhataError("Invalid role")
        changes["role"] = body["role"]
    if "is_suspended" in body:
        if not isinstance(body["is_suspended"], bool):
            raise KhataError("is_suspended must be boolean")
        changes["is_suspended"] = body["is_suspended"]
    return changes


def _mutate_user(user_id, changes=None, *, delete=False, vendor_only=False, action="Update User"):
    ref = doc(USERS, _identifier(user_id, "user_id"))
    audit_ref = col(AUDIT_LOGS).document()
    changes = dict(changes or {})

    @firestore.transactional
    def mutate(tx):
        actor_snap = doc(USERS, g.user_id).get(transaction=tx)
        snapshot = ref.get(transaction=tx)
        actor = actor_snap.to_dict() or {}
        if not actor_snap.exists or actor.get("role") not in {"admin", "super_admin"} or actor.get("is_suspended"):
            raise KhataError("Administrative account is unavailable", 403)
        if not snapshot.exists:
            raise KhataError("User not found", 404)
        target = snapshot.to_dict() or {}
        current_role = target.get("role") or target.get("suspended_role")
        if vendor_only and current_role != "vendor":
            raise KhataError("Vendor not found", 404)
        if (current_role in {"admin", "super_admin"} or "role" in changes and changes["role"] != current_role) and actor.get("role") != "super_admin":
            raise KhataError("Only a super admin can manage administrative accounts or change roles", 403)
        dangerous = delete or changes.get("is_suspended") is True or "role" in changes and changes["role"] != current_role
        if user_id == g.user_id and dangerous:
            raise KhataError("You cannot remove, suspend or demote your own administrative account", 409)
        if current_role == "super_admin" and dangerous and not target.get("is_suspended"):
            supers = list(tx.get(col(USERS).where(filter=FieldFilter("role", "==", "super_admin"))))
            if sum(1 for snap in supers if not (snap.to_dict() or {}).get("is_suspended")) <= 1:
                raise KhataError("At least one active super admin must remain", 409)
        if "email" in changes:
            duplicate = list(tx.get(col(USERS).where(filter=FieldFilter("email", "==", changes["email"]))))
            if any(snap.id != user_id for snap in duplicate):
                raise KhataError("Email already belongs to another account", 409)
        activate_subscription = subscriptions.vendor_activation_plan(tx, user_id, g.user_id, lookup=doc) if not delete and changes.get("role") == "vendor" and current_role != "vendor" else (lambda: None)
        updates = {**changes, "updated_at": now_iso()}
        if "is_suspended" in changes:
            updates.update({"suspended_role": current_role if changes["is_suspended"] else None,
                            "suspended_at": now_iso() if changes["is_suspended"] else None})
            if not changes["is_suspended"] and not target.get("role") and current_role in _ROLES:
                updates["role"] = current_role
        if delete:
            tx.delete(ref)
        else:
            tx.update(ref, updates)
        activate_subscription()
        tx.set(audit_ref, {"admin_id": g.user_id, "admin_email": actor.get("email", ""), "action": action,
                           "target_id": user_id, "target_type": "vendor" if vendor_only else "user", "created_at": now_iso()})
    mutate(db().transaction())


def _safe_user(snapshot):
    return {key: value for key, value in to_dict(snapshot).items()
            if not any(secret in key.lower() for secret in ("password", "token", "secret", "otp"))}


def _paid_revenue(order):
    if order.get("payment_status") != "paid" or order.get("refund_status") in {"refunded", "completed"}:
        return 0
    try:
        return _money_paise(order.get("total_price", 0), allow_zero=True)
    except KhataError:
        return 0


def _existing_update(collection, identifier, changes):
    ref = doc(collection, _identifier(identifier, "id"))
    @firestore.transactional
    def update(tx):
        if not ref.get(transaction=tx).exists:
            raise KhataError("Record not found", 404)
        tx.update(ref, {**changes, "updated_at": now_iso()})
    update(db().transaction())



def _users_by_role(role: str, include_suspended: bool = False):
    query = col(USERS).where(filter=FieldFilter("role", "==", role))
    users = [_safe_user(d) for d in query.stream()]
    if include_suspended and role == "vendor":
        suspended_query = col(USERS).where(
            filter=FieldFilter("suspended_role", "==", "vendor")
        )
        existing = {u.get("uid") for u in users}
        users.extend(
            _safe_user(d)
            for d in suspended_query.stream()
            if d.id not in existing
        )
    return users


@admin_bp.get("/admin/customers/<user_id>")
@admin_bp.get("/admin/users/<user_id>")
@require_role("admin", "super_admin")
def get_customers(user_id):
    snapshot = doc(USERS, user_id).get()

    if not snapshot.exists:
        return jsonify({
            "detail": "User not found",
        }), 404

    user = to_dict(snapshot)

    user.pop("password_hash", None)

    return jsonify({
        "uid": user.get("uid", snapshot.id),
        "full_name": user.get("full_name", ""),
        "email": user.get("email", ""),
        "phone": user.get("phone", ""),
        "role": user.get("role", ""),
        "is_suspended": bool(user.get("is_suspended", False)),
    })


@admin_bp.put("/admin/customers/<user_id>")
@admin_bp.put("/admin/users/<user_id>")
@require_role("admin", "super_admin")
def update_customer(user_id):
    _mutate_user(user_id, _user_changes(_payload()))
    return jsonify({"success": True})


@admin_bp.delete("/admin/customers/<user_id>")
@admin_bp.delete("/admin/users/<user_id>")
@require_role("admin", "super_admin")
def delete_customer(user_id):
    _mutate_user(user_id, delete=True, action="Delete User")
    return jsonify({"success": True})


@admin_bp.get("/admin/stats")
@require_role("admin", "super_admin")
def get_stats():
    vendors = list(
        col(USERS)
        .where(filter=FieldFilter("role", "==", "vendor"))
        .stream()
    )

    customers = list(
        col(USERS)
        .where(filter=FieldFilter("role", "==", "customer"))
        .stream()
    )

    active_subs = list(
        col(VENDOR_SUBSCRIPTIONS)
        .where(filter=FieldFilter("status", "==", "active"))
        .stream()
    )

    total_revenue = 0
    total_orders = 0

    pending_orders = 0
    confirmed_orders = 0
    delivered_orders = 0
    cancelled_orders = 0

    for d in col(CUSTOMER_ORDERS).stream():

        total_orders += 1

        data = d.to_dict() or {}

        status = str(
            data.get("status", "")
        ).lower()

        if status == "pending":
            pending_orders += 1

        elif status in {"confirmed", "accepted", "packed"}:
            confirmed_orders += 1

        elif status in {"delivered", "completed"}:
            delivered_orders += 1

        elif status == "cancelled":
            cancelled_orders += 1

        total_revenue += _paid_revenue(data) / 100

    return jsonify({
        "vendor_count": len(vendors),
        "customer_count": len(customers),
        "total_orders": total_orders,
        "active_subscriptions": len(active_subs),
        "pending_orders": pending_orders,
        "confirmed_orders": confirmed_orders,
        "delivered_orders": delivered_orders,
        "cancelled_orders": cancelled_orders,
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



@admin_bp.get("/admin/vendors/<vendor_id>")
@require_role("admin", "super_admin")
def get_vendor(vendor_id):
    snapshot = doc(USERS, vendor_id).get()

    if not snapshot.exists:
        return jsonify({
            "detail": "Vendor not found",
        }), 404

    vendor = to_dict(snapshot)

    if (
        vendor.get("role") != "vendor"
        and vendor.get("suspended_role") != "vendor"
    ):
        return jsonify({
            "detail": "Vendor not found",
        }), 404

    vendor.pop("password_hash", None)

    return jsonify({
        "uid": vendor.get("uid", snapshot.id),
        "full_name": vendor.get("full_name", ""),
        "email": vendor.get("email", ""),
        "phone": vendor.get("phone", ""),
        "role": "vendor",
        "is_suspended": bool(
            vendor.get("is_suspended", False),
        ),
    })

@admin_bp.put("/admin/vendors/<vendor_id>")
@require_role("admin", "super_admin")
def update_vendor(vendor_id):
    _mutate_user(vendor_id, _user_changes(_payload(), vendor_only=True), vendor_only=True, action="Update Vendor")
    return jsonify({"success": True})


@admin_bp.delete("/admin/vendors/<vendor_id>")
@require_role("admin", "super_admin")
def delete_vendor(vendor_id):
    _mutate_user(vendor_id, delete=True, vendor_only=True, action="Delete Vendor")
    return jsonify({"success": True})


@admin_bp.post("/admin/vendors/<vendor_id>/suspend")
@require_role("admin", "super_admin")
def suspend_vendor(vendor_id):
    _mutate_user(vendor_id, {"is_suspended": True}, vendor_only=True, action="Suspend Vendor")
    return jsonify({"success": True, "ok": True})


@admin_bp.post("/admin/vendors/<vendor_id>/unsuspend")
@require_role("admin", "super_admin")
def unsuspend_vendor(vendor_id):
    _mutate_user(vendor_id, {"is_suspended": False}, vendor_only=True, action="Unsuspend Vendor")
    return jsonify({"success": True, "ok": True})


@admin_bp.get("/admin/customers")
@admin_bp.get("/admin/users")
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


@admin_bp.post("/admin/customers/<user_id>/suspend")
@admin_bp.post("/admin/users/<user_id>/suspend")
@require_role("admin", "super_admin")
def suspend_customers(user_id):
    _mutate_user(user_id, {"is_suspended": True}, vendor_only=False, action="Suspend User")
    return jsonify({"success": True, "ok": True})


@admin_bp.post("/admin/customers/<user_id>/unsuspend")
@admin_bp.post("/admin/users/<user_id>/unsuspend")
@require_role("admin", "super_admin")
def unsuspend_customers(user_id):
    _mutate_user(user_id, {"is_suspended": False}, vendor_only=False, action="Unsuspend User")
    return jsonify({"success": True, "ok": True})


@admin_bp.get("/admin/orders")
@require_role("admin", "super_admin")
def admin_orders():
    docs = col(CUSTOMER_ORDERS).stream()

    orders = []

    for doc_snap in docs:
        data = to_dict(doc_snap)

        customer_name = data.get("customer_name")
        if not isinstance(customer_name, str):
            data["customer_name"] = ""

        vendor_name = data.get("vendor_name")
        if not isinstance(vendor_name, str):
            data["vendor_name"] = ""

        item_name = data.get("item_name")
        if not isinstance(item_name, str):
            data["item_name"] = ""

        status = data.get("status")
        if not isinstance(status, str):
            data["status"] = ""

        orders.append(data)

    return jsonify(orders)


@admin_bp.get("/admin/products")
@require_role("admin", "super_admin")
def admin_products():
    docs = col(SHOP_ITEMS).stream()

    products = []

    for doc_snap in docs:
        product = to_dict(doc_snap)

        image_urls = product.get("image_urls") or []
        if not isinstance(image_urls, list):
            image_urls = []

        try:
            stock = _stock(product.get("stock_quantity", 0))
        except KhataError:
            stock = 0

        product["total_images"] = len(image_urls)

        product["primary_image"] = (
            image_urls[0] if image_urls else ""
        )

        product["has_stock"] = stock > 0

        product["status"] = (
            "Available"
            if product.get("is_available", True)
            else "Disabled"
        )

        product["stock_status"] = (
            "Out of Stock"
            if stock <= 0
            else (
                "Low Stock"
                if stock < 10
                else "In Stock"
            )
        )

        products.append(product)

    products.sort(
        key=lambda x: x.get("updated_at") or "",
        reverse=True,
    )

    return jsonify(products)


@admin_bp.get("/admin/products/<product_id>")
@require_role("admin", "super_admin")
def get_product(product_id):
    snapshot = doc(SHOP_ITEMS, product_id).get()

    if not snapshot.exists:
        return jsonify(
            {
                "detail": "Product not found"
            }
        ), 404

    product = to_dict(snapshot)

    images = product.get("image_urls") or []
    if not isinstance(images, list):
        images = []

    try:
        stock = _stock(product.get("stock_quantity", 0))
    except KhataError:
        stock = 0

    product["total_images"] = len(images)

    product["primary_image"] = (
        images[0] if images else ""
    )

    product["status"] = (
        "Available"
        if product.get("is_available", True)
        else "Disabled"
    )

    product["has_stock"] = stock > 0

    return jsonify(product)


import uuid


@admin_bp.post("/admin/products")
@require_role("admin", "super_admin")
def create_product():
    body = _payload()
    vendor_id = _identifier(body.get("vendor_id"), "vendor_id")
    editable = {key: value for key, value in body.items() if key not in {"vendor_id", "vendor_name", "vendor_email", "vendor_phone", "vendor_shop_description"}}
    product = _item_patch(editable, creating=True)
    if product.get("is_available") and product["stock_quantity"] == 0:
        raise KhataError("An item with no stock cannot be available")
    ref = col(SHOP_ITEMS).document()
    @firestore.transactional
    def create(tx):
        snap = doc(USERS, vendor_id).get(transaction=tx)
        vendor = snap.to_dict() or {}
        if not snap.exists or vendor.get("role") != "vendor" or vendor.get("is_suspended"):
            raise KhataError("Vendor is unavailable", 404)
        apply_usage = subscriptions.catalog_change_plan(tx, vendor_id, delta=1, lookup=doc)
        tx.set(ref, {**product, "vendor_id": vendor_id, "vendor_name": vendor.get("shop_name") or vendor.get("full_name"),
                     "vendor_phone": vendor.get("phone"), "vendor_email": vendor.get("email"), "city_id": vendor.get("city_id"),
                     "vendor_shop_description": vendor.get("shop_address"), "created_at": now_iso(), "updated_at": now_iso()})
        apply_usage()
    create(db().transaction())
    log_admin_action(g.user_id, getattr(g, "user_email", ""), "Create Product", ref.id, "product")
    return jsonify({"success": True, "uid": ref.id})


@admin_bp.put("/admin/products/<product_id>")
@require_role("admin", "super_admin")
def update_product(product_id):
    changes = _item_patch(_payload())
    ref = doc(SHOP_ITEMS, _identifier(product_id, "product_id"))
    @firestore.transactional
    def update(tx):
        snap = ref.get(transaction=tx)
        if not snap.exists:
            raise KhataError("Product not found", 404)
        current = snap.to_dict() or {}
        combined = {**current, **changes}
        metadata(combined)
        if metadata(current)["stock_unit"] != metadata(combined)["stock_unit"]:
            raise KhataError("Create a new product to change its inventory measurement", 409)
        if any(field in changes for field in ("stock_quantity", "low_stock_threshold")):
            acknowledge(current, changes.get("stock_unit"))
        if changes.get("is_available") is True and _stock(changes.get("stock_quantity", current.get("stock_quantity", 0))) == 0:
            raise KhataError("An item with no stock cannot be available")
        tx.update(ref, {**changes, "updated_at": now_iso()})
    update(db().transaction())
    log_admin_action(g.user_id, getattr(g, "user_email", ""), "Update Product", product_id, "product")
    return jsonify({"success": True})


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

        revenue += _paid_revenue(data) / 100

    return jsonify({
        "vendors": len(vendors),
        "customers": len(customers),
        "orders": len(orders),
        "revenue": revenue,
    })




@admin_bp.post("/admin/notifications/send")
@require_role("admin", "super_admin")
def send_notification():
    data = _payload()

    title = _text(data.get("title"), "title", 200)
    message = _text(data.get("message"), "message", 4000)
    target = _text(data.get("target", "all"), "target", 20).lower()



    if not title:
        return jsonify({"detail": "Title is required"}), 400

    if not message:
        return jsonify({"detail": "Message is required"}), 400

    users_query = col(USERS)

    # Customers
    if target in ("customer", "customers"):
        users_query = users_query.where(
            filter=FieldFilter("role", "==", "customer")
        )

    # Vendors
    elif target in ("vendor", "vendors"):
        users_query = users_query.where(
            filter=FieldFilter("role", "==", "vendor")
        )

    # Admins
    elif target in ("admin", "admins"):
        users_query = users_query.where(
            filter=FieldFilter("role", "in", ["admin", "super_admin"])
        )

    # All users
    elif target == "all":
        pass

    else:
        return jsonify({"detail": f"Unknown target: {target}"}), 400

    users = list(users_query.stream())



    db = col(USERS)._client
    batch = db.batch()

    count = 0
    pending_pushes = []

    for user in users:
        if (user.to_dict() or {}).get("is_suspended"):
            continue
        ref = col(NOTIFICATIONS).document()

        batch.set(
            ref,
            {
                "uid": ref.id,
                "user_id": user.id,
                "title": title,
                "message": message,
                "body": message,
                "type": "announcement",
                "target": target,
                "is_read": False,
                "created_at": now_iso(),
            },
        )

        pending_pushes.append({"user_id": user.id, "type": "announcement", "title": title,
                               "body": message, "reference_id": ref.id})
        count += 1

        if count % 450 == 0:
            batch.commit()
            for event in pending_pushes:
                deliver_push(event, lookup=doc)
            pending_pushes.clear()
            batch = db.batch()

    if count % 450 != 0:
        batch.commit()
        for event in pending_pushes:
            deliver_push(event, lookup=doc)

    return jsonify(
        {
            "success": True,
            "sent": count,
            "target": target,
        }
    )


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
    from routes.support import list_support_tickets as canonical_list
    return canonical_list.__wrapped__()


@admin_bp.post("/admin/support/reply")
@require_role("admin", "super_admin")
def reply_support_ticket():
    from routes.support import send_ticket_reply
    data = _payload()
    ticket_id = _identifier(data.get("ticket_id"), "ticket_id")
    reply = _text(data.get("reply"), "reply", 4000)
    if not reply:
        raise KhataError("reply is required")
    result, status = send_ticket_reply(ticket_id, reply, g.user_id,
        getattr(g, "user_email", ""), getattr(g, "user_name", ""), request.headers.get("Idempotency-Key"))
    return jsonify(result), status


@admin_bp.post("/admin/support/create")
@require_role("admin", "super_admin")
def create_support_ticket():
    data = _payload()
    message = _text(data.get("message"), "message", 4000)
    if not message:
        raise KhataError("message is required")
    ref = col(SUPPORT_TICKETS).document()
    ticket = {"uid": ref.id, "user_name": _text(data.get("user_name"), "user_name", 200),
              "message": message, "status": "open", "created_at": now_iso()}
    ref.set(ticket)
    return jsonify(ticket)


@admin_bp.post("/admin/change-password")
@require_role("admin", "super_admin")
def change_password():
    data = _payload()
    current_password = data.get("current_password")
    new_password = data.get("new_password")
    if not isinstance(current_password, str) or not 1 <= len(current_password) <= 128 or not isinstance(new_password, str) or not 8 <= len(new_password) <= 128:
        raise KhataError("Current password and a new password of at least 8 characters are required")
    ref = doc(USERS, g.user_id)
    @firestore.transactional
    def change(tx):
        snapshot = ref.get(transaction=tx)
        if not snapshot.exists:
            raise KhataError("User not found", 404)
        user = snapshot.to_dict() or {}
        if not verify_password(current_password, user.get("password_hash", "")):
            raise KhataError("Current password incorrect", 403)
        tx.update(ref, {"password_hash": hash_password(new_password), "password_reset_at": now_iso(), "updated_at": now_iso()})
    change(db().transaction())
    return jsonify({"success": True})


@admin_bp.post("/admin/products/<product_id>/disable")
@require_role("admin", "super_admin")
def disable_product(product_id):
    product_ref = doc(SHOP_ITEMS, product_id)
    snapshot = product_ref.get()

    if not snapshot.exists:
        return jsonify({
            "detail": "Product not found"
        }), 404

    product_ref.update({
        "is_available": False,
        "disabled_by_admin": True,
        "updated_at": now_iso(),
    })

    log_admin_action(
        admin_id=g.user_id,
        admin_email=getattr(g, "user_email", ""),
        action="Disable Product",
        target_id=product_id,
        target_type="product",
    )

    return jsonify({
        "success": True,
        "message": "Product disabled successfully",
    }), 200


@admin_bp.post("/admin/products/<product_id>/enable")
@require_role("admin", "super_admin")
def enable_product(product_id):
    ref = doc(SHOP_ITEMS, _identifier(product_id, "product_id"))
    @firestore.transactional
    def enable(tx):
        snap = ref.get(transaction=tx)
        if not snap.exists:
            raise KhataError("Product not found", 404)
        if _stock((snap.to_dict() or {}).get("stock_quantity", 0)) == 0:
            raise KhataError("An item with no stock cannot be enabled", 409)
        tx.update(ref, {"is_available": True, "disabled_by_admin": False, "updated_at": now_iso()})
    enable(db().transaction())
    log_admin_action(g.user_id, getattr(g, "user_email", ""), "Enable Product", product_id, "product")
    return jsonify({"success": True})


@admin_bp.delete("/admin/products/<product_id>")
@require_role("admin", "super_admin")
def delete_product(product_id):
    ref = doc(SHOP_ITEMS, _identifier(product_id, "product_id"))
    @firestore.transactional
    def remove(tx):
        snapshot = ref.get(transaction=tx)
        if not snapshot.exists:
            raise KhataError("Product not found", 404)
        orders = tx.get(col(CUSTOMER_ORDERS).where(filter=FieldFilter("item_id", "==", product_id)))
        if any((snap.to_dict() or {}).get("status") in {"pending", "confirmed", "accepted", "packed"} for snap in orders):
            raise KhataError("Fulfill or cancel active orders before deleting this item", 409)
        proposals = tx.get(col("order_amendments").where(filter=FieldFilter("vendor_id", "==", (snapshot.to_dict() or {}).get("vendor_id"))))
        if any(((proposal.to_dict() or {}).get("status") in {"pending", "awaiting_payment"} or (proposal.to_dict() or {}).get("stock_reserved"))
               and any(line.get("item_id") == product_id for line in (proposal.to_dict() or {}).get("lines", []))
               for proposal in proposals):
            raise KhataError("Resolve the pending order amendment before deleting this reserved product", 409)
        apply_usage = subscriptions.catalog_change_plan(tx, (snapshot.to_dict() or {}).get("vendor_id"), delta=-1, lookup=doc)
        tx.delete(ref)
        apply_usage()
    remove(db().transaction())
    log_admin_action(g.user_id, getattr(g, "user_email", ""), "Delete Product", product_id, "product")
    return jsonify({"success": True})


@admin_bp.get("/admin/orders/<order_id>")
@require_role("admin", "super_admin")
def get_order_detail(order_id):
    snapshot = doc(CUSTOMER_ORDERS, order_id).get()

    if not snapshot.exists:
        return jsonify({
            "detail": "Order not found"
        }), 404

    return jsonify(to_dict(snapshot))


@admin_bp.post("/admin/orders/<order_id>/cancel")
@require_role("admin", "super_admin")
def admin_cancel_order(order_id):
    snapshot = doc(CUSTOMER_ORDERS, _identifier(order_id, "order_id")).get()
    if not snapshot.exists:
        raise KhataError("Order not found", 404)
    from routes.shops import cancel_order_atomic
    try:
        cancel_order_atomic(order_id, (snapshot.to_dict() or {}).get("vendor_id"), vendor=True)
    except PermissionError as exc:
        raise KhataError(str(exc), 403) from None
    except ValueError as exc:
        raise KhataError(str(exc), 409) from None
    return jsonify({"success": True})


@admin_bp.post("/admin/orders/<order_id>/refund")
@require_role("admin", "super_admin")
def refund_order(order_id):
    from routes.order_refunds import refund_order as process_refund
    try:
        result = process_refund(_identifier(order_id, "order_id"), g.user_id, allow_admin=True)
    except PermissionError as exc:
        raise KhataError(str(exc), 403) from None
    except ValueError as exc:
        raise KhataError(str(exc), 409) from None
    status = {"completed": 200, "submitted": 202, "processing": 202, "retryable": 503, "requires_review": 409}[result["status"]]
    return jsonify({"success": result["status"] in {"submitted", "completed"}, "refund": result}), status


@admin_bp.get("/admin/audit-logs")
@require_role("admin", "super_admin")
def audit_logs():
    try:
        print("AUDIT LOG ROUTE HIT")

        logs = [
            to_dict(d)
            for d in col(AUDIT_LOGS).stream()
        ]

        print(f"FOUND {len(logs)} LOGS")

        logs.sort(
            key=lambda x: x.get("created_at", ""),
            reverse=True,
        )

        return jsonify(logs)

    except Exception as e:
        import traceback
        traceback.print_exc()

        return jsonify({
            "error": str(e),
            "type": type(e).__name__,
        }), 500


@admin_bp.get("/maintenance-status")
def maintenance_status():
    settings_doc = doc(
        APP_SETTINGS,
        "config",
    ).get()

    if not settings_doc.exists:
        return jsonify({
            "maintenance_mode": False,
        })

    data = settings_doc.to_dict() or {}

    return jsonify({
        "maintenance_mode":
            data.get(
                "maintenance_mode",
                False,
            ),
    })


@admin_bp.post("/admin/maintenance")
@require_role("admin", "super_admin")
def update_maintenance_status():
    data = _payload()
    maintenance = data.get("maintenance_mode")
    if not isinstance(maintenance, bool):
        raise KhataError("maintenance_mode must be boolean")
    doc(APP_SETTINGS, "config").set({"maintenance_mode": maintenance, "updated_at": now_iso()}, merge=True)
    return jsonify({"success": True, "maintenance_mode": maintenance})


@admin_bp.get("/admin/maintenance")
@require_role("admin", "super_admin")
def get_maintenance_status():
    settings_doc = doc(
        APP_SETTINGS,
        "config",
    ).get()

    if not settings_doc.exists:
        return jsonify({
            "maintenance_mode": False,
        })

    data = settings_doc.to_dict() or {}

    return jsonify({
        "maintenance_mode":
            data.get(
                "maintenance_mode",
                False,
            ),
        "updated_at":
            data.get("updated_at"),
    })


@admin_bp.get("/admin/recent-orders")
@require_role("admin", "super_admin")
def get_recent_orders():
    try:

        docs = (
            col(CUSTOMER_ORDERS)
            .order_by("created_at", direction="DESCENDING")
            .limit(20)
            .stream()
        )

        orders = []

        for d in docs:
            data = d.to_dict() or {}

            orders.append({
                "id": d.id,
                "uid": d.id,
                "customer_id": data.get("customer_id"),
                "vendor_id": data.get("vendor_id"),
                "vendor_name": data.get("vendor_name", ""),
                "item_name": data.get("item_name", ""),
                "quantity": data.get("quantity", 0),
                "total_price": data.get("total_price", 0),
                "payment_method": data.get("payment_method", ""),
                "status": data.get("status", ""),
                "created_at": data.get("created_at", ""),
            })

        return jsonify(orders)

    except Exception as e:
        return jsonify({
            "error": str(e)
        }), 500
