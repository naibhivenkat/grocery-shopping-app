# from auth_utils import (
#     require_role,
#     verify_password,
#     hash_password,
#     log_admin_action, AUDIT_LOGS
# )
# from db import (
#     CUSTOMER_ORDERS,
#     SHOP_ITEMS,
#     USERS,
#     VENDOR_SUBSCRIPTIONS,
#     col,
#     doc,
#     now_iso,
#     to_dict,
#     NOTIFICATIONS,
#     SUPPORT_TICKETS,
#     SHOP_ITEMS,
#     APP_SETTINGS
# )
# from flask import Blueprint, jsonify, request, g
# from google.cloud.firestore_v1.base_query import FieldFilter
#
# admin_bp = Blueprint("admin", __name__)
#
#
# def _users_by_role(role: str, include_suspended: bool = False):
#     query = col(USERS).where(filter=FieldFilter("role", "==", role))
#     users = [to_dict(d) for d in query.stream()]
#     if include_suspended and role == "vendor":
#         suspended_query = col(USERS).where(
#             filter=FieldFilter("suspended_role", "==", "vendor")
#         )
#         existing = {u.get("uid") for u in users}
#         users.extend(
#             to_dict(d)
#             for d in suspended_query.stream()
#             if d.id not in existing
#         )
#     return users
#
#
# @admin_bp.get("/admin/customers/<user_id>")
# @require_role("admin", "super_admin")
# def get_customers(user_id):
#     snapshot = doc(USERS, user_id).get()
#
#     if not snapshot.exists:
#         return jsonify({
#             "detail": "User not found",
#         }), 404
#
#     user = to_dict(snapshot)
#
#     user.pop("password_hash", None)
#
#     return jsonify({
#         "uid": user.get("uid", snapshot.id),
#         "full_name": user.get("full_name", ""),
#         "email": user.get("email", ""),
#         "phone": user.get("phone", ""),
#         "role": user.get("role", ""),
#         "is_suspended": bool(user.get("is_suspended", False)),
#     })
#
#
# @admin_bp.put("/admin/customers/<user_id>")
# @require_role("admin", "super_admin")
# def update_customer(user_id):
#     snapshot = doc(USERS, user_id).get()
#
#     if not snapshot.exists:
#         return jsonify({
#             "detail": "User not found",
#         }), 404
#
#     body = request.get_json(force=True)
#
#     updates = {
#         "full_name": body.get("full_name"),
#         "email": body.get("email"),
#         "phone": body.get("phone"),
#         "role": body.get("role"),
#         "is_suspended": body.get("is_suspended"),
#         "updated_at": now_iso(),
#     }
#
#     updates = {
#         k: v
#         for k, v in updates.items()
#         if v is not None
#     }
#
#     doc(USERS, user_id).update(updates)
#
#     log_admin_action(
#         admin_id=g.user_id,
#         admin_email=getattr(g, "user_email", ""),
#         action="Update User",
#         target_id=user_id,
#         target_type="user",
#     )
#
#     return jsonify({
#         "success": True,
#     })
#
#
# @admin_bp.delete("/admin/customers/<user_id>")
# @require_role("admin", "super_admin")
# def delete_customer(user_id):
#     snapshot = doc(USERS, user_id).get()
#
#     if not snapshot.exists:
#         return jsonify({
#             "detail": "User not found",
#         }), 404
#
#     doc(USERS, user_id).delete()
#
#     log_admin_action(
#         admin_id=g.user_id,
#         admin_email=getattr(g, "user_email", ""),
#         action="Delete User",
#         target_id=user_id,
#         target_type="user",
#     )
#
#     return jsonify({
#         "success": True,
#     })
#
#
# @admin_bp.get("/admin/stats")
# @require_role("admin", "super_admin")
# def get_stats():
#     vendors = list(
#         col(USERS)
#         .where(filter=FieldFilter("role", "==", "vendor"))
#         .stream()
#     )
#
#     customers = list(
#         col(USERS)
#         .where(filter=FieldFilter("role", "==", "customer"))
#         .stream()
#     )
#
#     active_subs = list(
#         col(VENDOR_SUBSCRIPTIONS)
#         .where(filter=FieldFilter("status", "==", "active"))
#         .stream()
#     )
#
#     total_revenue = 0
#     total_orders = 0
#
#     pending_orders = 0
#     confirmed_orders = 0
#     delivered_orders = 0
#     cancelled_orders = 0
#
#     for d in col(CUSTOMER_ORDERS).stream():
#
#         total_orders += 1
#
#         data = d.to_dict() or {}
#
#         status = str(
#             data.get("status", "")
#         ).lower()
#
#         if status == "pending":
#             pending_orders += 1
#
#         elif status == "confirmed":
#             confirmed_orders += 1
#
#         elif status == "delivered":
#             delivered_orders += 1
#
#         elif status == "cancelled":
#             cancelled_orders += 1
#
#         if status in [
#             "confirmed",
#             "delivered",
#             "completed",
#             "paid",
#         ]:
#             try:
#                 total_revenue += float(
#                     data.get("total_price") or 0
#                 )
#             except:
#                 pass
#
#     return jsonify({
#         "vendor_count": len(vendors),
#         "customer_count": len(customers),
#         "total_orders": total_orders,
#         "active_subscriptions": len(active_subs),
#         "pending_orders": pending_orders,
#         "confirmed_orders": confirmed_orders,
#         "delivered_orders": delivered_orders,
#         "cancelled_orders": cancelled_orders,
#         "total_revenue": total_revenue,
#     })
#
#
# @admin_bp.get("/admin/vendors")
# @require_role("admin", "super_admin")
# def list_vendors():
#     vendors = _users_by_role("vendor", include_suspended=True)
#     for v in vendors:
#         v.pop("password_hash", None)
#         v["id"] = v.get("uid")
#         v["role"] = v.get("role") or "vendor"
#         v["is_suspended"] = bool(v.get("is_suspended"))
#     return jsonify(vendors)
#
#
#
# @admin_bp.get("/admin/vendors/<vendor_id>")
# @require_role("admin", "super_admin")
# def get_vendor(vendor_id):
#     snapshot = doc(USERS, vendor_id).get()
#
#     if not snapshot.exists:
#         return jsonify({
#             "detail": "Vendor not found",
#         }), 404
#
#     vendor = to_dict(snapshot)
#
#     if (
#         vendor.get("role") != "vendor"
#         and vendor.get("suspended_role") != "vendor"
#     ):
#         return jsonify({
#             "detail": "Vendor not found",
#         }), 404
#
#     vendor.pop("password_hash", None)
#
#     return jsonify({
#         "uid": vendor.get("uid", snapshot.id),
#         "full_name": vendor.get("full_name", ""),
#         "email": vendor.get("email", ""),
#         "phone": vendor.get("phone", ""),
#         "role": "vendor",
#         "is_suspended": bool(
#             vendor.get("is_suspended", False),
#         ),
#     })
#
# @admin_bp.put("/admin/vendors/<vendor_id>")
# @require_role("admin", "super_admin")
# def update_vendor(vendor_id):
#     snapshot = doc(USERS, vendor_id).get()
#
#     if not snapshot.exists:
#         return jsonify({
#             "detail": "Vendor not found",
#         }), 404
#
#     vendor = to_dict(snapshot)
#
#     if (
#         vendor.get("role") != "vendor"
#         and vendor.get("suspended_role") != "vendor"
#     ):
#         return jsonify({
#             "detail": "Vendor not found",
#         }), 404
#
#     body = request.get_json(force=True)
#
#     updates = {
#         "full_name": body.get("full_name"),
#         "email": body.get("email"),
#         "phone": body.get("phone"),
#         "is_suspended": body.get("is_suspended"),
#         "updated_at": now_iso(),
#     }
#
#     updates = {
#         k: v
#         for k, v in updates.items()
#         if v is not None
#     }
#
#     doc(USERS, vendor_id).update(updates)
#
#     log_admin_action(
#         admin_id=g.user_id,
#         admin_email=getattr(g, "user_email", ""),
#         action="Update Vendor",
#         target_id=vendor_id,
#         target_type="vendor",
#     )
#
#     return jsonify({
#         "success": True,
#     })
#
# @admin_bp.delete("/admin/vendors/<vendor_id>")
# @require_role("admin", "super_admin")
# def delete_vendor(vendor_id):
#     snapshot = doc(USERS, vendor_id).get()
#
#     if not snapshot.exists:
#         return jsonify({
#             "detail": "Vendor not found",
#         }), 404
#
#     vendor = to_dict(snapshot)
#
#     if (
#         vendor.get("role") != "vendor"
#         and vendor.get("suspended_role") != "vendor"
#     ):
#         return jsonify({
#             "detail": "Vendor not found",
#         }), 404
#
#     doc(USERS, vendor_id).delete()
#
#     log_admin_action(
#         admin_id=g.user_id,
#         admin_email=getattr(g, "user_email", ""),
#         action="Delete Vendor",
#         target_id=vendor_id,
#         target_type="vendor",
#     )
#
#     return jsonify({
#         "success": True,
#     })
#
# @admin_bp.post("/admin/vendors/<vendor_id>/suspend")
# @require_role("admin", "super_admin")
# def suspend_vendor(vendor_id):
#     snapshot = doc(USERS, vendor_id).get()
#
#     if not snapshot.exists:
#         return jsonify({
#             "detail": "Vendor not found",
#         }), 404
#
#     vendor = to_dict(snapshot)
#
#     if (
#         vendor.get("role") != "vendor"
#         and vendor.get("suspended_role") != "vendor"
#     ):
#         return jsonify({
#             "detail": "Vendor not found",
#         }), 404
#
#     current_role = vendor.get("role") or "vendor"
#
#     doc(USERS, vendor_id).set(
#         {
#             "is_suspended": True,
#             "suspended_role": current_role,
#             "suspended_at": now_iso(),
#             "updated_at": now_iso(),
#         },
#         merge=True,
#     )
#
#     log_admin_action(
#         admin_id=g.user_id,
#         admin_email=getattr(g, "user_email", ""),
#         action="Suspend Vendor",
#         target_id=vendor_id,
#         target_type="vendor",
#     )
#
#     return jsonify({
#         "success": True,
#         "message": "Vendor suspended successfully",
#     })
#
# @admin_bp.post("/admin/vendors/<vendor_id>/unsuspend")
# @require_role("admin", "super_admin")
# def unsuspend_vendor(vendor_id):
#     snapshot = doc(USERS, vendor_id).get()
#
#     if not snapshot.exists:
#         return jsonify({
#             "detail": "Vendor not found",
#         }), 404
#
#     vendor = to_dict(snapshot)
#
#     if (
#         vendor.get("role") != "vendor"
#         and vendor.get("suspended_role") != "vendor"
#     ):
#         return jsonify({
#             "detail": "Vendor not found",
#         }), 404
#
#     doc(USERS, vendor_id).set(
#         {
#             "is_suspended": False,
#             "suspended_role": None,
#             "suspended_at": None,
#             "updated_at": now_iso(),
#         },
#         merge=True,
#     )
#
#     log_admin_action(
#         admin_id=g.user_id,
#         admin_email=getattr(g, "user_email", ""),
#         action="Unsuspend Vendor",
#         target_id=vendor_id,
#         target_type="vendor",
#     )
#
#     return jsonify({
#         "success": True,
#         "message": "Vendor unsuspended successfully",
#     })
#
#
# @admin_bp.get("/admin/customers")
# @require_role("admin", "super_admin")
# def list_customers():
#     customers = _users_by_role("customer")
#     for c in customers:
#         c.pop("password_hash", None)
#         c["id"] = c.get("uid")
#         # Compute lightweight orders_count; safe for small datasets.
#         orders_query = col(CUSTOMER_ORDERS).where(
#             filter=FieldFilter("customer_id", "==", c["id"])
#         )
#         c["orders_count"] = sum(1 for _ in orders_query.stream())
#     return jsonify(customers)
#
#
# @admin_bp.post("/admin/customers/<user_id>/suspend")
# @require_role("admin", "super_admin")
# def suspend_customers(user_id):
#     snap = doc(USERS, user_id).get()
#     current_role = (snap.to_dict() or {}).get("role") if snap.exists else None
#     doc(USERS, user_id).set({
#         "is_suspended": True,
#         "suspended_role": current_role,
#         "suspended_at": now_iso(),
#     }, merge=True)
#
#     log_admin_action(
#         g.user_id,
#         "admin@gmail.com",
#         "Suspend User",
#         user_id,
#         "user",
#     )
#     return jsonify({"ok": True})
#
#
# @admin_bp.post("/admin/customers/<user_id>/unsuspend")
# @require_role("admin", "super_admin")
# def unsuspend_customers(user_id):
#     doc(USERS, user_id).set(
#         {"is_suspended": False, "suspended_at": None, "suspended_role": None},
#         merge=True,
#     )
#     log_admin_action(
#         g.user_id,
#         "admin@gmail.com",
#         "Suspend User",
#         user_id,
#         "user",
#     )
#     return jsonify({"ok": True})
#
#
# @admin_bp.get("/admin/orders")
# @require_role("admin", "super_admin")
# def admin_orders():
#     docs = col(CUSTOMER_ORDERS).stream()
#
#     orders = []
#
#     for doc_snap in docs:
#         data = to_dict(doc_snap)
#
#         customer_name = data.get("customer_name")
#         if not isinstance(customer_name, str):
#             data["customer_name"] = ""
#
#         vendor_name = data.get("vendor_name")
#         if not isinstance(vendor_name, str):
#             data["vendor_name"] = ""
#
#         item_name = data.get("item_name")
#         if not isinstance(item_name, str):
#             data["item_name"] = ""
#
#         status = data.get("status")
#         if not isinstance(status, str):
#             data["status"] = ""
#
#         orders.append(data)
#
#     return jsonify(orders)
#
#
# @admin_bp.get("/admin/products")
# @require_role("admin", "super_admin")
# def admin_products():
#     docs = col(SHOP_ITEMS).stream()
#
#     products = []
#
#     for doc_snap in docs:
#         product = to_dict(doc_snap)
#
#         image_urls = product.get("image_urls") or []
#
#         stock = product.get("stock_quantity", 0)
#
#         product["total_images"] = len(image_urls)
#
#         product["primary_image"] = (
#             image_urls[0] if image_urls else ""
#         )
#
#         product["has_stock"] = stock > 0
#
#         product["status"] = (
#             "Available"
#             if product.get("is_available", True)
#             else "Disabled"
#         )
#
#         product["stock_status"] = (
#             "Out of Stock"
#             if stock <= 0
#             else (
#                 "Low Stock"
#                 if stock < 10
#                 else "In Stock"
#             )
#         )
#
#         products.append(product)
#
#     products.sort(
#         key=lambda x: x.get("updated_at", ""),
#         reverse=True,
#     )
#
#     return jsonify(products)
#
#
# @admin_bp.get("/admin/products/<product_id>")
# @require_role("admin", "super_admin")
# def get_product(product_id):
#     snapshot = doc(SHOP_ITEMS, product_id).get()
#
#     if not snapshot.exists:
#         return jsonify(
#             {
#                 "detail": "Product not found"
#             }
#         ), 404
#
#     product = to_dict(snapshot)
#
#     images = product.get("image_urls") or []
#
#     stock = product.get("stock_quantity", 0)
#
#     product["total_images"] = len(images)
#
#     product["primary_image"] = (
#         images[0] if images else ""
#     )
#
#     product["status"] = (
#         "Available"
#         if product.get("is_available", True)
#         else "Disabled"
#     )
#
#     product["has_stock"] = stock > 0
#
#     return jsonify(product)
#
#
# import uuid
#
#
# @admin_bp.post("/admin/products")
# @require_role("admin", "super_admin")
# def create_product():
#     body = request.json or {}
#
#     product_id = uuid.uuid4().hex
#
#     product = {
#
#         "name": body.get("name", "").strip(),
#
#         "description": body.get("description", ""),
#
#         "price": float(body.get("price", 0)),
#
#         "stock_quantity": int(body.get("stock_quantity", 0)),
#
#         "category": body.get("category", ""),
#
#         "image_urls": body.get("image_urls", []),
#
#         "vendor_id": body.get("vendor_id"),
#
#         "vendor_name": body.get("vendor_name"),
#
#         "vendor_email": body.get("vendor_email"),
#
#         "vendor_phone": body.get("vendor_phone"),
#
#         "vendor_shop_description":
#             body.get("vendor_shop_description"),
#
#         "is_available": True,
#
#         "created_at": now_iso(),
#
#         "updated_at": now_iso(),
#     }
#
#     doc(SHOP_ITEMS, product_id).set(product)
#
#     log_admin_action(
#         g.user_id,
#         getattr(g, "user_email", ""),
#         "Create Product",
#         product_id,
#         "product",
#     )
#
#     return jsonify(
#         {
#             "success": True,
#             "uid": product_id,
#         }
#     )
#
#
# @admin_bp.put("/admin/products/<product_id>")
# @require_role("admin", "super_admin")
# def update_product(product_id):
#     snapshot = doc(SHOP_ITEMS, product_id).get()
#
#     if not snapshot.exists:
#         return jsonify(
#             {
#                 "detail": "Product not found"
#             }
#         ), 404
#
#     body = request.json or {}
#
#     updates = {
#
#         "name": body.get("name"),
#
#         "description": body.get("description"),
#
#         "price": body.get("price"),
#
#         "stock_quantity": body.get("stock_quantity"),
#
#         "category": body.get("category"),
#
#         "image_urls": body.get("image_urls"),
#
#         "is_available": body.get("is_available"),
#
#         "updated_at": now_iso(),
#     }
#
#     updates = {
#         k: v
#         for k, v in updates.items()
#         if v is not None
#     }
#
#     doc(SHOP_ITEMS, product_id).update(updates)
#
#     log_admin_action(
#         g.user_id,
#         getattr(g, "user_email", ""),
#         "Update Product",
#         product_id,
#         "product",
#     )
#
#     return jsonify(
#         {
#             "success": True
#         }
#     )
#
#
# @admin_bp.get("/admin/analytics")
# @require_role("admin", "super_admin")
# def analytics():
#     vendors = list(
#         col(USERS).where(
#             filter=FieldFilter("role", "==", "vendor")
#         ).stream()
#     )
#
#     customers = list(
#         col(USERS).where(
#             filter=FieldFilter("role", "==", "customer")
#         ).stream()
#     )
#
#     orders = list(col(CUSTOMER_ORDERS).stream())
#
#     revenue = 0.0
#
#     for d in orders:
#         data = d.to_dict() or {}
#
#         try:
#             revenue += float(
#                 data.get("total_price") or 0
#             )
#         except Exception:
#             pass
#
#     return jsonify({
#         "vendors": len(vendors),
#         "customers": len(customers),
#         "orders": len(orders),
#         "revenue": revenue,
#     })
#
#
#
#
# @admin_bp.post("/admin/notifications/send")
# @require_role("admin", "super_admin")
# def send_notification():
#     data = request.get_json(force=True)
#
#     title = data.get("title", "").strip()
#     message = data.get("message", "").strip()
#     target = data.get("target", "all").strip().lower()
#
#
#
#     if not title:
#         return jsonify({"detail": "Title is required"}), 400
#
#     if not message:
#         return jsonify({"detail": "Message is required"}), 400
#
#     users_query = col(USERS)
#
#     # Customers
#     if target in ("customer", "customers"):
#         users_query = users_query.where(
#             filter=FieldFilter("role", "==", "customer")
#         )
#
#     # Vendors
#     elif target in ("vendor", "vendors"):
#         users_query = users_query.where(
#             filter=FieldFilter("role", "==", "vendor")
#         )
#
#     # Admins
#     elif target in ("admin", "admins"):
#         users_query = users_query.where(
#             filter=FieldFilter("role", "in", ["admin", "super_admin"])
#         )
#
#     # All users
#     elif target == "all":
#         pass
#
#     else:
#         return jsonify({"detail": f"Unknown target: {target}"}), 400
#
#     users = list(users_query.stream())
#
#
#
#     db = col(USERS)._client
#     batch = db.batch()
#
#     count = 0
#
#     for user in users:
#         ref = col(NOTIFICATIONS).document()
#
#         batch.set(
#             ref,
#             {
#                 "uid": ref.id,
#                 "user_id": user.id,
#                 "title": title,
#                 "message": message,
#                 "target": target,
#                 "is_read": False,
#                 "created_at": now_iso(),
#             },
#         )
#
#         count += 1
#
#         if count % 450 == 0:
#             batch.commit()
#             batch = db.batch()
#
#     if count % 450 != 0:
#         batch.commit()
#
#     return jsonify(
#         {
#             "success": True,
#             "sent": count,
#             "target": target,
#         }
#     )
#
#
# @admin_bp.get("/admin/notifications")
# @require_role("admin", "super_admin")
# def list_notifications():
#     docs = col(NOTIFICATIONS).stream()
#
#     notifications = []
#
#     for d in docs:
#         notifications.append(to_dict(d))
#
#     return jsonify(notifications)
#
#
# @admin_bp.get("/admin/support")
# @require_role("admin", "super_admin")
# def list_support_tickets():
#     docs = col(SUPPORT_TICKETS).stream()
#
#     tickets = []
#
#     for d in docs:
#         tickets.append(to_dict(d))
#
#     return jsonify(tickets)
#
#
# @admin_bp.post("/admin/support/reply")
# @require_role("admin", "super_admin")
# def reply_support_ticket():
#     data = request.get_json(force=True)
#
#     ticket_id = data.get("ticket_id")
#
#     if not ticket_id:
#         return jsonify({
#             "error": "ticket_id required"
#         }), 400
#
#     update_data = {
#         "admin_reply": data.get("reply", ""),
#         "status": "resolved",
#         "resolved_at": now_iso(),
#     }
#
#     doc(SUPPORT_TICKETS, ticket_id).set(
#         update_data,
#         merge=True,
#     )
#
#     return jsonify({
#         "success": True,
#     })
#
#
# @admin_bp.post("/admin/support/create")
# @require_role("admin", "super_admin")
# def create_support_ticket():
#     data = request.get_json(force=True)
#
#     ref = col(SUPPORT_TICKETS).document()
#
#     ticket = {
#         "uid": ref.id,
#         "user_name": data.get("user_name"),
#         "message": data.get("message"),
#         "status": "open",
#         "created_at": now_iso(),
#     }
#
#     ref.set(ticket)
#
#     return jsonify(ticket)
#
#
# @admin_bp.post("/admin/change-password")
# @require_role("admin", "super_admin")
# def change_password():
#     data = request.get_json(force=True)
#
#     current_password = data.get("current_password")
#     new_password = data.get("new_password")
#
#     if not current_password:
#         return jsonify({
#             "detail": "Current password required"
#         }), 400
#
#     if not new_password:
#         return jsonify({
#             "detail": "New password required"
#         }), 400
#
#     user_snapshot = doc(USERS, g.user_id).get()
#
#     if not user_snapshot.exists:
#         return jsonify({
#             "detail": "User not found"
#         }), 404
#
#     user = user_snapshot.to_dict() or {}
#
#     stored_hash = user.get("password_hash", "")
#
#     if not verify_password(
#             current_password,
#             stored_hash,
#     ):
#         return jsonify({
#             "detail": "Current password incorrect"
#         }), 400
#
#     doc(USERS, g.user_id).set(
#         {
#             "password_hash":
#                 hash_password(new_password)
#         },
#         merge=True,
#     )
#
#     return jsonify({
#         "success": True
#     })
#
#
# @admin_bp.post("/admin/products/<product_id>/disable")
# @require_role("admin", "super_admin")
# def disable_product(product_id):
#     product_ref = doc(SHOP_ITEMS, product_id)
#     snapshot = product_ref.get()
#
#     if not snapshot.exists:
#         return jsonify({
#             "detail": "Product not found"
#         }), 404
#
#     product_ref.update({
#         "is_available": False,
#         "disabled_by_admin": True,
#         "updated_at": now_iso(),
#     })
#
#     log_admin_action(
#         admin_id=g.user_id,
#         admin_email=getattr(g, "user_email", ""),
#         action="Disable Product",
#         target_id=product_id,
#         target_type="product",
#     )
#
#     return jsonify({
#         "success": True,
#         "message": "Product disabled successfully",
#     }), 200
#
#
# @admin_bp.post("/admin/products/<product_id>/enable")
# @require_role("admin", "super_admin")
# def enable_product(product_id):
#     product_ref = doc(SHOP_ITEMS, product_id)
#     snapshot = product_ref.get()
#
#     if not snapshot.exists:
#         return jsonify({
#             "detail": "Product not found"
#         }), 404
#
#     product_ref.update({
#         "is_available": True,
#         "disabled_by_admin": False,
#         "updated_at": now_iso(),
#     })
#
#     log_admin_action(
#         admin_id=g.user_id,
#         admin_email=getattr(g, "user_email", ""),
#         action="Enable Product",
#         target_id=product_id,
#         target_type="product",
#     )
#
#     return jsonify({
#         "success": True,
#         "message": "Product enabled successfully",
#     }), 200
#
#
# @admin_bp.delete("/admin/products/<product_id>")
# @require_role("admin", "super_admin")
# def delete_product(product_id):
#     snapshot = doc(SHOP_ITEMS, product_id).get()
#
#     if not snapshot.exists:
#         return jsonify(
#             {
#                 "detail": "Product not found"
#             }
#         ), 404
#
#     doc(SHOP_ITEMS, product_id).delete()
#
#     log_admin_action(
#         admin_id=g.user_id,
#         admin_email=g.user_email,
#         action="Delete Product",
#         target_id=product_id,
#         target_type="product",
#     )
#
#     return jsonify(
#         {
#             "success": True
#         }
#     )
#
#
# @admin_bp.get("/admin/orders/<order_id>")
# @require_role("admin", "super_admin")
# def get_order_detail(order_id):
#     snapshot = doc(CUSTOMER_ORDERS, order_id).get()
#
#     if not snapshot.exists:
#         return jsonify({
#             "detail": "Order not found"
#         }), 404
#
#     return jsonify(to_dict(snapshot))
#
#
# @admin_bp.post("/admin/orders/<order_id>/cancel")
# @require_role("admin", "super_admin")
# def admin_cancel_order(order_id):
#     doc(CUSTOMER_ORDERS, order_id).set(
#         {
#             "status": "cancelled",
#             "cancelled_by": "admin",
#             "updated_at": now_iso(),
#         },
#         merge=True,
#     )
#
#     return jsonify({
#         "success": True
#     })
#
#
# @admin_bp.post("/admin/orders/<order_id>/refund")
# @require_role("admin", "super_admin")
# def refund_order(order_id):
#     doc(CUSTOMER_ORDERS, order_id).set(
#         {
#             "refund_status": "refunded",
#             "refunded_at": now_iso(),
#         },
#         merge=True,
#     )
#
#     return jsonify({
#         "success": True
#     })
#
#
# @admin_bp.get("/admin/subscriptions")
# @require_role("admin", "super_admin")
# def list_subscriptions():
#     return jsonify([
#         to_dict(d)
#         for d in col(VENDOR_SUBSCRIPTIONS).stream()
#     ])
#
#
# @admin_bp.post("/admin/subscriptions/<sub_id>/activate")
# @require_role("admin", "super_admin")
# def activate_subscription(sub_id):
#     doc(VENDOR_SUBSCRIPTIONS, sub_id).set(
#         {
#             "status": "active",
#             "updated_at": now_iso(),
#         },
#         merge=True,
#     )
#
#     return jsonify({"success": True})
#
#
# @admin_bp.post("/admin/subscriptions/<sub_id>/suspend")
# @require_role("admin", "super_admin")
# def suspend_subscription(sub_id):
#     doc(VENDOR_SUBSCRIPTIONS, sub_id).set(
#         {
#             "status": "suspended",
#             "updated_at": now_iso(),
#         },
#         merge=True,
#     )
#
#     return jsonify({"success": True})
#
#
# @admin_bp.get("/admin/audit-logs")
# @require_role("admin", "super_admin")
# def audit_logs():
#     try:
#         print("AUDIT LOG ROUTE HIT")
#
#         logs = [
#             to_dict(d)
#             for d in col(AUDIT_LOGS).stream()
#         ]
#
#         print(f"FOUND {len(logs)} LOGS")
#
#         logs.sort(
#             key=lambda x: x.get("created_at", ""),
#             reverse=True,
#         )
#
#         return jsonify(logs)
#
#     except Exception as e:
#         import traceback
#         traceback.print_exc()
#
#         return jsonify({
#             "error": str(e),
#             "type": type(e).__name__,
#         }), 500
#
#
# @admin_bp.get("/maintenance-status")
# def maintenance_status():
#     settings_doc = doc(
#         APP_SETTINGS,
#         "config",
#     ).get()
#
#     if not settings_doc.exists:
#         return jsonify({
#             "maintenance_mode": False,
#         })
#
#     data = settings_doc.to_dict() or {}
#
#     return jsonify({
#         "maintenance_mode":
#             data.get(
#                 "maintenance_mode",
#                 False,
#             ),
#     })
#
#
# @admin_bp.post("/admin/maintenance")
# @require_role("admin", "super_admin")
# def update_maintenance_status():
#     data = request.get_json(force=True)
#
#     maintenance_mode = bool(
#         data.get("maintenance_mode", False)
#     )
#
#     doc(
#         APP_SETTINGS,
#         "config",
#     ).set(
#         {
#             "maintenance_mode":
#                 maintenance_mode,
#             "updated_at": now_iso(),
#         },
#         merge=True,
#     )
#
#     return jsonify({
#         "success": True,
#         "maintenance_mode":
#             maintenance_mode,
#     })
#
#
# @admin_bp.get("/admin/maintenance")
# @require_role("admin", "super_admin")
# def get_maintenance_status():
#     settings_doc = doc(
#         APP_SETTINGS,
#         "config",
#     ).get()
#
#     if not settings_doc.exists:
#         return jsonify({
#             "maintenance_mode": False,
#         })
#
#     data = settings_doc.to_dict() or {}
#
#     return jsonify({
#         "maintenance_mode":
#             data.get(
#                 "maintenance_mode",
#                 False,
#             ),
#         "updated_at":
#             data.get("updated_at"),
#     })
#
#
# @admin_bp.get("/admin/recent-orders")
# @require_role("admin", "super_admin")
# def get_recent_orders():
#     try:
#
#         docs = (
#             col(CUSTOMER_ORDERS)
#             .order_by("created_at", direction="DESCENDING")
#             .limit(20)
#             .stream()
#         )
#
#         orders = []
#
#         for d in docs:
#             data = d.to_dict() or {}
#
#             orders.append({
#                 "id": d.id,
#                 "customer_id": data.get("customer_id"),
#                 "vendor_id": data.get("vendor_id"),
#                 "vendor_name": data.get("vendor_name", ""),
#                 "item_name": data.get("item_name", ""),
#                 "quantity": data.get("quantity", 0),
#                 "total_price": data.get("total_price", 0),
#                 "payment_method": data.get("payment_method", ""),
#                 "status": data.get("status", ""),
#                 "created_at": data.get("created_at", ""),
#             })
#
#         return jsonify(orders)
#
#     except Exception as e:
#         return jsonify({
#             "error": str(e)
#         }), 500




