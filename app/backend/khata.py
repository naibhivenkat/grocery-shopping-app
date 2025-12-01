# khata.py
from flask import Blueprint, request, jsonify
import firebase_db

khata_bp = Blueprint("khata_bp", __name__)

# ================================
#  KHATA / LEDGER ROUTES
# ================================

@khata_bp.route("/create_ledger", methods=["POST"])
def khata_create_ledger():
    data = request.json or {}
    shop_id = data.get("shop_id")
    customer_id = data.get("customer_id")
    name = data.get("customer_name") or data.get("name")
    phone = data.get("phone")

    if not shop_id or not customer_id:
        return jsonify({"success": False, "message": "shop_id and customer_id required"}), 400

    account = firebase_db.get_or_create_khata_account(shop_id, customer_id, name, phone)
    if not account:
        return jsonify({"success": False, "message": "Failed to create ledger"}), 500

    return jsonify({"success": True, "account": account}), 200


@khata_bp.route("/add_transaction", methods=["POST"])
def khata_add_transaction():
    data = request.json or {}
    shop_id = data.get("shop_id")
    customer_id = data.get("customer_id")
    tx_type = data.get("type")  # "debit" or "credit"
    amount = data.get("amount")
    note = data.get("note") or ""
    order_id = data.get("order_id")

    if not all([shop_id, customer_id, tx_type, amount]):
        return jsonify({"success": False, "message": "Missing required fields"}), 400

    try:
        amount = float(amount)
    except Exception:
        return jsonify({"success": False, "message": "amount must be numeric"}), 400

    result = firebase_db.add_khata_transaction(
        shop_id=shop_id,
        customer_id=customer_id,
        amount=amount,
        tx_type=tx_type,
        note=note,
        order_id=order_id
    )

    if not result:
        return jsonify({"success": False, "message": "Failed to add transaction"}), 500

    return jsonify({"success": True, **result}), 200


@khata_bp.route("/ledger/<shop_id>/<customer_id>", methods=["GET"])
def khata_get_ledger(shop_id, customer_id):
    account = firebase_db.get_khata_account(shop_id, customer_id)
    txs = firebase_db.list_khata_transactions(shop_id, customer_id, limit=200)

    if not account:
        return jsonify({"success": False, "message": "No ledger found"}), 404

    return jsonify({
        "success": True,
        "account": account,
        "transactions": txs
    }), 200


@khata_bp.route("/customers/<shop_id>", methods=["GET"])
def khata_list_customers(shop_id):
    accounts = firebase_db.list_khata_customers_for_shop(shop_id)
    return jsonify({
        "success": True,
        "accounts": accounts
    }), 200


@khata_bp.route("/my_accounts/<customer_id>", methods=["GET"])
def khata_list_for_customer(customer_id):
    accounts = firebase_db.list_khata_accounts_for_customer(customer_id)
    return jsonify({
        "success": True,
        "accounts": accounts
    }), 200
