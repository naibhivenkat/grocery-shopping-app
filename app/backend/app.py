import datetime
import datetime
import jwt
import logging
import os
import random
import requests
import time
import uuid
from firebase_admin import credentials, auth, db
from flask import Flask, request, jsonify, g
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import razorpay

import firebase_db

app = Flask(__name__)
CORS(app)
logging.basicConfig(level=logging.INFO)
SECRET_KEY = os.getenv("SECRET_KEY")  # keep secret and safe!

SENDINBLUE_API_KEY = os.getenv("SENDINBLUE_API_KEY")
FROM_EMAIL = os.getenv("FROM_EMAIL")

# Initialize limiter
limiter = Limiter(key_func=get_remote_address)
limiter.init_app(app)

otp_store = {}
forgot_password_otp_store = {}  # email -> {otp, expiry, attempts}

# 🔹 Initialize Razorpay client
RAZORPAY_KEY_ID = "rzp_test_RKK3DuGSaxK9fR"
RAZORPAY_KEY_SECRET = "VgVc96Pdn3t5T8ieX0nb2ajt"
razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

def generate_token(user):
    payload = {
    #    "id": user.get("id") or   # ✅ include id
        "id": user.get("customerId"),
        "username": user["username"],
        "role": user["role"],
        "exp": datetime.datetime.utcnow() + datetime.timedelta(days=7)
    }
    token = jwt.encode(payload, SECRET_KEY, algorithm="HS256")
    print("id ", user.get("id"))
    print(f"cust id { user.get("customerId")}")
    print(f"Payload in generate token : {payload}")


    # ensure it's str, not bytes
    if isinstance(token, bytes):
        token = token.decode("utf-8")

    return token


# Health check endpoint – exempt from rate limits
@app.get("/healthz")
@limiter.exempt
def healthz():
    try:
        # Example: check some real condition instead of random
        service_ok = True  # replace with actual check, e.g., DB ping, cache, etc.

        if service_ok:
           # logging.info("✅ Health check ping received")
            return jsonify(status="Up and Running"), 200
        else:
            logging.error("❌ Health check failed!")
            return jsonify(status="Service Down", error="Server unreachable"), 503
    except Exception as e:
        logging.error(f"❌ Health check exception: {e}")
        return jsonify(status="Service Down", error=str(e)), 503



@app.route("/login", methods=["POST"])
def login():
    data = request.get_json()
    username = data.get("username")
    password = data.get("password")

    user = firebase_db.get_user_by_username(username)
    if not user:
        return jsonify({"success": False, "message": "User not found"}), 404

    if user.get("password") != password:
        return jsonify({"success": False, "message": "Invalid password"}), 401

    # Default
    shop_info = None

    # 🔎 If shopkeeper/shopowner → fetch shop
    if user.get("role") in ["shopkeeper", "shopowner"]:
        shop_query = firebase_db.db.collection("shops").where(
            "shopkeeper_id", "==", user.get("shopkeeperId")
        ).stream()
        for doc in shop_query:
            shop_data = doc.to_dict()
            shop_info = {
                "id": doc.id,  # ✅ Firestore docId (not UUID)
                "name": shop_data.get("name"),
                "address": shop_data.get("address"),
                "location": shop_data.get("location"),
                "contact": shop_data.get("contact"),
                "shopkeeper_id": shop_data.get("shopkeeper_id"),
            }
            break

    response_user = {
        "id": user.get("id"),
        "username": user.get("username"),
        "fullName": user.get("fullName") or user.get("name", ""),
        "email": user.get("email", ""),
        "phone": user.get("phone", ""),
        "role": user.get("role", ""),
        "customerId": user.get("customerId") or user.get("customer_id"),
        "shopkeeperId": user.get("shopkeeperId") or user.get("shopkeeper_id"),
        "address": user.get("address", ""),
        "location": user.get("location", ""),
        "photoUrl": user.get("photoUrl") or user.get("photo_url", ""),
        "photoBase64": user.get("photoBase64") or user.get("photo_base64", ""),
        "shop": shop_info,
        "shopExists": shop_info is not None
    }

    # ✅ Generate JWT token
    # token = generate_token(user)
    token = generate_token(response_user)

    return jsonify({
        "success": True,
        "message": "Login successful",
        "user": response_user,
        "token": token
    }), 200