from auth_utils import (
    require_role,
    verify_password,
    hash_password,
    log_admin_action, AUDIT_LOGS
)
from db import (
    CUSTOMER_ORDERS,
    SHOP_ITEMS,
    USERS,
    VENDOR_SUBSCRIPTIONS,
    col,
    doc,
    now_iso,
    to_dict,
    NOTIFICATIONS,
    APP_SETTINGS
)
from flask import Blueprint, jsonify, request, g
from google.cloud.firestore_v1.base_query import FieldFilter

admin_bp = Blueprint("admin", __name__)


def _users_by_role(role: str, include_suspended: bool = False):
    query = col(USERS).where(filter=FieldFilter("role", "==", role))
    users = [to_dict(d) for d in query.stream()]
    if include_suspended and role == "vendor":
        suspended_query = col(USERS).where(
            filter=FieldFilter("suspended_role", "==", "vendor")
        )
        existing = {u.get("uid") for u in users}
        users.extend(
            to_dict(d)
            for d in suspended_query.stream()
            if d.id not in existing
        )
    return users


@admin_bp.get("/admin/customers/<user_id>")
@require_role("admin", "super_admin")
def get_customers(user_id):
    snapshot = doc(USERS, user_id).get()

    if not snapshot.exists:
        return jsonify({
            "detail": "User not found",
        }), 404

    user = to_dict(snapshot)

    user.pop("password_hash", None)

    return jsonify({
        "uid": user.get("uid", snapshot.id),
        "full_name": user.get("full_name", ""),
        "email": user.get("email", ""),
        "phone": user.get("phone", ""),
        "role": user.get("role", ""),
        "is_suspended": bool(user.get("is_suspended", False)),
    })


