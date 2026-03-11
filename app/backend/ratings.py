from flask import Blueprint, request, jsonify
from firebase_admin import firestore
import firebase_db

ratings_bp = Blueprint("ratings", __name__)
db = firestore.client()


@ratings_bp.route("/shop/reviews", methods=["GET"])
def shop_reviews():
    shop_id = request.args.get("shop_id")
    rating = request.args.get("rating", type=int)

    if not shop_id or rating is None:
        return jsonify({"reviews": []}), 200

    # 🔁 Map rating → emoji
    rating_to_emoji = {
        5: "😍",
        4: "🙂",
        3: "😐",
        1: "😡"
    }

    emoji = rating_to_emoji.get(rating)
    if not emoji:
        return jsonify({"reviews": []}), 200

    reviews = firebase_db.get_shop_reviews_by_emoji(shop_id, emoji)

    return jsonify({
        "reviews": reviews
    }), 200
