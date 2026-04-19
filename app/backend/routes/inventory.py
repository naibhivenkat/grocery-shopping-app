"""`/inventory/*` endpoints consumed by `InventoryRemoteDataSource`.

Inventory shares the `shop_items` collection; these endpoints project the
vendor-scoped subset in the shape expected by `InventoryItemModel`.
"""

from flask import Blueprint, g, jsonify, request
from google.cloud.firestore_v1.base_query import FieldFilter

from auth_utils import require_role
from db import SHOP_ITEMS, col, doc, now_iso, to_dict


inventory_bp = Blueprint("inventory", __name__)


def _inventory_shape(d) -> dict:
    base = to_dict(d)
    base.setdefault("low_stock_threshold", 5)
    base.setdefault("stock_quantity", 0)
    base.setdefault("is_available", True)
    return base


@inventory_bp.get("/inventory")
@require_role("vendor")
def list_inventory():
    query = col(SHOP_ITEMS).where(
        filter=FieldFilter("vendor_id", "==", g.user_id)
    )
    return jsonify([_inventory_shape(d) for d in query.stream()])


@inventory_bp.put("/inventory/<item_id>/stock")
@require_role("vendor")
def update_stock(item_id):
    payload = request.get_json(silent=True) or {}
    try:
        quantity = int(payload.get("quantity"))
    except (TypeError, ValueError):
        return jsonify({"detail": "quantity (int) is required"}), 422

    ref = doc(SHOP_ITEMS, item_id)
    snap = ref.get()
    if not snap.exists:
        return jsonify({"detail": "Item not found"}), 404
    if (snap.to_dict() or {}).get("vendor_id") != g.user_id:
        return jsonify({"detail": "Not your item"}), 403

    ref.update({
        "stock_quantity": quantity,
        "is_available": quantity > 0,
        "last_restocked": now_iso(),
        "updated_at": now_iso(),
    })
    return jsonify({"ok": True})


@inventory_bp.post("/inventory/bulk-update")
@require_role("vendor")
def bulk_update():
    payload = request.get_json(silent=True) or {}
    items = payload.get("items") or []
    if not isinstance(items, list):
        return jsonify({"detail": "items must be a list"}), 422

    batch = col(SHOP_ITEMS)._client.batch()
    updated = 0
    for entry in items:
        item_id = entry.get("item_id")
        try:
            quantity = int(entry.get("quantity"))
        except (TypeError, ValueError):
            continue
        if not item_id:
            continue
        ref = doc(SHOP_ITEMS, item_id)
        snap = ref.get()
        if not snap.exists:
            continue
        if (snap.to_dict() or {}).get("vendor_id") != g.user_id:
            continue
        batch.update(ref, {
            "stock_quantity": quantity,
            "is_available": quantity > 0,
            "last_restocked": now_iso(),
            "updated_at": now_iso(),
        })
        updated += 1
    if updated:
        batch.commit()
    return jsonify({"ok": True, "updated": updated})


@inventory_bp.get("/inventory/low-stock")
@require_role("vendor")
def low_stock():
    query = col(SHOP_ITEMS).where(
        filter=FieldFilter("vendor_id", "==", g.user_id)
    )
    low = []
    for d in query.stream():
        data = d.to_dict() or {}
        threshold = int(data.get("low_stock_threshold") or 5)
        stock = int(data.get("stock_quantity") or 0)
        if stock <= threshold:
            low.append(_inventory_shape(d))
    return jsonify(low)
