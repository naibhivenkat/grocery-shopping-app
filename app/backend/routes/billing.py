"""Party-scoped order bills and vendor discounts on uncollected cash orders."""
from io import BytesIO
from routes.measurement import metadata, quantity_label
from routes.discounts import allocate
from routes.order_amendments import guard_order_mutation
from xml.sax.saxutils import escape

from firebase_admin import firestore
from flask import Blueprint, g, jsonify, request, send_file, Response
from google.cloud.firestore_v1.base_query import FieldFilter

from auth_utils import require_auth, require_role
from db import CUSTOMER_ORDERS, col, db, doc, now_iso
from routes.khata import KhataError, _khata_error, _identifier, _money_paise, _payload

billing_bp = Blueprint("billing", __name__)
billing_bp.register_error_handler(KhataError, _khata_error)


def invoice_data(order_id, selected_ids=None):
    snap = doc(CUSTOMER_ORDERS, _identifier(order_id, "order_id")).get()
    if not snap.exists:
        raise KhataError("Order not found", 404)
    order = snap.to_dict() or {}
    if g.user_id not in {order.get("customer_id"), order.get("vendor_id")}:
        raise KhataError("This bill belongs to another account", 403)
    snapshots = [snap]
    batch_id = order.get("batch_id")
    if batch_id:
        snapshots = list(col(CUSTOMER_ORDERS).where(filter=FieldFilter("batch_id", "==", batch_id)).stream())
    if selected_ids is not None:
        if not selected_ids or len(selected_ids) > 100 or len(set(selected_ids)) != len(selected_ids):
            raise KhataError("Select between 1 and 100 distinct bill items", 422)
        selected_ids = {_identifier(value, "line_id") for value in selected_ids}
        available = {entry.id for entry in snapshots if (entry.to_dict() or {}).get("status") != "removed"}
        if not selected_ids.issubset(available):
            raise KhataError("Selected items do not belong to this current bill", 422)
    lines = []
    for entry in snapshots:
        value = entry.to_dict() or {}
        if value.get("status") == "removed":
            continue
        if (value.get("customer_id"), value.get("vendor_id")) != (order.get("customer_id"), order.get("vendor_id")):
            raise KhataError("Bill contains inconsistent parties", 409)
        if selected_ids is not None and entry.id not in selected_ids:
            continue
        total = _money_paise(value.get("total_price", 0), allow_zero=True)
        discount = _money_paise(value.get("discount_amount", 0), allow_zero=True)
        subtotal = _money_paise(value.get("subtotal", (total + discount) / 100), allow_zero=True)
        due = _money_paise(value.get("due_amount", 0 if value.get("payment_status") == "paid" else total / 100), allow_zero=True)
        lines.append({"order_id": entry.id, "name": value.get("item_name") or "Product",
                      "price_basis": f"INR {value.get('item_selling_price', value.get('item_unit_price', 0)):.2f} / {quantity_label(metadata(value)['pricing_quantity'], value)}",
                      "quantity": value.get("quantity", 1), "quantity_label": quantity_label(value.get("quantity", 1), value),
                      **metadata(value), "item_selling_price": value.get("item_selling_price", value.get("item_unit_price", 0)), "unit_price": value.get("item_unit_price", 0),
                      "subtotal": subtotal / 100, "discount": discount / 100, "total": total / 100,
                      "due": due / 100, "status": value.get("status"),
                      "payment_exempt": value.get("payment_exempt") is True,
                      "partial_amount_paid": value.get("partial_amount_paid", 0),
                      "payment_status": value.get("payment_status", "pending")})
    lines.sort(key=lambda value: value["order_id"])
    return {"invoice_number": f"LS-{batch_id or order_id}", "created_at": order.get("created_at"),
            "customer_name": order.get("customer_name") or "Customer", "shop_name": order.get("vendor_name") or "Shop",
            "payment_method": order.get("payment_method"), "lines": lines,
            "amendment_pending": any((entry.to_dict() or {}).get("amendment_pending") for entry in snapshots),
            "selection": selected_ids is not None,
            **{field: sum(round(line[key] * 100) for line in lines) / 100
               for field, key in (("subtotal", "subtotal"), ("discount", "discount"), ("total", "total"), ("due", "due"))}}


