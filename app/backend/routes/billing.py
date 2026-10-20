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
    """Restore the first mobile invoice's green/white card around trusted bill data.

    The caller owns selection, prices, allocations and authorization. Rendering
    never adds tax or treats a payment method as evidence of collected money.
    """
    def text(value):
        return escape(str(value if value is not None else "-"))

    def label(value):
        return text(str(value or "Not available").replace("_", " ").title())

    def money(value):
        return f"₹{value:,.2f}"

    lines = invoice['lines']
    payment_states = {str(line.get('payment_status') or 'unknown').strip().lower() for line in lines}
    if lines and all(line.get('payment_exempt') is True and line['total'] == 0 for line in lines):
        payment_label, badge_kind = 'No payment required', 'settled'
    elif payment_states == {'paid'} and invoice['due'] == 0:
        payment_label, badge_kind = 'Paid', 'settled'
    elif payment_states == {'paid'}:
        payment_label, badge_kind = 'Payment review required', 'pending'
    elif payment_states in ({'pending'}, {'unpaid'}):
        payment_label, badge_kind = 'Payment pending', 'pending'
    elif len(payment_states) == 1:
        payment_label, badge_kind = label(next(iter(payment_states))), 'pending'
    else:
        payment_label, badge_kind = 'Mixed payment status' if lines else 'Payment status unavailable', 'pending'

    rows = ''.join(f"""<tr>
        <td class="product"><strong>{text(line['name'])}</strong><span class="price-basis">{text(line['price_basis'])}</span></td>
        <td class="quantity numeric">{text(line['quantity_label'])}</td>
        <td class="numeric">{money(line['subtotal'])}</td>
        <td class="numeric">{money(line['discount'])}</td>
        <td class="numeric payable">{money(line['total'])}</td>
        <td class="line-status"><span>Order: {label(line['status'])}</span><span>Payment: {label(line['payment_status'])}</span></td>
        </tr>""" for line in lines)
    details = ''.join(f'<div class="detail"><span class="detail-label">{caption}</span><span class="detail-value">{text(invoice.get(field) or "-")}</span></div>'
        for caption, field in (('Customer', 'customer_name'), ('Invoice number', 'invoice_number'),
                               ('Order date', 'created_at'), ('Payment method', 'payment_method')))
    totals = ''.join(f'<tr class="{style}"><th scope="row">{caption}</th><td class="numeric">{money(invoice[field])}</td></tr>'
        for caption, field, style in (('Subtotal', 'subtotal', ''), ('Discount', 'discount', ''),
                                     ('Total payable', 'total', 'grand-total'), ('Amount due', 'due', 'amount-due')))
    selection = 'Selected items only' if invoice.get('selection') else 'Shop order items'
    amendment_note = '<p class="notice">An order change is awaiting confirmation. This invoice shows the current order amounts.</p>' if invoice.get('amendment_pending') else ''
    # loadHtmlString does not retain HTTP response headers. Keep an equivalent
    # document policy; frame-ancestors is enforced by the endpoint header only.
    policy = "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; frame-ancestors 'none'"
    return f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="{policy}">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ALL LOCAL Order Invoice</title>
