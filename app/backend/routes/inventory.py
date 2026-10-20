"""`/inventory/*` endpoints consumed by `InventoryRemoteDataSource`.

Inventory shares the `shop_items` collection; these endpoints project the
vendor-scoped subset in the shape expected by `InventoryItemModel`.
"""

from firebase_admin import firestore
from flask import Blueprint, g, jsonify, request
from google.cloud.firestore_v1.base_query import FieldFilter

from auth_utils import require_role
from db import SHOP_ITEMS, col, db, doc, now_iso, to_dict
from routes.khata import KhataError, _khata_error, _payload, _identifier
from routes.vendors import _stock
from routes.measurement import acknowledge


inventory_bp = Blueprint("inventory", __name__)
inventory_bp.register_error_handler(KhataError, _khata_error)


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
    payload = _payload()
    quantity = _stock(payload.get("quantity"))
    _update_atomic([(_identifier(item_id, "item_id"), quantity, payload.get("stock_unit"))])
    return jsonify({"ok": True})


def _update_atomic(items):
    @firestore.transactional
    def update(tx):
        refs = [doc(SHOP_ITEMS, identifier) for identifier, _, _ in items]
        snapshots = [ref.get(transaction=tx) for ref in refs]
        for snap, (_, _, unit) in zip(snapshots, items):
            if not snap.exists:
                raise KhataError("Item not found", 404)
            if (snap.to_dict() or {}).get("vendor_id") != g.user_id:
                raise KhataError("Not your item", 403)
            acknowledge(snap.to_dict() or {}, unit)
        timestamp = now_iso()
        for ref, snap, (_, quantity, _) in zip(refs, snapshots, items):
            available = quantity > 0 and (snap.to_dict() or {}).get("disabled_by_admin") is not True
            tx.update(ref, {"stock_quantity": quantity, "is_available": available,
                "last_restocked": timestamp, "updated_at": timestamp})
    update(db().transaction())


@inventory_bp.post("/inventory/bulk-update")
@require_role("vendor")
def bulk_update():
    items = _payload().get("items")
    if not isinstance(items, list) or not 1 <= len(items) <= 100:
        raise KhataError("items must contain 1 to 100 entries")
    prepared, seen = [], set()
    for entry in items:
        if not isinstance(entry, dict):
            raise KhataError("Each item must be an object")
        identifier = _identifier(entry.get("item_id"), "item_id")
        if identifier in seen:
            raise KhataError("Duplicate item_id in stock update")
        seen.add(identifier)
        prepared.append((identifier, _stock(entry.get("quantity")), entry.get("stock_unit")))
    _update_atomic(prepared)
    return jsonify({"ok": True, "updated": len(prepared)})


@inventory_bp.get("/inventory/low-stock")
@require_role("vendor")
def low_stock():
    query = col(SHOP_ITEMS).where(
        filter=FieldFilter("vendor_id", "==", g.user_id)
    )
    low = []
    for d in query.stream():
        data = d.to_dict() or {}
        try:
            threshold = _stock(data.get("low_stock_threshold", 5))
            stock = _stock(data.get("stock_quantity", 0))
        except KhataError:
            # Legacy corrupt stock is conservatively shown as needing attention.
            low.append(_inventory_shape(d))
            continue
        if stock <= threshold:
            low.append(_inventory_shape(d))
    return jsonify(low)
