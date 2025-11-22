# import firebase_admin
# from firebase_admin import credentials, firestore, storage as fb_storage
# import uuid
# import base64
# import os
# import json
# from firebase_admin import messaging
#
# # Firebase initialization
# if not firebase_admin._apps:
#     cred_path = "/secrets/FIREBASE_CREDENTIALS_JSON"
#     cred_env = os.getenv("FIREBASE_CREDENTIALS_JSON")
#
#     try:
#         if cred_env and cred_env.strip().startswith("{"):
#             print("🔹 Using FIREBASE_CREDENTIALS_JSON from environment variable (JSON string)")
#             cred_dict = json.loads(cred_env)
#             cred = credentials.Certificate(cred_dict)
#         elif os.path.exists(cred_path):
#             print(f"🔹 Using FIREBASE_CREDENTIALS_JSON secret file at {cred_path}")
#             cred = credentials.Certificate(cred_path)
#         elif os.path.exists("app/backend/firebase.json"):
#             print("🔹 Using local firebase.json file for development")
#             cred = credentials.Certificate("app/backend/firebase.json")
#         else:
#             raise FileNotFoundError("❌ No valid Firebase credentials found")
#
#         # firebase_admin.initialize_app(cred, {
#         #     "storageBucket": "groceryapp-fe2ec.appspot.com"
#         # })
#         # firebase_admin.initialize_app(cred, {
#         #     "storageBucket": "grocery-app-invoices.appspot.com"
#         # })
#
#         firebase_admin.initialize_app(cred, {
#             "storageBucket": "grocery-app-invoices"
#         })
#
#         print("✅ Firebase initialized successfully")
#
#     except Exception as e:
#         print(f"🔥 Firebase init failed: {e}")
#         raise
#
# db = firestore.client()
# bucket = fb_storage.bucket()
#
#
# # ---------------- USERS ----------------
#
# def get_user_by_credentials(username, password):
#     docs = db.collection("users").where("username", "==", username).where("password", "==",
#                                                                           password).stream()
#
#     for doc in docs:
#         return doc.to_dict()
#
#     return None
#
#
# def append_user(user_dict):
#     user_id = str(uuid.uuid4())
#     user_dict["id"] = user_id
#     db.collection("users").document(user_id).set(user_dict)
#     return user_dict
#
#
# # ---------------- SHOPS ----------------
#
# def get_all_shops():
#     return [doc.to_dict() for doc in db.collection("shops").stream()]
#
#
# # ---------------- ITEMS ----------------
#
# def get_items_by_shop(shop_id):
#     docs = db.collection("items").where("shopId", "==", str(shop_id)).stream()
#     return [doc.to_dict() for doc in docs]
#
#
# def append_item(item_dict):
#     item_id = str(uuid.uuid4())
#     item_dict["id"] = item_id
#     db.collection("items").document(item_id).set(item_dict)
#     return item_dict
#
#
# # ---------------- ORDERS ----------------
#
# # def append_order(order_dict):
# #     order_id = str(uuid.uuid4())
# #     order_dict["order_uuid"] = order_id
# #     # ✅ ensure shopId is string
# #     if "shopId" in order_dict:
# #         order_dict["shopId"] = str(order_dict["shopId"])
# #     db.collection("orders").document(order_id).set(order_dict)
# #
# #     return order_dict
#
# # def append_order(order_dict):
# #     order_id = str(uuid.uuid4())
# #     order_dict["order_uuid"] = order_id
# #
# #     # ✅ Ensure shopId is a string
# #     if "shopId" in order_dict:
# #         order_dict["shopId"] = str(order_dict["shopId"])
# #
# #     # ✅ Save with order_id as Firestore doc ID
# #     db.collection("orders").document(order_id).set(order_dict)
# #
# #     print(f"✅ Created order document with ID = {order_id}")
# #     return order_dict
#
#
# def append_order(order_dict):
#     """
#     Save an order to Firestore with customer info embedded.
#     """
#     try:
#         order_uuid = str(uuid.uuid4())
#         order_dict["order_uuid"] = order_uuid
#         order_dict["created_at"] = datetime.now().isoformat()
#
#         # ✅ Ensure customer subfield is stored
#         customer = order_dict.get("customer")
#         if not customer:
#             print("⚠️ Missing customer field in order_dict!")
#         else:
#             print(f"🧾 Saving order for customer_id={customer.get('id')}")
#
#         db.collection("orders").add(order_dict)
#         print(f"✅ Added order {order_uuid}")
#         return order_dict
#     except Exception as e:
#         print(f"[ERROR] append_order: {e}")
#         return None
#
#
# def get_orders_by_customer(customer_id):
#     docs = db.collection("orders").where("customer.id", "==", customer_id).stream()
#     return [doc.to_dict() for doc in docs]
#
#
# def get_orders_by_shop(shop_id):
#     docs = db.collection("orders").where("shopId", "==", shop_id).stream()
#     return [doc.to_dict() for doc in docs]
#
#
# # def update_order_status(order_uuid: str, new_status: str, extra_fields: dict = None):
# #     """
# #     Updates the order document with a new status and optional extra fields.
# #     Logs everything for debugging.
# #     """
# #     try:
# #         ref = db.collection("orders").document(order_uuid)
# #         doc = ref.get()
# #         if not doc.exists:
# #             print(f"❌ Order not found in Firestore: {order_uuid}")
# #             return False
# #
# #         update_data = {"status": new_status}
# #         if extra_fields and isinstance(extra_fields, dict):
# #             update_data.update(extra_fields)
# #
# #         ref.update(update_data)
# #
# #         print(f"✅ Order updated in Firestore")
# #         print(f"   order_uuid: {order_uuid}")
# #         print(f"   new_status: {new_status}")
# #         if extra_fields:
# #             print(f"   extra_fields: {extra_fields}")
# #
# #         return True
# #     except Exception as e:
# #         print(f"[ERROR] update_order_status failed for {order_uuid}: {e}")
# #         return False
#
#
# # ---------------- STORAGE ----------------
# def update_order_status(order_uuid: str, new_status: str, extra_fields: dict = None):
#     """
#     Updates the order document with a new status and optional extra fields.
#     Logs everything for debugging.
#     """
#     try:
#         ref = db.collection("orders").document(order_uuid)
#         doc = ref.get()
#
#         if not doc.exists:
#             # Try fallback: search by field 'order_uuid'
#             print(f"⚠️ Order not found by doc ID: {order_uuid}, trying fallback search...")
#             query = db.collection("orders").where("order_uuid", "==", order_uuid).limit(1).stream()
#             for found in query:
#                 ref = db.collection("orders").document(found.id)
#                 doc = found
#                 print(f"✅ Found order by field fallback: {found.id}")
#                 break
#             else:
#                 print(f"❌ Order not found anywhere: {order_uuid}")
#                 return False
#
#         # Build update data
#         update_data = {"status": new_status}
#         if extra_fields and isinstance(extra_fields, dict):
#             update_data.update(extra_fields)
#
#         ref.update(update_data)
#         print(f"✅ Order updated in Firestore ({ref.id})")
#         print(f"   new_status: {new_status}")
#         if extra_fields and isinstance(extra_fields, dict):
#             update_data.update(extra_fields)
#
#             print(f"   extra_fields: {extra_fields}")
#
#         return True
#
#     except Exception as e:
#         print(f"[ERROR] update_order_status failed for {order_uuid}: {e}")
#         return False
#
#
# def upload_base64_image(base64_str, folder="images"):
#     """Uploads a Base64 image string to Firebase Storage and returns public URL."""
#     if not base64_str:
#         return ""
#     image_bytes = base64.b64decode(base64_str)
#     filename = f"{folder}/{uuid.uuid4()}.jpg"
#     blob = bucket.blob(filename)
#     blob.upload_from_string(image_bytes, content_type="image/jpeg")
#     blob.make_public()
#     return blob.public_url
#
#
# # ---------------- SHOPS ----------------
#
# def get_shop_by_shopkeeper(shopkeeper_id):
#     """Returns the shop dict for a given shopkeeper_id, or None if not found."""
#     docs = db.collection("shops").where("shopkeeper_id", "==", shopkeeper_id).stream()
#     for doc in docs:
#         return doc.to_dict()
#     return None
#
#
# def get_user_by_username(username: str):
#     try:
#         users_ref = db.collection("users")
#         query = users_ref.where("username", "==", username).limit(1).stream()
#         for doc in query:
#             user = doc.to_dict()
#             user["id"] = doc.id  # keep Firestore doc id if needed
#             return user
#         return None
#     except Exception as e:
#         print(f"[ERROR] get_user_by_username failed: {e}")
#         return None
#
#
# def get_user_by_email(email: str):
#     try:
#         users_ref = db.collection("users")
#         query = users_ref.where("email", "==", email).limit(1).stream()
#         for doc in query:
#             user = doc.to_dict()
#             user["id"] = doc.id
#             return user
#         return None
#     except Exception as e:
#         print(f"[ERROR] get_user_by_email failed: {e}")
#         return None
#
#
# def append_shop(shop_dict):
#     # Firestore generates doc.id
#     doc_ref = db.collection("shops").add(shop_dict)
#     shop_id = doc_ref[1].id
#     print(f"shop-doc-id {shop_id}")
#
#     # Add this id back into the document
#     db.collection("shops").document(shop_id).update({"id": shop_id})
#
#     shop_dict["id"] = shop_id
#     return shop_dict
#
#
# def get_order_by_uuid(order_uuid: str):
#     """Fetch a single order document by its order_uuid."""
#     try:
#         doc_ref = db.collection("orders").document(order_uuid)
#         doc = doc_ref.get()
#         if doc.exists:
#             order = doc.to_dict()
#             order["order_uuid"] = doc.id  # ensure ID is attached
#             return order
#         return None
#     except Exception as e:
#         print(f"[ERROR] get_order_by_uuid failed: {e}")
#         return None
#
#
# def upload_invoice_to_storage(order_id, pdf_buffer, customer_id=None):
#     """Uploads PDF invoice to Firebase Storage under customer folder and returns public URL."""
#     try:
#         # Organize by customer folder
#         blob_path = f"invoices/{customer_id}/{order_id}.pdf" if customer_id else f"invoices/{order_id}.pdf"
#         blob = bucket.blob(blob_path)
#         blob.upload_from_file(pdf_buffer, content_type="application/pdf")
#         blob.make_public()  # optional, but needed if you want direct access from app
#         url = blob.public_url
#         print(f"✅ Uploaded invoice to {blob_path} — URL: {url}")
#         return url
#     except Exception as e:
#         print(f"[ERROR] Upload failed for {order_id}: {e}")
#         return None
#
#
# def generate_signed_invoice_url(order_id, expiry_hours=24):
#     """Generates a signed download URL for the uploaded invoice."""
#     try:
#         blob_path = f"invoices/{order_id}.pdf"
#         blob = bucket.blob(blob_path)  # ✅ use global bucket object
#         url = blob.generate_signed_url(
#             version="v4",
#             expiration=datetime.timedelta(hours=expiry_hours),
#             method="GET"
#         )
#         print(f"🔗 Generated signed URL for {blob_path}")
#         return url
#     except Exception as e:
#         print(f"[ERROR] Failed to generate signed URL: {e}")
#         return None
#
#
# # ---------------- FCM TOKENS ----------------
#
# def save_fcm_token_for_user(user_id: str, token: str, role: str) -> bool:
#     try:
#         if not user_id or not token:
#             return False
#
#         users_ref = db.collection("users")
#         # find user doc by role
#         query = users_ref.where(
#             "customerId" if role == "customer" else "shopkeeperId", "==", user_id
#         ).limit(1).stream()
#
#         user_doc_id = None
#         for doc in query:
#             user_doc_id = doc.id
#             break
#
#         if not user_doc_id:
#             print(f"⚠️ User not found for id={user_id}, role={role}")
#             return False
#
#         user_ref = users_ref.document(user_doc_id)
#         data = user_ref.get().to_dict() or {}
#         tokens = set(data.get("fcm_tokens", []))
#         tokens.add(token)
#         user_ref.update({"fcm_tokens": list(tokens)})
#
#         print(f"✅ Saved FCM token for user {user_id}")
#         return True
#
#     except Exception as e:
#         print(f"[ERROR] save_fcm_token_for_user: {e}")
#         return False
#
#
# def get_fcm_tokens_for_user(user_id: str):
#     """Return list of FCM tokens for a given customerId or shopkeeperId."""
#     try:
#         users_ref = db.collection("users")
#         query = users_ref.where("customerId", "==", user_id).limit(1).stream()
#
#         tokens = []
#         for doc in query:
#             data = doc.to_dict()
#             tokens = data.get("fcm_tokens") or []
#             if not tokens and data.get("fcm_token"):
#                 tokens = [data["fcm_token"]]
#             break
#
#         return tokens
#     except Exception as e:
#         print(f"[ERROR] get_fcm_tokens_for_user: {e}")
#         return []
#
#
#
#
# def remove_fcm_token_for_user(user_id: str, token: str) -> bool:
#     """Remove token (e.g., when user logs out or token is invalid)."""
#     try:
#         if not user_id or not token:
#             return False
#         user_ref = db.collection("users").document(user_id)
#         user_doc = user_ref.get()
#         if not user_doc.exists:
#             return False
#         data = user_doc.to_dict()
#         tokens = set(data.get("fcm_tokens", []))
#         if token in tokens:
#             tokens.remove(token)
#             user_ref.update({"fcm_tokens": list(tokens)})
#         return True
#     except Exception as e:
#         print(f"[ERROR] remove_fcm_token_for_user: {e}")
#         return False
#
#
# def send_fcm_notification_to_tokens(tokens: list, title: str, body: str, data_payload: dict = None):
#     """
#     Send a notification to a list of device tokens. Uses multicast if >1 token.
#     Returns a dict with success/failure counts.
#     """
#     if not tokens:
#         print("⚠️ No tokens provided for notification")
#         return {"success": 0, "failure": 0}
#
#     message = messaging.MulticastMessage(
#         notification=messaging.Notification(title=title, body=body),
#         tokens=tokens,
#         data=data_payload or {}
#     )
#
#     try:
#         response = messaging.send_multicast(message)
#         print(f"✅ Sent FCM: success={response.success_count} failure={response.failure_count}")
#         # Optionally handle failures: remove invalid tokens based on response.responses
#         for idx, resp in enumerate(response.responses):
#             if not resp.success:
#                 err = resp.exception
#                 print(f"⚠️ Token failed: {tokens[idx]} -> {err}")
#                 # If error is Unregistered or NotRegistered remove token from DB (optional)
#         return {"success": response.success_count, "failure": response.failure_count}
#     except Exception as e:
#         print(f"[ERROR] send_fcm_notification_to_tokens: {e}")
#         return {"success": 0, "failure": 1}