@app.route('/register', methods=['POST'])
def register():
    data = request.get_json()

    name = data.get("name") or data.get("full_name")
    username = data.get('username')
    password = data.get('password')
    email = data.get('email')
    role = data.get('role', '').lower()
    phone = data.get('phone', '')

    if role not in ['customer', 'shopowner', 'shopkeeper']:
        return jsonify({'success': False, 'message': 'Invalid role'}), 400

    # Duplicate check
    if firebase_db.get_user_by_username(username):
        return jsonify({'success': False, 'message': 'Username already exists'}), 400
    if firebase_db.get_user_by_email(email):
        return jsonify({'success': False, 'message': 'Email already exists'}), 400

    # Build user dict
    user_dict = {
        "username": username,
        "password": password,
        "role": role,
        "fullName": name,
        "address": data.get("address", ""),
        "phone": phone,
        "email": email,
        "location": data.get("location", ""),
        "photoBase64": data.get("photo_base64", ""),
        "photoUrl": "",
        # IDs
        "customerId": str(uuid.uuid4()) if role == "customer" else None,
        "shopkeeperId": str(uuid.uuid4()) if role in ["shopowner", "shopkeeper"] else None
    }

    # Generate JWT token
    token = generate_token(user_dict)
    user_dict["token"] = token

    # Handle profile photo
    if data.get("photo_base64"):
        photo_url = firebase_db.upload_base64_image(data["photo_base64"], folder="profile_photos")
        user_dict["photoUrl"] = photo_url

    # Save user
    firebase_db.append_user(user_dict)

    # ⬇️ Consistent response (same shape as /login)
    response_user = {
        "id": user_dict.get("id"),
        "username": user_dict.get("username"),
        "fullName": user_dict.get("fullName"),
        "email": user_dict.get("email"),
        "phone": user_dict.get("phone"),
        "role": user_dict.get("role"),
        "customerId": user_dict.get("customerId"),
        "shopkeeperId": user_dict.get("shopkeeperId"),
        "address": user_dict.get("address"),
        "location": user_dict.get("location"),
        "photoUrl": user_dict.get("photoUrl"),
        "photoBase64": user_dict.get("photoBase64"),
        "shop": None,          # no shop yet
        "shopExists": False    # must create after login
    }

    return jsonify({
        "success": True,
        "message": "Registered successfully",
        "user": response_user,
        "token": token
    }), 201


@app.route("/register_after_otp", methods=["POST"])
def register_after_otp():
    data = request.get_json()

    name = data.get("name") or data.get("full_name")
    email = data.get("email")
    phone = data.get("phone")
    username = data.get("username")
    role = data.get("role", "customer").lower()
    password = data.get("password")

    if not all([name, email, username, password]):
        return jsonify({"success": False, "message": "Missing fields"}), 400

    # Check if user already exists by email
    existing = firebase_db.db.collection("users").where("email", "==", email).stream()
    for doc in existing:
        return jsonify({"success": False, "message": "User already exists"}), 400

    # Build user dict
    user_dict = {
        "username": username,
        "role": role,
        "password": password,
        "fullName": name,
        "address": "",
        "phone": phone,
        "email": email,
        "location": "",
        "photoBase64": "",
        "photoUrl": "",
        # IDs
        "customerId": str(uuid.uuid4()) if role == "customer" else None,
        "shopkeeperId": str(uuid.uuid4()) if role in ["shopowner", "shopkeeper"] else None
    }

    # Generate JWT token
    token = generate_token(user_dict)
    user_dict["token"] = token

    # Save user
    firebase_db.append_user(user_dict)

    # Send welcome email
    send_welcome_email(email, name)

    # ⬇️ Consistent response (same shape as /login)
    response_user = {
        "id": user_dict.get("id"),
        "username": user_dict.get("username"),
        "fullName": user_dict.get("fullName"),
        "email": user_dict.get("email"),
        "phone": user_dict.get("phone"),
        "role": user_dict.get("role"),
        "customerId": user_dict.get("customerId"),
        "shopkeeperId": user_dict.get("shopkeeperId"),
        "address": user_dict.get("address"),
        "location": user_dict.get("location"),
        "photoUrl": user_dict.get("photoUrl"),
        "photoBase64": user_dict.get("photoBase64"),
        "shop": None,          # no shop yet
        "shopExists": False    # must create after login
    }

    return jsonify({
        "success": True,
        "message": "Registered successfully",
        "user": response_user,
        "token": token
    }), 201



