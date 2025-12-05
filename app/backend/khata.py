# # khata.py
# from flask import Blueprint, request, jsonify
# import firebase_db
#
# khata_bp = Blueprint("khata_bp", __name__)
#
# # ================================
# #  KHATA / LEDGER ROUTES
# # ================================
#
# @khata_bp.route("/create_ledger", methods=["POST"])
# def khata_create_ledger():
#     data = request.json or {}
#     shop_id = data.get("shop_id")
#     customer_id = data.get("customer_id")
#     name = data.get("customer_name") or data.get("name")
#     phone = data.get("phone")
#
#     if not shop_id or not customer_id:
#         return jsonify({"success": False, "message": "shop_id and customer_id required"}), 400
#
#     account = firebase_db.get_or_create_khata_account(shop_id, customer_id, name, phone)
#     if not account:
#         return jsonify({"success": False, "message": "Failed to create ledger"}), 500
#
#     return jsonify({"success": True, "account": account}), 200
#
#
# @khata_bp.route("/add_transaction", methods=["POST"])
# def khata_add_transaction():
#     data = request.json or {}
#     shop_id = data.get("shop_id")
#     customer_id = data.get("customer_id")
#     tx_type = data.get("type")  # "debit" or "credit"
#     amount = data.get("amount")
#     note = data.get("note") or ""
#     order_id = data.get("order_id")
#
#     if not all([shop_id, customer_id, tx_type, amount]):
#         return jsonify({"success": False, "message": "Missing required fields"}), 400
#
#     try:
#         amount = float(amount)
#     except Exception:
#         return jsonify({"success": False, "message": "amount must be numeric"}), 400
#
#     result = firebase_db.add_khata_transaction(
#         shop_id=shop_id,
#         customer_id=customer_id,
#         amount=amount,
#         tx_type=tx_type,
#         note=note,
#         order_id=order_id
#     )
#
#     if not result:
#         return jsonify({"success": False, "message": "Failed to add transaction"}), 500
#
#     return jsonify({"success": True, **result}), 200
#
#
# @khata_bp.route("/ledger/<shop_id>/<customer_id>", methods=["GET"])
# def khata_get_ledger(shop_id, customer_id):
#     account = firebase_db.get_khata_account(shop_id, customer_id)
#     txs = firebase_db.list_khata_transactions(shop_id, customer_id, limit=200)
#
#     if not account:
#         return jsonify({"success": False, "message": "No ledger found"}), 404
#
#     return jsonify({
#         "success": True,
#         "account": account,
#         "transactions": txs
#     }), 200
#
#
# @khata_bp.route("/customers/<shop_id>", methods=["GET"])
# def khata_list_customers(shop_id):
#     accounts = firebase_db.list_khata_customers_for_shop(shop_id)
#     return jsonify({
#         "success": True,
#         "accounts": accounts
#     }), 200
#
#
# @khata_bp.route("/my_accounts/<customer_id>", methods=["GET"])
# def khata_list_for_customer(customer_id):
#     accounts = firebase_db.list_khata_accounts_for_customer(customer_id)
#     return jsonify({
#         "success": True,
#         "accounts": accounts
#     }), 200


from flask import Blueprint, request, jsonify
import firebase_db
import logging
import uuid
from firebase_admin import firestore

import datetime


# logging.basicConfig(level=logging.INFO)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("order_api")

khata_bp = Blueprint("khata_bp", __name__)

# --------------------------------------------------------
# CREATE LEDGER
# --------------------------------------------------------
@khata_bp.route("/create_ledger", methods=["POST"])
def khata_create_ledger():
    data = request.json or {}
    shop_id = data.get("shop_id")
    customer_id = data.get("customer_id")
    name = data.get("customer_name")
    phone = data.get("phone")

    if not shop_id or not customer_id:
        return jsonify({"success": False, "message": "Missing required fields"}), 400

    account = firebase_db.get_or_create_khata_account(shop_id, customer_id, name, phone)

    return jsonify({"success": True, "account": account}), 200


# --------------------------------------------------------
# ADD TRANSACTION
# --------------------------------------------------------
@khata_bp.route("/add_transaction", methods=["POST"])
def khata_add_transaction():
    data = request.json or {}
    shop_id = data.get("shop_id")
    customer_id = data.get("customer_id")
    tx_type = data.get("type")
    amount = data.get("amount")
    note = data.get("note") or ""
    order_id = data.get("order_id")

    if not all([shop_id, customer_id, tx_type, amount]):
        return jsonify({"success": False, "message": "Missing required fields"}), 400

    result = firebase_db.add_khata_transaction(
        shop_id, customer_id, float(amount), tx_type, note, order_id
    )

    if not result:
        return jsonify({"success": False, "message": "Failed"}), 500

    return jsonify({"success": True, **result}), 200


