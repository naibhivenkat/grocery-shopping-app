import datetime
import logging
import os
import random
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
import uuid
import time
from firebase_admin import credentials, auth, db

import firebase_db

print("Starting Flask app (with Firebase)...")

app = Flask(__name__)
CORS(app)
logging.basicConfig(level=logging.INFO)

SENDINBLUE_API_KEY = os.getenv("SENDINBLUE_API_KEY")
FROM_EMAIL = os.getenv("FROM_EMAIL")

otp_store = {}

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()

    if not username or not password:
        return jsonify({'success': False, 'message': 'Username and password required'}), 400

    user = firebase_db.get_user_by_credentials(username, password)

    if not user:
        return jsonify({'success': False, 'message': 'Invalid username or password'}), 401

    # Remove sensitive info
    user.pop('password', None)

    role = user.get('role', '').lower()
    response_user = {
        'username': user.get('username'),
        'role': role,
        'fullName': user.get('fullName', ''),
        'address': user.get('address', ''),
        'phone': user.get('phone', ''),
        'email': user.get('email', ''),
        'location': user.get('location', ''),
        'photoBase64': user.get('photoBase64', '')
    }

    # Add only the relevant ID based on role
    if role == 'customer':
        response_user['customerId'] = user.get('customer_id')
    elif role == 'shopowner':
        shopkeeper_id = user.get('shopkeeper_id')
        response_user['shopkeeperId'] = shopkeeper_id

        # Check if shop exists for this shopkeeper
        shop = firebase_db.get_shop_by_shopkeeper(shopkeeper_id)
        print(shop)
        if shop:
            response_user['shopExists'] = True
            response_user['shop'] = shop  # optional, include shop info
        else:
            response_user['shopExists'] = False

    return jsonify({'success': True, 'user': response_user})


@app.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    email = data.get('email')
    role = data.get('role')

    if role not in ['customer', 'shopowner']:
        return jsonify({'success': False, 'message': 'Invalid role'})

    # Check duplicates
    if firebase_db.get_user_by_username(username):
        return jsonify({'success': False, 'message': 'Username already exists'})
    if firebase_db.get_user_by_email(email):
        return jsonify({'success': False, 'message': 'Email already exists'})

    # Create user dict
    user_dict = {
        'username': username,
        'password': password,
        'role': role,
        'full_name': data.get('full_name', ''),
        'address': data.get('address', ''),
        'phone': data.get('phone', ''),
        'email': email,
        'location': data.get('location', ''),
        'photo_url': '',
        'photo_base64': '',
    }

    if 'photo_base64' in data and data['photo_base64']:
        photo_url = firebase_db.upload_base64_image(data['photo_base64'], folder="profile_photos")
        user_dict['photo_url'] = photo_url
        user_dict['photo_base64'] = data['photo_base64']

    # Assign IDs
    user_dict['customer_id'] = str(uuid.uuid4()) if role == 'customer' else ''
    user_dict['shopkeeper_id'] = str(uuid.uuid4()) if role == 'shopowner' else ''

    # ✅ Save user first
    firebase_db.append_user(user_dict)

    shop_info = None
    if role == 'shopowner':
        # Auto create shop
        shop_dict = {
            "name": data.get("shop_name", f"{username}'s Shop"),
            "address": data.get("address", ""),
            "contact": data.get("phone", ""),
            "shopkeeper_id": user_dict['shopkeeper_id']
        }
        shop = firebase_db.append_shop(shop_dict)
        shop_info = {"shop_id": shop["id"], "name": shop["name"]}

    return jsonify({
        'success': True,
        'message': 'Registered successfully',
        'user': user_dict,
        'shop': shop_info
    })


@app.route('/change_password', methods=['POST'])
def change_password():
    data = request.get_json() if request.is_json else request.form
    username = data.get('username').strip()
    old_password = data.get('old_password').strip()
    new_password = data.get('new_password').strip()
    user = firebase_db.get_user_by_credentials(username, old_password)
    if not user:
        return jsonify({"success": False, "message": "Invalid credentials"}), 401
    user_id = user.get('id')
    firebase_db.db.collection("users").document(user_id).update({"password": new_password})
    return jsonify({"success": True, "message": "Password updated"}), 200

