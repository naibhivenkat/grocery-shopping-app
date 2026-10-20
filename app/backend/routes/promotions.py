"""Free, moderated shop/product promotions; no advertising payment is collected.

Shops are vendor profiles in USERS; products are documents in SHOP_ITEMS.
Dates are timezone-aware ISO-8601 strings, normalized to UTC. All content edits
require moderation again. A revision is required when moderating so approval
cannot accidentally apply to content edited since an administrator reviewed it.
"""

import math
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit

from firebase_admin import firestore
from flask import Blueprint, g, jsonify, request
from google.cloud.firestore_v1.base_query import FieldFilter

from auth_utils import require_role
from db import SHOP_ITEMS, USERS, NOTIFICATIONS, col, db, doc, now_iso, to_dict
from notification_delivery import notification_data, deliver_push
from routes.discounts import RULE_FIELDS, rules
from routes.khata import KhataError
import subscription_service as subscriptions
from routes.subscriptions import subscription_error


promotions_bp = Blueprint("promotions", __name__)
promotions_bp.register_error_handler(subscriptions.SubscriptionError, subscription_error)
PROMOTIONS = "promotions"
CONTENT_FIELDS = {
    "target_type", "shop_id", "product_id", "title", "body", "image_url",
    "starts_at", "ends_at",
} | RULE_FIELDS
PUBLIC_FIELDS = {
    "uid", "target_type", "shop_id", "product_id", "city_id", "title", "body",
    "image_url", "starts_at", "ends_at", "target_name",
} | RULE_FIELDS


class PromotionError(Exception):
    def __init__(self, detail, status=422):
        self.detail = detail
        self.status = status


@promotions_bp.errorhandler(PromotionError)
def _error(error):
    return jsonify({"detail": error.detail}), error.status


def _id(value, field):
    if (
        not isinstance(value, str)
        or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", value)
        or value in {".", ".."}
    ):
        raise PromotionError(f"{field} must be a valid document ID")
    return value


def _payload(allowed):
    value = request.get_json(silent=True)
    if not isinstance(value, dict):
        raise PromotionError("Request body must be a JSON object")
    unknown = set(value) - allowed
    if unknown:
        raise PromotionError("Unknown or read-only fields: " + ", ".join(sorted(unknown)))
    return value


def _text(value, field, maximum, required=False):
    if value is None and not required:
        return ""
    if not isinstance(value, str):
        raise PromotionError(f"{field} must be text")
    value = value.strip()
    if (required and not value) or len(value) > maximum:
        raise PromotionError(f"{field} must contain {'1' if required else '0'} to {maximum} characters")
    if any(ord(c) < 32 and c not in "\n\t" for c in value):
        raise PromotionError(f"{field} contains invalid control characters")
    return value


def _date(value, field):
    if not isinstance(value, str) or len(value) > 64:
        raise PromotionError(f"{field} must be an ISO-8601 date with a timezone")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None or result.utcoffset() is None:
            raise ValueError("missing timezone")
        return result.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        raise PromotionError(f"{field} must be an ISO-8601 date with a timezone")


def _image(value):
    if value in (None, ""):
        return None
    if not isinstance(value, str) or len(value) > 2048 or any(c.isspace() for c in value):
        raise PromotionError("image_url must be an HTTPS URL")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise PromotionError("image_url must be an HTTPS URL")
    if (
        parsed.scheme != "https" or not parsed.hostname or parsed.username
        or parsed.password or port not in (None, 443) or parsed.fragment
    ):
        raise PromotionError("image_url must be an HTTPS URL without credentials or fragment")
    return value


def _account(*roles):
    """Recheck current database role and suspension, including deleted accounts."""
    _id(g.user_id, "user_id")
    snapshot = doc(USERS, g.user_id).get()
    if not snapshot.exists:
        raise PromotionError("Account not found", 401)
    account = snapshot.to_dict() or {}
    if account.get("is_suspended") or account.get("role") not in roles:
        raise PromotionError("Insufficient permissions", 403)
    return account


def _target(content, vendor_id, vendor):
    target_type = content.get("target_type")
    if not isinstance(target_type, str) or target_type not in {"shop", "product"}:
        raise PromotionError("target_type must be shop or product")
    shop_id = content.get("shop_id")
    if shop_id in (None, ""):
        shop_id = vendor_id
    _id(shop_id, "shop_id")
    if shop_id != vendor_id:
        raise PromotionError("Only your own shop can be promoted", 403)
    city_id = vendor.get("city_id")
    target_name = vendor.get("shop_name") or vendor.get("full_name") or "Shop"
    product_id = content.get("product_id")
    if target_type == "product":
        _id(product_id, "product_id")
        snapshot = doc(SHOP_ITEMS, product_id).get()
        if not snapshot.exists:
            raise PromotionError("Product not found", 404)
        product = snapshot.to_dict() or {}
        if product.get("vendor_id") != vendor_id:
            raise PromotionError("Only your own product can be promoted", 403)
        if product.get("is_available") is False or product.get("disabled_by_admin"):
            raise PromotionError("Product is unavailable", 409)
        city_id = product.get("city_id") or city_id
        target_name = product.get("name") or "Product"
    elif product_id not in (None, ""):
        raise PromotionError("product_id is only valid for product promotions")
    else:
        product_id = None
    _id(city_id, "Shop or product city_id")
    return {
        "target_type": target_type, "shop_id": shop_id, "product_id": product_id,
        "city_id": city_id, "target_name": str(target_name)[:200],
    }


