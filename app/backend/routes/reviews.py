"""Eligible customer reviews with atomic item and service rating summaries."""
import hashlib
import json
import math
from firebase_admin import firestore
from flask import Blueprint, g, jsonify
from google.cloud.firestore_v1.base_query import FieldFilter
from auth_utils import require_role
from db import CUSTOMER_ORDERS, REVIEWS, SHOP_ITEMS, USERS, col, db, doc, now_iso, to_dict
from routes.khata import KhataError, _khata_error, _payload, _identifier, _text

reviews_bp = Blueprint("reviews", __name__)
reviews_bp.register_error_handler(KhataError, _khata_error)
_PUBLIC_FIELDS = {"uid", "user_id", "item_id", "vendor_id", "rating", "comment", "user_name", "user_avatar", "created_at", "updated_at"}


def _rating(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise KhataError("rating must be between 1 and 5")
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError):
        raise KhataError("rating must be between 1 and 5") from None
    if not math.isfinite(number) or not 1 <= number <= 5:
        raise KhataError("rating must be between 1 and 5")
    return number


@reviews_bp.post("/reviews")
@require_role("customer")
def add_review():
    payload = _payload()
    if "service_id" in payload or "provider_id" in payload:
        if "item_id" in payload or "vendor_id" in payload:
            raise KhataError("Choose exactly one review target family")
        return _add_service_review(payload)
    item_id = _identifier(payload.get("item_id"), "item_id")
    vendor_id = _identifier(payload.get("vendor_id"), "vendor_id")
    rating = _rating(payload.get("rating"))
    comment = _text(payload.get("comment"), "comment", 2000)
    identifier = hashlib.sha256(json.dumps([g.user_id, item_id]).encode()).hexdigest()
    ref = doc(REVIEWS, "review_" + identifier)
    item_ref = doc(SHOP_ITEMS, item_id)

    @firestore.transactional
    def save(tx):
        item = item_ref.get(transaction=tx)
        vendor = doc(USERS, vendor_id).get(transaction=tx)
        user = doc(USERS, g.user_id).get(transaction=tx)
        if not item.exists:
            raise KhataError("Item not found", 404)
        if (item.to_dict() or {}).get("vendor_id") != vendor_id:
            raise KhataError("Vendor does not own this item", 422)
        if not vendor.exists or (vendor.to_dict() or {}).get("role") != "vendor" or (vendor.to_dict() or {}).get("is_suspended"):
            raise KhataError("Vendor is unavailable", 404)
        if not user.exists or (user.to_dict() or {}).get("role") != "customer" or (user.to_dict() or {}).get("is_suspended"):
            raise KhataError("Customer is unavailable", 403)
        # Derive eligibility from trusted order records, never client linkage or
        # author fields. Batch checkout also stores one order per item here.
        orders = tx.get(col(CUSTOMER_ORDERS).where(filter=FieldFilter("customer_id", "==", g.user_id)))
        if not any(
            (order.to_dict() or {}).get("item_id") == item_id
            and (order.to_dict() or {}).get("vendor_id") == vendor_id
            and (order.to_dict() or {}).get("status") == "delivered"
            for order in orders
        ):
            raise KhataError("A completed order for this item is required", 403)
        previous = list(tx.get(col(REVIEWS).where(filter=FieldFilter("item_id", "==", item_id))))
        own = [snap for snap in previous if (snap.to_dict() or {}).get("user_id") == g.user_id]
        if len(own) > 1:
            raise KhataError("Duplicate customer reviews require reconciliation", 409)
        selected = own[0].reference if own else ref
        user_data = user.to_dict() or {}
        timestamp = now_iso()
        data = {"user_id": g.user_id, "item_id": item_id, "vendor_id": vendor_id,
                "rating": rating, "comment": comment, "user_name": user_data.get("full_name") or user_data.get("username") or "Customer",
                "user_avatar": user_data.get("avatar_url"), "created_at": (own[0].to_dict() or {}).get("created_at", timestamp) if own else timestamp,
                "updated_at": timestamp}
        ratings = [rating]
        for snap in previous:
            if snap.id == selected.id:
                continue
            try:
                ratings.append(_rating((snap.to_dict() or {}).get("rating")))
            except KhataError:
                continue
        tx.set(selected, data)
        tx.update(item_ref, {"average_rating": sum(ratings) / len(ratings), "rating_count": len(ratings)})
        return {**data, "uid": selected.id}, 200 if own else 201
    body, status = save(db().transaction())
    return jsonify(body), status


def _list(field, identifier):
    query = col(REVIEWS).where(filter=FieldFilter(field, "==", _identifier(identifier, field)))
    items = [{key: value for key, value in to_dict(snap).items() if key in _PUBLIC_FIELDS} for snap in query.stream() if not (snap.to_dict() or {}).get("service_id")]
    items.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    return jsonify(items)


@reviews_bp.get("/reviews/item/<item_id>")
def list_item_reviews(item_id):
    return _list("item_id", item_id)


@reviews_bp.get("/reviews/vendor/<vendor_id>")
def list_vendor_reviews(vendor_id):
    return _list("vendor_id", vendor_id)


_SERVICE_PUBLIC_FIELDS = (_PUBLIC_FIELDS - {"item_id", "vendor_id"}) | {"service_id", "provider_id"}