@admin_bp.put("/admin/customers/<user_id>")
@require_role("admin", "super_admin")
def update_customer(user_id):
    snapshot = doc(USERS, user_id).get()

    if not snapshot.exists:
        return jsonify({
            "detail": "User not found",
        }), 404

    body = request.get_json(force=True)

    updates = {
        "full_name": body.get("full_name"),
        "email": body.get("email"),
        "phone": body.get("phone"),
        "role": body.get("role"),
        "is_suspended": body.get("is_suspended"),
        "updated_at": now_iso(),
    }

    updates = {
        k: v
        for k, v in updates.items()
        if v is not None
    }

    doc(USERS, user_id).update(updates)

    log_admin_action(
        admin_id=g.user_id,
        admin_email=getattr(g, "user_email", ""),
        action="Update User",
        target_id=user_id,
        target_type="user",
    )

    return jsonify({
        "success": True,
    })


@admin_bp.delete("/admin/customers/<user_id>")
@require_role("admin", "super_admin")
def delete_customer(user_id):
    snapshot = doc(USERS, user_id).get()

    if not snapshot.exists:
        return jsonify({
            "detail": "User not found",
        }), 404

    doc(USERS, user_id).delete()

    log_admin_action(
        admin_id=g.user_id,
        admin_email=getattr(g, "user_email", ""),
        action="Delete User",
        target_id=user_id,
        target_type="user",
    )

    return jsonify({
        "success": True,
    })


