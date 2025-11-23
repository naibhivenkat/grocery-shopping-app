from flask import Blueprint, request, jsonify
from firebase_db import db
from datetime import datetime
import uuid
from google.cloud import firestore
import razorpay
import os
wallet_bp = Blueprint("wallet", __name__)


# 🔹 Initialize Razorpay client
RAZORPAY_KEY_ID = "rzp_test_RKK3DuGSaxK9fR"
RAZORPAY_KEY_SECRET = "VgVc96Pdn3t5T8ieX0nb2ajt"
razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
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

@wallet_bp.route("/create_wallet_order", methods=["POST"])
def create_wallet_order():
    data = request.json
    user_id = data["user_id"]
    amount = float(data["amount"])

    # Razorpay amount in paise
    razorpay_amount = int(amount * 100)

    # create order in Razorpay
    order = razorpay_client.order.create({
        "amount": razorpay_amount,
        "currency": "INR",
        "receipt": f"wallet_{user_id}_{uuid.uuid4()}"
    })

    backend_order_id = str(uuid.uuid4())

    # store this order in Firestore
    db.collection("wallet_orders").document(backend_order_id).set({
        "user_id": user_id,
        "amount": amount,
        "razorpay_order_id": order["id"],
        "status": "created",
        "timestamp": datetime.utcnow()
    })

    return jsonify({
        "backend_order_id": backend_order_id,
        "razorpay_order_id": order["id"]
    })


@wallet_bp.route("/verify_wallet_payment", methods=["POST"])
def verify_wallet_payment():
    data = request.json

    backend_order_id = data["backend_order_id"]
    razorpay_payment_id = data["payment_id"]
    razorpay_order_id = data["order_id"]
    signature = data["signature"]

    # Verify signature
    try:
        razorpay_client.utility.verify_payment_signature({
            "razorpay_order_id": razorpay_order_id,
            "razorpay_payment_id": razorpay_payment_id,
            "razorpay_signature": signature
        })
    except:
        return jsonify({"success": False, "message": "Signature verification failed"}), 400

    # 🎉 Save success in DB
    order_ref = db.collection("wallet_orders").document(backend_order_id)
    order_data = order_ref.get().to_dict()

    user_id = order_data["user_id"]
    amount = order_data["amount"]

    # update Firestore order status
    order_ref.update({
        "status": "paid",
        "payment_id": razorpay_payment_id
    })

    # add money to wallet
    user_ref = db.collection("users").document(user_id)
    user_doc = user_ref.get().to_dict()
    new_balance = user_doc.get("wallet_balance", 0.0) + amount

    user_ref.update({"wallet_balance": new_balance})

    # Add transaction
    tx_id = str(uuid.uuid4())
    db.collection("transactions").document(tx_id).set({
        "userId": user_id,
        "type": "Deposit",
        "amount": amount,
        "dateTime": datetime.utcnow(),
        "orderId": backend_order_id
    })

    return jsonify({"success": True, "balance": new_balance})