def _add_service_review(payload):
    service_id = _identifier(payload.get("service_id"), "service_id")
    provider_id = _identifier(payload.get("provider_id"), "provider_id")
    booking_id = _identifier(payload.get("booking_id"), "booking_id")
    rating = _rating(payload.get("rating"))
    comment = _text(payload.get("comment"), "comment", 2000)
    digest = hashlib.sha256(json.dumps([g.user_id, service_id]).encode()).hexdigest()
    ref = doc(REVIEWS, "service_review_" + digest)
    service_ref = doc("provider_services", service_id)

    @firestore.transactional
    def save(tx):
        service = service_ref.get(transaction=tx)
        provider = doc(USERS, provider_id).get(transaction=tx)
        profile = doc("provider_profiles", provider_id).get(transaction=tx)
        user = doc(USERS, g.user_id).get(transaction=tx)
        booking = doc("service_bookings", booking_id).get(transaction=tx)
        current = service.to_dict() or {}
        if not service.exists or current.get("is_deleted") or current.get("is_active") is False:
            raise KhataError("Service is unavailable", 404)
        if current.get("provider_id") != provider_id:
            raise KhataError("Provider does not own this service", 422)
        if (not provider.exists or (provider.to_dict() or {}).get("is_suspended")
                or not profile.exists or (profile.to_dict() or {}).get("is_active") is False):
            raise KhataError("Provider is unavailable", 404)
        user_data = user.to_dict() or {}
        if not user.exists or user_data.get("role") != "customer" or user_data.get("is_suspended"):
            raise KhataError("Customer is unavailable", 403)
        data = booking.to_dict() or {}
        if (not booking.exists or data.get("requester_id") != g.user_id
                or data.get("service_id") != service_id or data.get("provider_id") != provider_id
                or data.get("status") != "completed" or data.get("payment_status") != "paid"):
            raise KhataError("A completed paid booking for this service is required", 403)
        previous = list(tx.get(col(REVIEWS).where(filter=FieldFilter("service_id", "==", service_id))))
        own = [snap for snap in previous if (snap.to_dict() or {}).get("user_id") == g.user_id]
        if len(own) > 1:
            raise KhataError("Duplicate customer reviews require reconciliation", 409)
        selected = own[0].reference if own else ref
        timestamp = now_iso()
        data = {"user_id": g.user_id, "service_id": service_id, "provider_id": provider_id,
                "booking_id": booking_id, "rating": rating, "comment": comment,
                "user_name": user_data.get("full_name") or user_data.get("username") or "Customer",
                "user_avatar": user_data.get("avatar_url"),
                "created_at": (own[0].to_dict() or {}).get("created_at", timestamp) if own else timestamp,
                "updated_at": timestamp}
        ratings = [rating]
        for snap in previous:
            if snap.id == selected.id:
                continue
            try:
                ratings.append(_rating((snap.to_dict() or {}).get("rating")))
            except KhataError:
                continue
        tx.set(selected, data)
        tx.update(service_ref, {"average_rating": sum(ratings) / len(ratings), "rating_count": len(ratings)})
        return {**data, "uid": selected.id}, 200 if own else 201
    body, status = save(db().transaction())
    return jsonify(body), status


def _list_service(field, identifier):
    query = col(REVIEWS).where(filter=FieldFilter(field, "==", _identifier(identifier, field)))
    items = [{key: value for key, value in to_dict(snap).items() if key in _SERVICE_PUBLIC_FIELDS}
             for snap in query.stream() if (snap.to_dict() or {}).get("service_id")]
    items.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    return jsonify(items)


@reviews_bp.get("/reviews/service/<service_id>")
def list_service_reviews(service_id):
    return _list_service("service_id", service_id)


@reviews_bp.get("/reviews/provider/<provider_id>")
def list_provider_reviews(provider_id):
    return _list_service("provider_id", provider_id)


@reviews_bp.put("/reviews/<review_id>/reply")
@require_role("vendor", "service_provider")
def put_review_reply(review_id):
    review_id = _identifier(review_id, "review_id")
    payload = _payload()
    if set(payload) != {"text"}:
        raise KhataError("Only text is required")
    text = _text(payload["text"], "text", 2000)
    if not text:
        raise KhataError("text must not be blank")
    review_ref = doc(REVIEWS, review_id)
    reply_ref = doc("review_replies", review_id)

    @firestore.transactional
    def save(tx):
        review = review_ref.get(transaction=tx)
        if not review.exists:
            raise KhataError("Review not found", 404)
        data = review.to_dict() or {}
        is_service = bool(data.get("service_id"))
        target_id = data.get("service_id" if is_service else "item_id")
        owner_id = data.get("provider_id" if is_service else "vendor_id")
        role = "service_provider" if is_service else "vendor"
        if not isinstance(target_id, str) or not target_id or "/" in target_id:
            raise KhataError("Review target unavailable", 404)
        target = doc("provider_services" if is_service else SHOP_ITEMS, target_id).get(transaction=tx)
        if not target.exists:
            raise KhataError("Review target unavailable", 404)
        if (g.user_role != role or owner_id != g.user_id or
                (target.to_dict() or {}).get("provider_id" if is_service else "vendor_id") != g.user_id):
            raise KhataError("Insufficient permissions", 403)
        previous = reply_ref.get(transaction=tx)
        timestamp = now_iso()
        reply = {"text": text, "created_at": (previous.to_dict() or {}).get("created_at", timestamp) if previous.exists else timestamp,
                 "updated_at": timestamp}
        tx.set(reply_ref, reply)
        return reply, 200 if previous.exists else 201

    body, status = save(db().transaction())
    return jsonify(body), status


@reviews_bp.get("/reviews/<review_id>/reply")
def get_review_reply(review_id):
    review_id = _identifier(review_id, "review_id")
    if not doc(REVIEWS, review_id).get().exists:
        raise KhataError("Review not found", 404)
    reply = doc("review_replies", review_id).get()
    if not reply.exists:
        raise KhataError("Reply not found", 404)
    data = reply.to_dict() or {}
    return jsonify({key: data[key] for key in ("text", "created_at", "updated_at") if key in data})
