import base64
import datetime
import json
import logging
import os
import time
import uuid
from datetime import datetime, timedelta, timezone

import firebase_admin
from firebase_admin import credentials, firestore, storage as fb_storage, messaging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("order_api")
# ---------------------------------------------------------------------
# 🔹 Firebase Initialization
# ---------------------------------------------------------------------
if not firebase_admin._apps:
    cred_path = "/secrets/FIREBASE_CREDENTIALS_JSON"
    cred_env = os.getenv("FIREBASE_CREDENTIALS_JSON")

    try:
        if cred_env and cred_env.strip().startswith("{"):
            cred_dict = json.loads(cred_env)
            cred = credentials.Certificate(cred_dict)
        elif os.path.exists(cred_path):
            cred = credentials.Certificate(cred_path)
        elif os.path.exists("app/backend/firebase.json"):
            cred = credentials.Certificate("app/backend/firebase.json")
        else:
            raise FileNotFoundError("❌ No valid Firebase credentials found")

        firebase_admin.initialize_app(cred, {
            "storageBucket": "grocery-app-invoices"
        })

        logger.info("✅ Firebase initialized successfully")

    except Exception as e:
        raise

db = firestore.client()
bucket = fb_storage.bucket()


# ---------------------------------------------------------------------
# 🔹 USER FUNCTIONS
# ---------------------------------------------------------------------
def get_user_by_credentials(username, password):
    docs = db.collection("users").where("username", "==", username).where("password", "==",
                                                                          password).stream()
    for doc in docs:
        return doc.to_dict()
    return None


def get_user_by_username(username: str):
    query = db.collection("users").where("username", "==", username).limit(1).stream()
    for doc in query:
        user = doc.to_dict()
        user["id"] = doc.id
        return user
    return None


def append_user(user_dict):
    user_id = str(uuid.uuid4())
    user_dict["id"] = user_id
    db.collection("users").document(user_id).set(user_dict)
    return user_dict


def get_user_by_email(email: str):
    query = db.collection("users").where("email", "==", email).limit(1).stream()
    for doc in query:
        user = doc.to_dict()
        user["id"] = doc.id
        return user
    return None


def upload_base64_image(base64_str, folder="images"):
    """Uploads Base64 to GCS and returns a Signed URL (works with Public Access Prevention)."""
    if not base64_str:
        return ""

    # ✅ handle "data:image/jpeg;base64,...."
    if "," in base64_str:
        base64_str = base64_str.split(",")[1]

    image_bytes = base64.b64decode(base64_str)
    filename = f"{folder}/{uuid.uuid4()}.jpg"

    blob = bucket.blob(filename)
    blob.upload_from_string(image_bytes, content_type="image/jpeg")

    # ✅ Signed URL (valid 7 days)
    signed_url = blob.generate_signed_url(
        version="v4",
        expiration=timedelta(days=7),
        method="GET"
    )
    return signed_url


def get_all_shops():
    return [doc.to_dict() for doc in db.collection("shops").stream()]


def append_shop(shop_dict):
    doc_ref = db.collection("shops").add(shop_dict)
    shop_id = doc_ref[1].id
    db.collection("shops").document(shop_id).update({"id": shop_id})
    shop_dict["id"] = shop_id
    return shop_dict


def get_shop_by_shopkeeper(shopkeeper_id):
    docs = db.collection("shops").where("shopkeeper_id", "==", shopkeeper_id).stream()
    for doc in docs:
        return doc.to_dict()
    return None


# ---------------------------------------------------------------------
# 🔹 ITEM FUNCTIONS
# ---------------------------------------------------------------------
def get_items_by_shop(shop_id):
    docs = db.collection("items").where("shopId", "==", str(shop_id)).stream()
    return [doc.to_dict() for doc in docs]


def append_item(item_dict):
    item_id = str(uuid.uuid4())
    item_dict["id"] = item_id
    db.collection("items").document(item_id).set(item_dict)
    return item_dict


