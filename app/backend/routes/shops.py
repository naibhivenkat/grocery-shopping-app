"""`/shops/*` and `/orders/*` endpoints consumed by `ShopRemoteDataSource`."""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
from google.cloud import firestore
from flask import Blueprint, g, jsonify, request
from google.cloud.firestore_v1.base_query import FieldFilter

from auth_utils import require_auth, require_role
from db import (
    CATEGORIES,
    KHATA_TRANSACTIONS,
    NOTIFICATIONS,
    db,
    CUSTOMER_ORDERS,
    SHOP_ITEMS,
    USERS,
    USER_FAVORITES,
    col,
    doc,
    now_iso,
    to_dict,
)
from notification_delivery import notification_data, deliver_push


shops_bp = Blueprint("shops", __name__)


def _customer_name(user_id: str) -> str:
    """Resolve the display name without importing the legacy Firebase loader."""
    snapshot = doc(USERS, user_id).get()
    if not snapshot.exists:
        fallback = (
            col(USERS)
            .where(filter=FieldFilter("customerId", "==", user_id))
            .limit(1)
            .stream()
        )
        snapshot = next(iter(fallback), None)

    if snapshot is None or not snapshot.exists:
        return ""

    data = snapshot.to_dict() or {}
    return data.get("full_name") or data.get("name") or data.get("username") or ""


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
        if item.get("is_available") is False or item.get("disabled_by_admin") is True:
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
    item = to_dict(snapshot)
    if item.get("disabled_by_admin") is True:
        return jsonify({"detail": "Shop item not found"}), 404
    return jsonify(_with_vendor_profile(item))


# ── Customer orders ────────────────────────────────────────────────────────

