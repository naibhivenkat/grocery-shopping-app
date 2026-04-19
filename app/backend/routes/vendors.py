"""`/vendors/*` endpoints consumed by `VendorRemoteDataSource`."""

from flask import Blueprint, g, jsonify, request
from google.cloud.firestore_v1.base_query import FieldFilter

from auth_utils import require_role
from db import CUSTOMER_ORDERS, SHOP_ITEMS, USERS, col, doc, now_iso, to_dict


vendors_bp = Blueprint("vendors", __name__)


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
    payload = request.get_json(silent=True) or {}
    name = (payload.get("name") or "").strip()
    if not name:
        return jsonify({"detail": "name is required"}), 422

    stock_quantity = int(payload.get("stock_quantity") or 0)
    ref = col(SHOP_ITEMS).document()
    ref.set({
        **_vendor_profile_fields(),
        "name": name,
        "description": payload.get("description") or "",
        "price": float(payload.get("price") or 0),
        "category": payload.get("category") or "",
        "stock_quantity": stock_quantity,
        "image_urls": payload.get("image_urls") or [],
        "is_available": bool(payload.get("is_available", stock_quantity > 0)),
        "created_at": now_iso(),
    })
    return jsonify(to_dict(ref.get())), 201


def _assert_owner(item_id: str):
    ref = doc(SHOP_ITEMS, item_id)
    snap = ref.get()
    if not snap.exists:
        return None, (jsonify({"detail": "Item not found"}), 404)
    data = snap.to_dict() or {}
    if data.get("vendor_id") != g.user_id:
        return None, (jsonify({"detail": "Not your item"}), 403)
    return ref, None


@vendors_bp.put("/vendors/items/<item_id>")
@require_role("vendor")
def update_item(item_id):
    ref, err = _assert_owner(item_id)
    if err:
        return err
    payload = request.get_json(silent=True) or {}
    payload.pop("created_at", None)
    payload.pop("vendor_id", None)
    if "stock_quantity" in payload:
        try:
            stock = int(payload["stock_quantity"])
        except (TypeError, ValueError):
            stock = 0
        payload["stock_quantity"] = stock
        payload.setdefault("is_available", stock > 0)
    payload["updated_at"] = now_iso()
    ref.update(payload)
    return jsonify(to_dict(ref.get()))


@vendors_bp.delete("/vendors/items/<item_id>")
@require_role("vendor")
def delete_item(item_id):
    ref, err = _assert_owner(item_id)
    if err:
        return err
    ref.delete()
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
    payload = request.get_json(silent=True) or {}
    status = payload.get("status")
    if not status:
        return jsonify({"detail": "status is required"}), 422

    ref = doc(CUSTOMER_ORDERS, order_id)
    snap = ref.get()
    if not snap.exists:
        return jsonify({"detail": "Order not found"}), 404
    data = snap.to_dict() or {}
    if data.get("vendor_id") != g.user_id:
        return jsonify({"detail": "Not your order"}), 403
    ref.update({"status": status, "updated_at": now_iso()})
    return jsonify({"ok": True})
