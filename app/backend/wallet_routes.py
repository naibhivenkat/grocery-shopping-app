import logging
import os
import razorpay
import uuid
from datetime import datetime
from flask import Blueprint, request, jsonify
from google.cloud import firestore

import firebase_db
from firebase_db import db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("order_api")
wallet_bp = Blueprint("wallet", __name__)

# 🔹 Initialize Razorpay client
RAZORPAY_KEY_ID = "rzp_test_RKK3DuGSaxK9fR"
RAZORPAY_KEY_SECRET = "VgVc96Pdn3t5T8ieX0nb2ajt"
razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))


def get_user_ref(user_id):
    return db.collection("users").document(user_id)


@wallet_bp.route("/wallet/<user_id>", methods=["GET"])
def get_wallet_balance(user_id):
    # STEP 1 — Try Firestore doc ID
    user_ref = db.collection("users").document(user_id)
    snap = user_ref.get()

    if not snap.exists:
        # STEP 2 — Try fallback using customerId
        fallback = db.collection("users").where("customerId", "==", user_id).get()

        if len(fallback) == 0:
            return jsonify({"error": "User not found"}), 404

        snap = fallback[0]
        user_ref = snap.reference


    data = snap.to_dict()
    balance = float(data.get("wallet_balance", 0.0))

    return jsonify({
        "balance": balance,
        "success": True
    })


# Add money (deposit)
@wallet_bp.route("/wallet/add", methods=["POST"])
def add_money():
    data = request.json
    user_id = data["user_id"]
    amount = float(data["amount"])

    # --- STEP 1: Try primary Firestore ID (id field) ---
    user_ref = get_user_ref(user_id)
    user = user_ref.get()

    # --- STEP 2: If not found, try legacy customerId fallback ---
    if not user.exists:
        # search for old `customerId` field
        fallback_users = db.collection("users").where("customerId", "==", user_id).get()

        if len(fallback_users) == 0:
            return jsonify({"error": "User not found"}), 404

        # take the first match
        user = fallback_users[0]
        user_ref = user.reference


    # --- STEP 3: Now safe to update wallet ---
    user_data = user.to_dict()
    new_balance = float(user_data.get("wallet_balance", 0.0)) + amount

    user_ref.update({"wallet_balance": new_balance})

    # --- STEP 4: Add wallet transaction ---
    tx_id = str(uuid.uuid4())
    get_transactions_ref().document(tx_id).set({
        "userId": user_ref.id,  # ALWAYS use real Firestore ID
        "type": "Deposit",
        "amount": amount,
        "dateTime": datetime.utcnow(),
        "orderId": None
    })

    return jsonify({"balance": new_balance, "success": True})


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


def get_transactions_ref():
    return firebase_db.db.collection("transactions")


@wallet_bp.route("/wallet/refund", methods=["POST"])
def refund():
    try:
        data = request.json or {}


        firestore_id = data.get("user_id")  # could be doc id OR customerId OR id
        customer_id = data.get("customerId")  # your app UUID
        shop_id = data.get("shopId")
        order_id = data.get("order_id")
        amount = float(data.get("amount", 0))
        is_partial = bool(data.get("is_partial", False))

        if not firestore_id or not shop_id or amount <= 0:
            return jsonify({"error": "Invalid refund request"}), 400

        refund_type = "Partial Refund" if is_partial else "Refund"

        # ✅ Idempotency check (prevents duplicate refund)
        existing = firebase_db.db.collection("transactions") \
            .where("orderId", "==", order_id) \
            .where("type", "==", refund_type) \
            .limit(1) \
            .get()

        if existing:
            logger.warning(f"♻️ Duplicate refund blocked → {order_id}")
            return jsonify({"success": True, "message": "Already refunded"}), 200

        # ✅ Resolve correct user document safely
        user_ref, snap = firebase_db.get_user_firestore_ref(firestore_id)

        if not user_ref:
            fallback = firebase_db.db.collection("users").where("id", "==", firestore_id).limit(
                1).stream()
            for found in fallback:
                user_ref = found.reference
                snap = found
                break

        if not user_ref:
            return jsonify({"error": f"User not found: {firestore_id}"}), 404

        tx = firebase_db.db.transaction()

        @firestore.transactional
        def wallet_tx(transaction):
            snap2 = user_ref.get(transaction=transaction)
            user_data = snap2.to_dict() or {}
            balance = float(user_data.get("wallet_balance", 0))
            new_balance = balance + amount

            transaction.update(user_ref, {"wallet_balance": new_balance})

            firebase_db.db.collection("transactions").add({
                "userId": customer_id,
                "type": refund_type,
                "amount": amount,
                "orderId": order_id,
                "dateTime": datetime.utcnow(),
                "payment_type": "Wallet"
            })

            return new_balance

        new_balance = wallet_tx(tx)

        # ✅ Debit shop wallet (partial or full depends on is_partial)
        from shop_wallet_routes import deduct_shop_refund
        deduct_shop_refund(
            shop_id=shop_id,
            amount=amount,
            order_id=order_id,
            is_partial=is_partial
        )

        logger.info(f"💰 REFUND OK →")
        return jsonify({"success": True, "balance": new_balance}), 200

    except Exception as e:
        logger.error(f"❌ Refund failed: {e}")
        return jsonify({"error": "Refund failed"}), 500


@wallet_bp.route("/wallet/transactions/<user_id>", methods=["GET"])
def transaction_history(user_id):
    tx_docs = get_transactions_ref().where("userId", "==", user_id).stream()

    tx_list = []
    for doc in tx_docs:
        data = doc.to_dict()

        dt = data.get("dateTime")
        if hasattr(dt, "isoformat"):
            data["dateTime"] = dt.isoformat()
        else:
            data["dateTime"] = data.get("date") or None

        tx_list.append(data)

    tx_list.sort(key=lambda x: x["dateTime"] or "", reverse=True)
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
        # FIXED RECEIPT (must be ≤ 40 characters)
        "receipt": f"w_{user_id[:8]}_{str(uuid.uuid4())[:10]}"
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

    # fetch backend order
    order_ref = db.collection("wallet_orders").document(backend_order_id)
    order_data = order_ref.get().to_dict()

    if not order_data:
        return jsonify({"success": False, "message": "Order not found"}), 404

    user_id = order_data.get("user_id")
    amount = order_data.get("amount", 0.0)

    # fetch user
    # user_ref = db.collection("users").document(user_id)
    # user_doc = user_ref.get().to_dict()
    users = db.collection("users").where("customerId", "==", user_id).get()

    if len(users) == 0:
        return jsonify({"success": False, "message": "User not found"}), 404

    user_ref = users[0].reference
    user_doc = users[0].to_dict()

    if not user_doc:
        return jsonify({"success": False, "message": "User not found in database"}), 404

    # update wallet
    new_balance = float(user_doc.get("wallet_balance", 0.0)) + float(amount)
    user_ref.update({"wallet_balance": new_balance})

    # update order status
    order_ref.update({
        "status": "paid",
        "payment_id": razorpay_payment_id
    })

    # transaction entry
    tx_id = str(uuid.uuid4())
    db.collection("transactions").document(tx_id).set({
        "userId": user_id,
        "type": "Deposit",
        "amount": amount,
        "dateTime": datetime.utcnow(),
        "orderId": backend_order_id
    })

    return jsonify({"success": True, "balance": new_balance})
