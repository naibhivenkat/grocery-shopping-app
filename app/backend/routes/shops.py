"""`/shops/*` and `/orders/*` endpoints consumed by `ShopRemoteDataSource`."""

from flask import Blueprint, g, jsonify, request
from google.cloud.firestore_v1.base_query import FieldFilter

from auth_utils import require_auth, require_role
from db import (
    CATEGORIES,
    CUSTOMER_ORDERS,
    SHOP_ITEMS,
    USERS,
    USER_FAVORITES,
    col,
    doc,
    now_iso,
    to_dict,
)
from firebase_db import get_user_firestore_ref


shops_bp = Blueprint("shops", __name__)


# ── Shop item browsing ─────────────────────────────────────────────────────

def _fill_missing(item: dict, field: str, value):
    if item.get(field) in (None, "") and value not in (None, ""):
        item[field] = value


def _with_vendor_profile(item: dict) -> dict:
    vendor_id = item.get("vendor_id")
    if not vendor_id:
        return item

    needs_profile = any(
        item.get(field) in (None, "")
        for field in (
            "vendor_name",
            "vendor_phone",
            "vendor_email",
            "vendor_latitude",
            "vendor_longitude",
            "vendor_shop_description",
        )
    )
    if not needs_profile:
        return item

    vendor = doc(USERS, vendor_id).get()
    if not vendor.exists:
        return item

    data = vendor.to_dict() or {}
    enriched = dict(item)
    _fill_missing(
        enriched,
        "vendor_name",
        data.get("full_name") or data.get("shop_name"),
    )
    _fill_missing(enriched, "vendor_phone", data.get("phone"))
    _fill_missing(enriched, "vendor_email", data.get("email"))
    _fill_missing(enriched, "vendor_latitude", data.get("latitude"))
    _fill_missing(enriched, "vendor_longitude", data.get("longitude"))
    _fill_missing(enriched, "vendor_shop_description", data.get("shop_address"))
    return enriched

@shops_bp.get("/shops")
def list_shops():
    city_id = request.args.get("city_id")
    query = col(SHOP_ITEMS)
    if city_id:
        query = query.where(filter=FieldFilter("city_id", "==", city_id))
    items = []
    for d in query.stream():
        item = to_dict(d)
        if item.get("is_available") is False:
            continue
        stock = item.get("stock_quantity")
        if stock is not None:
            try:
                if int(stock) <= 0:
                    continue
            except (TypeError, ValueError):
                pass
        items.append(_with_vendor_profile(item))
    return jsonify(items)


# ── Categories (declared before `/shops/<id>` to win static match) ─────────

@shops_bp.get("/shops/categories")
def list_categories():
    return jsonify([to_dict(d) for d in col(CATEGORIES).stream()])


@shops_bp.post("/shops/categories")
@require_role("admin", "super_admin")
def add_category():
    payload = request.get_json(silent=True) or {}
    name = (payload.get("name") or "").strip()
    if not name:
        return jsonify({"detail": "name is required"}), 422
    ref = col(CATEGORIES).document()
    ref.set({
        "name": name,
        "icon_url": payload.get("icon_url"),
        "created_at": now_iso(),
    })
    return jsonify(to_dict(ref.get())), 201


@shops_bp.delete("/shops/categories/<category_id>")
@require_role("admin", "super_admin")
def delete_category(category_id):
    doc(CATEGORIES, category_id).delete()
    return jsonify({"ok": True})


# ── Favorites (declared before `/shops/<id>`) ──────────────────────────────

def _fav_id(user_id: str, item_id: str) -> str:
    return f"{user_id}__{item_id}"


@shops_bp.get("/shops/favorites")
@require_auth
def list_favorites():
    query = col(USER_FAVORITES).where(
        filter=FieldFilter("user_id", "==", g.user_id)
    )
    return jsonify([to_dict(d) for d in query.stream()])


@shops_bp.post("/shops/favorites")
@require_auth
def add_favorite():
    payload = request.get_json(silent=True) or {}
    item_id = payload.get("shop_item_id")
    if not item_id:
        return jsonify({"detail": "shop_item_id is required"}), 422

    item = (doc(SHOP_ITEMS, item_id).get().to_dict() or {})
    image_urls = item.get("image_urls") or (
        [item["image_url"]] if item.get("image_url") else []
    )
    doc(USER_FAVORITES, _fav_id(g.user_id, item_id)).set({
        "user_id": g.user_id,
        "shop_item_id": item_id,
        "item_name": item.get("name"),
        "price": item.get("price"),
        "image_urls": image_urls,
        "vendor_name": item.get("vendor_name"),
        "average_rating": item.get("average_rating"),
        "created_at": now_iso(),
    })
    return jsonify({"ok": True}), 201


@shops_bp.delete("/shops/favorites/<item_id>")
@require_auth
def remove_favorite(item_id):
    doc(USER_FAVORITES, _fav_id(g.user_id, item_id)).delete()
    return jsonify({"ok": True})


@shops_bp.get("/shops/favorites/<item_id>/check")
@require_auth
def check_favorite(item_id):
    snapshot = doc(USER_FAVORITES, _fav_id(g.user_id, item_id)).get()
    return jsonify({"is_favorite": snapshot.exists})


# ── Shop item detail ───────────────────────────────────────────────────────

@shops_bp.get("/shops/<shop_id>")
def get_shop(shop_id):
    snapshot = doc(SHOP_ITEMS, shop_id).get()
    if not snapshot.exists:
        return jsonify({"detail": "Shop item not found"}), 404
    return jsonify(_with_vendor_profile(to_dict(snapshot)))


# ── Customer orders ────────────────────────────────────────────────────────

