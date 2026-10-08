"""`/vendors/*` endpoints consumed by `VendorRemoteDataSource`."""

from firebase_admin import firestore
from flask import Blueprint, g, jsonify, request
from google.cloud.firestore_v1.base_query import FieldFilter

from auth_utils import require_role
from db import CUSTOMER_ORDERS, SHOP_ITEMS, USERS, col, db, doc, now_iso, to_dict
from routes.khata import KhataError, _khata_error, _payload, _identifier, _text, _money_paise


vendors_bp = Blueprint("vendors", __name__)
vendors_bp.register_error_handler(KhataError, _khata_error)


def _stock(value):
    if isinstance(value, bool) or not isinstance(value, (int, str)) or not str(value).isdigit():
        raise KhataError("Stock must be a nonnegative whole number")
    number = int(value)
    if not 0 <= number <= 10_000_000:
        raise KhataError("Stock must be between 0 and 10000000")
    return number


def _item_patch(payload, creating=False):
    allowed = {"name", "description", "price", "category", "stock_quantity", "image_urls", "is_available", "low_stock_threshold"}
    if set(payload) - allowed:
        raise KhataError("Unsupported item fields")
    if not payload:
        raise KhataError("Item fields required")
    data = {}
    for field, limit in (("name", 200), ("description", 4000), ("category", 200)):
        if field in payload or creating:
            data[field] = _text(payload.get(field), field, limit)
            if field == "name" and not data[field]:
                raise KhataError("name is required")
    if "price" in payload or creating:
        data["price"] = _money_paise(payload.get("price")) / 100
    for field in ("stock_quantity", "low_stock_threshold"):
        if field in payload or (creating and field == "stock_quantity"):
            data[field] = _stock(payload.get(field, 0))
    if "is_available" in payload:
        if not isinstance(payload["is_available"], bool):
            raise KhataError("is_available must be boolean")
        data["is_available"] = payload["is_available"]
    elif "stock_quantity" in data:
        data["is_available"] = data["stock_quantity"] > 0
    if "image_urls" in payload or creating:
        urls = payload.get("image_urls", [])
        if not isinstance(urls, list) or len(urls) > 10 or any(not isinstance(url, str) or len(url) > 2048 or not url.startswith(("https://", "http://")) for url in urls):
            raise KhataError("image_urls must contain at most 10 HTTP image URLs")
        data["image_urls"] = urls
    return data


def _vendor_profile_fields():
    snap = doc(USERS, g.user_id).get()
    if not snap.exists:
        return {}
    data = snap.to_dict() or {}
    return {
        "vendor_id": g.user_id,
        "vendor_name": data.get("full_name") or data.get("shop_name"),
        "vendor_phone": data.get("phone"),
        "vendor_email": data.get("email"),
        "vendor_latitude": data.get("latitude"),
        "vendor_longitude": data.get("longitude"),
        "vendor_shop_description": data.get("shop_address"),
        "city_id": data.get("city_id"),
    }


@vendors_bp.get("/vendors/items")
@require_role("vendor")
def list_items():
    query = col(SHOP_ITEMS).where(
        filter=FieldFilter("vendor_id", "==", g.user_id)
    )
    return jsonify([to_dict(d) for d in query.stream()])


@vendors_bp.post("/vendors/items")
@require_role("vendor")
def add_item():
    data = _item_patch(_payload(), creating=True)
    if data.get("is_available") and data["stock_quantity"] == 0:
        raise KhataError("An item with no stock cannot be available")
    ref = col(SHOP_ITEMS).document()
    data = {**_vendor_profile_fields(), **data, "created_at": now_iso()}
    ref.set(data)
    return jsonify({**data, "uid": ref.id}), 201