@app.route('/update_profile', methods=['POST'])
def update_profile():
    data = request.get_json()
    username = data.get('username')
    user_docs = firebase_db.db.collection("users").where("username", "==", username).stream()
    uid = None
    for doc in user_docs:
        uid = doc.id
        break
    if not uid:
        return jsonify({'success': False, 'message': 'User not found'})
    update_fields = {
        "full_name": data.get("name", ""),
        "email": data.get("email", ""),
        "phone": data.get("phone", ""),
        "address": data.get("address", ""),
        "location": data.get("location", "")
    }
    if data.get("photo_base64"):
        update_fields["photo_url"] = firebase_db.upload_base64_image(data["photo_base64"], folder="profile_photos")
        update_fields["photo_base64"] = data["photo_base64"]
    firebase_db.db.collection("users").document(uid).update(update_fields)
    return jsonify({'success': True})

# ----------- SHOPS -----------

@app.route("/api/shops", methods=["GET"])
def get_shops():
    return jsonify(firebase_db.get_all_shops())

@app.route('/api/shops/shopkeeper/<shopkeeper_id>', methods=['GET'])
def get_shops_for_shopkeeper(shopkeeper_id):
    all_shops = firebase_db.get_all_shops()
    result = [s for s in all_shops if s.get("shopkeeper_id") == shopkeeper_id]
    return jsonify(result)

@app.route('/create_shop', methods=['POST'])
def create_shop():
    data = request.form
    name = data.get('name')
    address = data.get('address')
    contact = data.get('contact')
    shopkeeper_id = data.get('shopkeeper_id')
    if not all([name, address, contact, shopkeeper_id]):
        return jsonify({'success': False, 'message': 'Missing fields'})
    shop_dict = {
        "name": name,
        "address": address,
        "contact": contact,
        "shopkeeper_id": shopkeeper_id,
    }
    shop = firebase_db.append_shop(shop_dict)
    return jsonify({'success': True, 'shop_id': shop['id']})

# ----------- ITEMS -----------

@app.route("/api/shops/<shop_id>/items", methods=["GET"])
def get_items(shop_id):
    print(f"📌 Fetching items for shop_id={shop_id}")
    items = firebase_db.get_items_by_shop(shop_id)
    if not items:
        return jsonify({"error": f"No items found for shop_id={shop_id}"}), 404
    return jsonify(items), 200


@app.route('/add_items', methods=['POST'])
def add_items():
    data = request.get_json()
    items_data = data.get("items", [])
    shop_id = data.get("shop_id")
    if not shop_id or not items_data:
        return jsonify({'success': False, 'message': 'Missing shop_id or items'}), 400

    for item_data in items_data:
        item_dict = {
            "name": item_data.get("name"),
            "price": item_data.get("price"),
            "stock_quantity": item_data.get("stock_quantity", item_data.get("stock", 0)),
            "description": item_data.get("description", ""),
            "shopid": shop_id,
            "imageurl": item_data.get("imageurl", ""),
        }
        firebase_db.append_item(item_dict)
    return jsonify({'success': True})

@app.route("/update_item/<item_id>", methods=["PUT"])
def update_item(item_id):
    ref = firebase_db.db.collection("items").document(item_id)
    doc = ref.get()
    if not doc.exists:
        return jsonify({"error": "Item not found"}), 404
    data = request.get_json()
    ref.update({
        "name": data.get("name", doc.get("name")),
        "price": data.get("price", doc.get("price")),
        "stock_quantity": data.get("stock_quantity", doc.get("stock_quantity")),
        "description": data.get("description", doc.get("description")),
        "imageurl": data.get("imageurl", doc.get("imageurl")),
    })
    return jsonify({"success": True})

@app.route('/delete_item/<item_id>', methods=['POST'])
def delete_item(item_id):
    doc = firebase_db.db.collection("items").document(item_id).get()
    if not doc.exists:
        return jsonify({'success': False, 'message': 'Item not found'})
    firebase_db.db.collection("items").document(item_id).delete()
    return jsonify({'success': True, 'message': 'Item deleted'})

