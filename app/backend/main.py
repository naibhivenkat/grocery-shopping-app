import base64
import datetime
import io
import jwt
import logging
import os
import random
import razorpay
import requests
import time
import uuid
from datetime import datetime
from datetime import datetime, timedelta, timezone
from firebase_admin import credentials, auth, db
from firebase_admin import messaging
from flask import Flask, request, jsonify, g, Response
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT, TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from weasyprint import HTML, CSS

import firebase_db
from wallet_routes import wallet_bp

app = Flask(__name__)
app.register_blueprint(wallet_bp)

# Initialize limiter
limiter = Limiter(key_func=get_remote_address)
limiter.init_app(app)

CORS(app)
SECRET_KEY = os.getenv("SECRET_KEY")  # keep secret and safe!

# logging.basicConfig(level=logging.INFO)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("order_api")

SENDINBLUE_API_KEY = os.getenv("SENDINBLUE_API_KEY")
FROM_EMAIL = os.getenv("FROM_EMAIL")
logo_url = "https://cdn-icons-png.flaticon.com/512/263/263142.png"
otp_store = {}
forgot_password_otp_store = {}

GITHUB_REPO = "naibhivenkat/grocery-shopping-app"

# 🔹 Initialize Razorpay client
RAZORPAY_KEY_ID = "rzp_test_RKK3DuGSaxK9fR"
RAZORPAY_KEY_SECRET = "VgVc96Pdn3t5T8ieX0nb2ajt"
razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

# Count of total HTTP requests
REQUEST_COUNT = Counter(
    "flask_app_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "http_status"]
)

# Histogram for request latency
REQUEST_LATENCY = Histogram(
    "flask_app_request_latency_seconds",
    "HTTP request latency in seconds",
    ["endpoint"]
)


@app.route("/")
def index():
    return "Backend is running!"


@app.get("/healthz")
def healthz():
    return jsonify(status="Up and Running"), 200


@app.get("/internal-healthz")
@limiter.exempt
def public_health():
    try:
        # Example: perform internal dependency checks here
        service_ok = True  # Replace with real check (e.g., DB, cache)
        if service_ok:
            logging.info("✅ /internal-healthz OK")
            return jsonify(status="Up and Running"), 200
        else:
            logging.warning("⚠️ /internal-healthz reports degraded service")
            return jsonify(status="Degraded", error="Dependency unavailable"), 503
    except Exception as e:
        logging.error(f"❌ Health check exception: {e}")
        return jsonify(status="Service Down", error=str(e)), 503


@app.before_request
def start_timer():
    g.start_time = time.time()


@app.after_request
def record_metrics(response):
    request_latency = time.time() - g.start_time
    REQUEST_LATENCY.labels(endpoint=request.path).observe(request_latency)
    REQUEST_COUNT.labels(
        method=request.method,
        endpoint=request.path,
        http_status=response.status_code
    ).inc()
    return response


@app.before_request
def load_current_user():
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        try:
            # ✅ decode with same algorithm
            payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
            g.current_user = payload
        except jwt.ExpiredSignatureError:
            g.current_user = None
        except jwt.InvalidTokenError:
            g.current_user = None
    else:
        g.current_user = None


def generate_token(user):
    IST = timezone(timedelta(hours=5, minutes=30))
    exp_time = datetime.now(IST) + timedelta(days=7)

    # ✅ Use correct ID field based on role
    user_id = user.get("customerId") or user.get("shopkeeperId") or user.get("id")

    payload = {
        "id": user_id,
        "username": user.get("username"),
        "role": user.get("role"),
        "exp": int(exp_time.timestamp())
    }

    token = jwt.encode(payload, SECRET_KEY, algorithm="HS256")
    if isinstance(token, bytes):
        token = token.decode("utf-8")

    return token


@app.route('/favicon.ico')
def favicon():
    return '', 204  # No content, no warning


@app.route("/metrics")
def metrics():
    return generate_latest(), 200, {"Content-Type": CONTENT_TYPE_LATEST}