import firebase_admin
from firebase_admin import credentials, firestore, storage as fb_storage, messaging
import uuid
import base64
import os
import json
import datetime
import logging

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
            print("🔹 Using FIREBASE_CREDENTIALS_JSON from environment variable (JSON string)")
            cred_dict = json.loads(cred_env)
            cred = credentials.Certificate(cred_dict)
        elif os.path.exists(cred_path):
            print(f"🔹 Using FIREBASE_CREDENTIALS_JSON secret file at {cred_path}")
            cred = credentials.Certificate(cred_path)
        elif os.path.exists("app/backend/firebase.json"):
            print("🔹 Using local firebase.json file for development")
            cred = credentials.Certificate("app/backend/firebase.json")
        else:
            raise FileNotFoundError("❌ No valid Firebase credentials found")

        # ✅ Must include .appspot.com suffix
        firebase_admin.initialize_app(cred, {
            "storageBucket": "grocery-app-invoices.appspot.com"
        })

        print("✅ Firebase initialized successfully")

    except Exception as e:
        print(f"🔥 Firebase init failed: {e}")
        raise

db = firestore.client()
bucket = fb_storage.bucket()

# ---------------------------------------------------------------------
# 🔹 USER FUNCTIONS
# ---------------------------------------------------------------------
def get_user_by_credentials(username, password):
    docs = db.collection("users").where("username", "==", username).where("password", "==", password).stream()
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


