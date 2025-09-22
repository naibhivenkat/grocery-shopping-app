import firebase_admin
from firebase_admin import credentials, firestore, storage as fb_storage
import uuid
import base64
import os
import json


# ✅ Initialize Firebase (serviceAccountKey.json must be in same folder)
if not firebase_admin._apps:
    cred_env = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if cred_env and cred_env.strip().startswith("{"):  # JSON string
        cred_dict = json.loads(cred_env)
        cred = credentials.Certificate(cred_dict)
    else:  # assume it's a file path
        cred = credentials.Certificate(cred_env or "/etc/secrets/firebase.json")

    firebase_admin.initialize_app(cred, {
        "storageBucket": "groceryapp-fe2ec.appspot.com"
    })

db = firestore.client()
bucket = fb_storage.bucket()

# ---------------- USERS ----------------

def get_user_by_credentials(username, password):
    docs = db.collection("users").where("username", "==", username).where("password", "==", password).stream()

    for doc in docs:
        return doc.to_dict()

    return None

def append_user(user_dict):
    user_id = str(uuid.uuid4())
    user_dict["id"] = user_id
    db.collection("users").document(user_id).set(user_dict)
    return user_dict

# ---------------- SHOPS ----------------

def get_all_shops():
    return [doc.to_dict() for doc in db.collection("shops").stream()]



# ---------------- ITEMS ----------------

def get_items_by_shop(shop_id):
    docs = db.collection("items").where("shopId", "==", str(shop_id)).stream()
    return [doc.to_dict() for doc in docs]


def append_item(item_dict):
    item_id = str(uuid.uuid4())
    item_dict["id"] = item_id
    db.collection("items").document(item_id).set(item_dict)
    return item_dict

# ---------------- ORDERS ----------------

def append_order(order_dict):
    order_id = str(uuid.uuid4())
    order_dict["order_uuid"] = order_id
    # ✅ ensure shopId is string
    if "shopId" in order_dict:
        order_dict["shopId"] = str(order_dict["shopId"])
    db.collection("orders").document(order_id).set(order_dict)
    return order_dict


def get_orders_by_customer(customer_id):
    docs = db.collection("orders").where("customer.id", "==", customer_id).stream()
    return [doc.to_dict() for doc in docs]

def get_orders_by_shop(shop_id):
    docs = db.collection("orders").where("shopId", "==", shop_id).stream()
    return [doc.to_dict() for doc in docs]


def update_order_status(order_uuid: str, new_status: str, extra_fields: dict = None):
    """
    Updates the order document with a new status and optional extra fields.
    Logs everything for debugging.
    """
    try:
        ref = db.collection("orders").document(order_uuid)
        doc = ref.get()
        if not doc.exists:
            print(f"❌ Order not found in Firestore: {order_uuid}")
            return False

        update_data = {"status": new_status}
        if extra_fields and isinstance(extra_fields, dict):
            update_data.update(extra_fields)

        ref.update(update_data)

        print(f"✅ Order updated in Firestore")
        print(f"   order_uuid: {order_uuid}")
        print(f"   new_status: {new_status}")
        if extra_fields:
            print(f"   extra_fields: {extra_fields}")

        return True
    except Exception as e:
        print(f"[ERROR] update_order_status failed for {order_uuid}: {e}")
        return False


# ---------------- STORAGE ----------------

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

# ---------------- SHOPS ----------------

def get_shop_by_shopkeeper(shopkeeper_id):
    """Returns the shop dict for a given shopkeeper_id, or None if not found."""
    docs = db.collection("shops").where("shopkeeper_id", "==", shopkeeper_id).stream()
    for doc in docs:
        return doc.to_dict()
    return None



def get_user_by_username(username: str):
    try:
        users_ref = db.collection("users")
        query = users_ref.where("username", "==", username).limit(1).stream()
        for doc in query:
            user = doc.to_dict()
            user["id"] = doc.id   # keep Firestore doc id if needed
            return user
        return None
    except Exception as e:
        print(f"[ERROR] get_user_by_username failed: {e}")
        return None


def get_user_by_email(email: str):
    try:
        users_ref = db.collection("users")
        query = users_ref.where("email", "==", email).limit(1).stream()
        for doc in query:
            user = doc.to_dict()
            user["id"] = doc.id
            return user
        return None
    except Exception as e:
        print(f"[ERROR] get_user_by_email failed: {e}")
        return None

def append_shop(shop_dict):
    # Firestore generates doc.id
    doc_ref = db.collection("shops").add(shop_dict)
    shop_id = doc_ref[1].id
    print(f"shop-doc-id {shop_id}")

    # Add this id back into the document
    db.collection("shops").document(shop_id).update({"id": shop_id})

    shop_dict["id"] = shop_id
    return shop_dict

def get_order_by_uuid(order_uuid: str):
    """Fetch a single order document by its order_uuid."""
    try:
        doc_ref = db.collection("orders").document(order_uuid)
        doc = doc_ref.get()
        if doc.exists:
            order = doc.to_dict()
            order["order_uuid"] = doc.id  # ensure ID is attached
            return order
        return None
    except Exception as e:
        print(f"[ERROR] get_order_by_uuid failed: {e}")
        return None

