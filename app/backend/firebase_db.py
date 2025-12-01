import base64
import datetime
import firebase_admin
import json
import logging
import os
import uuid
from firebase_admin import credentials, firestore, storage as fb_storage, messaging
from datetime import datetime, timedelta, timezone
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
            logger.info("🔹 Using FIREBASE_CREDENTIALS_JSON from environment variable (JSON string)")
            cred_dict = json.loads(cred_env)
            cred = credentials.Certificate(cred_dict)
        elif os.path.exists(cred_path):
            logger.info(f"🔹 Using FIREBASE_CREDENTIALS_JSON secret file at {cred_path}")
            cred = credentials.Certificate(cred_path)
        elif os.path.exists("app/backend/firebase.json"):
            logger.info("🔹 Using local firebase.json file for development")
            cred = credentials.Certificate("app/backend/firebase.json")
        else:
            raise FileNotFoundError("❌ No valid Firebase credentials found")

        # ✅ Must include .appspot.com suffix
        firebase_admin.initialize_app(cred, {
            "storageBucket": "grocery-app-invoices"
        })

        logger.info("✅ Firebase initialized successfully")

    except Exception as e:
        logger.info(f"🔥 Firebase init failed: {e}")
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
    """Uploads a Base64 image string to Firebase Storage and returns public URL."""
    if not base64_str:
        return ""
    image_bytes = base64.b64decode(base64_str)
    filename = f"{folder}/{uuid.uuid4()}.jpg"
    blob = bucket.blob(filename)
    blob.upload_from_string(image_bytes, content_type="image/jpeg")
    blob.make_public()
    return blob.public_url


# ---------------------------------------------------------------------
# 🔹 SHOP FUNCTIONS
# ---------------------------------------------------------------------
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
        order_dict["created_at"] = datetime.now(IST).replace(microsecond=0).isoformat(),

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


# def upload_invoice_to_storage(order_id, pdf_buffer, customer_id=None):
#     try:
#         blob_path = f"invoices/{customer_id}/{order_id}.pdf" if customer_id else f"invoices/{order_id}.pdf"
#         blob = bucket.blob(blob_path)
#         blob.upload_from_file(pdf_buffer, content_type="application/pdf")
#         #blob.make_public()
#         url = blob.public_url
#         logger.info(f"✅ Uploaded invoice: {url}")
#         return url
#     except Exception as e:
#         logger.info(f"[ERROR] upload_invoice_to_storage: {e}")
#         return None