def _create_single_order(payload: dict):
    """Create one customer order. Returns (response_dict, status) or (error_json, code)."""
    item_id = payload.get("item_id")
    try:
        quantity = int(payload.get("quantity") or 0)
        total_price = float(payload.get("total_price") or 0)
    except (TypeError, ValueError):
        return {"detail": "quantity and total_price must be numeric"}, 422

    if not item_id or quantity <= 0 or total_price <= 0:
        return {
            "detail": "item_id, positive quantity, positive total_price required"
        }, 422

    item_snap = doc(SHOP_ITEMS, item_id).get()
    if not item_snap.exists:
        return {"detail": "Item not found"}, 404

    item = item_snap.to_dict() or {}

    if item.get("is_available") is False:
        return {"detail": "Item is not available"}, 409

    stock = item.get("stock_quantity")
    stock_i = None

    if stock is not None:
        try:
            stock_i = int(stock)
        except (TypeError, ValueError):
            stock_i = None

        if stock_i is not None and stock_i < quantity:
            return {"detail": "Insufficient stock"}, 409

    partial = payload.get("partial_amount_paid")
    partial_f = float(partial) if partial is not None else None

    due_amount = None
    if partial_f is not None:
        due_amount = max(0.0, total_price - partial_f)

    # Keep BOTH values from the merged branches
    batch_id = payload.get("batch_id")
    customer_name = get_user_firestore_ref(g.user_id)

    order_ref = col(CUSTOMER_ORDERS).document()

    order_ref.set({
        "customer_id": g.user_id,
        "vendor_id": item.get("vendor_id"),
        "item_id": item_id,
        "quantity": quantity,
        "total_price": total_price,
        "status": "pending",
        "payment_method": payload.get("payment_method"),
        "partial_amount_paid": partial_f,
        "due_amount": due_amount,
        "item_name": item.get("name"),
        "item_description": item.get("description"),
        "item_image_urls": item.get("image_urls")
            or ([item["image_url"]] if item.get("image_url") else []),
        "item_unit_price": item.get("price"),
        "vendor_name": item.get("vendor_name"),
        "batch_id": batch_id,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "customer_name": customer_name,
    })

    if stock_i is not None:
        new_stock = max(0, stock_i - quantity)

        doc(SHOP_ITEMS, item_id).set({
            "stock_quantity": new_stock,
            "is_available": new_stock > 0,
            "updated_at": now_iso(),
        }, merge=True)

    return {
        "order_id": order_ref.id,
        "uid": order_ref.id,
        "vendor_id": item.get("vendor_id"),
        "item_id": item_id,
        "total_price": total_price,
    }, 201

@shops_bp.post("/orders")
@require_auth
def create_order():
    payload = request.get_json(silent=True) or {}
    body, code = _create_single_order(payload)
    return jsonify(body), code


@shops_bp.post("/orders/batch")
@require_auth
def create_orders_batch():
    """Place multiple cart lines as separate orders under one batch_id.

    Enforces single-vendor cart. On partial failure, cancels already-created
    orders in this batch (best-effort) so the client can retry cleanly.
    Wallet deduct/credit remains client-driven (see Flutter placeOrder).
    """
    payload = request.get_json(silent=True) or {}
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        return jsonify({"detail": "items array required"}), 422

    payment_method = payload.get("payment_method")
    batch_id = col(CUSTOMER_ORDERS).document().id
    created = []
    vendor_ids = set()

    for raw in items:
        if not isinstance(raw, dict):
            # rollback
            for oid in created:
                doc(CUSTOMER_ORDERS, oid).set(
                    {"status": "cancelled", "updated_at": now_iso()}, merge=True
                )
            return jsonify({"detail": "each item must be an object"}), 422
        line = dict(raw)
        line["payment_method"] = payment_method or line.get("payment_method")
        line["batch_id"] = batch_id
        body, code = _create_single_order(line)
        if code != 201:
            for oid in created:
                doc(CUSTOMER_ORDERS, oid).set(
                    {"status": "cancelled", "updated_at": now_iso()}, merge=True
                )
            return jsonify({
                "detail": body.get("detail") if isinstance(body, dict) else "Order failed",
                "batch_id": batch_id,
                "cancelled_order_ids": created,
            }), code
        created.append(body["order_id"])
        if body.get("vendor_id"):
            vendor_ids.add(body["vendor_id"])
        if len(vendor_ids) > 1:
            for oid in created:
                doc(CUSTOMER_ORDERS, oid).set(
                    {"status": "cancelled", "updated_at": now_iso()}, merge=True
                )
            return jsonify({
                "detail": "All cart items must be from the same shop",
                "batch_id": batch_id,
                "cancelled_order_ids": created,
            }), 422

    return jsonify({
        "batch_id": batch_id,
        "order_ids": created,
        "order_id": created[-1] if created else None,
        "count": len(created),
    }), 201


@shops_bp.get("/orders")
@require_auth
def list_customer_orders():
    query = col(CUSTOMER_ORDERS).where(
        filter=FieldFilter("customer_id", "==", g.user_id)
    )
    return jsonify([to_dict(d) for d in query.stream()])


@shops_bp.post("/orders/<order_id>/cancel")
@require_auth
def cancel_order(order_id):
    ref = doc(CUSTOMER_ORDERS, order_id)
    snapshot = ref.get()
    if not snapshot.exists:
        return jsonify({"detail": "Order not found"}), 404
    data = snapshot.to_dict() or {}
    if data.get("customer_id") != g.user_id and g.user_role not in {"admin", "super_admin"}:
        return jsonify({"detail": "Not your order"}), 403
    ref.update({"status": "cancelled", "updated_at": now_iso()})
    return jsonify({"ok": True})
