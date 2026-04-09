import datetime
import logging
import uuid

import razorpay
from firebase_admin import firestore
from flask import Blueprint, request, jsonify

import firebase_db

# logging.basicConfig(level=logging.INFO)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("order_api")

khata_bp = Blueprint("khata_bp", __name__)

RAZORPAY_KEY_ID = "rzp_test_RKK3DuGSaxK9fR"       # todo: Need to Change with live api Id
RAZORPAY_KEY_SECRET = "VgVc96Pdn3t5T8ieX0nb2ajt"  # todo: Need to Change with live api Key

razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))


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
    logger.info(f"🔥 PAY_KHATA_FROM_WALLET RECEIVED → {data}")

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
        logger.info(f"Wallet deducted.")
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
            "userId": customer_id,  # <-- FIXED HERE
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


# ---------------------#-----------#------
@khata_bp.route("/cash_payment_request", methods=["POST"])
def cash_payment_request():
    data = request.json or {}

    shop_id = data.get("shop_id")
    customer_id = data.get("customer_id")
    amount = float(data.get("amount", 0))

    if not shop_id or not customer_id or amount <= 0:
        return jsonify({"success": False, "message": "Invalid data"}), 400

    # 1️⃣ Create a new cash payment request document
    request_id = str(uuid.uuid4())

    firebase_db.db.collection("cash_payments").document(request_id).set({
        "request_id": request_id,
        "shop_id": shop_id,
        "customer_id": customer_id,
        "amount": amount,
        "status": "pending",
        "timestamp": datetime.datetime.utcnow()
    })

    # 2️⃣ FIND THE CUSTOMER'S KHATA ACCOUNT
    acc_ref = (
        firebase_db.db.collection("khata_accounts")
        .where("shop_id", "==", shop_id)
        .where("customer_id", "==", customer_id)
        .limit(1)
    )

    docs = acc_ref.stream()
    acc_doc = next(docs, None)

    if acc_doc is None:
        return jsonify({"success": False, "message": "Khata account not found"}), 404

    # 3️⃣ UPDATE KHATA ACCOUNT with PENDING DETAILS
    acc_doc.reference.update({
        "pending_cash": amount,
        "pending_status": "pending",
        "pending_request_id": request_id,
        "updated_at": datetime.datetime.utcnow().isoformat()
    })

    return jsonify({
        "success": True,
        "message": "Cash payment request submitted",
        "request_id": request_id
    })


@khata_bp.route("/cash_status/<customerId>/<shopId>", methods=["GET"])
def get_cash_status(customerId, shopId):
    try:
        query = (
            firebase_db.db.collection("cash_payments")
            .where("customer_id", "==", customerId)
            .where("shop_id", "==", shopId)
            .order_by("timestamp", direction=firestore.Query.DESCENDING)
            .limit(1)
        )

        docs = query.stream()
        doc = next(docs, None)

        if doc is None:
            return jsonify({
                "success": True,
                "status": "none",
                "message": "No pending cash payments"
            }), 200

        data = doc.to_dict()

        return jsonify({
            "success": True,
            "status": data.get("status"),
            "amount": data.get("amount"),
            "request_id": data.get("request_id")
        }), 200

    except Exception as e:
        print("🔥 CASH STATUS ERROR:", e)
        return jsonify({"success": False, "message": "Server error"}), 500


@khata_bp.route("/cash_payment_update", methods=["POST"])
def update_cash_payment_status():
    data = request.json or {}

    request_id = data.get("request_id")
    status = data.get("status")  # approved / rejected

    if not request_id or status not in ["approved", "rejected"]:
        return jsonify({"success": False, "message": "Invalid data"}), 400

    try:
        doc_ref = firebase_db.db.collection("cash_payments").document(request_id)
        doc = doc_ref.get()

        if not doc.exists:
            return jsonify({"success": False, "message": "Request not found"}), 404

        pay_data = doc.to_dict()

        # Update status
        doc_ref.update({"status": status})

        if status == "approved":
            # Add khata transaction
            firebase_db.add_khata_transaction(
                shop_id=pay_data["shop_id"],
                customer_id=pay_data["customer_id"],
                amount=pay_data["amount"],
                tx_type="credit",
                note="Cash Payment Approved",
                order_id=None
            )

        return jsonify({"success": True, "status": status}), 200

    except Exception as e:
        print("🔥 CASH UPDATE ERROR:", e)
        return jsonify({"success": False, "message": "Server error"}), 500


@khata_bp.route("/approve_cash_payment", methods=["POST"])
def approve_cash_payment():
    data = request.json or {}

    shop_id = data.get("shop_id")
    customer_id = data.get("customer_id")

    if not shop_id or not customer_id:
        return jsonify({"success": False, "message": "Invalid data"}), 400

    # Get khata account
    acc_ref = (
        firebase_db.db.collection("khata_accounts")
        .where("shop_id", "==", shop_id)
        .where("customer_id", "==", customer_id)
        .limit(1)
    )

    docs = acc_ref.stream()
    acc_doc = next(docs, None)

    if not acc_doc:
        return jsonify({"success": False, "message": "Account not found"}), 404

    acc = acc_doc.to_dict()
    pending_amount = acc.get("pending_cash")

    if not pending_amount or pending_amount <= 0:
        return jsonify({"success": False, "message": "No pending request"}), 400

    # APPROVE — Add khata CREDIT entry
    firebase_db.add_khata_transaction(
        shop_id=shop_id,
        customer_id=customer_id,
        amount=pending_amount,
        tx_type="credit",
        note="Cash payment approved",
        order_id=None
    )

    # Update khata account
    acc_doc.reference.update({
        "balance": acc.get("balance", 0) - pending_amount,
        "pending_cash": None,
        "pending_status": None,
        "pending_request_id": None,
        "updated_at": datetime.datetime.utcnow().isoformat()
    })

    return jsonify({
        "success": True,
        "message": "Cash payment approved",
        "amount": pending_amount
    })