@billing_bp.get("/orders/<order_id>/invoice")
@require_auth
def get_invoice(order_id):
    return jsonify(invoice_data(order_id, request.args.getlist("line_id") if "line_id" in request.args else None))


def invoice_html(invoice):
    rows = ''.join('<tr>' + ''.join(f'<td>{escape(str(cell))}</td>' for cell in (
        f"{line['name']} ({line['price_basis']})", line['quantity_label'], f"{line['subtotal']:.2f}", f"{line['discount']:.2f}",
        f"{line['total']:.2f}", f"{line['status']} / {line['payment_status']}")) + '</tr>' for line in invoice['lines'])
    details = ''.join(f'<p>{label}: {escape(str(invoice.get(key) or "-"))}</p>' for label, key in (
        ('Bill', 'invoice_number'), ('Date', 'created_at'), ('Shop', 'shop_name'), ('Customer', 'customer_name'), ('Payment', 'payment_method')))
    totals = ''.join(f'<p>{field.title()} (INR): {invoice[field]:.2f}</p>' for field in ('subtotal', 'discount', 'total', 'due'))
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1"><title>LocalShop Order Bill</title><style>
        @page {{ size:A4; margin:18mm; }}
        body {{ font-family:"Noto Sans", "Noto Sans Kannada", "Noto Sans Devanagari", sans-serif; color:#183c28; font-size:10pt; max-width:1000px; margin:24px auto; padding:12px; }}
        h1 {{ font-size:22pt; color:#25733c; border-bottom:3px solid #25733c; padding-bottom:12pt; }}
        table {{ border-collapse:collapse; width:100%; margin:16pt 0; }}
        th,td {{ border:1px solid #b9cbbd; padding:7pt; overflow-wrap:anywhere; text-align:left; }}
        th {{ background:#e8f5e9; white-space:nowrap; font-size:8pt; }} td:nth-child(2) {{ white-space:nowrap; }} thead {{ display:table-header-group; }}
        tr {{ break-inside:avoid; }} .note {{ color:#46564b; }}
        @media print {{ body {{ margin:0; padding:0; }} button {{ display:none; }} }}
        </style></head><body><h1>LocalShop Order Bill</h1>{details}
        <p>{"Selected items only" if invoice.get("selection") else "Shop order items"}</p>
        <table><thead><tr><th>Product</th><th>Qty</th><th>Subtotal</th><th>Discount</th><th>Payable</th><th>Status</th></tr></thead><tbody>{rows}</tbody></table>
        {totals}<p class="note">An order bill is not proof of payment. Payment status and amount due are shown above.</p>
        <button onclick="window.print()">Print bill</button></body></html>'''


def render_invoice(invoice):
    from weasyprint import HTML
    return HTML(string=invoice_html(invoice)).write_pdf()


@billing_bp.get("/orders/<order_id>/invoice.html")
@require_auth
def get_invoice_html(order_id):
    invoice = invoice_data(order_id, request.args.getlist("line_id") if "line_id" in request.args else None)
    response = Response(invoice_html(invoice), mimetype="text/html")
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; frame-ancestors 'none'"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@billing_bp.get("/orders/<order_id>/invoice.pdf")
@require_auth
def get_invoice_pdf(order_id):
    invoice = invoice_data(order_id, request.args.getlist("line_id") if "line_id" in request.args else None)
    return send_file(BytesIO(render_invoice(invoice)), mimetype="application/pdf", as_attachment=True,
                     download_name=f"{invoice['invoice_number']}.pdf", max_age=0)


@billing_bp.put("/vendors/orders/<order_id>/discount")
@require_role("vendor")
def discount_order(order_id):
    payload = _payload()
    amount = _money_paise(payload.get("amount"), allow_zero=True)
    ref = doc(CUSTOMER_ORDERS, _identifier(order_id, "order_id"))
    audit_ref = col("order_discount_changes").document()

    @firestore.transactional
    def update(tx):
        snap = ref.get(transaction=tx)
        if not snap.exists:
            raise KhataError("Order not found", 404)
        order = snap.to_dict() or {}
        if order.get("vendor_id") != g.user_id:
            raise KhataError("Not your order", 403)
        guard_order_mutation(tx, order, lookup=doc)
        if order.get("pricing_revision", 0) > 0:
            raise KhataError("Use a customer-approved amendment to change a revised order discount", 409)
        snapshots = [snap]
        batch_id = order.get("batch_id")
        batch_ref = doc("order_batches", batch_id) if batch_id else None
        batch_snap = batch_ref.get(transaction=tx) if batch_ref else None
        if batch_id:
            snapshots = list(tx.get(col(CUSTOMER_ORDERS).where(filter=FieldFilter("batch_id", "==", batch_id))))
        lines = []
        for member in snapshots:
            value = member.to_dict() or {}
            if (value.get("vendor_id"), value.get("customer_id")) != (g.user_id, order.get("customer_id")):
                raise KhataError("Order contains inconsistent parties", 409)
            exempt = value.get("payment_exempt") is True and _money_paise(value.get("total_price"), allow_zero=True) == 0
            collected = _money_paise(value.get("partial_amount_paid", 0), allow_zero=True)
            if (value.get("payment_method") != "cash" or value.get("status") not in {"pending", "confirmed", "packed"}
                    or value.get("payment_status") not in ({"pending", "paid"} if exempt else {"pending"})
                    or collected > 0 or value.get("payment_intent_id") or value.get("refund_status")
                    or value.get("payment_id") or value.get("razorpay_payment_id") or value.get("paid_at")):
                raise KhataError("Discounts can be changed only on uncollected cash orders", 409)
            total = _money_paise(value.get("total_price"), allow_zero=True)
            previous = _money_paise(value.get("discount_amount", 0), allow_zero=True)
            gross = _money_paise(value.get("subtotal", (total + previous) / 100), allow_zero=True)
            lines.append((member, value, gross))
        shares = allocate([(member.id, gross) for member, _, gross in lines], amount)
        subtotal = sum(gross for _, _, gross in lines)
        timestamp = now_iso()
        for member, _, gross in lines:
            discount = shares[member.id]
            total = gross - discount
            tx.update(member.reference, {"subtotal": gross / 100, "discount_amount": discount / 100,
                "total_price": total / 100, "total_paise": total, "due_amount": total / 100,
                "payment_exempt": total == 0, "payment_status": "paid" if subtotal == amount else "pending",
                "partial_amount_paid": 0, "promotion_id": None, "promotion_revision": None, "promotion_rules": None,
                "discount_source": "manual", "discount_updated_by": g.user_id, "updated_at": timestamp})
        tx.set(audit_ref, {"vendor_id": g.user_id, "customer_id": order.get("customer_id"),
                           "batch_id": batch_id, "order_id": order_id, "amount_paise": amount,
                           "previous": [{"order_id": member.id, "discount_amount": value.get("discount_amount", 0),
                                         "promotion_id": value.get("promotion_id"), "promotion_revision": value.get("promotion_revision"),
                                         "promotion_rules": value.get("promotion_rules")} for member, value, _ in lines],
                           "created_at": timestamp})
        if batch_snap is not None and batch_snap.exists:
            batch = batch_snap.to_dict() or {}
            response = {**batch.get("response", {}), "subtotal": subtotal / 100, "discount_amount": amount / 100,
                        "total_price": (subtotal - amount) / 100, "payment_exempt": amount == subtotal,
                        "promotion_id": None, "promotion_revision": None}
            tx.set(batch_ref, {"response": response, "promotion_rules": None, "discount_updated_by": g.user_id,
                               "discount_source": "manual", "manual_discount_paise": amount,
                               "updated_at": timestamp}, merge=True)
    update(db().transaction())
    return jsonify(invoice_data(order_id))