# --------------------------------------------------------
# GET LEDGER
# --------------------------------------------------------
@khata_bp.route("/ledger/<shop_id>/<customer_id>", methods=["GET"])
def khata_get_ledger(shop_id, customer_id):
    account = firebase_db.get_khata_account(shop_id, customer_id)
    txs = firebase_db.list_khata_transactions(shop_id, customer_id)

    if not account:
        return jsonify({"success": False, "message": "Ledger not found"}), 404

    return jsonify({
        "success": True,
        "account": account,
        "transactions": txs
    }), 200


# --------------------------------------------------------
# SHOP OWNER → LIST ACCOUNTS
# --------------------------------------------------------
@khata_bp.route("/customers/<shop_id>", methods=["GET"])
def khata_list_customers(shop_id):
    accounts = firebase_db.list_khata_customers_for_shop(shop_id)
    return jsonify({"success": True, "accounts": accounts}), 200


# --------------------------------------------------------
# CUSTOMER → MY ACCOUNTS
# --------------------------------------------------------
@khata_bp.route("/my_accounts/<customer_id>", methods=["GET"])
def khata_list_for_customer(customer_id):
    accounts = firebase_db.list_khata_accounts_for_customer(customer_id)
    return jsonify({"success": True, "accounts": accounts}), 200


@khata_bp.route("/pay_khata_from_wallet", methods=["POST"])
def pay_khata_from_wallet():
    data = request.json or {}
    logger.error(f"🔥 PAY_KHATA_FROM_WALLET RECEIVED → {data}")


    shop_id = data.get("shop_id")
    customer_id = data.get("customer_id")
    amount = float(data.get("amount", 0))

    if not shop_id or not customer_id or amount <= 0:
        return jsonify({"success": False, "message": "Invalid data"}), 400

    # -------------------------------------------------------------
    # 🔍 Fetch user using customerId
    # -------------------------------------------------------------
    try:
        user_stream = (
            firebase_db.db.collection("users")
            .where("customerId", "==", customer_id)
            .limit(1)
            .stream()
        )

        user_doc = next(user_stream, None)

    except Exception as e:
        logger.error(f"🔥 Firestore USER FETCH ERROR: {e}")
        return jsonify({"success": False, "message": "Server error"}), 500

    if user_doc is None:
        return jsonify({"success": False, "message": "User not found"}), 404

    user_ref = user_doc.reference
    user_data = user_doc.to_dict()

    wallet_balance = float(user_data.get("wallet_balance", 0.0))

    # -------------------------------------------------------------
    # ❌ Not enough balance
    # -------------------------------------------------------------
    if wallet_balance < amount:
        return jsonify({"success": False, "message": "Insufficient wallet balance"}), 400

    # -------------------------------------------------------------
    # 💰 Deduct wallet balance
    # -------------------------------------------------------------
    new_balance = wallet_balance - amount
    try:
        user_ref.update({"wallet_balance": new_balance})
        logger.info(f"Wallet deducted. Old: {wallet_balance}, New: {new_balance}")
    except Exception as e:
        logger.error(f"🔥 WALLET UPDATE ERROR: {e}")
        return jsonify({"success": False, "message": "Wallet update failed"}), 500

    # -------------------------------------------------------------
    # 🧾 Add Khata CREDIT entry
    # -------------------------------------------------------------
    try:
        firebase_db.add_khata_transaction(
            shop_id=shop_id,
            customer_id=customer_id,
            amount=amount,
            tx_type="credit",
            note="Khata Payment via Wallet",
            order_id=None
        )
        logger.info("Khata credit transaction added.")
    except Exception as e:
        logger.error(f"🔥 KHATA TX ERROR: {e}")

    # -------------------------------------------------------------
    # 🧾 Add WALLET TRANSACTION entry (FULLY FIXED)
    # -------------------------------------------------------------
    try:
        tx_id = str(uuid.uuid4())

        firebase_db.db.collection("transactions").document(tx_id).set({
            "txId": tx_id,
            "userId": customer_id,                 # <-- FIXED HERE
            "shopId": shop_id,
            "type": "Payment",
            "amount": amount,
            "dateTime": firestore.SERVER_TIMESTAMP,
            "orderId": None,
            "source": "wallet",
            "description": "Khata Payment from Wallet"
        })

        logger.info(f"Wallet transaction added successfully → ID={tx_id}")

    except Exception as e:
        logger.error(f"🔥 WALLET TRANSACTION ERROR: {e}")

        # Still return success, because wallet + khata update succeeded
        return jsonify({
            "success": True,
            "wallet_balance": new_balance,
            "warning": "Payment done, but transaction log failed. Check server logs."
        }), 200

    # -------------------------------------------------------------
    # ✅ Success Response
    # -------------------------------------------------------------
    return jsonify({
        "success": True,
        "wallet_balance": new_balance,
        "message": "Khata payment successful"
    }), 200