def _content(content, vendor_id, vendor):
    starts = _date(content.get("starts_at"), "starts_at")
    ends = _date(content.get("ends_at"), "ends_at")
    if ends <= starts:
        raise PromotionError("ends_at must be after starts_at")
    if ends <= datetime.now(timezone.utc):
        raise PromotionError("ends_at must be in the future")
    if (ends - starts).days > 90 or (ends - starts).total_seconds() > 90 * 86400:
        raise PromotionError("A promotion can run for at most 90 days")
    try:
        discount_rules = rules(content)
    except KhataError as error:
        raise PromotionError(error.detail) from None
    return {
        **discount_rules, **_target(content, vendor_id, vendor),
        "title": _text(content.get("title"), "title", 100, required=True),
        "body": _text(content.get("body"), "body", 1000),
        "image_url": _image(content.get("image_url")),
        "starts_at": starts.isoformat(), "ends_at": ends.isoformat(),
    }


def _reference(promotion_id):
    return doc(PROMOTIONS, _id(promotion_id, "promotion_id"))


def _owner(snapshot):
    if not snapshot.exists:
        raise PromotionError("Promotion not found", 404)
    data = snapshot.to_dict() or {}
    if data.get("vendor_id") != g.user_id:
        raise PromotionError("Not your promotion", 403)
    return data


def _currently_valid(data, now):
    try:
        return (
            not data.get("is_paused")
            and _date(data.get("starts_at"), "starts_at") <= now
            < _date(data.get("ends_at"), "ends_at")
        )
    except PromotionError:
        return False


def _visible_target(data):
    vendor_id = data.get("vendor_id")
    try:
        _id(vendor_id, "vendor_id")
        vendor = doc(USERS, vendor_id).get()
        account = vendor.to_dict() or {}
        if not vendor.exists or account.get("is_suspended") or account.get("role") != "vendor":
            return False
        if data.get("target_type") == "product":
            _id(data.get("product_id"), "product_id")
            snapshot = doc(SHOP_ITEMS, data["product_id"]).get()
            product = snapshot.to_dict() or {}
            if (not snapshot.exists or product.get("vendor_id") != vendor_id
                or product.get("is_available") is False or product.get("disabled_by_admin")):
                return False
            stock = product.get("stock_quantity")
            if stock is not None:
                stock = float(stock)
                if not math.isfinite(stock) or stock <= 0:
                    return False
        return True
    except (PromotionError, TypeError, ValueError):
        return False


@promotions_bp.get("/promotions")
def list_promotions():
    # Shop campaigns belong only on that shop's page. Legacy global-feed
    # callers receive an empty list; admin advertisements have a separate feed.
    shop_id = request.args.get("shop_id")
    if shop_id is not None:
        _id(shop_id, "shop_id")
    city_id = request.args.get("city_id")
    if city_id is not None:
        _id(city_id, "city_id")
    try:
        limit = int(request.args.get("limit", "20"))
    except ValueError:
        raise PromotionError("limit must be an integer from 1 to 100")
    if not 1 <= limit <= 100:
        raise PromotionError("limit must be an integer from 1 to 100")
    if not shop_id:
        return jsonify([])
    query = col(PROMOTIONS).where(filter=FieldFilter("status", "==", "approved"))
    query = query.where(filter=FieldFilter("shop_id", "==", shop_id))
    if city_id:
        query = query.where(filter=FieldFilter("city_id", "==", city_id))
    now = datetime.now(timezone.utc)
    items = []
    for snapshot in query.stream():
        data = to_dict(snapshot)
        if _currently_valid(data, now) and _visible_target(data):
            items.append({key: data.get(key) for key in PUBLIC_FIELDS})
            if len(items) >= limit:
                break
    return jsonify(items)


@promotions_bp.get("/promotions/mine")
@require_role("vendor")
def my_promotions():
    _account("vendor")
    query = col(PROMOTIONS).where(filter=FieldFilter("vendor_id", "==", g.user_id))
    items = [to_dict(snapshot) for snapshot in query.stream()]
    items.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    return jsonify(items)


@promotions_bp.post("/promotions")
@require_role("vendor")
def create_promotion():
    account = _account("vendor")
    content = _content(_payload(CONTENT_FIELDS), g.user_id, account)
    ref = col(PROMOTIONS).document()
    timestamp = now_iso()
    @firestore.transactional
    def create(transaction):
        apply_capability = subscriptions.catalog_change_plan(transaction, g.user_id, capability="promotions", lookup=doc)
        transaction.set(ref, {
        **content, "vendor_id": g.user_id, "status": "pending", "is_paused": False,
        "revision": 1, "price_paise": 0, "moderation_reason": None,
        "moderated_at": None, "moderated_by": None, "approved_revision": None,
        "created_at": timestamp, "updated_at": timestamp,
        })
        apply_capability()
    create(db().transaction())
    return jsonify(to_dict(ref.get())), 201


