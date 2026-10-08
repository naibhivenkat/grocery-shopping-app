"""Inventory aggregation and private budget suggestions, without an external LLM."""

from collections import Counter, defaultdict
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP

from flask import Blueprint, g, jsonify, request
from google.cloud.firestore_v1.base_query import FieldFilter

from auth_utils import require_auth
from db import AI_SUMMARIES, SHOP_ITEMS, USERS, col, doc, now_iso, to_dict
from routes.provider_profiles import ValidationError, validation_response, valid_id, json_object, text, finite_number

ai_bp = Blueprint("ai", __name__)
ai_bp.register_error_handler(ValidationError, validation_response)
PUBLIC_SUMMARY_FIELDS = {"uid", "city_id", "area", "summary", "top_categories", "total_shops", "avg_rating", "generated_at"}


def _available_items(city_id):
    query = col(SHOP_ITEMS)
    if city_id:
        query = query.where(filter=FieldFilter("city_id", "==", city_id))
    vendors = {}
    for snapshot in query.stream():
        item = {**(snapshot.to_dict() or {}), "uid": snapshot.id}
        if item.get("is_available") is False or item.get("disabled_by_admin"):
            continue
        try:
            item["price"] = finite_number(item.get("price"), "price", 0.01)
            if item.get("stock_quantity") is not None:
                stock = finite_number(item["stock_quantity"], "stock_quantity", 1)
                if not stock.is_integer():
                    continue
            vendor_id = valid_id(item.get("vendor_id"), "vendor_id")
            if vendor_id not in vendors:
                user = doc(USERS, vendor_id).get()
                vendor = user.to_dict() or {} if user.exists else {}
                vendors[vendor_id] = user.exists and vendor.get("role") == "vendor" and not vendor.get("is_suspended")
            if not vendors[vendor_id]:
                continue
            item["category"] = text(item.get("category"), "category", 100)
            for field in ("name", "vendor_name", "area", "shop_area", "city_name"):
                item[field] = text(item.get(field), field, 200)
        except ValidationError:
            continue
        yield item


@ai_bp.get("/ai/summary")
def area_summaries():
    city_id = request.args.get("city_id") or ""
    if city_id:
        valid_id(city_id, "city_id")
    query = col(AI_SUMMARIES)
    if city_id:
        query = query.where(filter=FieldFilter("city_id", "==", city_id))
    cached = []
    for snapshot in query.stream():
        data = to_dict(snapshot)
        # AI_SUMMARIES also contains private per-user budget documents.
        if "user_id" in data or "suggested_items" in data or snapshot.id.startswith("budget__") or not isinstance(data.get("area"), str):
            continue
        public = {key: data.get(key) for key in PUBLIC_SUMMARY_FIELDS}
        try:
            public["avg_rating"] = finite_number(data.get("avg_rating") or 0, "avg_rating", 0, 5)
        except ValidationError:
            public["avg_rating"] = 0
        cached.append(public)
    if cached:
        return jsonify(cached)
    areas = defaultdict(list)
    for item in _available_items(city_id):
        areas[item.get("area") or item.get("shop_area") or item.get("city_name") or "General"].append(item)
    summaries = []
    for area, items in areas.items():
        categories = Counter(item["category"] or "Other" for item in items).most_common(5)
        ratings = []
        for item in items:
            try:
                rating = finite_number(item.get("average_rating") or 0, "rating", 0, 5)
                if rating:
                    ratings.append(rating)
            except ValidationError:
                pass
        summaries.append({"uid": f"{city_id}__{area}", "city_id": city_id, "area": area,
            "summary": f"{len(items)} items across {len(categories)} categories.",
            "top_categories": [name for name, _ in categories],
            "total_shops": len({item["vendor_id"] for item in items}),
            "avg_rating": sum(ratings) / len(ratings) if ratings else 0,
            "generated_at": now_iso()})
    return jsonify(summaries)


@ai_bp.post("/ai/budget-plan")
@require_auth
def budget_plan():
    payload = json_object({"budget", "city_id", "preferred_categories"})
    budget = finite_number(payload.get("budget"), "budget", 0.01)
    budget_paise = int((Decimal(str(budget)) * 100).quantize(Decimal("1"), rounding=ROUND_DOWN))
    city_id = payload.get("city_id")
    if city_id in (None, ""):
        city_id = ""
    else:
        valid_id(city_id, "city_id")
    preferred = payload.get("preferred_categories", [])
    if not isinstance(preferred, list) or len(preferred) > 30:
        raise ValidationError("preferred_categories must be a list of at most 30 names")
    preferred = {text(value, "category", 100, True) for value in preferred}
    items = sorted(_available_items(city_id), key=lambda item: (0 if item["category"] in preferred else 1, item["price"]))
    suggested, total_paise = [], 0
    for item in items:
        price_paise = int((Decimal(str(item["price"])) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        if total_paise + price_paise > budget_paise:
            continue
        suggested.append({"item_id": item["uid"], "item_name": item["name"], "shop_name": item["vendor_name"],
            "price": price_paise / 100, "category": item["category"]})
        total_paise += price_paise
        if len(suggested) >= 20:
            break
    ref = doc(AI_SUMMARIES, f"budget__{g.user_id}")
    body = {"user_id": g.user_id, "budget": budget_paise / 100, "city_id": city_id,
        "suggested_items": suggested, "total_cost": total_paise / 100, "created_at": now_iso()}
    ref.set(body)
    return jsonify({**body, "uid": ref.id})
