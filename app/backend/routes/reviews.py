"""Customer reviews with bounded ratings and an atomic item rating summary."""
import hashlib
import json
import math
from firebase_admin import firestore
from flask import Blueprint, g, jsonify
from google.cloud.firestore_v1.base_query import FieldFilter
from auth_utils import require_role
from db import REVIEWS, SHOP_ITEMS, USERS, col, db, doc, now_iso, to_dict
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
    items = [{key: value for key, value in to_dict(snap).items() if key in _PUBLIC_FIELDS} for snap in query.stream()]
    items.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    return jsonify(items)


@reviews_bp.get("/reviews/item/<item_id>")
def list_item_reviews(item_id):
    return _list("item_id", item_id)


@reviews_bp.get("/reviews/vendor/<vendor_id>")
def list_vendor_reviews(vendor_id):
    return _list("vendor_id", vendor_id)