<style>
@page {{ size: A4; margin: 14mm; }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: #f3f6f4; color: #23382b; font-family: "Poppins", "Noto Sans", "Noto Sans Kannada", "Noto Sans Devanagari", Arial, sans-serif; font-size: 1rem; line-height: 1.5; }}
.container {{ max-width: 800px; margin: 0 auto; padding: 24px 16px; }}
.invoice-card {{ background: #fff; border: 1px solid #dce7df; border-radius: 16px; box-shadow: 0 2px 12px rgba(24, 60, 40, .10); overflow: hidden; }}
.invoice-header {{ position: relative; padding: 28px 24px; background: linear-gradient(135deg, #4caf50, #2e7d32); color: #fff; text-align: center; }}
.invoice-header::before {{ content: ""; position: absolute; inset: 0; background: rgba(0, 0, 0, .25); }}
.invoice-header > * {{ position: relative; }}
.brand-name {{ display: block; font-size: .875rem; font-weight: 700; letter-spacing: .12em; }}
h1 {{ margin: 5px 0 14px; font-size: 1.75rem; line-height: 1.25; }}
.payment-badge {{ display: inline-block; max-width: 100%; padding: 5px 14px; border: 1px solid rgba(255,255,255,.65); border-radius: 24px; background: #fff; color: #184d25; font-size: .875rem; font-weight: 700; overflow-wrap: anywhere; }}
.payment-badge.pending {{ background: #fff5d6; color: #714900; }}
.section {{ padding: 22px 24px; }}
.invoice-details {{ display: flex; flex-wrap: wrap; padding-bottom: 6px; }}
.detail {{ flex: 1 1 44%; min-width: 0; margin: 0 16px 16px 0; }}
.detail-label {{ display: block; margin-bottom: 3px; color: #526659; font-size: .8125rem; font-weight: 600; }}
.detail-value {{ display: block; font-weight: 600; overflow-wrap: anywhere; word-break: break-word; }}
.shop-band {{ margin: 0 24px; padding: 14px 18px; border-left: 4px solid #4caf50; border-radius: 8px; background: #f1f8e9; }}
.shop-band .detail-value {{ color: #1b5e20; font-size: 1.0625rem; }}
h2 {{ margin: 0 0 4px; font-size: 1rem; color: #1b5e20; }}
.section-note {{ margin: 0 0 14px; color: #526659; font-size: .875rem; }}
.table-scroll {{ overflow-x: auto; width: 100%; border: 1px solid #d4e3d7; border-radius: 8px; }}
.table-scroll:focus-visible {{ outline: 3px solid #2e7d32; outline-offset: 3px; }}
.items-table {{ width: 100%; min-width: 660px; border-collapse: collapse; font-size: .875rem; }}
.items-table th {{ background: #c8e6c9; color: #183c28; padding: 11px 10px; font-weight: 700; text-align: left; white-space: nowrap; }}
.items-table td {{ padding: 12px 10px; vertical-align: top; border-top: 1px solid #dce7df; }}
.items-table tbody tr:nth-child(even) {{ background: #f8fbf8; }}
.product {{ width: 28%; min-width: 170px; overflow-wrap: anywhere; word-break: break-word; }}
.product strong {{ display: block; font-weight: 600; }}
.price-basis {{ display: block; margin-top: 4px; color: #526659; font-size: .8125rem; }}
.numeric {{ text-align: right !important; white-space: nowrap; font-variant-numeric: tabular-nums; word-break: normal; overflow-wrap: normal; }}
.payable {{ font-weight: 700; color: #1b5e20; }}
.line-status {{ min-width: 125px; font-size: .8125rem; overflow-wrap: anywhere; }}
.line-status span {{ display: block; }}
.line-status span + span {{ margin-top: 4px; color: #526659; }}
.summary {{ max-width: 360px; margin: 20px 0 0 auto; }}
.summary-table {{ width: 100%; border-collapse: collapse; }}
.summary-table th, .summary-table td {{ padding: 8px 4px; text-align: left; font-weight: 400; }}
.summary-table .grand-total {{ border-top: 1px solid #b7d5bd; color: #1b5e20; }}
.summary-table .grand-total th, .summary-table .grand-total td {{ font-weight: 700; font-size: 1.0625rem; }}
.summary-table .amount-due {{ background: #f1f8e9; }}
.summary-table .amount-due th, .summary-table .amount-due td {{ padding: 10px 8px; font-weight: 700; }}
.notice {{ padding: 12px 14px; border-left: 3px solid #a16a00; background: #fff7e2; color: #644500; font-size: .875rem; overflow-wrap: anywhere; }}
.invoice-footer {{ padding: 18px 24px; border-top: 1px solid #dce7df; text-align: center; color: #526659; font-size: .8125rem; }}
.invoice-footer p {{ margin: 4px 0; }}
.thank-you {{ color: #1b5e20; font-size: .9375rem; }}
.print-actions {{ padding: 20px 0 4px; text-align: center; }}
.print-button {{ min-height: 44px; padding: 11px 24px; border: 0; border-radius: 8px; background: #2e7d32; color: #fff; font: inherit; font-weight: 600; cursor: pointer; }}
.print-button:focus-visible {{ outline: 3px solid #1b5e20; outline-offset: 3px; }}
thead {{ display: table-header-group; }}
tr, .invoice-header, .shop-band, .summary, .invoice-footer {{ break-inside: avoid; page-break-inside: avoid; }}
@media (max-width: 520px) {{
    .container {{ padding: 14px 10px; }}
    .invoice-header {{ padding: 24px 18px; }}
    .section {{ padding: 18px; }}
    .detail {{ flex-basis: 100%; margin-right: 0; }}
    .shop-band {{ margin: 0 18px; padding: 12px 14px; }}
    .invoice-footer {{ padding: 16px 18px; }}
}}
@media print {{
    body {{ background: #fff; font-size: 10pt; }}
    .container {{ max-width: none; margin: 0; padding: 0; }}
    .invoice-card {{ border: 0; border-radius: 0; box-shadow: none; overflow: visible; }}
    .invoice-header {{ padding: 12pt; background: #e8f5e9; color: #1b5e20; border-bottom: 2pt solid #2e7d32; }}
    .invoice-header::before {{ display: none; }}
    h1 {{ font-size: 20pt; margin-bottom: 8pt; }}
    .brand-name, .payment-badge {{ font-size: 9pt; }}
    .payment-badge {{ border: 1pt solid #60866a; background: #fff; color: #183c28; }}
    .section {{ padding: 12pt 0; }}
    .invoice-details {{ display: block; padding-bottom: 0; }}
    .detail {{ display: inline-block; width: 48%; margin: 0 1% 8pt 0; vertical-align: top; }}
    .shop-band {{ margin: 0; padding: 8pt 10pt; }}
    .table-scroll {{ overflow: visible; border: 0; border-radius: 0; }}
    .items-table {{ min-width: 0; table-layout: fixed; font-size: 8pt; }}
    .items-table th, .items-table td {{ padding: 6pt 4pt; }}
    .items-table th:first-child, .items-table td:first-child {{ width: 28%; min-width: 0; }}
    .items-table th:nth-child(2), .items-table td:nth-child(2) {{ width: 10%; }}
    .items-table th:nth-child(3), .items-table td:nth-child(3), .items-table th:nth-child(4), .items-table td:nth-child(4), .items-table th:nth-child(5), .items-table td:nth-child(5) {{ width: 12%; }}
    .items-table th:last-child, .items-table td:last-child {{ width: 26%; min-width: 0; }}
    .price-basis, .line-status {{ font-size: 8pt; }}
    .summary {{ max-width: 260pt; margin-top: 12pt; }}
    .invoice-footer {{ padding: 10pt 0; font-size: 8pt; }}
    .print-actions {{ display: none; }}
}}
</style>
</head>
<body>
<main class="container">
<article class="invoice-card" aria-label="Order invoice">
<header class="invoice-header"><span class="brand-name">ALL LOCAL</span><h1>Order Invoice</h1><span class="payment-badge {badge_kind}">{payment_label}</span></header>
<section class="section invoice-details" aria-label="Invoice details">{details}</section>
<section class="shop-band" aria-label="Shop"><span class="detail-label">Shop</span><span class="detail-value">{text(invoice.get('shop_name') or 'Shop')}</span></section>
<section class="section" aria-label="Invoice items">
<h2>{selection}</h2><p class="section-note">Amounts in INR (₹). Quantities and price basis are shown for each item.</p>
{amendment_note}
<div class="table-scroll" role="region" aria-label="Invoice items; scroll horizontally on a narrow screen" tabindex="0">
<table class="items-table"><thead><tr><th scope="col">Product</th><th scope="col" class="numeric">Qty</th><th scope="col" class="numeric">Subtotal</th><th scope="col" class="numeric">Discount</th><th scope="col" class="numeric">Payable</th><th scope="col">Status</th></tr></thead><tbody>{rows}</tbody></table>
</div>
<div class="summary"><table class="summary-table" aria-label="Invoice totals"><tbody>{totals}</tbody></table></div>
</section>
<footer class="invoice-footer"><p class="thank-you">Thank you for shopping with <strong>ALL LOCAL</strong>!</p><p>An order bill is not proof of payment. Payment status and amount due are shown above.</p></footer>
</article>
<div class="print-actions"><button id="print-bill" class="print-button" type="button" onclick="window.print()">Print bill</button></div>
</main>
</body>
</html>'''


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