@admin_bp.get("/admin/stats")
@require_role("admin", "super_admin")
def get_stats():
    vendors = list(
        col(USERS)
        .where(filter=FieldFilter("role", "==", "vendor"))
        .stream()
    )

    customers = list(
        col(USERS)
        .where(filter=FieldFilter("role", "==", "customer"))
        .stream()
    )

    active_subs = list(
        col(VENDOR_SUBSCRIPTIONS)
        .where(filter=FieldFilter("status", "==", "active"))
        .stream()
    )

    total_revenue = 0
    total_orders = 0

    pending_orders = 0
    confirmed_orders = 0
    delivered_orders = 0
    cancelled_orders = 0

    for d in col(CUSTOMER_ORDERS).stream():

        total_orders += 1

        data = d.to_dict() or {}

        status = str(
            data.get("status", "")
        ).lower()

        if status == "pending":
            pending_orders += 1

        elif status == "confirmed":
            confirmed_orders += 1

        elif status == "delivered":
            delivered_orders += 1

        elif status == "cancelled":
            cancelled_orders += 1

        if status in [
            "confirmed",
            "delivered",
            "completed",
            "paid",
        ]:
            try:
                total_revenue += float(
                    data.get("total_price") or 0
                )
            except:
                pass

    return jsonify({
        "vendor_count": len(vendors),
        "customer_count": len(customers),
        "total_orders": total_orders,
        "active_subscriptions": len(active_subs),
        "pending_orders": pending_orders,
        "confirmed_orders": confirmed_orders,
        "delivered_orders": delivered_orders,
        "cancelled_orders": cancelled_orders,
        "total_revenue": total_revenue,
    })