# ----------- ORDERS -----------

@app.route("/api/orders", methods=["POST"])
def create_order():
    data = request.json

    # Compute total from items
    items = data.get("items", [])
    # Each item: {item_id, quantity}
    total = 0
    detailed_items = []
    for entry in items:
        item_id = entry.get("item_id")
        quantity = float(entry.get("quantity", 1))
        item_doc = firebase_db.db.collection("items").document(item_id).get()
        if item_doc.exists:
            item = item_doc.to_dict()
            item_price = float(item.get("price", 0))
            total += item_price * quantity
            detailed_items.append({"item_id": item_id, "name": item.get("name", ""), "price": item_price, "quantity": quantity})

    order_dict = {
        "shop_id": data["shop_id"],
        "customer": data.get("customerName", "test"),
        "items": detailed_items,
        "total": total,
        "status": "Pending",
        "created_at": datetime.datetime.utcnow().isoformat()
    }
    new_order = firebase_db.append_order(order_dict)
    return jsonify({"success": True, "order_id": new_order["order_uuid"]})

@app.route("/api/orders/shopkeeper/<shop_id>", methods=["GET"])
def get_shop_orders(shop_id):
    orders = firebase_db.get_orders_by_shop(shop_id)
    return jsonify(orders)

@app.route("/api/orders/customer/<customer_id>", methods=["GET"])
def get_customer_orders(customer_id):
    orders = firebase_db.get_orders_by_customer(customer_id)
    return jsonify(orders)

@app.route('/api/orders/<order_uuid>', methods=['GET'])
def get_order_details(order_uuid):
    order_doc = firebase_db.db.collection("orders").document(order_uuid).get()
    if not order_doc.exists:
        return jsonify({'error': 'Order not found'}), 404
    return jsonify(order_doc.to_dict())

@app.route("/api/orders/<order_uuid>", methods=["PATCH"])
def patch_order_by_uuid(order_uuid):
    data = request.get_json()
    new_status = data.get("status")
    cancel_message = data.get("cancel_message", "")

    updated = firebase_db.update_order_status(order_uuid, new_status)
    if updated:
        # Optionally update cancel_message
        if new_status and new_status.lower() == "cancelled" and cancel_message:
            firebase_db.db.collection("orders").document(order_uuid).update({"cancel_message": cancel_message})
        return jsonify({"success": True, "message": "Order updated successfully"})
    return jsonify({"success": False, "message": "Order not found"}), 404

@app.route("/api/orders/shopkeeper", methods=["GET"])
def get_shop_orders_multi():
    # Accepts multiple shop_ids as query params: ?shop_id=abc&shop_id=xyz
    ids = request.args.getlist('shop_id')
    all_orders = []
    for shop_id in ids:
        all_orders.extend(firebase_db.get_orders_by_shop(shop_id))
    return jsonify(all_orders), 200

# ----------- APP VERSION ------------

@app.route("/check_update", methods=["GET"])
def check_update():
    # Leave logic as before
    try:
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        version_file = os.path.join(base_dir, "version.properties")
        if not os.path.exists(version_file):
            logging.error("version.properties file not found at %s", version_file)
            return jsonify({"error": "version.properties file not found"}), 500
        props = {}
        with open(version_file, "r") as f:
            for line in f:
                line = line.strip()
                if line and "=" in line:
                    key, value = line.split("=", 1)
                    props[key.strip()] = value.strip()
        version_code = int(props.get("VERSION_CODE", 1))
        version_name = props.get("VERSION_NAME", "0.1")
        apk_url = "https://github.com/naibhivenkat/grocery-shopping-app/releases/latest/download/app-shopowner-debug.apk"
        apk_size = 0
        try:
            r = requests.head(apk_url, allow_redirects=True, timeout=10)
            apk_size = int(r.headers.get("Content-Length", "0"))
        except Exception as e:
            logging.error(f"Unable to fetch APK size: {e}")
            apk_size = 0
        logging.info("Returning version %s (code %d) with size %d", version_name, version_code, apk_size)
        return jsonify({
            "versionCode": version_code,
            "versionName": version_name,
            "apkUrl": apk_url,
            "apkSize": apk_size
        })
    except Exception as e:
        logging.exception("Error checking update")
        return jsonify({"error": str(e)}), 500