def get_user_by_email(email: str):
    query = db.collection("users").where("email", "==", email).limit(1).stream()
    for doc in query:
        user = doc.to_dict()
        user["id"] = doc.id
        return user
    return None


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
        order_uuid = str(uuid.uuid4())
        order_dict["order_uuid"] = order_uuid
        order_dict["created_at"] = datetime.datetime.now().isoformat()

        db.collection("orders").add(order_dict)
        print(f"✅ Added order {order_uuid}")
        return order_dict
    except Exception as e:
        print(f"[ERROR] append_order: {e}")
        return None


def get_orders_by_customer(customer_id):
    docs = db.collection("orders").where("customer.id", "==", customer_id).stream()
    return [doc.to_dict() for doc in docs]


def get_orders_by_shop(shop_id):
    docs = db.collection("orders").where("shopId", "==", shop_id).stream()
    return [doc.to_dict() for doc in docs]


def get_order_by_uuid(order_uuid: str):
    try:
        doc_ref = db.collection("orders").document(order_uuid)
        doc = doc_ref.get()
        if doc.exists:
            data = doc.to_dict()
            data["order_uuid"] = doc.id
            return data

        # fallback search
        query = db.collection("orders").where("order_uuid", "==", order_uuid).limit(1).stream()
        for found in query:
            return found.to_dict()
        return None
    except Exception as e:
        print(f"[ERROR] get_order_by_uuid: {e}")
        return None