@promotions_bp.put("/promotions/<promotion_id>")
@require_role("vendor")
def update_promotion(promotion_id):
    account = _account("vendor")
    payload = _payload(CONTENT_FIELDS)
    if not payload:
        raise PromotionError("At least one content field is required")
    ref = _reference(promotion_id)

    @firestore.transactional
    def update(transaction):
        data = _owner(ref.get(transaction=transaction))
        merged = {key: data.get(key) for key in CONTENT_FIELDS}
        merged.update(payload)
        if payload.get("target_type") == "shop":
            merged["product_id"] = payload.get("product_id")
        content = _content(merged, g.user_id, account)
        apply_capability = subscriptions.catalog_change_plan(transaction, g.user_id, capability="promotions", lookup=doc)
        transaction.update(ref, {
            **content, "status": "pending", "revision": data.get("revision", 0) + 1,
            "moderation_reason": None, "moderated_at": None, "moderated_by": None, "approved_revision": None,
            "updated_at": now_iso(),
        })
        apply_capability()

    update(db().transaction())
    return jsonify(to_dict(ref.get()))


@promotions_bp.patch("/promotions/<promotion_id>/pause")
@require_role("vendor")
def pause_promotion(promotion_id):
    _account("vendor")
    payload = _payload({"is_paused"})
    if not isinstance(payload.get("is_paused"), bool):
        raise PromotionError("is_paused must be true or false")
    ref = _reference(promotion_id)

    @firestore.transactional
    def pause(transaction):
        _owner(ref.get(transaction=transaction))
        apply_capability = subscriptions.catalog_change_plan(transaction, g.user_id, capability="promotions", lookup=doc) if not payload["is_paused"] else (lambda: None)
        transaction.update(ref, {"is_paused": payload["is_paused"], "updated_at": now_iso()})
        apply_capability()

    pause(db().transaction())
    return jsonify(to_dict(ref.get()))


@promotions_bp.get("/promotions/admin")
@require_role("admin", "super_admin")
def moderation_queue():
    _account("admin", "super_admin")
    status = request.args.get("status", "pending")
    if status not in {"pending", "approved", "rejected"}:
        raise PromotionError("status must be pending, approved, or rejected")
    query = col(PROMOTIONS).where(filter=FieldFilter("status", "==", status))
    items = [to_dict(snapshot) for snapshot in query.stream()]
    items.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
    return jsonify(items)


@promotions_bp.post("/promotions/<promotion_id>/moderation")
@require_role("admin", "super_admin")
def moderate_promotion(promotion_id):
    _account("admin", "super_admin")
    payload = _payload({"decision", "revision", "reason"})
    decision = payload.get("decision")
    if not isinstance(decision, str) or decision not in {"approved", "rejected"}:
        raise PromotionError("decision must be approved or rejected")
    revision = payload.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise PromotionError("revision must be the positive integer reviewed by the administrator")
    reason = _text(payload.get("reason"), "reason", 500, required=decision == "rejected")
    ref = _reference(promotion_id)

    @firestore.transactional
    def moderate(transaction):
        snapshot = ref.get(transaction=transaction)
        if not snapshot.exists:
            raise PromotionError("Promotion not found", 404)
        data = snapshot.to_dict() or {}
        if data.get("revision") != revision:
            raise PromotionError("Promotion changed; review the current revision", 409)
        if data.get("status") != "pending":
            raise PromotionError("Only pending promotions can be moderated", 409)
        if decision == "approved":
            if _date(data.get("ends_at"), "ends_at") <= datetime.now(timezone.utc):
                raise PromotionError("Cannot approve an expired promotion", 409)
            if not _visible_target(data):
                raise PromotionError("The promoted shop or product is unavailable", 409)
        apply_capability = subscriptions.catalog_change_plan(transaction, data["vendor_id"], capability="promotions", lookup=doc) if decision == "approved" else (lambda: None)
        timestamp = now_iso()
        transaction.update(ref, {
            "status": decision, "moderation_reason": reason or None,
            "moderated_by": g.user_id, "moderated_at": timestamp, "updated_at": timestamp,
            "approved_revision": revision if decision == "approved" else None,
        })
        apply_capability()
        event = notification_data(data['vendor_id'], 'promotion_review', 'Promotion ' + decision,
                                  reason or 'Your shop promotion is approved.', promotion_id)
        transaction.set(doc(NOTIFICATIONS, f'promotion_{promotion_id}_{revision}_{decision}'), event)
        return event

    event = moderate(db().transaction())
    deliver_push(event, lookup=doc)
    return jsonify(to_dict(ref.get()))