@app.route("/login", methods=["POST"])
def login():
    data = request.get_json()
    username = data.get("username")
    password = data.get("password")

    logger.info(f"🔵 LOGIN: Attempt username={username}")

    # ----------------------------------------------------------
    # Fetch user
    # ----------------------------------------------------------
    user = firebase_db.get_user_by_username(username)
    if not user:
        logger.warning(f"⚠️ LOGIN FAILED: User not found: {username}")
        return jsonify({"success": False, "message": "User not found"}), 404

    if user.get("password") != password:
        logger.warning(f"⚠️ LOGIN FAILED: Wrong password for {username}")
        return jsonify({"success": False, "message": "Invalid password"}), 401

    logger.info(f"🔵 LOGIN: User authenticated: {username}")

    # ----------------------------------------------------------
    # SHOP INFO (for shopowner)
    # ----------------------------------------------------------
    shop_info = None

    if user.get("role") in ["shopkeeper", "shopowner"]:
        sk_id = user.get("shopkeeperId")
        logger.info(f"🔵 LOGIN: Fetching shop for shopkeeperId={sk_id}")

        shop_query = (
            firebase_db.db.collection("shops")
            .where("shopkeeper_id", "==", sk_id)
            .stream()
        )

        for doc in shop_query:
            shop_data = doc.to_dict()
            shop_info = {
                "id": doc.id,
                "name": shop_data.get("name"),
                "address": shop_data.get("address"),
                "location": shop_data.get("location"),
                "contact": shop_data.get("contact"),
                "shopkeeper_id": shop_data.get("shopkeeper_id"),
            }
            logger.info(f"🔵 LOGIN: Shop found: {shop_info}")
            break

    # ----------------------------------------------------------
    # FIX: CUSTOMER & SHOPKEEPER IDS (ensure always present)
    # ----------------------------------------------------------
    customer_id = user.get("customerId") or user.get("customer_id")
    shopkeeper_id = user.get("shopkeeperId") or user.get("shopkeeper_id")

    if user.get("role") == "customer" and not customer_id:
        logger.warning(f"⚠️ LOGIN FIX: customerId missing → using user.id")
        customer_id = user.get("id")

    if user.get("role") in ["shopkeeper", "shopowner"] and not shopkeeper_id:
        logger.warning(f"⚠️ LOGIN FIX: shopkeeperId missing → using user.id")
        shopkeeper_id = user.get("id")

    # ----------------------------------------------------------
    # Build response user object
    # ----------------------------------------------------------
    response_user = {
        "id": user.get("id"),
        "username": user.get("username"),
        "fullName": user.get("fullName") or user.get("name", ""),
        "email": user.get("email", ""),
        "phone": user.get("phone", ""),
        "role": user.get("role", ""),
        "customerId": customer_id,
        "shopkeeperId": shopkeeper_id,
        "address": user.get("address", ""),
        "location": user.get("location", ""),
        "photoUrl": user.get("photoUrl") or user.get("photo_url", ""),
        "photoBase64": user.get("photoBase64") or user.get("photo_base64", ""),
        "shop": shop_info,
        "shopExists": shop_info is not None
    }

    logger.info(f"🔵 LOGIN: Final response_user = {response_user}")

    # ----------------------------------------------------------
    # Generate JWT Token
    # ----------------------------------------------------------
    token = generate_token(response_user)

    logger.info(
        f"✅ LOGIN SUCCESS: username={username}, role={user.get('role')}, "
        f"userId={response_user.get('customerId') or response_user.get('shopkeeperId')}"
    )

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
        "shop": None,  # no shop yet
        "shopExists": False  # must create after login
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
        "shop": None,  # no shop yet
        "shopExists": False  # must create after login
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
        logger.info(f"Request JSON: {data}")  # debug
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
@app.route("/api/shops/<shop_id>", methods=["GET"])
def get_shop_by_id(shop_id):
    try:
        shop = firebase_db.db.collection("shops").document(shop_id).get()
        if not shop.exists:
            return jsonify({"error": "Shop not found"}), 404
        return jsonify(shop.to_dict()), 200
    except Exception as e:
        logger.info(f"[ERROR] Failed to fetch shop {shop_id}: {e}")
        return jsonify({"error": str(e)}), 500


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
    # ✅ Check logged-in user
    user = getattr(g, "current_user", None)
    if not user:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    if user.get("role") not in ["shopowner", "shopkeeper"]:
        return jsonify({'success': False, 'message': 'Unauthorized role'}), 403

    # ✅ Get data from request
    data = request.get_json(silent=True) or {}
    name = data.get('name')
    address = data.get('address')
    contact = data.get('contact')
    shopkeeper_id = user.get("id")  # use logged-in user's ID

    if not all([name, address, contact, shopkeeper_id]):
        return jsonify({'success': False, 'message': 'Missing fields'}), 400

    # ✅ Define IST timezone
    IST = timezone(timedelta(hours=5, minutes=30))
    created_at = datetime.now(IST).replace(microsecond=0).isoformat()

    # ✅ Create shop dict
    shop_dict = {
        "name": name,
        "address": address,
        "contact": contact,
        "shopkeeper_id": shopkeeper_id,
        "createdAt": created_at
    }

    shop = firebase_db.append_shop(shop_dict)

    # ✅ Update user document
    user_ref = firebase_db.db.collection("users").where("shopkeeperId", "==",
                                                        shopkeeper_id).stream()
    for doc in user_ref:
        firebase_db.db.collection("users").document(doc.id).update({
            "shopId": shop["id"],
            "shop": {
                "id": shop["id"],
                "name": shop["name"],
                "shopkeeper_id": shop["shopkeeper_id"]
            }
        })
        break

    # ✅ Return response
    return jsonify({
        'success': True,
        'message': 'Shop created successfully',
        'shop': {
            'id': shop['id'],
            'name': shop['name'],
            'address': shop['address'],
            'contact': shop['contact'],
            'createdAt': created_at
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


# @app.route("/api/orders", methods=["POST"])
# def create_order():
#     logger.info("🟦 DEBUG: /api/orders endpoint hit")
#
#     data = request.json
#     logger.info(f"🟦 DEBUG: Incoming order data = {data}")
#
#     # 1️⃣ Compute total
#     items = data.get("items", [])
#     total = 0
#     detailed_items = []
#     ist = timezone(timedelta(hours=5, minutes=30))
#
#     for entry in items:
#         item_id = entry.get("item_id")
#         quantity = float(entry.get("quantity", 1))
#         item_doc = firebase_db.db.collection("items").document(item_id).get()
#
#         if item_doc.exists:
#             item = item_doc.to_dict()
#             item_price = float(item.get("price", 0))
#             total += item_price * quantity
#             detailed_items.append({
#                 "item_id": item_id,
#                 "name": item.get("name", ""),
#                 "price": item_price,
#                 "quantity": quantity
#             })
#
#     # 2️⃣ Current logged-in user
#     user = getattr(g, "current_user", None)
#     if not user:
#         return jsonify({"success": False, "message": "User not logged in"}), 401
#
#     user_ref = firebase_db.db.collection("users").document(user["id"])
#     user_doc = user_ref.get()
#
#     # Fallback for users where Firestore ID != customerId
#     if not user_doc.exists:
#         fallback = firebase_db.db.collection("users").where("customerId", "==", user["id"]).get()
#
#         if len(fallback) == 0:
#             return jsonify({"success": False, "message": "User not found"}), 404
#
#         user_doc = fallback[0]
#         user_ref = user_doc.reference
#         user_doc = user_doc.to_dict()
#
#     else:
#         user_doc = user_doc.to_dict()
#
#     # 3️⃣ Resolve shop docId from shopId
#     input_shop_id = data["shopId"]
#     invoice_url = data.get("invoice_url", "")
#
#     shop_query = firebase_db.db.collection("shops").where("id", "==", input_shop_id).stream()
#     shop_doc_id = None
#     shop_name = ""
#
#     for doc in shop_query:
#         shop_doc_id = doc.id
#         shop_name = doc.to_dict().get("name", "")
#         break
#
#     if not shop_doc_id:
#         return jsonify({"success": False, "message": "Invalid shopId"}), 400
#
#     # 4️⃣ Payment logic
#     payment_method = data.get("payment_method", "Razorpay")
#     razorpay_order_id = None
#
#     # ⭐ WALLET PAYMENT FLOW (corrected)
#     if payment_method.lower() == "wallet":
#
#         wallet_balance = float(user_doc.get("wallet_balance", 0.0))
#
#         if wallet_balance < total:
#             return jsonify({"success": False, "message": "Insufficient wallet balance"}), 400
#
#         new_balance = wallet_balance - total
#         user_ref.update({"wallet_balance": new_balance})
#
#         logger.info(f"🟦 Wallet deduction: {wallet_balance} → {new_balance}")
#
#     # ⭐ RAZORPAY FLOW (unchanged)
#     elif payment_method == "Razorpay":
#         razorpay_order = razorpay_client.order.create({
#             "amount": int(total * 100),
#             "currency": "INR",
#             "receipt": f"order_{datetime.now(ist).replace(microsecond=0).isoformat()}",
#             "payment_capture": 1
#         })
#         razorpay_order_id = razorpay_order["id"]
#
#     # 5️⃣ Save the order
#     order_dict = {
#         "shopId": shop_doc_id,
#         "shopName": shop_name,
#         "customer_id": user["id"],
#         "customer": {
#             "id": user["id"],
#             "username": user["username"],
#             "fullName": user_doc.get("fullName", ""),
#             "email": user_doc.get("email", ""),
#             "phone": user_doc.get("phone", "")
#         },
#         "items": detailed_items,
#         "total": total,
#         "payment_method": payment_method,
#         "transaction_id": (
#             "" if payment_method == "Razorpay"
#             else "Wallet" if payment_method.lower() == "wallet"
#             else "Cash"
#         ),
#         "razorpay_order_id": razorpay_order_id or "",
#         "status": "Pending" if payment_method == "Razorpay" else "Confirmed",
#         "invoice_url": invoice_url,
#         "created_at": datetime.now(ist).replace(microsecond=0).isoformat(),
#     }
#
#     new_order = firebase_db.append_order(order_dict)
#
#     # 6️⃣ If wallet payment, create transaction now
#     if payment_method.lower() == "wallet":
#         tx_id = str(uuid.uuid4())
#         firebase_db.db.collection("transactions").document(tx_id).set({
#             "userId": user["id"],
#             "type": "Payment",
#             "amount": total,
#             "dateTime": datetime.utcnow(),
#             "orderId": new_order["order_uuid"]
#         })
#
#     # 🔔 Send notification to shopkeeper
#     try:
#         shop_doc = firebase_db.db.collection("shops").document(shop_doc_id).get()
#         if shop_doc.exists:
#             shopkeeper_id = shop_doc.to_dict().get("shopkeeper_id")
#             if shopkeeper_id:
#                 tokens = firebase_db.get_fcm_tokens_for_user(shopkeeper_id)
#                 if tokens:
#                     firebase_db.send_fcm_notification_to_tokens(
#                         tokens,
#                         "New Order Received",
#                         f"New order from {user_doc.get('fullName') or user['username']}",
#                         {"order_id": new_order["order_uuid"], "type": "new_order"}
#                     )
#     except Exception as e:
#         logger.error(f"❌ Notification error: {e}")
#
#     # 7️⃣ Final response
#     if payment_method == "Razorpay":
#         return jsonify({
#             "success": True,
#             "order_id": new_order["order_uuid"],
#             "razorpay_order_id": razorpay_order_id,
#             "amount": total,
#             "shopName": shop_name
#         })
#
#     return jsonify({
#         "success": True,
#         "order_id": new_order["order_uuid"],
#         "amount": total,
#         "message": f"{payment_method} order placed successfully",
#         "shopName": shop_name
#     })
#
#
# @app.route("/api/verify_payment", methods=["POST"])
# def verify_payment():
#     data = request.json or {}
#     order_uuid = data.get("order_id")
#     razorpay_payment_id = data.get("razorpay_payment_id")
#     razorpay_order_id = data.get("razorpay_order_id")
#     razorpay_signature = data.get("razorpay_signature")
#
#     if not order_uuid:
#         return jsonify({"success": False, "message": "Missing order_id"}), 400
#
#     order_doc = firebase_db.get_order_by_uuid(order_uuid)
#     if not order_doc:
#         return jsonify({"success": False,
#                         "message": "Order not found - Verify Payment"}), 404  ##TODO: NEED TO CHANGE MSG
#
#     payment_method = order_doc.get("payment_method", "Razorpay")
#
#     if payment_method != "Cash":
#         if not razorpay_payment_id or not razorpay_order_id or not razorpay_signature:
#             return jsonify({"success": False, "message": "Missing Razorpay payment details"}), 400
#         try:
#             razorpay_client.utility.verify_payment_signature({
#                 "razorpay_order_id": razorpay_order_id,
#                 "razorpay_payment_id": razorpay_payment_id,
#                 "razorpay_signature": razorpay_signature
#             })
#         except razorpay.errors.SignatureVerificationError:
#             return jsonify({"success": False, "message": "Payment verification failed"}), 400
#         firebase_db.update_order_status(order_uuid, "Paid",
#                                         extra_fields={"transaction_id": razorpay_payment_id})
#         message = "Payment verified"
#     else:
#         firebase_db.update_order_status(order_uuid, "Confirmed")
#         message = "Cash order confirmed"
#
#     return jsonify({"success": True, "message": f"{message} successfully"})

@app.route("/api/orders", methods=["POST"])
def create_order():
    logger.info("🟦 DEBUG: /api/orders endpoint hit")

    data = request.json
    logger.info(f"🟦 DEBUG: Incoming order data = {data}")

    # 1️⃣ Compute total
    items = data.get("items", [])
    total = 0
    detailed_items = []
    ist = timezone(timedelta(hours=5, minutes=30))

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

    # 2️⃣ Current logged-in user
    user = getattr(g, "current_user", None)
    if not user:
        return jsonify({"success": False, "message": "User not logged in"}), 401

    user_ref = firebase_db.db.collection("users").document(user["id"])
    user_doc = user_ref.get()

    # Fallback for users where Firestore ID != customerId
    if not user_doc.exists:
        fallback = firebase_db.db.collection("users").where("customerId", "==", user["id"]).get()

        if len(fallback) == 0:
            return jsonify({"success": False, "message": "User not found"}), 404

        user_doc = fallback[0]
        user_ref = user_doc.reference
        user_doc = user_doc.to_dict()

    else:
        user_doc = user_doc.to_dict()

    # 3️⃣ Resolve shop docId from shopId
    input_shop_id = data["shopId"]
    invoice_url = data.get("invoice_url", "")

    shop_query = firebase_db.db.collection("shops").where("id", "==", input_shop_id).stream()
    shop_doc_id = None
    shop_name = ""

    for doc in shop_query:
        shop_doc_id = doc.id
        shop_name = doc.to_dict().get("name", "")
        break

    if not shop_doc_id:
        return jsonify({"success": False, "message": "Invalid shopId"}), 400

    # 4️⃣ Payment logic
    payment_method = data.get("payment_method", "Razorpay")
    razorpay_order_id = None

    # ⭐ WALLET FLOW
    if payment_method.lower() == "wallet":

        wallet_balance = float(user_doc.get("wallet_balance", 0.0))

        if wallet_balance < total:
            return jsonify({"success": False, "message": "Insufficient wallet balance"}), 400

        new_balance = wallet_balance - total
        user_ref.update({"wallet_balance": new_balance})
        logger.info(f"🟦 Wallet deduction: {wallet_balance} → {new_balance}")

    # ⭐ RAZORPAY FLOW
    elif payment_method == "Razorpay":
        razorpay_order = razorpay_client.order.create({
            "amount": int(total * 100),
            "currency": "INR",
            "receipt": f"order_{datetime.now(ist).replace(microsecond=0).isoformat()}",
            "payment_capture": 1
        })
        razorpay_order_id = razorpay_order["id"]

    # 5️⃣ Save the order
    order_dict = {
        "shopId": shop_doc_id,
        "shopName": shop_name,
        "customer_id": user["id"],
        "customer": {
            "id": user["id"],
            "username": user["username"],
            "fullName": user_doc.get("fullName", ""),
            "email": user_doc.get("email", ""),
            "phone": user_doc.get("phone", "")
        },
        "items": detailed_items,
        "total": total,
        "payment_method": payment_method,
        "transaction_id": (
            "" if payment_method == "Razorpay"
            else "Wallet" if payment_method.lower() == "wallet"
            else "Cash"
        ),
        "razorpay_order_id": razorpay_order_id or "",
        "status": "Pending" if payment_method == "Razorpay" else "Confirmed",
        "invoice_url": invoice_url,
        "created_at": datetime.now(ist).replace(microsecond=0).isoformat(),
    }

    new_order = firebase_db.append_order(order_dict)

    # 6️⃣ Wallet transaction record
    if payment_method.lower() == "wallet":
        tx_id = str(uuid.uuid4())
        firebase_db.db.collection("transactions").document(tx_id).set({
            "userId": user["id"],
            "type": "Payment",
            "amount": total,
            "dateTime": datetime.utcnow(),
            "orderId": new_order["order_uuid"]
        })

    # 🧊 REMOVED (Old notification block for Razorpay)
    # 🔥 CHANGE: Now notify ONLY for CASH & WALLET

    if payment_method.lower() in ["wallet", "cash"]:
        try:
            shop_doc = firebase_db.db.collection("shops").document(shop_doc_id).get()
            if shop_doc.exists:
                shopkeeper_id = shop_doc.to_dict().get("shopkeeper_id")
                if shopkeeper_id:
                    tokens = firebase_db.get_fcm_tokens_for_user(shopkeeper_id)
                    if tokens:
                        firebase_db.send_fcm_notification_to_tokens(
                            tokens,
                            "New Order Received",
                            f"New order from {user_doc.get('fullName') or user['username']}",
                            {"order_id": new_order["order_uuid"], "type": "new_order"}
                        )
        except Exception as e:
            logger.error(f"❌ Notification error: {e}")

    # 7️⃣ Final response
    if payment_method == "Razorpay":
        return jsonify({
            "success": True,
            "order_id": new_order["order_uuid"],
            "razorpay_order_id": razorpay_order_id,
            "amount": total,
            "shopName": shop_name
        })

    return jsonify({
        "success": True,
        "order_id": new_order["order_uuid"],
        "amount": total,
        "message": f"{payment_method} order placed successfully",
        "shopName": shop_name
    })


@app.route("/api/verify_payment", methods=["POST"])
def verify_payment():
    data = request.json or {}
    order_uuid = data.get("order_id")
    razorpay_payment_id = data.get("razorpay_payment_id")
    razorpay_order_id = data.get("razorpay_order_id")
    razorpay_signature = data.get("razorpay_signature")

    if not order_uuid:
        return jsonify({"success": False, "message": "Missing order_id"}), 400

    order_doc = firebase_db.get_order_by_uuid(order_uuid)
    if not order_doc:
        return jsonify({"success": False, "message": "Order not found - Verify Payment"}), 404

    payment_method = order_doc.get("payment_method", "Razorpay")

    # ------------------ RAZORPAY PAYMENT ------------------
    if payment_method != "Cash":

        if not razorpay_payment_id or not razorpay_order_id or not razorpay_signature:
            return jsonify({"success": False, "message": "Missing Razorpay payment details"}), 400

        # Verify Signature
        try:
            razorpay_client.utility.verify_payment_signature({
                "razorpay_order_id": razorpay_order_id,
                "razorpay_payment_id": razorpay_payment_id,
                "razorpay_signature": razorpay_signature
            })
        except razorpay.errors.SignatureVerificationError:
            return jsonify({"success": False, "message": "Payment verification failed"}), 400

        # Update order status
        firebase_db.update_order_status(order_uuid, "Paid",
                                        extra_fields={"transaction_id": razorpay_payment_id})
        message = "Payment verified"

        # 🔥 ADDED — SEND NOTIFICATION AFTER SUCCESSFUL PAYMENT
        try:
            shop_id = order_doc.get("shopId")
            shop_doc = firebase_db.db.collection("shops").document(shop_id).get()

            if shop_doc.exists:
                shopkeeper_id = shop_doc.to_dict().get("shopkeeper_id")

                if shopkeeper_id:
                    tokens = firebase_db.get_fcm_tokens_for_user(shopkeeper_id)

                    if tokens:
                        firebase_db.send_fcm_notification_to_tokens(
                            tokens,
                            "New Paid Order",
                            f"New paid order from {order_doc['customer'].get('fullName')}",
                            {"order_id": order_uuid, "type": "new_order"}
                        )
        except Exception as e:
            logger.error(f"❌ Notification error (Razorpay): {e}")

    # ------------------ CASH PAYMENT ------------------
    else:
        firebase_db.update_order_status(order_uuid, "Confirmed")
        message = "Cash order confirmed"

        # 🔥 ADDED — Notify after cash confirmation
        try:
            shop_id = order_doc.get("shopId")
            shop_doc = firebase_db.db.collection("shops").document(shop_id).get()

            if shop_doc.exists:
                shopkeeper_id = shop_doc.to_dict().get("shopkeeper_id")

                if shopkeeper_id:
                    tokens = firebase_db.get_fcm_tokens_for_user(shopkeeper_id)
                    if tokens:
                        firebase_db.send_fcm_notification_to_tokens(
                            tokens,
                            "New Cash Order",
                            f"New cash order from {order_doc['customer'].get('fullName')}",
                            {"order_id": order_uuid, "type": "new_order"}
                        )
        except Exception as e:
            logger.error(f"❌ Notification error (Cash): {e}")

    return jsonify({"success": True, "message": f"{message} successfully"})

@app.route("/api/update_order_status", methods=["POST"])
def update_order_status():
    data = request.json or {}
    order_uuid = data.get("order_id")
    new_status = data.get("status")

    if not order_uuid or not new_status:
        return jsonify({"success": False, "message": "Missing data"}), 400

    normalized_status = new_status.strip().lower()

    # -----------------------------------------
    #  FETCH ORDER (includes correct doc_id)
    # -----------------------------------------
    order_doc = firebase_db.get_order_by_uuid(order_uuid)
    if not order_doc:
        return jsonify({"success": False, "message": "Order not found"}), 404

    order_firestore_id = order_doc["doc_id"]
    customerId = order_doc.get("customer", {}).get("id") or order_doc.get("customer_id")
    total = float(order_doc["total"])

    # -----------------------------------------
    #  IDEMPOTENT REFUND CHECK
    # -----------------------------------------
    if normalized_status.startswith("cancel") and order_doc.get("refund_processed"):
        logger.info(f"♻️ Refund already processed for order {order_uuid}")
        return jsonify({"success": True, "message": "Refund already processed"}), 200

    # -----------------------------------------
    #  UPDATE ORDER STATUS
    # -----------------------------------------
    firebase_db.db.collection("orders").document(order_firestore_id).update({
        "status": new_status
    })
    logger.info(f"✅ Order {order_uuid} updated → {new_status}")

    # -----------------------------------------
    #  REFUND SECTION
    # -----------------------------------------
    try:
        if normalized_status.startswith("cancel"):
            logger.info("==== REFUND DEBUG START ====")
            logger.info(f"order_uuid = {order_uuid}")
            logger.info(f"doc_id = {order_firestore_id}")
            logger.info(f"payment_method = {order_doc.get('payment_method')}")
            logger.info(f"amount = {total}")
            logger.info(f"customerId = {customerId}")
            logger.info("==== REFUND DEBUG END ====")

            payment_method = order_doc.get("payment_method", "").lower()

            if payment_method == "cash":
                logger.info("⛔ Cash order cancelled → no refund needed")
                return jsonify({"success": True, "message": "Order cancelled (cash)"}), 200

            # Wallet or Razorpay → Refund to WALLET
            process_wallet_refund(customerId, total, order_uuid, order_firestore_id)

        if normalized_status.lower() == "delivered":
            try:
                logger.info(f"📦 Generating final delivery invoice for order {order_uuid}...")
                success = process_and_send_invoice(order_doc, logo_url=logo_url)
                if success:
                    logger.info("✅ Invoice generated, emailed, and uploaded to Firestore.")
            except Exception as e:
                logger.info(f"[ERROR] Failed to send delivery invoice: {e}")

    except Exception as e:
        logger.info(f"[ERROR] Refund failed: {e}")

    return jsonify({"success": True, "message": f"Order updated to {new_status}"}), 200


def process_wallet_refund(customerId, amount, order_uuid, order_firestore_id):
    """Refund ANY payment method into wallet (Wallet + Razorpay refunded to wallet)."""

    try:
        # Resolve Firestore user doc
        user_ref, snap = firebase_db.get_user_firestore_ref(customerId)

        if not snap:
            logger.info(f"❌ Refund failed — user not found for {customerId}")
            return

        firestore_user_id = user_ref.id  # REAL doc ID

        # -----------------------------------------
        #  CALL INTERNAL /wallet/refund API
        # -----------------------------------------
        payload = {
            "user_id": firestore_user_id,
            "customerId": customerId,
            "amount": amount,
            "order_id": order_uuid
        }

        resp = requests.post(
            url="https://grocery-backend-956424262985.asia-south1.run.app/wallet/refund",
            json=payload,
            timeout=5
        )

        logger.info(f"🔁 /wallet/refund response: {resp.status_code} {resp.text}")

        if resp.status_code != 200:
            logger.info(f"❌ Wallet refund API failed: {resp.text}")
            return

        # -----------------------------------------
        #  MARK ORDER AS REFUNDED
        # -----------------------------------------
        firebase_db.db.collection("orders").document(order_firestore_id).update({
            "refund_processed": True
        })

        logger.info(f"💰 WALLET REFUND (API) → +₹{amount} added for {firestore_user_id}")

    except Exception as e:
        logger.info(f"[ERROR] process_wallet_refund failed: {e}")


@app.route("/api/orders/shopkeeper/<shop_id>", methods=["GET"])
def get_shop_orders(shop_id):
    orders = firebase_db.get_orders_by_shop(shop_id)

    # 🔹 Fetch shop details once
    shop_doc = firebase_db.db.collection("shops").document(shop_id).get()
    shop_name = "Unknown"
    if shop_doc.exists:
        shop_data = shop_doc.to_dict()
        shop_name = shop_data.get("name", "Unknown")

    # 🔹 Add shopName to every order
    enriched_orders = []
    for order in orders:
        if "shopName" not in order or not order["shopName"]:
            order["shopName"] = shop_name
        enriched_orders.append(order)

    return jsonify(enriched_orders)


@app.route("/api/orders/customer/<customer_id>", methods=["GET"])
def get_customer_orders(customer_id):
    orders = firebase_db.get_orders_by_customer(customer_id)
    for order in orders:
        order["invoice_url"] = order.get("invoice_url", "")
    return jsonify(orders)


@app.route('/api/orders/<order_uuid>', methods=['GET'])
def get_order_details(order_uuid):
    orders_ref = firebase_db.db.collection("orders")

    # 1️⃣ Try direct Firestore doc ID
    doc = orders_ref.document(order_uuid).get()
    if doc.exists:
        data = doc.to_dict()
        data["order_uuid"] = doc.id
        data["doc_id"] = doc.id
        return jsonify(data)

    # 2️⃣ Try order_uuid field (YOUR REAL FIELD)
    query = orders_ref.where("order_uuid", "==", order_uuid).limit(1).stream()
    order_list = list(query)
    if order_list:
        order_doc = order_list[0]
        data = order_doc.to_dict()
        data["order_uuid"] = order_doc.id
        data["doc_id"] = order_doc.id
        return jsonify(data)

    # 3️⃣ Try id field (optional)
    query = orders_ref.where("id", "==", order_uuid).limit(1).stream()
    order_list = list(query)
    if order_list:
        order_doc = order_list[0]
        data = order_doc.to_dict()
        data["order_uuid"] = order_doc.id
        data["doc_id"] = order_doc.id
        return jsonify(data)

    return jsonify({'error': 'Order not found - Get Order Details'}), 404


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
    return jsonify({"success": False,
                    "message": "Order not found -Patch order"}), 404  ##TODO: NEED TO CHANGE MSG


@app.route("/api/orders/shopkeeper", methods=["GET"])
def get_shop_orders_multi():
    # Accepts multiple shop_ids as query params: ?shop_id=abc&shop_id=xyz
    ids = request.args.getlist('shop_id')
    all_orders = []
    for shop_id in ids:
        all_orders.extend(firebase_db.get_orders_by_shop(shop_id))
    return jsonify(all_orders), 200


@app.route("/check_update", methods=["GET"])
def check_update():
    try:
        # Get user role from query parameter
        role = request.args.get("role", "customer").lower()
        if role not in ["customer", "shopowner"]:
            return jsonify({"error": "Invalid role"}), 400

        # Fetch the latest release from GitHub
        api_url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
        r = requests.get(api_url, timeout=10)
        r.raise_for_status()
        release = r.json()

        # Extract version info from tag
        version_name = release.get("tag_name", "0.1")
        if version_name.startswith("v"):
            version_name = version_name[1:]

        # Convert version_name to Android versionCode (1.153 -> 1153)
        parts = version_name.split(".")
        version_code = int("".join(f"{int(p):02d}" for p in parts))

        # Find APK asset dynamically based on role
        apk_url = None
        apk_size = 0
        for asset in release.get("assets", []):
            if role in asset["name"].lower() and asset["name"].endswith(".apk"):
                apk_url = asset["browser_download_url"]
                apk_size = asset.get("size", 0)
                break

        if not apk_url:
            logging.error("No APK found for role %s in latest release", role)
            return jsonify({"error": f"No APK found for role {role}"}), 500

        logging.info("Returning version %s (code %d) with size %d for role %s",
                     version_name, version_code, apk_size, role)
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
        logger.info(f"SENDINBLUE_API_KEY {SENDINBLUE_API_KEY}")
        logger.info(f"FROM_EMAIL : {FROM_EMAIL}")

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
        logger.info(f"[DEBUG] Sendinblue response: {response.status_code}, {response.text}")

        return response.status_code in (200, 201)

    except Exception as e:
        logger.info(f"[ERROR] Failed to send OTP email: {e}")
        return False



@app.route("/send_otp", methods=["POST"])
def send_otp():
    data = request.get_json()
    email = data.get("email")

    if not email:
        return jsonify({"status": "error", "message": "Email required"}), 400

    otp = random.randint(100000, 999999)
    expiry = int(time.time()) + 120  # 2 minutes

    # 🔥 SAVE OTP IN FIRESTORE INSTEAD OF RAM
    firebase_db.db.collection("otp").document(email).set({
        "otp": str(otp),
        "expiry": expiry,
        "attempts": 0
    })

    if send_email_otp(email, otp):
        logger.info(f"Send OTP to {email} | OTP={otp}")
        return jsonify({"status": "success", "message": "OTP sent"}), 200

    return jsonify({"status": "error", "message": "Failed to send OTP"}), 500


@app.route("/verify_otp", methods=["POST"])
def verify_otp():
    data = request.get_json()
    email = data.get("email")
    otp_input = str(data.get("otp"))

    logger.info(f"Verify OTP | EMAIL={email} | OTP_ENTERED={otp_input}")

    # 🔥 FETCH OTP DOCUMENT FROM FIRESTORE
    otp_doc = firebase_db.db.collection("otp").document(email).get()

    if not otp_doc.exists:
        return jsonify({"status": "error", "message": "No OTP sent for this email"}), 400

    record = otp_doc.to_dict()

    # attempt limit
    if record.get("attempts", 0) >= 5:
        return jsonify({"status": "error", "message": "Too many attempts. Request new OTP"}), 400

    current_time = int(time.time())
    if current_time > record["expiry"]:
        return jsonify({"status": "error", "message": "OTP expired"}), 400

    # OTP MATCH SUCCESS
    if str(record["otp"]) == otp_input:
        # delete after success
        firebase_db.db.collection("otp").document(email).delete()
        logger.info("OTP DELETED SUCCESSFULLY FROM FIREBASE STORAGE")
        return jsonify({"status": "success", "message": "OTP verified"}), 200

    # increment attempts count
    firebase_db.db.collection("otp").document(email).update({
        "attempts": record.get("attempts", 0) + 1
    })

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
    logger.info(f"Welcome email response: {response.status_code} | {response.text}")
    return response.status_code in [200, 201]


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
        q = firebase_db.db.collection("shops").where("id", "==", raw_shop_id).limit(1).stream()
        shop_doc = None
        canonical_shop_id = None
        for d in q:
            shop_doc = d.to_dict()
            canonical_shop_id = d.id
            logger.info(f"canonical_shop_id : {canonical_shop_id}")
            break

    if not canonical_shop_id:
        return jsonify({'success': False, 'message': f'Shop not found for id={raw_shop_id}'}), 404

    IST = timezone(timedelta(hours=5, minutes=30))
    saved_items = []
    username = user.get('username')

    for it in items:
        item_dict = {
            "name": it.get("name"),
            "price": float(it.get("price") or 0),
            "quantity": int(it.get("stockQuantity") or 0),
            "description": it.get("description") or "",
            "shopId": canonical_shop_id,
            "createdAt": datetime.now(IST).replace(microsecond=0).isoformat(),
            "createdBy": username,

            # ✅ ADD THIS LINE
            "image": it.get("image") or it.get("imageUrl") or ""
        }

        saved_items.append(firebase_db.append_item(item_dict))

    return jsonify({
        'success': True,
        'message': 'Items added successfully',
        'items': saved_items
    }), 201


@app.route('/get_shop_by_owner', methods=['GET'])
def get_shop_by_owner():
    user = getattr(g, "current_user", None)
    if not user:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401

    shopkeeper_id = user.get("username")  # or user.get("id") depending on your schema
    if not shopkeeper_id:
        return jsonify({'success': False, 'shop': None, 'message': 'Missing shopkeeperId'}), 400

    shop = firebase_db.get_shop_by_shopkeeper(shopkeeper_id)
    if shop:
        return jsonify({'success': True, 'shop': shop})
    else:
        return jsonify({'success': False, 'shop': None})


@app.route("/send_password_reset_otp", methods=["POST"])
def send_password_reset_otp():
    data = request.get_json()
    email = data.get("email")
    logger.info(f"DEBUG: Looking for email: {email}")
    if not email:
        return jsonify({"success": False, "message": "Email required"}), 400

    # Check if user exists in Firestore
    users_ref = firebase_db.db.collection("users")
    query = users_ref.where("email", "==", email).limit(1).get()
    logger.info(f"DEBUG: Query result : {query}")
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
        logger.info(f"[DEBUG] Sending OTP email to {email}")
        logger.info(f"[DEBUG] Using FROM_EMAIL: {FROM_EMAIL}")

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
        logger.info(f"[DEBUG] Sendinblue response: {response.status_code}, {response.text}")

        return response.status_code in (200, 201)

    except Exception as e:
        logger.info(f"[ERROR] Failed to send OTP email: {e}")
        return False


@app.before_request
def require_authentication():
    public_paths = [
        "/", "/healthz", "/internal-healthz",
        "/send_otp", "/verify_otp", "/register", "/login",
        "/register_after_otp", "/check_update", "/update_password",
        "/verify_password_reset_otp", "/send_password_reset_otp",
    ]

    for path in public_paths:
        if request.path.startswith(path):
            return None  # ✅ allow access without token

    auth_header = request.headers.get("Authorization")

    if not auth_header or not auth_header.startswith("Bearer "):
        return jsonify(
            {"message": "authentication not found in headers", "code": "unauthorized"}), 401

    token = auth_header.split(" ")[1]

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        g.current_user = payload
    except jwt.ExpiredSignatureError:
        return jsonify({"message": "Token expired", "code": "unauthorized"}), 401
    except jwt.InvalidTokenError:
        return jsonify({"message": "Invalid token", "code": "unauthorized"}), 401


@app.route("/api/update_order_items/<order_id>", methods=["PATCH"])
def update_order_items(order_id):
    """
    Shopkeeper updates item details (price, quantity, comments) inside an order.
    """

    try:
        data = request.json
        updated_items = data.get("items", [])

        if not updated_items:
            return jsonify({"success": False, "message": "No items provided"}), 400

        # 🔹 Step 1: Find order document by custom order_uuid field
        order_query = firebase_db.db.collection("orders").where("order_uuid", "==",
                                                                order_id).stream()
        order_doc_ref = None
        order_data = None
        for doc in order_query:
            order_doc_ref = doc.reference
            order_data = doc.to_dict()
            break

        if not order_doc_ref or not order_data:
            return jsonify(
                {"success": False, "message": "Order not found-in Database- Update status"}), 404

        # 🔹 Step 2: Update items (matching by item_id)
        existing_items = order_data.get("items", [])
        for upd in updated_items:
            item_id = upd.get("item_id")
            for existing in existing_items:
                if existing.get("item_id") == item_id:
                    if "price" in upd:
                        existing["price"] = float(upd["price"])
                    if "quantity" in upd:
                        existing["quantity"] = float(upd["quantity"])
                    if "comment" in upd:
                        existing["comment"] = upd["comment"]
                    break

        # 🔹 Step 3: Recalculate total
        total = sum(float(i.get("price", 0)) * float(i.get("quantity", 1)) for i in existing_items)

        # 🔹 Step 4: Update order document
        order_doc_ref.update({
            "items": existing_items,
            "total": total,
            "last_updated": datetime.now().isoformat()
        })

        return jsonify({
            "success": True,
            "message": "Order items updated successfully",
            "new_total": total
        })

    except Exception as e:
        logger.info("🔥 Error updating order:", str(e))
        return jsonify({"success": False, "message": str(e)}), 500


# ============================================================
# 🧩 Common Helpers
# ============================================================

def prepare_basic_invoice_data(order_data):
    """Compute totals and payment info (no GST)."""
    items = order_data.get("items", [])
    payment_method = order_data.get("payment_method", "Razorpay")

    # Basic total calculation
    total_amount = sum(
        float(i.get("price", 0)) * int(i.get("quantity", 1)) for i in items
    )

    # Payment badge styling
    badge_color = "#be2be3" if payment_method.lower() != "cash" else "#1565C0"
    badge_text = (
        "PAID (Online)" if payment_method.lower() != "cash" else "CASH ON DELIVERY"
    )

    return {
        **order_data,
        "total_amount": total_amount,
        "badge_color": badge_color,
        "badge_text": badge_text,
        "timestamp": datetime.now().strftime("%d %B %Y, %I:%M %p"),
    }


def prepare_gst_invoice_data(order_data):
    """Compute totals + GST breakdown for PDF/Mobile."""
    GST_RATE = 0.18
    CGST_RATE = SGST_RATE = GST_RATE / 2

    base = prepare_basic_invoice_data(order_data)
    total = base["total_amount"]

    taxable_value = total / (1 + GST_RATE)
    cgst_total = taxable_value * CGST_RATE
    sgst_total = taxable_value * SGST_RATE

    return {
        **base,
        "GST_RATE": GST_RATE,
        "CGST_RATE": CGST_RATE,
        "SGST_RATE": SGST_RATE,
        "taxable_value": taxable_value,
        "cgst_total": cgst_total,
        "sgst_total": sgst_total,
    }


def generate_invoice_html(order_data, logo_url=None):
    """
    HTML invoice for desktop/email view (NO GST breakdown).
    Uses prepare_basic_invoice_data() for consistency.
    """
    d = prepare_basic_invoice_data(order_data)
    total_amount = d["total_amount"]
    badge_color = d["badge_color"]
    badge_text = d["badge_text"]

    # --- Table Rows ---
    table_rows = "".join([
        f"""
        <tr>
            <td style="padding:12px 8px;border-bottom:1px solid #eee;">{i.get('name', '')}</td>
            <td style="padding:12px 8px;text-align:center;border-bottom:1px solid #eee;">{i.get('quantity', 0)}</td>
            <td style="padding:12px 8px;text-align:right;border-bottom:1px solid #eee;">₹{float(i.get('price', 0)):.2f}</td>
            <td style="padding:12px 8px;text-align:right;border-bottom:1px solid #eee;font-weight:600;">
                ₹{float(i.get('price', 0)) * int(i.get('quantity', 1)):.2f}
            </td>
        </tr>
        """ for i in d.get('items', [])
    ])

    # --- Logo (optional) ---
    logo_html = (
        f'<img src="{logo_url}" width="100" height="100" '
        f'style="display:block;margin:0 auto 10px;" />' if logo_url else ""
    )

    # --- HTML Structure (unchanged) ---
    return f"""
    <div style="font-family:'Segoe UI',Arial,sans-serif;color:#222;background:#f4f7fa;padding:30px;">
      <div style="max-width:650px;margin:0 auto;background:#fff;border-radius:12px;
                  box-shadow:0 4px 10px rgba(0,0,0,0.08);overflow:hidden;">
        
        <!-- Header -->
        <div style="text-align:center;background:linear-gradient(135deg,#43A047,#2E7D32);
                    color:#fff;padding:25px 15px;">
            {logo_html}
            <h1 style="margin:0;font-size:24px;font-weight:600;">Grocery App Invoice</h1>
            <span style="display:inline-block;margin-top:10px;background:{badge_color};
                         color:#fff;padding:6px 16px;border-radius:25px;font-size:13px;
                         box-shadow:0 2px 5px rgba(0,0,0,0.2);">
                {badge_text}
            </span>
        </div>

        <!-- Body -->
        <div style="padding:25px;">
          <p style="font-size:15px;margin:0 0 10px;">Hello <b>{d.get('customer_name', 'Customer')}</b>,</p>
          <p style="font-size:14px;color:#555;margin:0 0 20px;">
            Thank you for your purchase! Your order <b>#{d.get('order_id', '')}</b> 
            was delivered on <i>{d['timestamp']}</i>.
          </p>

          <div style="background:#e8f5e9;padding:15px;border-left:4px solid #43A047;
                      border-radius:6px;margin-bottom:25px;">
            <p style="margin:4px 0;font-size:14px;"><b>Shop:</b> {d.get('shop_name', '')}</p>
            <p style="margin:4px 0;font-size:14px;"><b>Email:</b> {d.get('customer_email', '')}</p>
            <p style="margin:4px 0;font-size:14px;"><b>Phone:</b> {d.get('customer_phone', '')}</p>
          </div>

          <!-- Table -->
          <table style="width:100%;border-collapse:collapse;font-size:14px;border-radius:8px;overflow:hidden;">
            <thead>
              <tr style="background:#A5D6A7;font-weight:bold;color:#1B5E20;">
                <th style="padding:10px;text-align:left;">Item</th>
                <th style="padding:10px;text-align:center;">Qty</th>
                <th style="padding:10px;text-align:right;">Price</th>
                <th style="padding:10px;text-align:right;">Total</th>
              </tr>
            </thead>
            <tbody>{table_rows}</tbody>
            <tfoot>
              <tr style="background:#C8E6C9;font-weight:bold;color:#1B5E20;">
                <td colspan="3" style="padding:12px 8px;text-align:right;">Grand Total</td>
                <td style="padding:12px 8px;text-align:right;">₹{total_amount:.2f}</td>
              </tr>
            </tfoot>
          </table>

          <!-- Footer -->
          <div style="margin-top:25px;">
            <p style="font-size:14px;color:#444;line-height:1.6;margin-bottom:10px;">
              We appreciate your trust in <b>Grocery App</b>.<br/>
              Thank you for shopping with us. 😊
            </p>
            <p style="font-size:13px;color:#666;margin-top:15px;">
              For a detailed breakdown, please check the <b>PDF invoice</b> sent to your email.
            </p>
            <p style="font-size:12px;color:#999;margin-top:20px;">— The Grocery App Team</p>
          </div>
        </div>
      </div>
    </div>
    """


def send_invoice_email(email, order_data, pdf_buffer, logo_url=None):
    try:
        if not email:
            logger.error(
                f"[ERROR] send_invoice_email() called with empty email! order_data={order_data}")
            return False

        pdf_base64 = base64.b64encode(pdf_buffer.getvalue()).decode('utf-8')
        html_content = generate_invoice_html(order_data, logo_url=logo_url)

        data = {
            "sender": {"name": "Grocery App", "email": FROM_EMAIL},
            "to": [{"email": email}],
            "subject": f"🧾 Invoice for Order #{order_data['order_id']} - Grocery App",
            "htmlContent": html_content,
            "attachment": [
                {
                    "content": pdf_base64,
                    "name": f"Invoice_{order_data['order_id']}.pdf"
                }
            ]
        }

        headers = {"api-key": SENDINBLUE_API_KEY, "Content-Type": "application/json"}
        response = requests.post("https://api.sendinblue.com/v3/smtp/email", headers=headers,
                                 json=data)
        logger.info(f"[DEBUG] Invoice email response: {response.status_code}, {response.text}")
        return response.status_code in (200, 201, 202)

    except Exception as e:
        logger.error(f"[ERROR] Failed to send invoice email: {e}")
        return False


def generate_invoice_pdf(order_data, logo_url=None):
    """
    Generate a GST-inclusive invoice PDF.
    ✅ Keeps exact original layout and behaviour.
    ✅ Uses prepare_gst_invoice_data() for shared logic.
    """
    import io
    from weasyprint import HTML

    d = prepare_gst_invoice_data(order_data)

    GST_RATE = d["GST_RATE"]
    CGST_RATE = d["CGST_RATE"]
    SGST_RATE = d["SGST_RATE"]

    total = 0.0
    adjustment_total = 0.0
    discount_total = 0.0
    rows_html = ""

    has_discount = False
    has_adjustment = False
    has_price_change = False

    # --- Detect optional columns ---
    for i in d["items"]:
        if i.get("discount", 0) > 0 or i.get("discount_percent"):
            has_discount = True
        if i.get("original_price") and i["original_price"] != i["price"]:
            has_price_change = True

    # --- Generate item rows ---
    for idx, i in enumerate(d["items"], start=1):
        qty = i.get("quantity", 1)
        original_price = i.get("original_price", i["price"])
        base_price = i["price"]
        discount = i.get("discount", 0)

        if "discount_percent" in i:
            discount = base_price * (i["discount_percent"] / 100)

        final_price = base_price - discount
        discount_total += discount * qty

        taxable_base = final_price / (1 + GST_RATE)
        cgst = taxable_base * CGST_RATE * qty
        sgst = taxable_base * SGST_RATE * qty
        subtotal = final_price * qty
        total += subtotal

        # Adjustment for price difference
        original_subtotal = original_price * qty
        difference = subtotal - original_subtotal
        if abs(difference) > 0.01:
            has_adjustment = True
        adjustment_total += difference

        # Build dynamic columns
        cols = [
            f"<td>{idx}</td>",
            f"<td>{i['name']}</td>",
            f"<td style='text-align:center;'>{qty}</td>",
        ]

        if has_price_change:
            cols.append(f"<td style='text-align:right;'>₹{original_price:.2f}</td>")
        cols.append(f"<td style='text-align:right;'>₹{base_price:.2f}</td>")

        if has_discount:
            cols.append(f"<td style='text-align:right;'>₹{discount:.2f}</td>")
            cols.append(f"<td style='text-align:right;'>₹{final_price:.2f}</td>")
        elif has_price_change:
            cols.append(f"<td style='text-align:right;'>₹{final_price:.2f}</td>")

        cols.extend([
            f"<td style='text-align:right;'>₹{taxable_base:.2f}</td>",
            f"<td style='text-align:right;'>₹{cgst:.2f}</td>",
            f"<td style='text-align:right;'>₹{sgst:.2f}</td>",
        ])

        if has_adjustment:
            if difference > 0:
                status = f"<span style='color:#d32f2f;'>+₹{difference:.2f} (To Pay)</span>"
            elif difference < 0:
                status = f"<span style='color:#388e3c;'>₹{abs(difference):.2f} (Refund)</span>"
            else:
                status = "-"
            cols.append(f"<td style='text-align:right;'>{status}</td>")

        cols.append(f"<td style='text-align:right;'>₹{subtotal:.2f}</td>")
        rows_html += "<tr>" + "".join(cols) + "</tr>"

    taxable_value = total / (1 + GST_RATE)
    cgst_total = taxable_value * CGST_RATE
    sgst_total = taxable_value * SGST_RATE

    # --- Header info ---
    logo_html = (
        f'<img src="{logo_url}" style="height:60px;width:auto;margin-right:10px;">'
        if logo_url else ""
    )
    shop_gstin = d.get("shop_gstin", "TEST GSTN")
    payment_method = d.get("payment_method", "Razorpay")
    badge_text = "PAID (Online)" if payment_method.lower() != "cash" else "CASH ON DELIVERY"
    badge_color = "#4A148C" if payment_method.lower() != "cash" else "#1565C0"

    diff_label = (
        "Customer to Pay" if adjustment_total > 0
        else "Refund to Customer" if adjustment_total < 0
        else "No Adjustment"
    )
    diff_color = (
        "#d32f2f" if adjustment_total > 0
        else "#388e3c" if adjustment_total < 0
        else "#333"
    )

    headers = ["No.", "Item", "Qty"]
    if has_price_change:
        headers.append("Orig (₹)")
    headers.append("Price (₹)")
    if has_discount:
        headers.append("Disc (₹)")
        headers.append("Final (₹)")
    elif has_price_change:
        headers.append("Final (₹)")
    headers.extend(["Taxable (₹)", "CGST (9%)", "SGST (9%)"])
    if has_adjustment:
        headers.append("Adj.")
    headers.append("Total (₹ incl. GST)")

    header_html = "".join([f"<th>{h}</th>" for h in headers])

    # --- Final HTML ---
    html = f"""
    <html>
    <head>
      <meta charset="utf-8">
      <style>
        body {{
          font-family: 'Roboto', sans-serif;
          color: #222;
          background: #fafafa;
          padding: 20px;
          margin: 0;
        }}
        .header {{
          display: flex; align-items: center; justify-content: space-between;
          border-bottom: 3px solid #4A148C;
          padding-bottom: 8px; margin-bottom: 20px;
        }}
        .header-info {{
          text-align: right; font-size: 12px; color: #555;
        }}
        h1 {{ color: #4A148C; text-align: center; margin-bottom: 8px; }}
        .badge {{
          background: {badge_color};
          color: #fff;
          padding: 5px 12px;
          border-radius: 20px;
          font-size: 11px;
          font-weight: 500;
        }}
        table {{
          width: 100%;
          border-collapse: collapse;
          font-size: 12px;
          margin-top: 12px;
        }}
        th {{
          background: #4A148C;
          color: #fff;
          padding: 6px;
          text-align: center;
        }}
        td {{
          border-bottom: 1px solid #ddd;
          padding: 5px;
          text-align: right;
        }}
        td:first-child, th:first-child, td:nth-child(2), th:nth-child(2) {{
          text-align: left;
        }}
        tfoot td {{
          font-weight: bold;
          background: #ede7f6;
          color: #4A148C;
        }}
        .footer {{
          text-align: center;
          font-size: 12px;
          margin-top: 20px;
          color: #555;
        }}
      </style>
    </head>
    <body>
      <div class="header">
        <div style="display:flex;align-items:center;">{logo_html}</div>
        <div class="header-info">
          <strong>{d.get('shop_name', 'Grocery App')}</strong><br/>
          Sringeri, India<br/>
          GSTIN: <b>{shop_gstin}</b><br/>
          ☎️ +91 98765 43210<br/>
          📧 support@groceryapp.in
        </div>
      </div>

      <h1>INVOICE</h1>
      <p style="text-align:center;"><span class="badge">{badge_text}</span></p>

      <table>
        <tr><td><b>📄 Invoice No</b></td><td>{d['order_id']}</td></tr>
        <tr><td><b>🗓️ Date</b></td><td>{d['timestamp']}</td></tr>
        <tr><td><b>👤 Customer</b></td><td>{d['customer_name']}</td></tr>
        <tr><td><b>📨 Email</b></td><td>{d.get('customer_email', '')}</td></tr>
        <tr><td><b>☎️ Phone</b></td><td>{d.get('customer_phone', '')}</td></tr>
        <tr><td><b>🛍️ Shop</b></td><td>{d.get('shop_name', '')}</td></tr>
      </table>

      <table>
        <thead><tr>{header_html}</tr></thead>
        <tbody>{rows_html}</tbody>
        <tfoot>
          {f"<tr><td colspan='{len(headers) - 1}' style='text-align:right;'>Discount Total</td><td>₹{discount_total:.2f}</td></tr>" if has_discount else ""}
          <tr><td colspan='{len(headers) - 1}' style='text-align:right;'>Taxable Value</td><td>₹{taxable_value:.2f}</td></tr>
          <tr><td colspan='{len(headers) - 1}' style='text-align:right;'>CGST (9%)</td><td>₹{cgst_total:.2f}</td></tr>
          <tr><td colspan='{len(headers) - 1}' style='text-align:right;'>SGST (9%)</td><td>₹{sgst_total:.2f}</td></tr>
          <tr><td colspan='{len(headers) - 1}' style='text-align:right;'>Total (Incl. GST)</td><td><b>₹{total:.2f}</b></td></tr>
          {f"<tr><td colspan='{len(headers) - 1}' style='text-align:right;color:{diff_color};'>{diff_label}</td><td style='color:{diff_color};'><b>₹{abs(adjustment_total):.2f}</b></td></tr>" if has_adjustment else ""}
        </tfoot>
      </table>

      <div class="footer">
        <p><i>Thank you for shopping with <b>Grocery App 😊</b>!</i></p>
        <p>We appreciate your business and hope to see you again soon. 🫡</p>
      </div>
    </body>
    </html>
    """

    pdf_buffer = io.BytesIO()
    HTML(string=html).write_pdf(pdf_buffer)
    pdf_buffer.seek(0)
    return pdf_buffer


def process_and_send_invoice(order_doc, logo_url=None):
    """
    Generates PDF & HTML invoices, emails them, and uploads to Firestore.
    ✅ 100% same workflow and data structure as before.
    """
    try:
        # --- Extract order data ---
        order_data = {
            "order_id": order_doc["order_uuid"],
            "customer_name": order_doc["customer"]["fullName"],
            "customer_email": order_doc["customer"].get("email", ""),
            "customer_phone": order_doc["customer"].get("phone", ""),
            "shop_name": order_doc.get("shopName", ""),
            "items": order_doc.get("items", []),
            "total": order_doc.get("total", 0.0),
            "payment_method": order_doc.get("payment_method", "Razorpay"),
        }

        logger.info(f"[DEBUG] 🧾 Order data for invoice: {order_data}")

        # --- Generate PDF ---
        pdf_buffer = generate_invoice_pdf(order_data, logo_url=logo_url)
        logger.info(f"[DEBUG] ✅ PDF generated ({len(pdf_buffer.getvalue())} bytes)")

        # --- Send Email (as before) ---
        send_invoice_email(
            order_data["customer_email"],
            order_data,
            pdf_buffer,
            logo_url=logo_url
        )

        # --- Upload PDF to Firebase Storage ---
        customer_id = order_doc["customer"]["id"]
        invoice_url = firebase_db.upload_invoice_to_storage(
            order_data["order_id"], pdf_buffer, customer_id
        )

        if invoice_url:
            logger.info(f"✅ Invoice uploaded for {customer_id}")
            firebase_db.update_order_status(order_data["order_id"], "delivered", {
                "invoice_url": invoice_url
            })
            logger.info("🔗 Invoice URL stored in Firestore")

        return True

    except Exception as e:
        logger.error(f"[ERROR] ❌ Failed in process_and_send_invoice: {e}")
        return False


def generate_invoice_html_mobile(order_data, logo_url=None):
    """
    Mobile & web compatible invoice with GST summary (18%)
    Restores Back button and uses prepare_gst_invoice_data()
    """
    d = prepare_gst_invoice_data(order_data)
    items = d.get("items", [])

    # --- Table rows ---
    items_html = ""
    subtotal = 0.0
    for item in items:
        qty = float(item.get("quantity", 1))
        price = float(item.get("price", 0))
        total_item = qty * price
        subtotal += total_item
        items_html += f"""
        <tr>
            <td>{item.get('name', '')}</td>
            <td>{qty:.2f}</td>
            <td>₹{price:.2f}</td>
            <td>₹{total_item:.2f}</td>
        </tr>
        """

    # --- Logo ---
    logo_html = f'<img src="{logo_url}" alt="Logo">' if logo_url else ""

    # --- HTML Layout ---
    html = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Invoice</title>
    <style>
        body {{
            font-family: 'Poppins', sans-serif;
            background: #f3f6f4;
            margin: 0;
            padding: 0;
        }}
        .container {{
            max-width: 700px;
            margin: 0 auto;
            padding: 15px;
        }}
        .invoice-card {{
            background: #fff;
            border-radius: 16px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            overflow: hidden;
        }}
        .header {{
            background: linear-gradient(135deg, #4CAF50, #2E7D32);
            color: white;
            text-align: center;
            padding: 20px;
            position: relative;
        }}
        .header img {{
            width: 80px;
            margin-bottom: 10px;
        }}
        .back-btn {{
            position: fixed;
            top: 10px;
            left: 10px;
            background: #E8F5E9;
            color: #1B5E20;
            border: none;
            padding: 8px 14px;
            border-radius: 8px;
            font-weight: 600;
            cursor: pointer;
            font-size: 14px;
            z-index: 999;
            box-shadow: 0 2px 4px rgba(0,0,0,0.2);
        }}
        h2 {{
            margin: 8px 0 0;
            font-size: 20px;
        }}
        .badge {{
            display: inline-block;
            background: {d['badge_color']};
            color: white;
            padding: 4px 10px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
        }}
        .section {{
            padding: 15px 20px;
        }}
        .section p {{
            margin: 4px 0;
            color: #333;
        }}
        .table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 10px;
        }}
        .table th {{
            background: #C8E6C9;
            text-align: left;
            padding: 8px;
        }}
        .table td {{
            padding: 8px;
            border-top: 1px solid #ddd;
        }}
        .summary-table td {{
            padding: 6px 8px;
        }}
        .footer {{
            text-align: center;
            font-size: 13px;
            color: #666;
            padding: 15px;
            border-top: 1px solid #ddd;
        }}
    </style>
</head>
<body>

<button class="back-btn" onclick="goBack()">← Back</button>

<div class="container">
    <div class="invoice-card">
        <div class="header">
            {logo_html}
            <h2>Grocery App Invoice</h2>
            <span class="badge">{d['badge_text']}</span>
        </div>

        <div class="section">
            <p><strong>Customer:</strong> {d.get('customer_name', 'N/A')}</p>
            <p><strong>Email:</strong> {d.get('customer_email', 'N/A')}</p>
            <p><strong>Phone:</strong> {d.get('customer_phone', 'N/A')}</p>
            <p><strong>Order ID:</strong> {d.get('order_id', '')}</p>
            <p><strong>Date:</strong> {d['timestamp']}</p>
        </div>

        <div class="section" style="background:#F1F8E9;border-radius:8px;">
            <p><strong>Shop:</strong> {d.get('shop_name', 'N/A')}</p>
        </div>

        <div class="section">
            <table class="table">
                <thead>
                    <tr>
                        <th>Item</th>
                        <th>Qty</th>
                        <th>Price</th>
                        <th>Total</th>
                    </tr>
                </thead>
                <tbody>
                    {items_html}
                </tbody>
            </table>

            <table class="summary-table" style="width:100%;margin-top:15px;">
                <tr><td>Taxable Value:</td><td style="text-align:right;">₹{d['taxable_value']:.2f}</td></tr>
                <tr><td>CGST (9%):</td><td style="text-align:right;">₹{d['cgst_total']:.2f}</td></tr>
                <tr><td>SGST (9%):</td><td style="text-align:right;">₹{d['sgst_total']:.2f}</td></tr>
                <tr><td><strong>Grand Total (Incl. GST):</strong></td><td style="text-align:right;font-weight:bold;">₹{d['total_amount']:.2f}</td></tr>
            </table>
        </div>

        <div class="footer">
            <p>Thank you for shopping with <b>Grocery App</b>! 😊</p>
        </div>
    </div>
</div>

<script>
function goBack() {{
    if (window.AndroidApp && window.AndroidApp.goBackToApp) {{
        window.AndroidApp.goBackToApp();
    }} else if (window.history.length > 1) {{
        window.history.back();
    }} else {{
        window.close();
    }}
}}
</script>

</body>
</html>
"""
    return html


@app.route("/api/invoice_html/<order_id>", methods=["GET"])
def get_invoice_html(order_id):
    try:
        order_doc = firebase_db.get_order_by_uuid(order_id)
        if not order_doc:
            return jsonify({"error": "Order not found -- Invoice"}), 404  ##TODO: NEED TO CHANGE MSG

        order_data = {
            "order_id": order_doc["order_uuid"],
            "customer_name": order_doc["customer"]["fullName"],
            "customer_email": order_doc["customer"].get("email", ""),
            "customer_phone": order_doc["customer"].get("phone", ""),
            "shop_name": order_doc.get("shopName", ""),
            "items": order_doc.get("items", []),
            "total": order_doc.get("total", 0.0),
            "payment_method": order_doc.get("payment_method", "Cash"),
        }

        html = generate_invoice_html_mobile(order_data, logo_url=logo_url)
        return Response(html, mimetype="text/html")

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/register_fcm_token", methods=["POST"])
def register_fcm_token():
    data = request.json
    user_id = data.get("user_id")
    role = data.get("role")
    token = data.get("token")

    if not user_id or not token:
        return jsonify({"success": False, "message": "Missing user_id or token"}), 400

    ok = firebase_db.save_fcm_token_for_user(user_id, token, role)
    if ok:
        return jsonify({"success": True, "message": "Token updated"}), 200
    else:
        return jsonify({"success": False, "message": "User not found"}), 404


if __name__ == "__main__":
    logger.info("Gunicorn setup complete, about to run...")
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