def update_order_status(order_uuid: str, new_status: str, extra_fields: dict = None):
    try:
        ref = db.collection("orders").document(order_uuid)
        doc = ref.get()

        if not doc.exists:
            query = db.collection("orders").where("order_uuid", "==", order_uuid).limit(1).stream()
            for found in query:
                ref = db.collection("orders").document(found.id)
                doc = found
                break
            else:
                print(f"❌ Order not found anywhere: {order_uuid}")
                return False

        update_data = {"status": new_status}
        if extra_fields:
            update_data.update(extra_fields)

        ref.update(update_data)
        print(f"✅ Order updated in Firestore ({ref.id}) → {new_status}")
        return True
    except Exception as e:
        print(f"[ERROR] update_order_status: {e}")
        return False


# ---------------------------------------------------------------------
# 🔹 FILE STORAGE / INVOICES
# ---------------------------------------------------------------------
def upload_invoice_to_storage(order_id, pdf_buffer, customer_id=None):
    try:
        blob_path = f"invoices/{customer_id}/{order_id}.pdf" if customer_id else f"invoices/{order_id}.pdf"
        blob = bucket.blob(blob_path)
        blob.upload_from_file(pdf_buffer, content_type="application/pdf")
        blob.make_public()
        url = blob.public_url
        print(f"✅ Uploaded invoice: {url}")
        return url
    except Exception as e:
        print(f"[ERROR] upload_invoice_to_storage: {e}")
        return None