@admin_bp.get("/admin/vendors")
@require_role("admin", "super_admin")
def list_vendors():
    vendors = _users_by_role("vendor", include_suspended=True)
    for v in vendors:
        v.pop("password_hash", None)
        v["id"] = v.get("uid")
        v["role"] = v.get("role") or "vendor"
        v["is_suspended"] = bool(v.get("is_suspended"))
    return jsonify(vendors)



@admin_bp.get("/admin/vendors/<vendor_id>")
@require_role("admin", "super_admin")
def get_vendor(vendor_id):
    snapshot = doc(USERS, vendor_id).get()

    if not snapshot.exists:
        return jsonify({
            "detail": "Vendor not found",
        }), 404

    vendor = to_dict(snapshot)

    if (
        vendor.get("role") != "vendor"
        and vendor.get("suspended_role") != "vendor"
    ):
        return jsonify({
            "detail": "Vendor not found",
        }), 404

    vendor.pop("password_hash", None)

    return jsonify({
        "uid": vendor.get("uid", snapshot.id),
        "full_name": vendor.get("full_name", ""),
        "email": vendor.get("email", ""),
        "phone": vendor.get("phone", ""),
        "role": "vendor",
        "is_suspended": bool(
            vendor.get("is_suspended", False),
        ),
    })