# ---------------------------------------------------------------------
# 🔹 ORDER FUNCTIONS
# ---------------------------------------------------------------------
def append_order(order_dict):
    try:
        IST = timezone(timedelta(hours=5, minutes=30))
        order_uuid = str(uuid.uuid4())
        order_dict["order_uuid"] = order_uuid
        order_dict["created_at"] = datetime.now(IST).replace(microsecond=0).isoformat()

        db.collection("orders").add(order_dict)
        logger.info(f"✅ Added order {order_uuid}")
        return order_dict
    except Exception as e:
        logger.info(f"[ERROR] append_order: {e}")
        return None


def get_orders_by_customer(customer_id):
    docs = db.collection("orders").where("customer.id", "==", customer_id).stream()
    return [doc.to_dict() for doc in docs]


def get_orders_by_shop(shop_id):
    docs = db.collection("orders").where("shopId", "==", shop_id).stream()
    return [doc.to_dict() for doc in docs]


def get_order_by_uuid(order_uuid: str):
    try:
        orders_ref = db.collection("orders")

        # 1️⃣ Try Firestore document ID directly
        doc = orders_ref.document(order_uuid).get()
        if doc.exists:
            data = doc.to_dict()
            data["doc_id"] = doc.id  # <-- Firestore ID
            return data

        # 2️⃣ Try orderId field
        query = orders_ref.where("orderId", "==", order_uuid).limit(1).stream()
        for found in query:
            data = found.to_dict()
            data["doc_id"] = found.id  # <-- Firestore ID
            return data

        # 3️⃣ Try order_uuid field (your app's uuid)
        query = orders_ref.where("order_uuid", "==", order_uuid).limit(1).stream()
        for found in query:
            data = found.to_dict()
            data["doc_id"] = found.id  # <-- Firestore ID
            return data

        # 4️⃣ Try id field
        query = orders_ref.where("id", "==", order_uuid).limit(1).stream()
        for found in query:
            data = found.to_dict()
            data["doc_id"] = found.id  # <-- Firestore ID
            return data

        logger.info(f"❌ Order not found with ANY lookup: {order_uuid}")
        return None

    except Exception as e:
        logger.info("[ERROR] get_order_by_uuid: {e}")
        return None


def update_order_status(order_uuid: str, new_status: str, extra_fields: dict = None):
    try:
        orders_ref = db.collection("orders")

        # 1️⃣ Direct Firestore document ID
        doc_ref = orders_ref.document(order_uuid)
        doc = doc_ref.get()

        # 2️⃣ orderId fallback
        if not doc.exists:
            query = orders_ref.where("orderId", "==", order_uuid).limit(1).stream()
            for found in query:
                doc_ref = orders_ref.document(found.id)
                doc = found
                break

        # 3️⃣ order_uuid fallback
        if not doc.exists:
            query = orders_ref.where("order_uuid", "==", order_uuid).limit(1).stream()
            for found in query:
                doc_ref = orders_ref.document(found.id)
                doc = found
                break

        # 4️⃣ id fallback
        if not doc.exists:
            query = orders_ref.where("id", "==", order_uuid).limit(1).stream()
            for found in query:
                doc_ref = orders_ref.document(found.id)
                doc = found
                break

        # 🔥 No document found
        if not doc.exists:
            logger.info(f"❌ Order not found anywhere: {order_uuid}")
            return False

        # 📝 Prepare update payload
        update_data = {"status": new_status}
        if extra_fields:
            update_data.update(extra_fields)

        # ✅ Update Firestore order
        doc_ref.update(update_data)
        logger.info(f"✅ Order updated in Firestore ({doc_ref.id}) → {new_status}")
        return True

    except Exception as e:
        logger.info(f"[ERROR] update_order_status: {e}")
        return False