@app.get("/healthz")
def healthz():
    print("Checking health...")
    return jsonify(status="ok"), 200


# ---------------- Helper Function ----------------
def send_email_otp(email, otp):
    print(f"SENDINBLUE_API_KEY {SENDINBLUE_API_KEY}")
    print(f"FROM_EMAIL : {FROM_EMAIL}")
    url = "https://api.sendinblue.com/v3/smtp/email"
    headers = {
        "api-key": SENDINBLUE_API_KEY,
        "Content-Type": "application/json"
    }
    data = {
        "sender": {"name": "Grocery App", "email": FROM_EMAIL},
        "to": [{"email": email}],
        "subject": "Your OTP for Grocery App",
        "htmlContent": f"<h3>Your OTP is: {otp}</h3><p>Valid for 2 minutes</p>"
    }
    response = requests.post(url, headers=headers, json=data)
    print(response.status_code, response.text)
    return response.status_code == 201 or response.status_code == 200

# ---------------- 1️⃣ Send OTP ----------------
@app.route("/send_otp", methods=["POST"])
def send_otp():
    data = request.get_json()
    email = data.get("email")
    if not email:
        return jsonify({"status": "error", "message": "Email required"}), 400

    otp = random.randint(100000, 999999)
    expiry = int(time.time()) + 120  # 2 minutes expiry
    otp_store[email] = {"otp": otp, "expiry": expiry, "attempts": 0}

    if send_email_otp(email, otp):
        return jsonify({"status": "success", "message": "OTP sent"}), 200
    return jsonify({"status": "error", "message": "Failed to send OTP"}), 500


# ---------------- 2️⃣ Verify OTP ----------------
@app.route("/verify_otp", methods=["POST"])
def verify_otp():
    data = request.get_json()
    email = data.get("email")
    otp_input = data.get("otp")
    record = otp_store.get(email)

    if not record:
        return jsonify({"status": "error", "message": "No OTP sent for this email"}), 400

    current_time = int(time.time())
    if current_time > record["expiry"]:
        return jsonify({"status": "error", "message": "OTP expired"}), 400

    if str(record["otp"]) == str(otp_input):
        return jsonify({"status": "success", "message": "OTP verified"}), 200

    return jsonify({"status": "error", "message": "Invalid OTP"}), 400


# ---------------- 3️⃣ Register After OTP ----------------
@app.route("/register_after_otp", methods=["POST"])
def register_after_otp():
    data = request.get_json()
    name = data.get("name")
    email = data.get("email")
    phone = data.get("phone")
    role = data.get("role", "customer").lower()

    if not all([name, email, phone]):
        return jsonify({"success": False, "message": "Missing fields"}), 400

    # Check if user already exists in Firestore
    existing = firebase_db.db.collection("users").where("email", "==", email).stream()
    for doc in existing:
        return jsonify({"success": False, "message": "User already exists"}), 400

    # Add new user to Firestore
    user_dict = {
        "name": name,
        "email": email,
        "phone": phone,
        "role": role,
        "profile_photo": ""
    }
    firebase_db.append_user(user_dict)

    return jsonify({"success": True, "message": "User registered"}), 201


@app.before_request
def require_authentication():
    public_paths = ["/healthz", "/send_otp", "/verify_otp", "/register", "/login", "/register_after_otp"]

    # Allow if matches or starts with
    for path in public_paths:
        if request.path.startswith(path):
            return None

    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return jsonify({"message": "authentication not found in headers", "code": "unauthorized"}), 401

    token = auth_header.split(" ")[1]
    if token != "expected_token":
        return jsonify({"message": "invalid token", "code": "unauthorized"}), 401



if __name__ == "__main__":
    print("Gunicorn setup complete, about to run...")
    app.run(host="0.0.0.0", port=5000, debug=True)