def _paise(value):
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number < 0:
            raise ValueError("Invalid amount")
        return int((number * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except (InvalidOperation, TypeError, ValueError, OverflowError):
        raise ValueError("Amounts must be finite positive numbers")


def _whole_quantity(value, *, allow_zero=False):
    if isinstance(value, bool) or not isinstance(value, (int, str)) or not str(value).isdigit():
        raise ValueError("Stock and quantity must be whole numbers")
    quantity = int(value)
    if quantity < (0 if allow_zero else 1):
        raise ValueError("Stock and quantity cannot be negative or empty")
    return quantity


def _create_orders(payload, lines):
    from routes.khata import lookup_ledger_txn, _money_paise, KhataError
    if not isinstance(payload, dict) or not isinstance(lines, list) or not 1 <= len(lines) <= 50:
        return {"detail": "Between 1 and 50 cart lines are required"}, 422
    method = payload.get("payment_method", "cash")
    if method is None or method == "":
        method = "cash"
    if method == "wallet":
        return {"detail": "Wallet is temporarily disabled", "code": "WALLET_DISABLED"}, 410
    if not isinstance(method, str) or method not in {"cash", "khata", "razorpay", "upi"}:
        return {"detail": "Unsupported payment method"}, 422
    if method == "upi":
        method = "razorpay"
    key = request.headers.get("Idempotency-Key") or payload.get("idempotency_key")
    if key is not None and (not isinstance(key, str) or not 8 <= len(key) <= 128):
        return {"detail": "idempotency_key must contain 8 to 128 characters"}, 422
    prepared = []
    seen = set()
    try:
        for line in lines:
            if not isinstance(line, dict):
                raise ValueError("Each cart line must be an object")
            item_id = line.get("item_id")
            qty = line.get("quantity")
            if not isinstance(item_id, str) or not item_id or "/" in item_id or item_id in seen:
                raise ValueError("Each item must have a unique valid item_id")
            if isinstance(qty, bool) or not str(qty).isdigit() or not 1 <= int(qty) <= 10000:
                raise ValueError("quantity must be a positive integer up to 10000")
            seen.add(item_id)
            if method == "khata" and _paise(line.get("partial_amount_paid", 0)) != 0:
                raise ValueError("Khata payments must be confirmed by the shop owner")
            prepared.append((item_id, int(qty), line))
    except ValueError as exc:
        return {"detail": str(exc)}, 422
    batch_ref = col("order_batches").document(
        hashlib.sha256(f"{g.user_id}:{key}".encode()).hexdigest() if key else None)
    order_refs = [col(CUSTOMER_ORDERS).document() for _ in prepared]
    fingerprint = hashlib.sha256(repr((method, [(i, q) for i, q, _ in prepared])).encode()).hexdigest()
    customer_name = _customer_name(g.user_id)

    @firestore.transactional
    def commit(tx):
        existing = batch_ref.get(transaction=tx)
        if existing.exists:
            saved = existing.to_dict() or {}
            if saved.get("fingerprint") != fingerprint:
                raise ValueError("idempotency_key already belongs to a different order")
            return saved["response"], None
        snapshots = [doc(SHOP_ITEMS, i).get(transaction=tx) for i, _, _ in prepared]
        vendor_ids = {(d.to_dict() or {}).get("vendor_id") for d in snapshots if d.exists}
        if len(vendor_ids) != 1 or None in vendor_ids:
            raise ValueError("All items must belong to the same valid shop")
        vendor_id = next(iter(vendor_ids))
        vendor = doc(USERS, vendor_id).get(transaction=tx)
        if not vendor.exists or (vendor.to_dict() or {}).get("role") != "vendor" or (vendor.to_dict() or {}).get("is_suspended"):
            raise ValueError("Shop is unavailable")
        ledger_ref = ledger = None
        if method == "khata":
            ledger_ref, ledger, exists = lookup_ledger_txn(tx, vendor_id, g.user_id)
            if not exists or ledger.get("status") != "active":
                raise ValueError("Ask the shop owner to open an active Khata ledger first")
        documents = []
        debt = 0
        for (item_id, quantity, line), snap, ref in zip(prepared, snapshots, order_refs):
            if not snap.exists:
                raise ValueError("Item not found")
            item = snap.to_dict() or {}
            if item.get("is_available") is False or item.get("disabled_by_admin") is True:
                raise ValueError("Item is unavailable")
            price = _paise(item.get("price"))
            if price <= 0:
                raise ValueError("Item price is invalid")
            total = price * quantity
            if "total_price" in line and _paise(line["total_price"]) != total:
                raise ValueError("Item price changed; refresh your cart")
            stock = item.get("stock_quantity")
            if stock is not None:
                stock = _whole_quantity(stock, allow_zero=True)
                if stock < quantity:
                    raise ValueError("Insufficient stock")
            debt += total
            documents.append((ref, snap.reference, stock, quantity, {
                "customer_id": g.user_id, "vendor_id": vendor_id, "item_id": item_id,
                "quantity": quantity, "total_price": total / 100, "total_paise": total,
                "status": "pending", "payment_status": "pending", "payment_method": method,
                "partial_amount_paid": 0.0, "due_amount": total / 100,
                "item_name": item.get("name"), "item_description": item.get("description"),
                "item_image_urls": item.get("image_urls") or ([item["image_url"]] if item.get("image_url") else []),
                "item_unit_price": price / 100, "vendor_name": item.get("vendor_name"),
                "batch_id": batch_ref.id, "customer_name": customer_name,
                "khata_ledger_id": ledger_ref.id if ledger_ref else None,
                "created_at": now_iso(), "updated_at": now_iso(),
            }))
        if debt > 1_000_000_000:
            raise ValueError("Order total exceeds the supported limit")
        new_balance = None
        if ledger_ref:
            new_balance = _money_paise(ledger.get("balance", 0), allow_zero=True) + debt
            if new_balance > 1_000_000_000:
                raise ValueError("Khata balance exceeds the supported limit")
        # All related documents were read before the first transaction write.
        for ref, item_ref, stock, quantity, data in documents:
            tx.create(ref, data)
            if stock is not None:
                remaining = int(stock) - quantity
                tx.update(item_ref, {"stock_quantity": remaining, "is_available": remaining > 0, "updated_at": now_iso()})
            if ledger_ref:
                tx.create(doc(KHATA_TRANSACTIONS, f"order_{ref.id}"), {
                    "ledger_id": ledger_ref.id, "vendor_id": vendor_id,
                    "customer_id": g.user_id, "type": "credit", "amount": data["total_price"],
                    "order_id": ref.id, "description": "Khata order", "created_at": now_iso(),
                })
        if ledger_ref:
            tx.update(ledger_ref, {"balance": new_balance / 100, "updated_at": now_iso()})
        response = {"batch_id": batch_ref.id, "order_ids": [r.id for r in order_refs],
                    "order_id": order_refs[-1].id, "uid": order_refs[-1].id,
                    "vendor_id": vendor_id, "count": len(order_refs), "total_price": debt / 100}
        tx.create(batch_ref, {"customer_id": g.user_id, "fingerprint": fingerprint,
                              "response": response, "created_at": now_iso()})
        event = notification_data(vendor_id, "new_order", "New order",
            f"{customer_name or 'A customer'} placed an order for INR {debt / 100:.2f}.", response["order_id"])
        tx.set(col(NOTIFICATIONS).document(), event)
        return response, event
    try:
        response, event = commit(db().transaction())
        deliver_push(event, lookup=doc)
        return response, 201
    except KhataError as exc:
        return {"detail": exc.detail}, exc.status
    except (ValueError, TypeError, OverflowError) as exc:
        return {"detail": str(exc)}, 422


@shops_bp.post("/orders")
@require_role("customer", "vendor", "service")
def create_order():
    payload = request.get_json(silent=True) or {}
    body, code = _create_orders(payload, [payload])
    return jsonify(body), code


@shops_bp.post("/orders/batch")
@require_role("customer", "vendor", "service")
def create_orders_batch():
    payload = request.get_json(silent=True) or {}
    body, code = _create_orders(payload, payload.get("items") if isinstance(payload, dict) else None)
    return jsonify(body), code


@shops_bp.get("/orders")
@require_auth
def list_customer_orders():
    query = col(CUSTOMER_ORDERS).where(filter=FieldFilter("customer_id", "==", g.user_id))
    return jsonify([to_dict(d) for d in query.stream()])


def cancel_order_atomic(order_id, actor_id, vendor=False):
    @firestore.transactional
    def commit(tx):
        ref = doc(CUSTOMER_ORDERS, order_id)
        snap = ref.get(transaction=tx)
        if not snap.exists:
            raise ValueError("Order not found")
        order = snap.to_dict() or {}
        if order.get("vendor_id" if vendor else "customer_id") != actor_id:
            raise PermissionError("Not your order")
        if order.get("status") == "cancelled":
            return None
        if order.get("status") not in {"pending", "confirmed"}:
            raise ValueError("Order cannot be cancelled at this stage")
        if order.get("payment_status") == "paid" and order.get("payment_method") in {"razorpay", "upi", "cash"}:
            raise ValueError("Paid orders require an original-method refund before cancellation")
        item_ref = doc(SHOP_ITEMS, order["item_id"])
        item = item_ref.get(transaction=tx)
        ledger_ref = ledger = None
        if order.get("khata_ledger_id"):
            from db import KHATA_LEDGERS
            ledger_ref = doc(KHATA_LEDGERS, order["khata_ledger_id"])
            ledger = ledger_ref.get(transaction=tx)
        item_data = item.to_dict() or {}
        restored_stock = None
        if item.exists and item_data.get("stock_quantity") is not None:
            restored_stock = _whole_quantity(item_data["stock_quantity"], allow_zero=True) + _whole_quantity(order["quantity"])
        balance = amount = None
        if ledger_ref:
            if not ledger.exists:
                raise ValueError("Khata ledger is missing; shop owner reconciliation required")
            ledger_data = ledger.to_dict() or {}
            if ledger_data.get("vendor_id") != order.get("vendor_id") or ledger_data.get("customer_id") != order.get("customer_id"):
                raise ValueError("Khata ledger parties do not match the order")
            balance = _paise(ledger_data.get("balance", 0))
            amount = _paise(order["total_price"])
            if balance < amount:
                raise ValueError("Khata payments require shop owner reconciliation before cancellation")
        tx.update(ref, {"status": "cancelled", "due_amount": 0.0, "updated_at": now_iso()})
        if restored_stock is not None:
            tx.update(item_ref, {"stock_quantity": restored_stock, "is_available": item_data.get("disabled_by_admin") is not True, "updated_at": now_iso()})
        if ledger_ref:
            tx.update(ledger_ref, {"balance": (balance - amount) / 100, "updated_at": now_iso()})
            tx.create(doc(KHATA_TRANSACTIONS, f"cancel_{order_id}"), {
                "ledger_id": ledger_ref.id, "vendor_id": order["vendor_id"],
                "customer_id": order["customer_id"], "type": "debit", "amount": amount / 100,
                "order_id": order_id, "description": "Cancelled Khata order", "created_at": now_iso()})
        event = notification_data(order["customer_id"] if vendor else order["vendor_id"], "order_status",
            "Order cancelled", "The order was cancelled.", order_id)
        tx.set(col(NOTIFICATIONS).document(), event)
        return event
    deliver_push(commit(db().transaction()), lookup=doc)


@shops_bp.post("/orders/<order_id>/cancel")
@require_auth
def cancel_order(order_id):
    try:
        cancel_order_atomic(order_id, g.user_id)
        return jsonify({"ok": True})
    except PermissionError as exc:
        return jsonify({"detail": str(exc)}), 403
    except ValueError as exc:
        return jsonify({"detail": str(exc)}), 409