def upload_invoice_to_storage(order_id, pdf_buffer, customer_id=None):
    try:
        blob_path = f"invoices/{customer_id}/{order_id}.pdf" if customer_id else f"invoices/{order_id}.pdf"
        blob = bucket.blob(blob_path)

        blob.upload_from_file(pdf_buffer, content_type="application/pdf")

        # 🔥 Generate signed URL instead of blob.make_public()
        url = blob.generate_signed_url(
            version="v4",
            expiration=timedelta(days=7),  # link valid for 7 days
            method="GET"
        )

        logger.info(f"✅ Uploaded invoice & generated signed URL: {url}")
        return url

    except Exception as e:
        logger.error(f"[ERROR] upload_invoice_to_storage: {e}")
        return None


def save_fcm_token_for_user(user_id: str, token: str, role: str) -> bool:
    try:
        if not user_id or not token:
            logger.warning("⚠️ save_fcm_token_for_user: Missing user_id or token")
            return False

        users_ref = db.collection("users")

        # ------------------------------------------------------
        # PRIMARY MATCH (customerId / shopkeeperId)
        # ------------------------------------------------------
        role_field = "customerId" if role == "customer" else "shopkeeperId"
        query = users_ref.where(role_field, "==", user_id).limit(1).stream()

        user_doc_id = None
        for doc in query:
            user_doc_id = doc.id
            break

        # ------------------------------------------------------
        # FALLBACK MATCH (id = Firestore user.id)
        # ------------------------------------------------------
        if not user_doc_id:
            logger.warning(f"⚠️ No match on {role_field}. Trying fallback id={user_id}")
            fallback_query = users_ref.where("id", "==", user_id).limit(1).stream()
            for doc in fallback_query:
                user_doc_id = doc.id
                break

        if not user_doc_id:
            logger.error(f"❌ FCM SAVE FAILED: No user found with id={user_id}, role={role}")
            return False

        # ------------------------------------------------------
        # SAVE TOKEN
        # ------------------------------------------------------
        user_ref = users_ref.document(user_doc_id)
        data = user_ref.get().to_dict() or {}

        user_ref.update({"fcm_tokens": [token]})

        return True

    except Exception as e:
        logger.error(f"[ERROR] save_fcm_token_for_user: {e}")
        return False


def get_fcm_tokens_for_user(user_id: str):
    """Fetches FCM tokens for a user. Supports customerId, shopkeeperId, and fallback to id."""
    try:
        users_ref = db.collection("users")
        tokens = []

        search_fields = ["customerId", "shopkeeperId", "id"]

        for field in search_fields:

            query = users_ref.where(field, "==", user_id).limit(1).stream()

            for doc in query:
                user_data = doc.to_dict()
                tokens = user_data.get("fcm_tokens", [])
                if tokens:
                    return tokens

        logger.warning(f"⚠️ FCM: No tokens found for user {user_id}")
        return []

    except Exception as e:
        logger.error(f"[ERROR] get_fcm_tokens_for_user: {e}")
        return []


def remove_fcm_token_for_user(user_id: str, token: str):
    try:
        users_ref = db.collection("users")
        query = users_ref.where("id", "==", user_id).limit(1).stream()
        for doc in query:
            ref = users_ref.document(doc.id)
            data = ref.get().to_dict() or {}
            tokens = set(data.get("fcm_tokens", []))
            if token in tokens:
                tokens.remove(token)
                ref.update({"fcm_tokens": list(tokens)})
                logger.info(f"🗑️ Removed invalid token for {user_id}")
                break
    except Exception as e:
        logger.info(f"[ERROR] remove_fcm_token_for_user: {e}")


