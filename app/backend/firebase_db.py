import firebase_admin
from firebase_admin import credentials, firestore, storage as fb_storage
import uuid
import base64
import os

# ✅ Initialize Firebase (serviceAccountKey.json must be in same folder)

if not firebase_admin._apps:
    cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "/etc/secrets/firebase.json")
    cred = credentials.Certificate(cred_path)
    firebase_admin.initialize_app(cred, {
        "storageBucket": "groceryapp-fe2ec.appspot.com"  # keep your bucket name
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

def append_shop(shop_dict):
    shop_id = str(uuid.uuid4())
    shop_dict["id"] = shop_id
    db.collection("shops").document(shop_id).set(shop_dict)
    return shop_dict

# ---------------- ITEMS ----------------

def get_items_by_shop(shop_id):
    docs = db.collection("items").where("shopid", "==", shop_id).stream()
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
    db.collection("orders").document(order_id).set(order_dict)
    return order_dict

def get_orders_by_customer(customer_id):
    docs = db.collection("orders").where("customer.id", "==", customer_id).stream()
    return [doc.to_dict() for doc in docs]

def get_orders_by_shop(shop_id):
    docs = db.collection("orders").where("shop_id", "==", shop_id).stream()
    return [doc.to_dict() for doc in docs]

def update_order_status(order_uuid, new_status):
    ref = db.collection("orders").document(order_uuid)
    doc = ref.get()
    if doc.exists:
        ref.update({
            "status": new_status
        })
        return True
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


def get_user_by_username(username):
    users = db.collection("users")
    for user in users:
        if user.get("username") == username:
            return user
    return None

def get_user_by_email(email):
    users = db.collection("users")
    for user in users:
        if user.get("email") == email:
            return user
    return None