def upload_invoice_to_storage(order_id, pdf_buffer, customer_id=None):
    try:
        blob_path = f"invoices/{customer_id}/{order_id}.pdf" if customer_id else f"invoices/{order_id}.pdf"
        blob = bucket.blob(blob_path)

        blob.upload_from_file(pdf_buffer, content_type="application/pdf")

        # 🔥 Generate signed URL instead of blob.make_public()
        url = blob.generate_signed_url(
            version="v4",
            expiration=datetime.timedelta(days=7),  # link valid for 7 days
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

        # tokens = set(data.get("fcm_tokens", []))
        # tokens.add(token)

        # user_ref.update({"fcm_tokens": list(tokens)})
        user_ref.update({"fcm_tokens": [token]})
        # logger.info(
        #     f"✅ FCM token saved for user_id={user_id}, doc={user_doc_id}, "
        #     f"total_tokens={len(tokens)}"
        # )

        logger.info(
            f"✅ FCM token replaced for user_id={user_id}, doc={user_doc_id}, token={token[:15]}..."
        )
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
            logger.info(f"🔵 FCM: Searching user tokens where {field} == {user_id}")

            query = users_ref.where(field, "==", user_id).limit(1).stream()

            for doc in query:
                user_data = doc.to_dict()
                tokens = user_data.get("fcm_tokens", [])
                if tokens:
                    logger.info(f"🟢 FCM: Found {len(tokens)} tokens via {field}={user_id}")
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
            logger.info(f"📩 FCM sent → token={token[:15]}... response={response}")
            results["success"] += 1

        except Exception as e:
            # ✅ Everything related to 'e' must be inside this block
            logger.error(f"[ERROR] FCM send failed → token={token[:15]}... error={e}")
            results["failure"] += 1

            if user_id and "Requested entity was not found" in str(e):
                remove_fcm_token_for_user(user_id, token)
                logger.info(f"🗑️ Removed invalid FCM token for user_id={user_id}")

    logger.info(f"📲 FCM Summary: {results['success']} success | {results['failure']} failed")
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


# ================================
#  KHATA / LEDGER HELPERS
# ================================

# khata_accounts: doc_id = f"{shop_id}_{customer_id}"
KHATA_ACCOUNTS = "khata_accounts"
KHATA_TX = "khata_transactions"


def get_khata_account_doc_id(shop_id: str, customer_id: str) -> str:
    return f"{shop_id}_{customer_id}"


def get_or_create_khata_account(shop_id: str, customer_id: str,
                                customer_name: str = None,
                                phone: str = None) -> dict:
    """
    Get or create a khata account row in khata_accounts.
    """
    try:
        doc_id = get_khata_account_doc_id(shop_id, customer_id)
        doc_ref = db.collection(KHATA_ACCOUNTS).document(doc_id)
        snap = doc_ref.get()
        IST = timezone(timedelta(hours=5, minutes=30))
        if not snap.exists:
            payload = {
                "shop_id": shop_id,
                "customer_id": customer_id,
                "customer_name": customer_name or "",
                "phone": phone or "",
                "balance": 0.0,
                "updated_at": datetime.now(IST).replace(microsecond=0).isoformat()
            }
            doc_ref.set(payload)
            return {"doc_id": doc_id, **payload}

        data = snap.to_dict()
        data["doc_id"] = doc_id
        return data

    except Exception as e:
        logger.info(f"[ERROR] get_or_create_khata_account: {e}")
        return None


def update_khata_balance(shop_id: str, customer_id: str, delta: float) -> dict | None:
    """
    Add delta to current balance. Positive delta = customer owes more (debit).
    Negative delta = customer paid (credit).
    """
    try:
        doc_id = get_khata_account_doc_id(shop_id, customer_id)
        doc_ref = db.collection(KHATA_ACCOUNTS).document(doc_id)

        snap = doc_ref.get()
        if not snap.exists:
            logger.info(f"⚠ No khata account found, creating new for {shop_id}/{customer_id}")
            account = get_or_create_khata_account(shop_id, customer_id)
            if not account:
                return None
            balance = float(account.get("balance", 0.0))
        else:
            data = snap.to_dict()
            balance = float(data.get("balance", 0.0))

        new_balance = balance + float(delta)
        if new_balance < 0:
            new_balance = 0  # Prevent negative balance

        IST = timezone(timedelta(hours=5, minutes=30))
        update_data = {
            "balance": new_balance,
            "updated_at": datetime.now(IST).replace(microsecond=0).isoformat()
        }
        doc_ref.update(update_data)

        updated = doc_ref.get().to_dict()
        updated["doc_id"] = doc_id
        return updated

    except Exception as e:
        logger.info(f"[ERROR] update_khata_balance: {e}")
        return None


def add_khata_transaction(shop_id: str,
                          customer_id: str,
                          amount: float,
                          tx_type: str,
                          note: str = "",
                          order_id: str | None = None) -> dict | None:
    """
    Add an entry to khata_transactions and update balance.
    tx_type: "debit" or "credit" or "adjustment" etc.
    debit  = customer owes more  (delta = +amount)
    credit = customer pays back  (delta = -amount)
    """
    try:
        amount = float(amount)
        if amount <= 0:
            logger.info("⚠ add_khata_transaction: amount <= 0, ignoring")
            return None

        tx_id = str(uuid.uuid4())
        IST = timezone(timedelta(hours=5, minutes=30))
        created_at = datetime.now(IST).replace(microsecond=0).isoformat()

        # 1) Create / ensure account
        account = get_or_create_khata_account(shop_id, customer_id)
        if not account:
            return None

        # 2) Compute delta for balance
        tx_type_lower = tx_type.lower()
        if tx_type_lower == "debit":
            delta = amount      # customer owes more
        elif tx_type_lower == "credit":
            delta = -amount     # customer pays back
        else:
            delta = 0.0         # adjustment won't change balance here

        # 3) Update balance
        updated_account = update_khata_balance(shop_id, customer_id, delta)

        # 4) Add transaction row
        tx_doc = {
            "shop_id": shop_id,
            "customer_id": customer_id,
            "tx_id": tx_id,
            "type": tx_type,
            "amount": amount,
            "note": note or "",
            "order_id": order_id,
            "created_at": created_at
        }
        db.collection(KHATA_TX).document(tx_id).set(tx_doc)

        # Merge account & tx for response
        return {
            "transaction": tx_doc,
            "account": updated_account
        }

    except Exception as e:
        logger.info(f"[ERROR] add_khata_transaction: {e}")
        return None


def get_khata_account(shop_id: str, customer_id: str) -> dict | None:
    try:
        doc_id = get_khata_account_doc_id(shop_id, customer_id)
        snap = db.collection(KHATA_ACCOUNTS).document(doc_id).get()
        if not snap.exists:
            return None
        data = snap.to_dict()
        data["doc_id"] = doc_id
        return data
    except Exception as e:
        logger.info(f"[ERROR] get_khata_account: {e}")
        return None


def list_khata_customers_for_shop(shop_id: str) -> list[dict]:
    try:
        q = db.collection(KHATA_ACCOUNTS).where("shop_id", "==", shop_id).stream()
        result = []
        for doc in q:
            d = doc.to_dict()
            d["doc_id"] = doc.id
            result.append(d)
        return result
    except Exception as e:
        logger.info(f"[ERROR] list_khata_customers_for_shop: {e}")
        return []


def list_khata_accounts_for_customer(customer_id: str) -> list[dict]:
    """All khata accounts for a given customer across shops."""
    try:
        q = db.collection(KHATA_ACCOUNTS).where("customer_id", "==", customer_id).stream()
        result = []
        for doc in q:
            d = doc.to_dict()
            d["doc_id"] = doc.id
            result.append(d)
        return result
    except Exception as e:
        logger.info(f"[ERROR] list_khata_accounts_for_customer: {e}")
        return []


def list_khata_transactions(shop_id: str, customer_id: str, limit: int = 100) -> list[dict]:
    try:
        q = (db.collection(KHATA_TX)
             .where("shop_id", "==", shop_id)
             .where("customer_id", "==", customer_id)
             .order_by("created_at", direction=firestore.Query.DESCENDING)
             .limit(limit))

        result = []
        for doc in q.stream():
            d = doc.to_dict()
            d["doc_id"] = doc.id
            result.append(d)
        return result
    except Exception as e:
        logger.info(f"[ERROR] list_khata_transactions: {e}")
        return []