def send_fcm_notification_to_tokens(tokens, title, body, user_id=None, data_payload=None):
    """
    Sends FCM notifications to a list of tokens.
    Uses Firebase Admin SDK v1 (individual send).

    Automatically removes invalid tokens if "Requested entity was not found".
    Returns a summary: {"success": int, "failure": int}
    """
    if not tokens:
        logger.warning("⚠️ FCM: No tokens to send notification")
        return {"success": 0, "failure": 0}

    results = {"success": 0, "failure": 0}

    for token in tokens:
        try:
            message = messaging.Message(
                notification=messaging.Notification(title=title, body=body),
                token=token,
                data=data_payload or {}
            )

            response = messaging.send(message)
            logger.info(f"📩 FCM sent")
            results["success"] += 1

        except Exception as e:
            # ✅ Everything related to 'e' must be inside this block
            logger.error(f"[ERROR] FCM send failed → error={e}")
            results["failure"] += 1

            if user_id and "Requested entity was not found" in str(e):
                remove_fcm_token_for_user(user_id, token)
                logger.info(f"🗑️ Removed invalid FCM token for user_id={user_id}")

    return results


def get_user_firestore_ref(customerId):
    """Resolve Firestore user doc using either doc ID OR customerId field."""
    # try doc_id first
    user_ref = db.collection("users").document(customerId)
    snap = user_ref.get()

    if snap.exists:
        return user_ref, snap

    # fallback by customerId
    fallback = (
        db.collection("users")
        .where("customerId", "==", customerId)
        .limit(1)
        .stream()
    )
    for found in fallback:
        return found.reference, found

    return None, None


# -----------------------------
# Helper: Get shop document
# -----------------------------
# -----------------------------
# GET SHOP
# -----------------------------
def get_shop(shop_id):
    doc = db.collection("shops").document(shop_id).get()
    return doc.to_dict() if doc.exists else None


# -----------------------------
# CREATE OR GET KHATA ACCOUNT
# -----------------------------
def get_or_create_khata_account(shop_id, customer_id, name=None, phone=None):
    doc_id = f"{shop_id}_{customer_id}"
    ref = db.collection("khata_accounts").document(doc_id)
    snap = ref.get()

    # Already exists → ensure shop_name is present
    if snap.exists:
        data = snap.to_dict()
        data["doc_id"] = doc_id

        # FIX: if shop_name missing, set & update it
        if not data.get("shop_name"):
            shop = get_shop(shop_id)
            shop_name = shop.get("name") if shop else "Unknown"
            data["shop_name"] = shop_name
            ref.update({"shop_name": shop_name})

        return data

    # Create new account
    shop = get_shop(shop_id)
    shop_name = shop.get("name") if shop else "Unknown"

    IST = timezone(timedelta(hours=5, minutes=30))
    time_data = datetime.now(IST).replace(microsecond=0).isoformat()

    data = {
        "doc_id": doc_id,
        "shop_id": shop_id,
        "customer_id": customer_id,
        "customer_name": name or "",
        "phone": phone or "",
        "balance": 0.0,
        "shop_name": shop_name,
        "updated_at": time_data
    }

    ref.set(data)
    return data


# -----------------------------
# ADD TRANSACTION
# -----------------------------
def add_khata_transaction(shop_id, customer_id, amount, tx_type, note="", order_id=None):
    doc_id = f"{shop_id}_{customer_id}"
    ref = db.collection("khata_accounts").document(doc_id)
    acc = ref.get().to_dict()

    if not acc:
        return None

    old_balance = float(acc.get("balance", 0.0))

    # Balance logic
    if tx_type == "debit":
        new_balance = old_balance + amount
    elif tx_type == "credit":
        new_balance = old_balance - amount
    else:
        new_balance = old_balance

    # Exact timestamp (epoch ms)
    ts_ms = int(time.time() * 1000)
    tx_id = f"tx_{ts_ms}"

    tx_data = {
        "tx_id": tx_id,
        "shop_id": shop_id,
        "customer_id": customer_id,
        "type": tx_type,
        "amount": float(amount),
        "note": note,
        "order_id": order_id,
        "created_at": str(ts_ms)
    }

    # Save transaction
    db.collection("khata_transactions").document(tx_id).set(tx_data)

    # FIX: Ensure shop_name always updated (never missing again)
    shop = get_shop(shop_id)
    shop_name = acc.get("shop_name") or (shop.get("name") if shop else "Unknown")

    ref.update({
        "balance": float(new_balance),
        "updated_at": datetime.utcnow(),
        "shop_name": shop_name
    })

    return {
        "transaction": tx_data,
        "balance": new_balance
    }


