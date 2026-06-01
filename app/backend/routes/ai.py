"""`/ai/*` endpoints consumed by `AiRemoteDataSource`.

The implementation uses lightweight aggregation over the existing shop-item
data rather than calling an external LLM — the Flutter layer treats the
response as canonical model data.
"""

from collections import Counter, defaultdict

from flask import Blueprint, g, jsonify, request
from google.cloud.firestore_v1.base_query import FieldFilter

from app.backend.auth_utils import require_auth
from app.backend.db import (
    AI_SUMMARIES,
    SHOP_ITEMS,
    USERS,
    col,
    doc,
    now_iso,
    to_dict,
)


ai_bp = Blueprint("ai", __name__)


@ai_bp.get("/ai/summary")
def area_summaries():
    city_id = request.args.get("city_id") or ""
    query = col(AI_SUMMARIES)
    if city_id:
        query = query.where(filter=FieldFilter("city_id", "==", city_id))
    cached = [to_dict(d) for d in query.stream()]
    if cached:
        return jsonify(cached)

    # Build a lightweight summary on the fly if no cached summaries exist.
    items_query = col(SHOP_ITEMS)
    if city_id:
        items_query = items_query.where(filter=FieldFilter("city_id", "==", city_id))
    items = [d.to_dict() or {} for d in items_query.stream()]
    if not items:
        return jsonify([])

    by_area: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        area = (
            item.get("area")
            or item.get("shop_area")
            or item.get("city_name")
            or "General"
        )
        by_area[area].append(item)

    summaries = []
    for area, area_items in by_area.items():
        categories = Counter(
            (i.get("category") or "Other") for i in area_items
        ).most_common(5)
        ratings = [
            float(i.get("average_rating") or 0)
            for i in area_items
            if i.get("average_rating")
        ]
        avg_rating = sum(ratings) / len(ratings) if ratings else 0.0
        summaries.append({
            "uid": f"{city_id}__{area}",
            "city_id": city_id,
            "area": area,
            "summary": f"{len(area_items)} items across {len(categories)} categories.",
            "top_categories": [c for c, _ in categories],
            "total_shops": len({i.get("vendor_id") for i in area_items if i.get("vendor_id")}),
            "avg_rating": avg_rating,
            "generated_at": now_iso(),
        })
    return jsonify(summaries)


@ai_bp.post("/ai/budget-plan")
@require_auth
def budget_plan():
    payload = request.get_json(silent=True) or {}
    try:
        budget = float(payload.get("budget") or 0)
    except (TypeError, ValueError):
        budget = 0.0
    city_id = payload.get("city_id") or ""
    preferred = set(payload.get("preferred_categories") or [])
    if budget <= 0:
        return jsonify({"detail": "budget must be positive"}), 422

    items_query = col(SHOP_ITEMS)
    if city_id:
        items_query = items_query.where(filter=FieldFilter("city_id", "==", city_id))
    items = sorted(
        (
            {**(d.to_dict() or {}), "uid": d.id}
            for d in items_query.stream()
        ),
        key=lambda i: (
            0 if (i.get("category") or "") in preferred else 1,
            float(i.get("price") or 0),
        ),
    )

    suggested: list[dict] = []
    total_cost = 0.0
    for item in items:
        price = float(item.get("price") or 0)
        if price <= 0:
            continue
        if total_cost + price > budget:
            continue
        suggested.append({
            "item_id": item.get("uid"),
            "item_name": item.get("name") or "",
            "shop_name": item.get("vendor_name") or "",
            "price": price,
            "category": item.get("category") or "",
        })
        total_cost += price
        if len(suggested) >= 20:
            break

    ref = doc(AI_SUMMARIES, f"budget__{g.user_id}")
    body = {
        "user_id": g.user_id,
        "budget": budget,
        "city_id": city_id,
        "suggested_items": suggested,
        "total_cost": total_cost,
        "created_at": now_iso(),
    }
    # Reuse AI_SUMMARIES doc space so the client receives a consistent uid.
    ref.set(body)
    return jsonify({**body, "uid": ref.id})
