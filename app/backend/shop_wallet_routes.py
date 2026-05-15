import logging
import uuid
from datetime import datetime

from flask import Blueprint, jsonify
from google.cloud import firestore

from firebase_db import db

shop_wallet_bp = Blueprint("shop_wallet", __name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("order_api")


# ============================================================
# 🔹 Helpers
# ============================================================

def get_shop_ref(shop_id):
    return db.collection("shops").document(shop_id)


def get_shop_wallet_balance(shop_doc):
    return float(shop_doc.get("wallet_balance", 0.0))


def shop_transactions_ref():
    return db.collection("shop_wallet_transactions")


# ============================================================
# 🔹 GET WALLET BALANCE (Shop)
# ============================================================
@shop_wallet_bp.route("/shop/wallet/<shop_id>", methods=["GET"])
def shop_wallet_balance(shop_id):
    shop_ref = get_shop_ref(shop_id)
    snap = shop_ref.get()

    if not snap.exists:
        return jsonify({"error": "Shop not found"}), 404

    balance = float(snap.to_dict().get("wallet_balance", 0.0))
    logger.info(f"balance on shop wallet - {balance}")

    return jsonify({
        "balance": balance,
        "success": True
    })


# ============================================================
# 🔹 GET SHOP TRANSACTIONS
# ============================================================
@shop_wallet_bp.route("/shop/wallet/transactions/<shop_id>", methods=["GET"])
def shop_wallet_transactions(shop_id):
    try:
        docs = shop_transactions_ref().where("shopId", "==", shop_id).stream()
        tx_list = []

        for d in docs:
            data = d.to_dict()

            # Safe datetime conversion
            dt = data.get("dateTime")
            if hasattr(dt, "isoformat"):
                data["dateTime"] = dt.isoformat()
            else:
                data["dateTime"] = None

            tx_list.append(data)

        # Safe manual sort
        tx_list.sort(key=lambda x: x["dateTime"] or "", reverse=True)

        return jsonify(tx_list)

    except Exception as e:
        import traceback
        print("\n🔥 ERROR IN shop_wallet_transactions\n", traceback.format_exc())
        return jsonify({"error": str(e)}), 500


# ============================================================
# 🔹 BACKWARD COMPATIBILITY ALIASES (ANDROID USES THESE)
# ============================================================

@shop_wallet_bp.route("/wallet/shop/balance/<shop_id>", methods=["GET"])
def shop_wallet_balance_alias(shop_id):
    return shop_wallet_balance(shop_id)


@shop_wallet_bp.route("/wallet/shop/transactions/<shop_id>", methods=["GET"])
def shop_wallet_transactions_alias(shop_id):
    try:
        return shop_wallet_transactions(shop_id)
    except Exception as e:
        import traceback
        print("\n🔥 ERROR IN TRANSACTION ALIAS ROUTE\n", traceback.format_exc())
        return jsonify({"error": str(e)}), 500


# ============================================================
# 🔹 CREDIT SHOP WALLET (Income)
#     Called when an order is successfully paid
# ============================================================
def add_income_to_shop(shop_id, amount, order_id):
    shop_ref = get_shop_ref(shop_id)
    snap = shop_ref.get()

    if not snap.exists:
        raise Exception("Shop not found")

    shop_data = snap.to_dict()

    # Ensure wallet_balance exists locally too
    if "wallet_balance" not in shop_data:
        shop_ref.update({"wallet_balance": 0.0})
        shop_data["wallet_balance"] = 0.0  # FIX

    # Use legacy id for Android
    legacy_id = shop_data.get("id") or snap.id
    legacy_ref = db.collection("shops").document(legacy_id)

    # Ensure legacy doc exists
    legacy_snap = legacy_ref.get()
    if not legacy_snap.exists:
        legacy_ref.set({"wallet_balance": 0.0}, merge=True)

    # Compute new balance
    current_balance = float(shop_data.get("wallet_balance", 0.0))
    new_balance = current_balance + float(amount)

    # Update both docs
    shop_ref.update({"wallet_balance": new_balance})
    legacy_ref.update({"wallet_balance": new_balance})

    # Write only ONE transaction
    tx_id = str(uuid.uuid4())
    tx = {
        "type": "Order Income",
        "amount": float(amount),
        "dateTime": datetime.utcnow(),
        "orderId": order_id,
        "shopId": legacy_id
    }

    shop_transactions_ref().document(tx_id).set(tx)
    logger.info(f"✅✅ ***** Amount Added to Shop Wallet *****")


# ============================================================
# 🔹 REFUND / PARTIAL REFUND
# ===========================================================


def deduct_shop_refund(shop_id, amount, order_id, is_partial=False):
    shop_ref = get_shop_ref(shop_id)
    refund_type = "Partial Refund" if is_partial else "Refund"

    transaction = db.transaction()

    @firestore.transactional
    def shop_wallet_txn(transaction):
        snap = shop_ref.get(transaction=transaction)
        if not snap.exists:
            raise Exception("Shop not found")

        shop_data = snap.to_dict() or {}
        current_balance = float(shop_data.get("wallet_balance", 0.0))

        if current_balance < amount:
            raise Exception("Insufficient shop wallet balance")

        new_balance = current_balance - amount

        transaction.update(shop_ref, {
            "wallet_balance": new_balance
        })

        tx_id = str(uuid.uuid4())
        shop_transactions_ref().document(tx_id).set({
            "shopId": shop_id,
            "type": refund_type,
            "amount": amount,
            "dateTime": datetime.utcnow(),
            "orderId": order_id
        })

        logger.info(f"💸 SHOP WALLET UPDATED →")

    # ✅ THIS IS THE CORRECT WAY TO EXECUTE
    shop_wallet_txn(transaction)