@admin_bp.put("/admin/vendors/<vendor_id>")
@require_role("admin", "super_admin")
def update_vendor(vendor_id):
    snapshot = doc(USERS, vendor_id).get()

    if not snapshot.exists:
        return jsonify({
            "detail": "Vendor not found",
        }), 404

    vendor = to_dict(snapshot)

    if (
        vendor.get("role") != "vendor"
        and vendor.get("suspended_role") != "vendor"
    ):
        return jsonify({
            "detail": "Vendor not found",
        }), 404

    body = request.get_json(force=True)

    updates = {
        "full_name": body.get("full_name"),
        "email": body.get("email"),
        "phone": body.get("phone"),
        "is_suspended": body.get("is_suspended"),
        "updated_at": now_iso(),
    }

    updates = {
        k: v
        for k, v in updates.items()
        if v is not None
    }

    doc(USERS, vendor_id).update(updates)

    log_admin_action(
        admin_id=g.user_id,
        admin_email=getattr(g, "user_email", ""),
        action="Update Vendor",
        target_id=vendor_id,
        target_type="vendor",
    )

    return jsonify({
        "success": True,
    })

@admin_bp.delete("/admin/vendors/<vendor_id>")
@require_role("admin", "super_admin")
def delete_vendor(vendor_id):
    snapshot = doc(USERS, vendor_id).get()

    if not snapshot.exists:
        return jsonify({
            "detail": "Vendor not found",
        }), 404

    vendor = to_dict(snapshot)

    if (
        vendor.get("role") != "vendor"
        and vendor.get("suspended_role") != "vendor"
    ):
        return jsonify({
            "detail": "Vendor not found",
        }), 404

    doc(USERS, vendor_id).delete()

    log_admin_action(
        admin_id=g.user_id,
        admin_email=getattr(g, "user_email", ""),
        action="Delete Vendor",
        target_id=vendor_id,
        target_type="vendor",
    )

    return jsonify({
        "success": True,
    })

@admin_bp.post("/admin/vendors/<vendor_id>/suspend")
@require_role("admin", "super_admin")
def suspend_vendor(vendor_id):
    snapshot = doc(USERS, vendor_id).get()

    if not snapshot.exists:
        return jsonify({
            "detail": "Vendor not found",
        }), 404

    vendor = to_dict(snapshot)

    if (
        vendor.get("role") != "vendor"
        and vendor.get("suspended_role") != "vendor"
    ):
        return jsonify({
            "detail": "Vendor not found",
        }), 404

    current_role = vendor.get("role") or "vendor"

    doc(USERS, vendor_id).set(
        {
            "is_suspended": True,
            "suspended_role": current_role,
            "suspended_at": now_iso(),
            "updated_at": now_iso(),
        },
        merge=True,
    )

    log_admin_action(
        admin_id=g.user_id,
        admin_email=getattr(g, "user_email", ""),
        action="Suspend Vendor",
        target_id=vendor_id,
        target_type="vendor",
    )

    return jsonify({
        "success": True,
        "message": "Vendor suspended successfully",
    })

@admin_bp.post("/admin/vendors/<vendor_id>/unsuspend")
@require_role("admin", "super_admin")
def unsuspend_vendor(vendor_id):
    snapshot = doc(USERS, vendor_id).get()

    if not snapshot.exists:
        return jsonify({
            "detail": "Vendor not found",
        }), 404

    vendor = to_dict(snapshot)

    if (
        vendor.get("role") != "vendor"
        and vendor.get("suspended_role") != "vendor"
    ):
        return jsonify({
            "detail": "Vendor not found",
        }), 404

    doc(USERS, vendor_id).set(
        {
            "is_suspended": False,
            "suspended_role": None,
            "suspended_at": None,
            "updated_at": now_iso(),
        },
        merge=True,
    )

    log_admin_action(
        admin_id=g.user_id,
        admin_email=getattr(g, "user_email", ""),
        action="Unsuspend Vendor",
        target_id=vendor_id,
        target_type="vendor",
    )

    return jsonify({
        "success": True,
        "message": "Vendor unsuspended successfully",
    })


@admin_bp.get("/admin/customers")
@require_role("admin", "super_admin")
def list_customers():
    customers = _users_by_role("customer")
    for c in customers:
        c.pop("password_hash", None)
        c["id"] = c.get("uid")
        # Compute lightweight orders_count; safe for small datasets.
        orders_query = col(CUSTOMER_ORDERS).where(
            filter=FieldFilter("customer_id", "==", c["id"])
        )
        c["orders_count"] = sum(1 for _ in orders_query.stream())
    return jsonify(customers)


@admin_bp.post("/admin/customers/<user_id>/suspend")
@require_role("admin", "super_admin")
def suspend_customers(user_id):
    snap = doc(USERS, user_id).get()
    current_role = (snap.to_dict() or {}).get("role") if snap.exists else None
    doc(USERS, user_id).set({
        "is_suspended": True,
        "suspended_role": current_role,
        "suspended_at": now_iso(),
    }, merge=True)

    log_admin_action(
        g.user_id,
        "admin@gmail.com",
        "Suspend User",
        user_id,
        "user",
    )
    return jsonify({"ok": True})


@admin_bp.post("/admin/customers/<user_id>/unsuspend")
@require_role("admin", "super_admin")
def unsuspend_customers(user_id):
    doc(USERS, user_id).set(
        {"is_suspended": False, "suspended_at": None, "suspended_role": None},
        merge=True,
    )
    log_admin_action(
        g.user_id,
        "admin@gmail.com",
        "Suspend User",
        user_id,
        "user",
    )
    return jsonify({"ok": True})