# ---------------------------------------------------------------------
# 🔹 FCM TOKEN MANAGEMENT
# ---------------------------------------------------------------------
# def save_fcm_token_for_user(user_id: str, token: str, role: str) -> bool:
#     try:
#         if not user_id or not token:
#             return False
#         users_ref = db.collection("users")
#         query = users_ref.where("customerId" if role == "customer" else "shopkeeperId", "==", user_id).limit(1).stream()
#
#         user_doc_id = None
#         for doc in query:
#             user_doc_id = doc.id
#             break
#
#         if not user_doc_id:
#             print(f"⚠️ User not found for id={user_id}, role={role}")
#             return False
#
#         user_ref = users_ref.document(user_doc_id)
#         data = user_ref.get().to_dict() or {}
#         tokens = set(data.get("fcm_tokens", []))
#         tokens.add(token)
#         user_ref.update({"fcm_tokens": list(tokens)})
#
#         print(f"✅ Saved FCM token for user {user_id}")
#         return True
#     except Exception as e:
#         print(f"[ERROR] save_fcm_token_for_user: {e}")
#         return False

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

        #user_ref.update({"fcm_tokens": list(tokens)})
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


# def get_fcm_tokens_for_user(user_id: str):
#     """Return list of FCM tokens for a given user_id, checking both customerId and id."""
#     try:
#         users_ref = db.collection("users")
#         tokens = []
#
#         query1 = users_ref.where("customerId", "==", user_id).limit(1).stream()
#         for doc in query1:
#             tokens = doc.to_dict().get("fcm_tokens", [])
#             if tokens:
#                 print(f"✅ Found {len(tokens)} tokens via customerId={user_id}")
#                 return tokens
#
#         query2 = users_ref.where("id", "==", user_id).limit(1).stream()
#         for doc in query2:
#             tokens = doc.to_dict().get("fcm_tokens", [])
#             if tokens:
#                 print(f"✅ Found {len(tokens)} tokens via id={user_id}")
#                 return tokens
#
#         print(f"⚠️ No tokens found for user {user_id}")
#         return tokens
#     except Exception as e:
#         print(f"[ERROR] get_fcm_tokens_for_user: {e}")
#         return []
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
                print(f"🗑️ Removed invalid token for {user_id}")
                break
    except Exception as e:
        print(f"[ERROR] remove_fcm_token_for_user: {e}")


