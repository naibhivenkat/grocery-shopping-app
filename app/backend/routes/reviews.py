"""`/reviews/*` endpoints consumed by `ReviewRemoteDataSource`."""

from flask import Blueprint, g, jsonify, request
from google.cloud.firestore_v1.base_query import FieldFilter

from auth_utils import require_auth
from db import REVIEWS, SHOP_ITEMS, USERS, col, doc, now_iso, to_dict


reviews_bp = Blueprint("reviews", __name__)


def _recompute_item_rating(item_id: str) -> None:
    ratings = []
    for d in col(REVIEWS).where(filter=FieldFilter("item_id", "==", item_id)).stream():
        data = d.to_dict() or {}
        try:
            ratings.append(float(data.get("rating") or 0))
        except (TypeError, ValueError):
            pass
    if not ratings:
        return
    doc(SHOP_ITEMS, item_id).set({
        "average_rating": sum(ratings) / len(ratings),
        "rating_count": len(ratings),
    }, merge=True)


@reviews_bp.post("/reviews")
@require_auth
def add_review():
    payload = request.get_json(silent=True) or {}
    item_id = payload.get("item_id")
    vendor_id = payload.get("vendor_id")
    try:
        rating = float(payload.get("rating"))
    except (TypeError, ValueError):
        return jsonify({"detail": "rating is required"}), 422
    comment = (payload.get("comment") or "").strip()

    if not item_id or not vendor_id or rating <= 0:
        return jsonify({"detail": "item_id, vendor_id, rating required"}), 422

    user = doc(USERS, g.user_id).get().to_dict() or {}
    ref = col(REVIEWS).document()
    ref.set({
        "user_id": g.user_id,
        "item_id": item_id,
        "vendor_id": vendor_id,
        "rating": rating,
        "comment": comment,
        "user_name": user.get("full_name"),
        "user_avatar": user.get("avatar_url"),
        "created_at": now_iso(),
    })
    _recompute_item_rating(item_id)
    return jsonify(to_dict(ref.get())), 201


@reviews_bp.get("/reviews/item/<item_id>")
def list_item_reviews(item_id):
    query = col(REVIEWS).where(filter=FieldFilter("item_id", "==", item_id))
    items = [to_dict(d) for d in query.stream()]
    items.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    return jsonify(items)


@reviews_bp.get("/reviews/vendor/<vendor_id>")
def list_vendor_reviews(vendor_id):
    query = col(REVIEWS).where(filter=FieldFilter("vendor_id", "==", vendor_id))
    items = [to_dict(d) for d in query.stream()]
    items.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    return jsonify(items)



@reviews_bp.post("/services/ratings/submit")
@require_auth
def submit_legacy_rating():
    # Redirects to V2 logic
    return add_review()

@reviews_bp.get("/services/ratings/<provider_id>")
def get_legacy_provider_reviews(provider_id):
    query = col(REVIEWS).where(filter=FieldFilter("vendor_id", "==", provider_id))
    items = [to_dict(d) for d in query.stream()]
    return jsonify({"reviews": items})

@reviews_bp.get("/services/ratings/<provider_id>/aggregate")
def get_legacy_provider_aggregate(provider_id):
    query = col(REVIEWS).where(filter=FieldFilter("vendor_id", "==", provider_id))
    ratings = [float((d.to_dict() or {}).get("rating", 0)) for d in query.stream()]
    avg = sum(ratings) / len(ratings) if ratings else 0.0
    return jsonify({"rating": avg})