@admin_bp.get("/admin/orders")
@require_role("admin", "super_admin")
def admin_orders():
    docs = col(CUSTOMER_ORDERS).stream()

    orders = []

    for doc_snap in docs:
        data = to_dict(doc_snap)

        customer_name = data.get("customer_name")
        if not isinstance(customer_name, str):
            data["customer_name"] = ""

        vendor_name = data.get("vendor_name")
        if not isinstance(vendor_name, str):
            data["vendor_name"] = ""

        item_name = data.get("item_name")
        if not isinstance(item_name, str):
            data["item_name"] = ""

        status = data.get("status")
        if not isinstance(status, str):
            data["status"] = ""

        orders.append(data)

    return jsonify(orders)


@admin_bp.get("/admin/products")
@require_role("admin", "super_admin")
def admin_products():
    docs = col(SHOP_ITEMS).stream()

    products = []

    for doc_snap in docs:
        product = to_dict(doc_snap)

        image_urls = product.get("image_urls") or []

        stock = product.get("stock_quantity", 0)

        product["total_images"] = len(image_urls)

        product["primary_image"] = (
            image_urls[0] if image_urls else ""
        )

        product["has_stock"] = stock > 0

        product["status"] = (
            "Available"
            if product.get("is_available", True)
            else "Disabled"
        )

        product["stock_status"] = (
            "Out of Stock"
            if stock <= 0
            else (
                "Low Stock"
                if stock < 10
                else "In Stock"
            )
        )

        products.append(product)

    products.sort(
        key=lambda x: x.get("updated_at", ""),
        reverse=True,
    )

    return jsonify(products)


@admin_bp.get("/admin/products/<product_id>")
@require_role("admin", "super_admin")
def get_product(product_id):
    snapshot = doc(SHOP_ITEMS, product_id).get()

    if not snapshot.exists:
        return jsonify(
            {
                "detail": "Product not found"
            }
        ), 404

    product = to_dict(snapshot)

    images = product.get("image_urls") or []

    stock = product.get("stock_quantity", 0)

    product["total_images"] = len(images)

    product["primary_image"] = (
        images[0] if images else ""
    )

    product["status"] = (
        "Available"
        if product.get("is_available", True)
        else "Disabled"
    )

    product["has_stock"] = stock > 0

    return jsonify(product)


import uuid


@admin_bp.post("/admin/products")
@require_role("admin", "super_admin")
def create_product():
    body = request.json or {}

    product_id = uuid.uuid4().hex

    product = {

        "name": body.get("name", "").strip(),

        "description": body.get("description", ""),

        "price": float(body.get("price", 0)),

        "stock_quantity": int(body.get("stock_quantity", 0)),

        "category": body.get("category", ""),

        "image_urls": body.get("image_urls", []),

        "vendor_id": body.get("vendor_id"),

        "vendor_name": body.get("vendor_name"),

        "vendor_email": body.get("vendor_email"),

        "vendor_phone": body.get("vendor_phone"),

        "vendor_shop_description":
            body.get("vendor_shop_description"),

        "is_available": True,

        "created_at": now_iso(),

        "updated_at": now_iso(),
    }

    doc(SHOP_ITEMS, product_id).set(product)

    log_admin_action(
        g.user_id,
        getattr(g, "user_email", ""),
        "Create Product",
        product_id,
        "product",
    )

    return jsonify(
        {
            "success": True,
            "uid": product_id,
        }
    )


@admin_bp.put("/admin/products/<product_id>")
@require_role("admin", "super_admin")
def update_product(product_id):
    snapshot = doc(SHOP_ITEMS, product_id).get()

    if not snapshot.exists:
        return jsonify(
            {
                "detail": "Product not found"
            }
        ), 404

    body = request.json or {}

    updates = {

        "name": body.get("name"),

        "description": body.get("description"),

        "price": body.get("price"),

        "stock_quantity": body.get("stock_quantity"),

        "category": body.get("category"),

        "image_urls": body.get("image_urls"),

        "is_available": body.get("is_available"),

        "updated_at": now_iso(),
    }

    updates = {
        k: v
        for k, v in updates.items()
        if v is not None
    }

    doc(SHOP_ITEMS, product_id).update(updates)

    log_admin_action(
        g.user_id,
        getattr(g, "user_email", ""),
        "Update Product",
        product_id,
        "product",
    )

    return jsonify(
        {
            "success": True
        }
    )


@admin_bp.get("/admin/analytics")
@require_role("admin", "super_admin")
def analytics():
    vendors = list(
        col(USERS).where(
            filter=FieldFilter("role", "==", "vendor")
        ).stream()
    )

    customers = list(
        col(USERS).where(
            filter=FieldFilter("role", "==", "customer")
        ).stream()
    )

    orders = list(col(CUSTOMER_ORDERS).stream())

    revenue = 0.0

    for d in orders:
        data = d.to_dict() or {}

        try:
            revenue += float(
                data.get("total_price") or 0
            )
        except Exception:
            pass

    return jsonify({
        "vendors": len(vendors),
        "customers": len(customers),
        "orders": len(orders),
        "revenue": revenue,
    })




@admin_bp.post("/admin/notifications/send")
@require_role("admin", "super_admin")
def send_notification():
    data = request.get_json(force=True)

    title = data.get("title", "").strip()
    message = data.get("message", "").strip()
    target = data.get("target", "all").strip().lower()



    if not title:
        return jsonify({"detail": "Title is required"}), 400

    if not message:
        return jsonify({"detail": "Message is required"}), 400

    users_query = col(USERS)

    # Customers
    if target in ("customer", "customers"):
        users_query = users_query.where(
            filter=FieldFilter("role", "==", "customer")
        )

    # Vendors
    elif target in ("vendor", "vendors"):
        users_query = users_query.where(
            filter=FieldFilter("role", "==", "vendor")
        )

    # Admins
    elif target in ("admin", "admins"):
        users_query = users_query.where(
            filter=FieldFilter("role", "in", ["admin", "super_admin"])
        )

    # All users
    elif target == "all":
        pass

    else:
        return jsonify({"detail": f"Unknown target: {target}"}), 400

    users = list(users_query.stream())



    db = col(USERS)._client
    batch = db.batch()

    count = 0

    for user in users:
        ref = col(NOTIFICATIONS).document()

        batch.set(
            ref,
            {
                "uid": ref.id,
                "user_id": user.id,
                "title": title,
                "message": message,
                "target": target,
                "is_read": False,
                "created_at": now_iso(),
            },
        )

        count += 1

        if count % 450 == 0:
            batch.commit()
            batch = db.batch()

    if count % 450 != 0:
        batch.commit()

    return jsonify(
        {
            "success": True,
            "sent": count,
            "target": target,
        }
    )


@admin_bp.get("/admin/notifications")
@require_role("admin", "super_admin")
def list_notifications():
    docs = col(NOTIFICATIONS).stream()

    notifications = []

    for d in docs:
        notifications.append(to_dict(d))

    return jsonify(notifications)


@admin_bp.post("/admin/change-password")
@require_role("admin", "super_admin")
def change_password():
    data = request.get_json(force=True)

    current_password = data.get("current_password")
    new_password = data.get("new_password")

    if not current_password:
        return jsonify({
            "detail": "Current password required"
        }), 400

    if not new_password:
        return jsonify({
            "detail": "New password required"
        }), 400

    user_snapshot = doc(USERS, g.user_id).get()

    if not user_snapshot.exists:
        return jsonify({
            "detail": "User not found"
        }), 404

    user = user_snapshot.to_dict() or {}

    stored_hash = user.get("password_hash", "")

    if not verify_password(
            current_password,
            stored_hash,
    ):
        return jsonify({
            "detail": "Current password incorrect"
        }), 400

    doc(USERS, g.user_id).set(
        {
            "password_hash":
                hash_password(new_password)
        },
        merge=True,
    )

    return jsonify({
        "success": True
    })