# -----------------------------
# GET KHATA ACCOUNT
# -----------------------------
def get_khata_account(shop_id, customer_id):
    doc_id = f"{shop_id}_{customer_id}"
    snap = db.collection("khata_accounts").document(doc_id).get()
    if not snap.exists:
        return None
    data = snap.to_dict()
    data["doc_id"] = doc_id
    return data


def list_khata_transactions(shop_id, customer_id, limit=200):
    snap = (
        db.collection("khata_transactions")
        .where("shop_id", "==", shop_id)
        .where("customer_id", "==", customer_id)
        .order_by("created_at", direction=firestore.Query.DESCENDING)
        .limit(limit)
        .get()
    )

    tx_list = []

    for doc in snap:
        data = doc.to_dict()
        ts = data.get("created_at")

        # ⬇ KEEP your timestamp cleanup code exactly as is ⬇
        # (DO NOT CHANGE ANYTHING ELSE)
        epoch_ms = None

        if isinstance(ts, str) and ts.isdigit():
            epoch_ms = int(ts)
        elif isinstance(ts, datetime):
            epoch_ms = int(ts.timestamp() * 1000)
        elif isinstance(ts, (float, int)):
            epoch_ms = int(float(ts) * 1000)
        elif isinstance(ts, str) and "," in ts:
            try:
                dt = datetime.strptime(ts, "%a, %d %b %Y %H:%M:%S %Z")
                epoch_ms = int(dt.timestamp() * 1000)
            except:
                epoch_ms = None

        if not epoch_ms:
            try:
                epoch_ms = int(data["tx_id"].replace("tx_", ""))
            except:
                epoch_ms = int(time.time() * 1000)

        data["created_at"] = str(epoch_ms)

        tx_list.append(data)

    return tx_list


def list_khata_customers_for_shop(shop_id):
    snap = db.collection("khata_accounts").where("shop_id", "==", shop_id).get()
    return [doc.to_dict() for doc in snap]


# -----------------------------
# LIST KHATA FOR CUSTOMER
# -----------------------------
def list_khata_accounts_for_customer(customer_id):
    snap = db.collection("khata_accounts").where("customer_id", "==", customer_id).get()
    return [doc.to_dict() for doc in snap]


def credit_customer_wallet_only(customer_id, amount, order_uuid):
    """
    Credit customer wallet WITHOUT debiting shop wallet.
    Used ONLY for Razorpay refunds (ledger consistency).
    """

    if not customer_id or amount <= 0:
        return False

    try:
        customer_ref = db.collection("customers").document(customer_id)

        db.run_transaction(lambda tx: _credit_wallet_tx(
            tx, customer_ref, amount, order_uuid
        ))

        return True

    except Exception:
        logger.exception("❌ Customer wallet credit failed")
        return False


def _credit_wallet_tx(tx, customer_ref, amount, order_uuid):
    snap = customer_ref.get(transaction=tx)
    current_balance = snap.get("wallet_balance", 0)

    tx.update(customer_ref, {
        "wallet_balance": current_balance + amount,
        "wallet_last_updated": firestore.SERVER_TIMESTAMP
    })

    # Optional ledger entry
    customer_ref.collection("wallet_orders").add({
        "type": "CREDIT",
        "amount": amount,
        "reason": "Razorpay refund",
        "order_uuid": order_uuid,
        "created_at": firestore.SERVER_TIMESTAMP
    })