@app.route('/change_password', methods=['POST'])
def change_password():
    try:
        data = request.get_json(force=True)
        print(f"Request JSON: {data}")  # debug
        username = data.get('username', '').strip()
        old_password = data.get('old_password', '').strip()
        new_password = data.get('new_password', '').strip()

        user = firebase_db.get_user_by_credentials(username, old_password)
        if not user:
            return jsonify({"success": False, "message": "Incorrect old password"}), 401

        user_id = user.get('id')
        firebase_db.db.collection("users").document(user_id).update({"password": new_password})

        return jsonify({"success": True, "message": "Password updated"}), 200

    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


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
        update_fields["photo_url"] = firebase_db.upload_base64_image(data["photo_base64"],
                                                                     folder="profile_photos")
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
    data = request.form if request.form else request.get_json()
    name = data.get('name')
    address = data.get('address')
    contact = data.get('contact')
    shopkeeper_id = data.get('shopkeeper_id')

    if not all([name, address, contact, shopkeeper_id]):
        return jsonify({'success': False, 'message': 'Missing fields'}), 400

    # ✅ Create shop entry (doc.id is Firestore’s ID now)
    shop_dict = {
        "name": name,
        "address": address,
        "contact": contact,
        "shopkeeper_id": shopkeeper_id,
        "createdAt": datetime.utcnow().isoformat()
    }
    shop = firebase_db.append_shop(shop_dict)  # returns with correct "id" field

    # ✅ Update user record with shopId + embed shop object
    user_ref = firebase_db.db.collection("users").where("shopkeeperId", "==", shopkeeper_id).stream()
    for doc in user_ref:
        firebase_db.db.collection("users").document(doc.id).update({
            "shopId": shop["id"],
            "shop": {   # ✅ embed minimal shop info so client sees it immediately
                "id": shop["id"],
                "name": shop["name"],
                "shopkeeper_id": shop["shopkeeper_id"]
            }
        })
        break

    # ✅ Return shop info immediately
    return jsonify({
        'success': True,
        'message': 'Shop created successfully',
        'shop': {
            'id': shop['id'],
            'name': shop['name'],
            'address': shop['address'],
            'contact': shop['contact']
        }
    }), 200





@app.route('/api/shops/<shop_id>/items', methods=['GET'])
def get_shop_items(shop_id):
    # First try direct doc.id
    ref = firebase_db.db.collection("shops").document(shop_id).get()
    doc = ref if ref.exists else None

    # Fallback: legacy UUID stored in the 'id' field
    if not doc:
        q = firebase_db.db.collection("shops").where("id", "==", shop_id).limit(1).stream()
        for d in q:
            doc = d
            break

    if not doc:
        return jsonify({"success": False, "message": f"Shop not found for id={shop_id}"}), 404

    shop_doc_id = doc.id  # canonical
    shop = doc.to_dict()

    # Load items by canonical doc.id
    items_snap = firebase_db.db.collection("items").where("shopId", "==", shop_doc_id).stream()
    items = [i.to_dict() for i in items_snap]

    return jsonify({"success": True, "shop": shop, "items": items}), 200