@vendors_bp.put("/vendors/items/<item_id>")
@require_role("vendor")
def update_item(item_id):
    item_id = _identifier(item_id, "item_id")
    changes = _item_patch(_payload())
    ref = doc(SHOP_ITEMS, item_id)

    @firestore.transactional
    def update(tx):
        snap = ref.get(transaction=tx)
        if not snap.exists:
            raise KhataError("Item not found", 404)
        current = snap.to_dict() or {}
        if current.get("vendor_id") != g.user_id:
            raise KhataError("Not your item", 403)
        if current.get("disabled_by_admin") is True and changes.get("is_available") is True and "stock_quantity" not in changes:
            raise KhataError("Only an admin can enable this item", 403)
        stock = changes.get("stock_quantity", current.get("stock_quantity", 0))
        if changes.get("is_available") is True and _stock(stock) == 0:
            raise KhataError("An item with no stock cannot be available")
        data = {**changes, "updated_at": now_iso()}
        if current.get("disabled_by_admin") is True:
            # Stock edits remain available while administrative visibility stays off.
            data["is_available"] = False
        tx.update(ref, data)
        return {**current, **data, "uid": ref.id}
    return jsonify(update(db().transaction()))


@vendors_bp.delete("/vendors/items/<item_id>")
@require_role("vendor")
def delete_item(item_id):
    ref = doc(SHOP_ITEMS, _identifier(item_id, "item_id"))
    @firestore.transactional
    def remove(tx):
        snapshot = ref.get(transaction=tx)
        if not snapshot.exists:
            raise KhataError("Item not found", 404)
        if (snapshot.to_dict() or {}).get("vendor_id") != g.user_id:
            raise KhataError("Not your item", 403)
        orders = tx.get(col(CUSTOMER_ORDERS).where(filter=FieldFilter("item_id", "==", item_id)))
        if any((snap.to_dict() or {}).get("status") in {"pending", "confirmed", "accepted", "packed"} for snap in orders):
            raise KhataError("Fulfill or cancel active orders before deleting this item", 409)
        tx.delete(ref)
    remove(db().transaction())
    return jsonify({"ok": True})


@vendors_bp.get("/vendors/orders")
@require_role("vendor")
def list_orders():
    query = col(CUSTOMER_ORDERS).where(
        filter=FieldFilter("vendor_id", "==", g.user_id)
    )
    return jsonify([to_dict(d) for d in query.stream()])


@vendors_bp.put("/vendors/orders/<order_id>/status")
@require_role("vendor")
def update_order_status(order_id):
    payload = _payload()
    status = payload.get("status")
    if not isinstance(status, str):
        raise KhataError("status is required")
    aliases = {"accepted": "confirmed", "completed": "delivered"}
    status = aliases.get(status, status)
    if status not in {"confirmed", "packed", "delivered", "cancelled"}:
        raise KhataError("Unsupported order status")
    order_id = _identifier(order_id, "order_id")
    if status == "cancelled":
        from routes.shops import cancel_order_atomic
        try:
            cancel_order_atomic(order_id, g.user_id, vendor=True)
        except PermissionError as exc:
            raise KhataError(str(exc), 403) from None
        except ValueError as exc:
            raise KhataError(str(exc), 409) from None
        return jsonify({"ok": True})
    ref = doc(CUSTOMER_ORDERS, order_id)

    @firestore.transactional
    def update(tx):
        snap = ref.get(transaction=tx)
        if not snap.exists:
            raise KhataError("Order not found", 404)
        order = snap.to_dict() or {}
        if order.get("vendor_id") != g.user_id:
            raise KhataError("Not your order", 403)
        if order.get("refund_status") in {"processing", "retryable", "submitted", "requires_review", "completed"}:
            raise KhataError("Refund is in progress or already processed", 409)
        current = aliases.get(order.get("status"), order.get("status"))
        if current == status:
            return
        if {"pending": "confirmed", "confirmed": "packed", "packed": "delivered"}.get(current) != status:
            raise KhataError("Order status transition is not allowed", 409)
        if order.get("payment_method") in {"razorpay", "upi"} and order.get("payment_status") != "paid":
            raise KhataError("Online payment must be captured before fulfillment", 409)
        changes = {"status": status, "updated_at": now_iso()}
        if status == "delivered" and order.get("payment_method") == "cash":
            changes.update({"payment_status": "paid", "partial_amount_paid": order.get("total_price", 0), "due_amount": 0.0})
        tx.update(ref, changes)
    update(db().transaction())
    return jsonify({"ok": True})