@admin_bp.post("/admin/products/<product_id>/disable")
@require_role("admin", "super_admin")
def disable_product(product_id):
    product_ref = doc(SHOP_ITEMS, product_id)
    snapshot = product_ref.get()

    if not snapshot.exists:
        return jsonify({
            "detail": "Product not found"
        }), 404

    product_ref.update({
        "is_available": False,
        "disabled_by_admin": True,
        "updated_at": now_iso(),
    })

    log_admin_action(
        admin_id=g.user_id,
        admin_email=getattr(g, "user_email", ""),
        action="Disable Product",
        target_id=product_id,
        target_type="product",
    )

    return jsonify({
        "success": True,
        "message": "Product disabled successfully",
    }), 200


@admin_bp.post("/admin/products/<product_id>/enable")
@require_role("admin", "super_admin")
def enable_product(product_id):
    product_ref = doc(SHOP_ITEMS, product_id)
    snapshot = product_ref.get()

    if not snapshot.exists:
        return jsonify({
            "detail": "Product not found"
        }), 404

    product_ref.update({
        "is_available": True,
        "disabled_by_admin": False,
        "updated_at": now_iso(),
    })

    log_admin_action(
        admin_id=g.user_id,
        admin_email=getattr(g, "user_email", ""),
        action="Enable Product",
        target_id=product_id,
        target_type="product",
    )

    return jsonify({
        "success": True,
        "message": "Product enabled successfully",
    }), 200


@admin_bp.delete("/admin/products/<product_id>")
@require_role("admin", "super_admin")
def delete_product(product_id):
    snapshot = doc(SHOP_ITEMS, product_id).get()

    if not snapshot.exists:
        return jsonify(
            {
                "detail": "Product not found"
            }
        ), 404

    doc(SHOP_ITEMS, product_id).delete()

    log_admin_action(
        admin_id=g.user_id,
        admin_email=g.user_email,
        action="Delete Product",
        target_id=product_id,
        target_type="product",
    )

    return jsonify(
        {
            "success": True
        }
    )


@admin_bp.get("/admin/orders/<order_id>")
@require_role("admin", "super_admin")
def get_order_detail(order_id):
    snapshot = doc(CUSTOMER_ORDERS, order_id).get()

    if not snapshot.exists:
        return jsonify({
            "detail": "Order not found"
        }), 404

    return jsonify(to_dict(snapshot))


@admin_bp.post("/admin/orders/<order_id>/cancel")
@require_role("admin", "super_admin")
def admin_cancel_order(order_id):
    doc(CUSTOMER_ORDERS, order_id).set(
        {
            "status": "cancelled",
            "cancelled_by": "admin",
            "updated_at": now_iso(),
        },
        merge=True,
    )

    return jsonify({
        "success": True
    })


@admin_bp.post("/admin/orders/<order_id>/refund")
@require_role("admin", "super_admin")
def refund_order(order_id):
    doc(CUSTOMER_ORDERS, order_id).set(
        {
            "refund_status": "refunded",
            "refunded_at": now_iso(),
        },
        merge=True,
    )

    return jsonify({
        "success": True
    })


@admin_bp.get("/admin/subscriptions")
@require_role("admin", "super_admin")
def list_subscriptions():
    return jsonify([
        to_dict(d)
        for d in col(VENDOR_SUBSCRIPTIONS).stream()
    ])


@admin_bp.post("/admin/subscriptions/<sub_id>/activate")
@require_role("admin", "super_admin")
def activate_subscription(sub_id):
    doc(VENDOR_SUBSCRIPTIONS, sub_id).set(
        {
            "status": "active",
            "updated_at": now_iso(),
        },
        merge=True,
    )

    return jsonify({"success": True})


@admin_bp.post("/admin/subscriptions/<sub_id>/suspend")
@require_role("admin", "super_admin")
def suspend_subscription(sub_id):
    doc(VENDOR_SUBSCRIPTIONS, sub_id).set(
        {
            "status": "suspended",
            "updated_at": now_iso(),
        },
        merge=True,
    )

    return jsonify({"success": True})


@admin_bp.get("/admin/audit-logs")
@require_role("admin", "super_admin")
def audit_logs():
    try:
        print("AUDIT LOG ROUTE HIT")

        logs = [
            to_dict(d)
            for d in col(AUDIT_LOGS).stream()
        ]

        print(f"FOUND {len(logs)} LOGS")

        logs.sort(
            key=lambda x: x.get("created_at", ""),
            reverse=True,
        )

        return jsonify(logs)

    except Exception as e:
        import traceback
        traceback.print_exc()

        return jsonify({
            "error": str(e),
            "type": type(e).__name__,
        }), 500


@admin_bp.get("/maintenance-status")
def maintenance_status():
    settings_doc = doc(
        APP_SETTINGS,
        "config",
    ).get()

    if not settings_doc.exists:
        return jsonify({
            "maintenance_mode": False,
        })

    data = settings_doc.to_dict() or {}

    return jsonify({
        "maintenance_mode":
            data.get(
                "maintenance_mode",
                False,
            ),
    })


@admin_bp.post("/admin/maintenance")
@require_role("admin", "super_admin")
def update_maintenance_status():
    data = request.get_json(force=True)

    maintenance_mode = bool(
        data.get("maintenance_mode", False)
    )

    doc(
        APP_SETTINGS,
        "config",
    ).set(
        {
            "maintenance_mode":
                maintenance_mode,
            "updated_at": now_iso(),
        },
        merge=True,
    )

    return jsonify({
        "success": True,
        "maintenance_mode":
            maintenance_mode,
    })


@admin_bp.get("/admin/maintenance")
@require_role("admin", "super_admin")
def get_maintenance_status():
    settings_doc = doc(
        APP_SETTINGS,
        "config",
    ).get()

    if not settings_doc.exists:
        return jsonify({
            "maintenance_mode": False,
        })

    data = settings_doc.to_dict() or {}

    return jsonify({
        "maintenance_mode":
            data.get(
                "maintenance_mode",
                False,
            ),
        "updated_at":
            data.get("updated_at"),
    })


@admin_bp.get("/admin/recent-orders")
@require_role("admin", "super_admin")
def get_recent_orders():
    try:

        docs = (
            col(CUSTOMER_ORDERS)
            .order_by("created_at", direction="DESCENDING")
            .limit(20)
            .stream()
        )

        orders = []

        for d in docs:
            data = d.to_dict() or {}

            orders.append({
                "id": d.id,
                "customer_id": data.get("customer_id"),
                "vendor_id": data.get("vendor_id"),
                "vendor_name": data.get("vendor_name", ""),
                "item_name": data.get("item_name", ""),
                "quantity": data.get("quantity", 0),
                "total_price": data.get("total_price", 0),
                "payment_method": data.get("payment_method", ""),
                "status": data.get("status", ""),
                "created_at": data.get("created_at", ""),
            })

        return jsonify(orders)

    except Exception as e:
        return jsonify({
            "error": str(e)
        }), 500