@app.route("/update_item/<item_id>", methods=["PUT"])
def update_item(item_id):
    ref = firebase_db.db.collection("items").document(item_id)
    doc = ref.get()
    if not doc.exists:
        return jsonify({"error": "Item not found"}), 404
    data = request.get_json() or {}
    ref.update({
        "name": data.get("name", doc.get("name")),
        "price": float(data.get("price", doc.get("price"))),
        "quantity": int(data.get("quantity", doc.get("quantity"))),
        "description": data.get("description", doc.get("description")),
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

    # 1️⃣ Compute total from items
    items = data.get("items", [])
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
            detailed_items.append({
                "item_id": item_id,
                "name": item.get("name", ""),
                "price": item_price,
                "quantity": quantity
            })

    # 2️⃣ Get current user
    user = getattr(g, "current_user", None)
    if not user:
        return jsonify({"success": False, "message": "User not logged in"}), 401

    # 3️⃣ Resolve shop doc ID
    input_shop_id = data["shopId"]
    shop_query = firebase_db.db.collection("shops").where("id", "==", input_shop_id).stream()
    shop_doc_id = None
    for doc in shop_query:
        shop_doc_id = doc.id
        break
    if not shop_doc_id:
        return jsonify({"success": False, "message": "Invalid shopId"}), 400

    # 4️⃣ Decide based on payment method
    payment_method = data.get("payment_method", "Razorpay")
    razorpay_order_id = None

    if payment_method == "Razorpay":
        # Create Razorpay order
        razorpay_order = razorpay_client.order.create({
            "amount": int(total * 100),  # in paise
            "currency": "INR",
            "receipt": f"order_{datetime.datetime.utcnow().timestamp()}",
            "payment_capture": 1
        })
        razorpay_order_id = razorpay_order["id"]

    # 5️⃣ Store order in Firestore
    order_dict = {
        "shopId": shop_doc_id,
        "customer": {
            "id": user.get("id"),
            "username": user.get("username"),
            "fullName": user.get("fullName"),
            "email": user.get("email"),
            "phone": user.get("phone"),
        },
        "items": detailed_items,
        "total": total,
        "payment_method": payment_method,
        "transaction_id": "" if payment_method == "Razorpay" else "Cash",
        "razorpay_order_id": razorpay_order_id if razorpay_order_id else "",
        "status": "Pending" if payment_method == "Razorpay" else "Confirmed",
        "created_at": datetime.datetime.utcnow().isoformat()
    }

    new_order = firebase_db.append_order(order_dict)

    # 6️⃣ Return response based on method
    if payment_method == "Razorpay":
        return jsonify({
            "success": True,
            "order_id": new_order["order_uuid"],
            "razorpay_order_id": razorpay_order_id,
            "amount": total
        })
    else:
        # For cash, no Razorpay order needed
        return jsonify({
            "success": True,
            "order_id": new_order["order_uuid"],
            "amount": total,
            "message": "Cash order placed successfully"
        })



@app.route("/api/verify_payment", methods=["POST"])
def verify_payment():
    data = request.json or {}
    print("\n=== /api/verify_payment CALLED ===")
    print("Raw request JSON:", data)

    order_uuid = data.get("order_id")
    razorpay_payment_id = data.get("razorpay_payment_id")
    razorpay_order_id = data.get("razorpay_order_id")
    razorpay_signature = data.get("razorpay_signature")

    print(f"order_id (backend): {order_uuid}")
    print(f"razorpay_payment_id: {razorpay_payment_id}")
    print(f"razorpay_order_id: {razorpay_order_id}")
    print(f"razorpay_signature: {razorpay_signature}")

    if not order_uuid:
        return jsonify({"success": False, "message": "Missing order_id"}), 400

    # 1️⃣ Fetch order from Firestore
    order_doc = firebase_db.get_order_by_uuid(order_uuid)
    if not order_doc:
        print("❌ Order not found in Firestore")
        return jsonify({"success": False, "message": "Order not found"}), 404

    payment_method = order_doc.get("payment_method", "Razorpay")
    print(f"Payment method for order: {payment_method}")

    # 2️⃣ Cash orders (skip Razorpay)
    if payment_method == "Cash":
        updated = firebase_db.update_order_status(order_uuid, "Confirmed")
        print(f"Cash order update result: {updated}")
        return jsonify({"success": True, "message": "Cash order confirmed"})

    # 3️⃣ Razorpay verification
    if not razorpay_payment_id or not razorpay_order_id or not razorpay_signature:
        print("❌ Missing Razorpay details in request")
        return jsonify({"success": False, "message": "Missing Razorpay payment details"}), 400

    params_dict = {
        "razorpay_order_id": razorpay_order_id,
        "razorpay_payment_id": razorpay_payment_id,
        "razorpay_signature": razorpay_signature
    }

    try:
        razorpay_client.utility.verify_payment_signature(params_dict)
        print("✅ Razorpay signature verified successfully")
    except razorpay.errors.SignatureVerificationError:
        print("❌ Razorpay signature verification failed")
        return jsonify({"success": False, "message": "Payment verification failed"}), 400

    # 4️⃣ Update Firestore order
    updated = firebase_db.update_order_status(
        order_uuid,
        "Paid",
        extra_fields={"transaction_id": razorpay_payment_id}
    )
    print(f"Firestore update result: {updated}")

    return jsonify({"success": True, "message": "Payment verified and order updated"})






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
            firebase_db.db.collection("orders").document(order_uuid).update(
                {"cancel_message": cancel_message})
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
        logging.info("Returning version %s (code %d) with size %d", version_name, version_code,
                     apk_size)
        return jsonify({
            "versionCode": version_code,
            "versionName": version_name,
            "apkUrl": apk_url,
            "apkSize": apk_size
        })
    except Exception as e:
        logging.exception("Error checking update")
        return jsonify({"error": str(e)}), 500


def send_email_otp(email, otp):
    try:
        print(f"SENDINBLUE_API_KEY {SENDINBLUE_API_KEY}")
        print(f"FROM_EMAIL : {FROM_EMAIL}")

        url = "https://api.sendinblue.com/v3/smtp/email"
        headers = {
            "api-key": SENDINBLUE_API_KEY,
            "Content-Type": "application/json"
        }

        subject = "🎉 Welcome to Grocery App – Verify Your Email"
        html_content = f"""
        <div style="font-family: Arial, sans-serif; color: #333; padding: 20px;">
            <h2 style="color:#4CAF50;">Welcome to Grocery App! 🛒</h2>
            <p>Thank you for registering with <b>Grocery App</b>. To complete your signup, please verify your email address.</p>
            <p style="font-size:16px;">
                Use the following One-Time Password (OTP) to verify your account:
            </p>
            <div style="background:#f4f4f4; padding:15px 25px; margin:20px 0; border-radius:8px; text-align:center;">
                <h1 style="letter-spacing:5px; color:#2E7D32;">{otp}</h1>
            </div>
            <p>This OTP is valid for <b>2 minutes</b>. Please enter it in the app to verify your email.</p>
            <p>If you did not create this account, you can safely ignore this email.</p>
            <br/>
            <p style="font-size:12px; color:#888;">– The Grocery App Team</p>
        </div>
        """

        data = {
            "sender": {"name": "Grocery App", "email": FROM_EMAIL},
            "to": [{"email": email}],
            "subject": subject,
            "htmlContent": html_content
        }

        response = requests.post(url, headers=headers, json=data)
        print(f"[DEBUG] Sendinblue response: {response.status_code}, {response.text}")

        return response.status_code in (200, 201)

    except Exception as e:
        print(f"[ERROR] Failed to send OTP email: {e}")
        return False

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




def send_welcome_email(email, name):
    url = "https://api.sendinblue.com/v3/smtp/email"
    headers = {
        "api-key": SENDINBLUE_API_KEY,
        "Content-Type": "application/json"
    }
    data = {
        "sender": {"name": "Grocery App", "email": FROM_EMAIL},
        "to": [{"email": email}],
        "subject": "🎉 Welcome to Grocery App!",
        "htmlContent": f"""
            <h2>Hi {name},</h2>
            <p>Thank you for registering with <b>Grocery App</b> 🛒</p>
            <p>You can now log in and start shopping from your favorite stores.</p>
            <br>
            <p>Happy Shopping!<br>– The Grocery App Team</p>
        """
    }
    response = requests.post(url, headers=headers, json=data)
    print("Welcome email response:", response.status_code, response.text)
    return response.status_code in [200, 201]

@app.before_request
def require_authentication():
    public_paths = [
        "/healthz", "/send_otp", "/verify_otp", "/register", "/login",
        "/register_after_otp", "/check_update", "/update_password", "/verify_password_reset_otp", "/send_password_reset_otp",
    ]

    # Allow if matches public paths
    for path in public_paths:
        if request.path.startswith(path):
            return None

    auth_header = request.headers.get("Authorization")


    if not auth_header or not auth_header.startswith("Bearer "):
        return jsonify(
            {"message": "authentication not found in headers", "code": "unauthorized"}), 401

    token = auth_header.split(" ")[1]

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        # ✅ store user info globally for this request
        g.current_user = payload
    except jwt.ExpiredSignatureError:
        return jsonify({"message": "Token expired", "code": "unauthorized"}), 401
    except jwt.InvalidTokenError:
        return jsonify({"message": "Invalid token", "code": "unauthorized"}), 401


@app.route('/shop/add_items', methods=['POST'])
def add_item():
    user = getattr(g, "current_user", None)
    if not user:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    if user.get('role') not in ['shopowner', 'shopkeeper']:
        return jsonify({'success': False, 'message': 'Unauthorized role'}), 403

    data = request.get_json(silent=True) or {}
    raw_shop_id = (data.get("shop_id") or "").strip()
    items = data.get("items", [])

    if not raw_shop_id or not items:
        return jsonify({'success': False, 'message': 'Missing shop_id or items'}), 400

    # 🔁 Normalize shop_id: prefer doc.id; fall back to field match
    shop_ref = firebase_db.db.collection("shops").document(raw_shop_id).get()
    if shop_ref.exists:
        canonical_shop_id = shop_ref.id
        shop_doc = shop_ref.to_dict()
    else:
        # legacy path: client sent the old UUID stored inside the 'id' field
        q = firebase_db.db.collection("shops").where("id", "==", raw_shop_id).limit(1).stream()
        shop_doc = None
        canonical_shop_id = None
        for d in q:
            shop_doc = d.to_dict()
            canonical_shop_id = d.id     # ✅ translate to doc.id
            print (f"canonical_shop_id : {canonical_shop_id}")
            break

    if not canonical_shop_id:
        return jsonify({'success': False, 'message': f'Shop not found for id={raw_shop_id}'}), 404

    saved_items = []
    username = user.get('username')
    for it in items:
        item_dict = {
            "name": it.get("name"),
            "price": float(it.get("price") or 0),
            "quantity": int(it.get("stockQuantity") or 0),
            "description": it.get("description") or "",
            "shopId": canonical_shop_id,             # ✅ always store doc.id
            "createdAt": datetime.datetime.utcnow().isoformat(),
            "createdBy": username
        }
        saved_items.append(firebase_db.append_item(item_dict))

    return jsonify({'success': True, 'message': 'Items added successfully', 'items': saved_items}), 201



@app.route('/get_shop_by_owner', methods=['GET'])
def get_shop_by_owner():
    user = getattr(g, "current_user", None)
    if not user:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401

    shopkeeper_id = user.get("username")   # or user.get("id") depending on your schema
    if not shopkeeper_id:
        return jsonify({'success': False, 'shop': None, 'message': 'Missing shopkeeperId'}), 400

    shop = firebase_db.get_shop_by_owner(shopkeeper_id)
    if shop:
        return jsonify({'success': True, 'shop': shop})
    else:
        return jsonify({'success': False, 'shop': None})

@app.route("/send_password_reset_otp", methods=["POST"])
def send_password_reset_otp():
    data = request.get_json()
    email = data.get("email")
    print("DEBUG: Looking for email:", email)
    if not email:
        return jsonify({"success": False, "message": "Email required"}), 400

    # Check if user exists in Firestore
    users_ref = firebase_db.db.collection("users")
    query = users_ref.where("email", "==", email).limit(1).get()
    print("DEBUG: Query result:", query)
    if not query:
        return jsonify({"success": False, "message": "Email not registered"}), 404

    # Generate OTP
    otp = random.randint(100000, 999999)
    expiry = int(time.time()) + 120  # 2 minutes expiry
    forgot_password_otp_store[email] = {"otp": otp, "expiry": expiry, "attempts": 0}

    # Send OTP via email
    if send_password_reset_email_otp(email, otp):
        return jsonify({"success": True, "message": "OTP sent"}), 200
    return jsonify({"success": False, "message": "Failed to send OTP"}), 500

@app.route("/verify_password_reset_otp", methods=["POST"])
def verify_password_reset_otp():
    data = request.get_json()
    email = data.get("email")
    otp = data.get("otp")

    if not email or not otp:
        return jsonify({"success": False, "message": "Email and OTP required"}), 400

    record = forgot_password_otp_store.get(email)
    if not record:
        return jsonify({"success": False, "message": "No OTP sent"}), 404

    # Check expiry
    if int(time.time()) > record["expiry"]:
        return jsonify({"success": False, "message": "OTP expired"}), 400

    # Check OTP
    if str(record["otp"]) != str(otp):
        record["attempts"] += 1
        if record["attempts"] > 3:
            del forgot_password_otp_store[email]
            return jsonify({"success": False, "message": "Too many attempts, OTP invalidated"}), 403
        return jsonify({"success": False, "message": "Invalid OTP"}), 400

    return jsonify({"success": True, "message": "OTP verified"}), 200

@app.route("/update_password", methods=["POST"])
def update_password():
    data = request.get_json()
    email = data.get("email")
    new_password = data.get("password")

    if not email or not new_password:
        return jsonify({"success": False, "message": "Email and new password required"}), 400

    # Check if OTP verified (optional: only allow if exists in store)
    if email not in forgot_password_otp_store:
        return jsonify({"success": False, "message": "OTP not verified"}), 403

    # Update password in Firestore
    users_ref = firebase_db.db.collection("users")
    query = users_ref.where("email", "==", email).limit(1).get()
    if not query:
        return jsonify({"success": False, "message": "User not found"}), 404

    user_doc = query[0].reference
    user_doc.update({"password": new_password})

    # Remove OTP record
    del forgot_password_otp_store[email]

    return jsonify({"success": True, "message": "Password updated successfully"}), 200



def send_password_reset_email_otp(email, otp):
    try:
        print(f"[DEBUG] Sending OTP email to {email}")
        print(f"[DEBUG] Using FROM_EMAIL: {FROM_EMAIL}")

        url = "https://api.sendinblue.com/v3/smtp/email"
        headers = {
            "api-key": SENDINBLUE_API_KEY,
            "Content-Type": "application/json"
        }

        subject = "🔐 Grocery App – Password Reset Verification Code"
        html_content = f"""
        <div style="font-family: Arial, sans-serif; color: #333; padding: 20px;">
            <h2 style="color:#4CAF50;">Grocery App Password Reset</h2>
            <p>Hello,</p>
            <p>We received a request to reset your password for your <b>Grocery App</b> account.</p>
            <p style="font-size:16px;">
                Please use the following One-Time Password (OTP) to reset your password:
            </p>
            <div style="background:#f4f4f4; padding:10px 20px; margin:20px 0; border-radius:8px; text-align:center;">
                <h1 style="letter-spacing:5px; color:#2E7D32;">{otp}</h1>
            </div>
            <p>This OTP is valid for <b>2 minutes</b>. Do not share it with anyone.</p>
            <p>If you didn’t request a password reset, you can safely ignore this email.</p>
            <br/>
            <p style="font-size:12px; color:#888;">– The Grocery App Team</p>
        </div>
        """

        data = {
            "sender": {"name": "Grocery App", "email": FROM_EMAIL},
            "to": [{"email": email}],
            "subject": subject,
            "htmlContent": html_content
        }

        response = requests.post(url, headers=headers, json=data)
        print(f"[DEBUG] Sendinblue response: {response.status_code}, {response.text}")

        return response.status_code in (200, 201)

    except Exception as e:
        print(f"[ERROR] Failed to send OTP email: {e}")
        return False


if __name__ == "__main__":
    print("Gunicorn setup complete, about to run...")
    app.run(host="0.0.0.0", port=5000, debug=True)
