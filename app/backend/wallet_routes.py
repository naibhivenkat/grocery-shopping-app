from flask import Blueprint, request, jsonify
from firebase_db import db
from datetime import datetime
import uuid
from google.cloud import firestore

wallet_bp = Blueprint("wallet", __name__)

def get_user_ref(user_id):
    return db.collection("users").document(user_id)

def get_transactions_ref():
    return db.collection("transactions")

# Get wallet balance
@wallet_bp.route("/wallet/<user_id>", methods=["GET"])
def get_wallet_balance(user_id):
    user = get_user_ref(user_id).get()
    if not user.exists:
        return jsonify({"error": "User not found"}), 404
    return jsonify({"balance": user.to_dict().get("wallet_balance", 0.0)})

# Add money (deposit)
@wallet_bp.route("/wallet/add", methods=["POST"])
def add_money():
    data = request.json
    user_id = data["user_id"]
    amount = float(data["amount"])

    user_ref = get_user_ref(user_id)
    user = user_ref.get()
    if not user.exists:
        return jsonify({"error": "User not found"}), 404

    new_balance = user.to_dict().get("wallet_balance", 0.0) + amount
    user_ref.update({"wallet_balance": new_balance})

    # Add transaction
    tx_id = str(uuid.uuid4())
    get_transactions_ref().document(tx_id).set({
        "userId": user_id,
        "type": "Deposit",
        "amount": amount,
        "dateTime": datetime.utcnow(),
        "orderId": None
    })
    return jsonify({"balance": new_balance})

# Pay for order
@wallet_bp.route("/wallet/pay", methods=["POST"])
def pay_order():
    data = request.json
    user_id = data["user_id"]
    amount = float(data["amount"])
    order_id = data.get("order_id")

    user_ref = get_user_ref(user_id)
    user = user_ref.get()
    if not user.exists:
        return jsonify({"error": "User not found"}), 404

    current_balance = user.to_dict().get("wallet_balance", 0.0)
    if current_balance < amount:
        return jsonify({"error": "Insufficient balance"}), 400

    new_balance = current_balance - amount
    user_ref.update({"wallet_balance": new_balance})

    tx_id = str(uuid.uuid4())
    get_transactions_ref().document(tx_id).set({
        "userId": user_id,
        "type": "Payment",
        "amount": amount,
        "dateTime": datetime.utcnow(),
        "orderId": order_id
    })
    return jsonify({"balance": new_balance})

# Refund to wallet
@wallet_bp.route("/wallet/refund", methods=["POST"])
def refund():
    data = request.json
    user_id = data["user_id"]
    amount = float(data["amount"])
    order_id = data.get("order_id")

    user_ref = get_user_ref(user_id)
    user = user_ref.get()
    if not user.exists:
        return jsonify({"error": "User not found"}), 404

    new_balance = user.to_dict().get("wallet_balance", 0.0) + amount
    user_ref.update({"wallet_balance": new_balance})

    tx_id = str(uuid.uuid4())
    get_transactions_ref().document(tx_id).set({
        "userId": user_id,
        "type": "Refund",
        "amount": amount,
        "dateTime": datetime.utcnow(),
        "orderId": order_id
    })
    return jsonify({"balance": new_balance})

# Transaction history
@wallet_bp.route("/wallet/transactions/<user_id>", methods=["GET"])
def transaction_history(user_id):
    tx_ref = get_transactions_ref().where("userId", "==", user_id).order_by("dateTime", direction=firestore.Query.DESCENDING)
    tx_docs = tx_ref.stream()
    tx_list = []
    for doc in tx_docs:
        data = doc.to_dict()
        data["dateTime"] = data["dateTime"].isoformat()
        tx_list.append(data)
    return jsonify(tx_list)