@khata_bp.route("/reject_cash_payment", methods=["POST"])
def reject_cash_payment():
    data = request.json or {}

    shop_id = data.get("shop_id")
    customer_id = data.get("customer_id")

    if not shop_id or not customer_id:
        return jsonify({"success": False, "message": "Invalid data"}), 400

    acc_ref = (
        firebase_db.db.collection("khata_accounts")
        .where("shop_id", "==", shop_id)
        .where("customer_id", "==", customer_id)
        .limit(1)
    )

    docs = acc_ref.stream()
    acc_doc = next(docs, None)

    if not acc_doc:
        return jsonify({"success": False, "message": "Account not found"}), 404

    acc = acc_doc.to_dict()
    pending_amount = acc.get("pending_cash") or 0.0

    # 1️⃣ Add REJECTED transaction entry (DOES NOT affect balance)
    firebase_db.add_khata_transaction(
        shop_id=shop_id,
        customer_id=customer_id,
        amount=pending_amount,
        tx_type="reject",
        note="Cash payment rejected",
        order_id=None
    )

    # 2️⃣ Update khata account fields
    acc_doc.reference.update({
        "pending_cash": None,
        "pending_status": "rejected",
        "pending_request_id": None,
        "updated_at": datetime.datetime.utcnow().isoformat()
    })

    return jsonify({
        "success": True,
        "message": "Cash payment rejected",
        "amount": pending_amount
    })


@khata_bp.route("/create_razorpay_order", methods=["POST"])
def create_khata_razorpay_order():
    data = request.json or {}
    customer_id = data.get("customer_id")
    shop_id = data.get("shop_id")
    amount = float(data.get("amount", 0))

    if not customer_id or not shop_id or amount <= 0:
        logger.info(f" Customer-ID {customer_id}  and Shop Id {shop_id}")
        return {"success": False, "message": "Invalid data"}, 400

    backend_order_id = str(uuid.uuid4())

    try:
        # Create Razorpay Order
        razorpay_order = razorpay_client.order.create({
            "amount": int(amount * 100),
            "currency": "INR",
            "receipt": backend_order_id,
            "payment_capture": 1
        })

        razorpay_order_id = razorpay_order["id"]

        # Save to Firestore
        firebase_db.db.collection("khata_pay_orders").document(backend_order_id).set({
            "backend_order_id": backend_order_id,
            "razorpay_order_id": razorpay_order_id,
            "customer_id": customer_id,
            "shop_id": shop_id,
            "amount": amount,
            "status": "pending",
            "timestamp": datetime.datetime.utcnow()
        })
        logger.info(f"✅ Wallet Payment Order Created Successfully")

        return {
            "success": True,
            "backend_order_id": backend_order_id,
            "razorpay_order_id": razorpay_order_id
        }

    except Exception as e:
        print("🔥 ERROR create_khata_razorpay_order:", e)
        return {"success": False, "message": "Failed to create Razorpay order"}, 500


@khata_bp.route("/verify_razorpay_payment", methods=["POST"])
def verify_khata_razorpay_payment():
    data = request.json or {}

    backend_order_id = data.get("backend_order_id")
    razorpay_order_id = data.get("order_id")
    razorpay_payment_id = data.get("payment_id")
    razorpay_signature = data.get("signature")

    if not backend_order_id or not razorpay_order_id or not razorpay_payment_id or not razorpay_signature:
        return {"success": False, "message": "Missing verification data"}, 400

    try:
        # ---------------------------
        # 1️⃣ VERIFY SIGNATURE SAFELY
        # ---------------------------
        razorpay_client.utility.verify_payment_signature({
            "razorpay_order_id": razorpay_order_id,
            "razorpay_payment_id": razorpay_payment_id,
            "razorpay_signature": razorpay_signature
        })
        logger.info(f"✅ Verify-Razorpay-Payment Successful")

    except Exception as e:
        print("🔥 Razorpay Verification Failed:", e)
        return {"success": False, "message": "Invalid signature"}, 400

    # ---------------------------
    # 2️⃣ Fetch backend order
    # ---------------------------
    doc = firebase_db.db.collection("khata_pay_orders").document(backend_order_id).get()
    logger.info(f"✅ khata_pay_orders Added to Firebase")
    if not doc.exists:
        return {"success": False, "message": "Order not found"}, 404

    pay = doc.to_dict()

    # ---------------------------
    # 3️⃣ Add Khata CREDIT transaction
    # ---------------------------
    try:
        firebase_db.add_khata_transaction(
            shop_id=pay["shop_id"],
            customer_id=pay["customer_id"],
            amount=pay["amount"],
            tx_type="credit",
            note="Khata Payment via Razorpay"
        )

        # Update status in DB
        doc.reference.update({
            "status": "success",
            "razorpay_payment_id": razorpay_payment_id,
            "updated_at": datetime.datetime.utcnow()
        })

        logger.info(f"✅ khata_pay_orders Transactions Added to Firebase")
        return {"success": True, "message": "Khata payment verified"}

    except Exception as e:
        print("🔥 Failed to save khata credit:", e)
        return {"success": False, "message": "Transaction error"}, 500