# ---------------------------------------------------------------------
# 🔹 RATING FUNCTIONS
# ---------------------------------------------------------------------
def add_shop_rating(rating_data: dict):
    try:
        order_id = rating_data.get("order_id")
        customer_id = rating_data.get("customer_id")

        if not order_id or not customer_id:
            return False, "Missing order_id or customer_id"

        # ⭐ NEW: safely read customer_name
        customer_name = rating_data.get("customer_name", "Customer")

        # 🔐 Prevent duplicate rating
        existing = (
            db.collection("ratings")
            .where("order_id", "==", order_id)
            .where("customer_id", "==", customer_id)
            .limit(1)
            .stream()
        )

        for _ in existing:
            return False, "Rating already submitted"

        IST = timezone(timedelta(hours=5, minutes=30))
        rating_data["created_at"] = datetime.now(IST).replace(microsecond=0).isoformat()

        # ⭐ ENSURE customer_name IS SAVED
        rating_data["customer_name"] = customer_name

        db.collection("ratings").add(rating_data)

        logger.info(f"⭐ Rating saved")

        return True, "Rating saved"

    except Exception as e:
        logger.error(f"[ERROR] add_shop_rating: {e}")
        return False, str(e)


def get_shop_rating_analytics(shop_id: str):
    """
    Returns emoji analytics + average rating for a shop.
    """

    try:
        ratings = (
            db.collection("ratings")
            .where("shop_id", "==", shop_id)
            .stream()
        )

        total = 0
        rating_sum = 0

        emoji_counts = {
            "😡": 0,
            "😐": 0,
            "🙂": 0,
            "😍": 0
        }

        for r in ratings:
            data = r.to_dict()
            total += 1
            rating_sum += int(data.get("rating", 0))
            emoji = data.get("emoji")
            if emoji in emoji_counts:
                emoji_counts[emoji] += 1

        if total == 0:
            return {
                "shop_id": shop_id,
                "total_ratings": 0,
                "average_rating": 0,
                "emoji_breakdown": emoji_counts
            }

        return {
            "shop_id": shop_id,
            "total_ratings": total,
            "average_rating": round(rating_sum / total, 2),
            "emoji_breakdown": emoji_counts
        }

    except Exception as e:
        logger.error(f"[ERROR] get_shop_rating_analytics: {e}")
        return None


def get_shop_reviews_by_emoji(shop_id, emoji, limit=20, last_created_at=None):
    query = (
        db.collection("ratings")
        .where("shop_id", "==", shop_id)
        .where("emoji", "==", emoji)
        .order_by("created_at", direction=firestore.Query.DESCENDING)
        .limit(limit)
    )

    if last_created_at:
        query = query.start_after({"created_at": last_created_at})

    return [r.to_dict() for r in query.stream()]


def log_transaction(user_id, shop_id, amount, tx_type, description, source="wallet", order_id=None):
    """
    Logs a transaction in SAME FORMAT used by wallet/transactions API
    so that it appears in Flutter wallet history.
    """
    IST = timezone(timedelta(hours=5, minutes=30))
    created_at = datetime.now(IST).replace(microsecond=0).isoformat()
    try:
        tx_id = str(uuid.uuid4())

        # ✅ Map Credit into Refund type (because your UI expects Refund)
        txn_type = "Refund" if tx_type.lower() == "credit" else "Payment"

        transaction_data = {
            "userId": user_id,
            "type": txn_type,
            "amount": float(amount),
            "orderId": order_id,
            "dateTime": created_at,
            "payment_type": source if source else "Wallet",
            "shopId": shop_id
        }

        db.collection("transactions").document(tx_id).set(transaction_data)

        return True

    except Exception as e:
        logger.error(f"🔥 Error logging transaction: {e}")
        return False


def credit_customer_wallet(customer_id, amount, reference=""):
    user_ref = db.collection("users").document(customer_id)
    user_data = user_ref.get().to_dict() or {}
    bal = float(user_data.get("wallet_balance", 0))
    user_ref.update({"wallet_balance": bal + float(amount)})

    logger.info(f"Credited to Customer Wallet")