# def send_fcm_notification_to_tokens(tokens, title, body, data_payload=None):
#     """
#     Send FCM notifications (compatible with Firebase Admin SDK v1).
#     Avoids deprecated /batch endpoint by sending individually.
#     """
#     if not tokens:
#         print("⚠️ No tokens to send")
#         return {"success": 0, "failure": 0}
#
#     results = {"success": 0, "failure": 0}
#
#     for token in tokens:
#         try:
#             message = messaging.Message(
#                 notification=messaging.Notification(title=title, body=body),
#                 token=token,
#                 data=data_payload or {}
#             )
#             response = messaging.send(message)
#             print(f"📩 Sent FCM to {token[:15]}... → {response}")
#             results["success"] += 1
#         except Exception as e:
#             print(f"[ERROR] FCM send failed for {token[:15]}... → {e}")
#             results["failure"] += 1
#
#     print(f"📲 Notification summary: success={results['success']}, failure={results['failure']}")
#     return results
# def send_fcm_notification_to_tokens(tokens, title, body, data_payload=None):
#     """
#     Send FCM notifications to a list of tokens.
#     Uses Firebase Admin SDK v1 (individual send).
#     """
#     if not tokens:
#         logger.warning("⚠️ FCM: No tokens to send notification")
#         return {"success": 0, "failure": 0}
#
#     results = {"success": 0, "failure": 0}
#
#     for token in tokens:
#         try:
#             message = messaging.Message(
#                 notification=messaging.Notification(title=title, body=body),
#                 token=token,
#                 data=data_payload or {}
#             )
#
#             response = messaging.send(message)
#
#             logger.info(f"📩 FCM sent → token={token[:15]}... response={response}")
#             results["success"] += 1
#
#         except Exception as e:
#             logger.error(f"[ERROR] FCM failed → token={token[:15]}... error={e}")
#
#         if "Requested entity was not found" in str(e):
#             remove_fcm_token_for_user(user_id, token)
#
#     results["failure"] += 1
#
#
#     logger.info(f"📲 FCM Summary: {results['success']} success | {results['failure']} failed")
#     return results

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
            logger.error(f"[ERROR] FCM send failed → token={token[:15]}... error={e}")
            results["failure"] += 1

            # Remove invalid token automatically
            if user_id and "Requested entity was not found" in str(e):
                remove_fcm_token_for_user(user_id, token)
                logger.info(f"🗑️ Removed invalid FCM token for user_id={user_id}")

    logger.info(f"📲 FCM Summary: {results['success']} success | {results['failure']} failed")
    return results
