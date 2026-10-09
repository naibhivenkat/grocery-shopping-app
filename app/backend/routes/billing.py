"""Party-scoped order bills and vendor discounts on uncollected cash orders."""
from io import BytesIO
from xml.sax.saxutils import escape

from firebase_admin import firestore
from flask import Blueprint, g, jsonify, request, send_file
from google.cloud.firestore_v1.base_query import FieldFilter

from auth_utils import require_auth, require_role
from db import CUSTOMER_ORDERS, col, db, doc, now_iso
from routes.khata import KhataError, _khata_error, _identifier, _money_paise, _payload

billing_bp = Blueprint("billing", __name__)
billing_bp.register_error_handler(KhataError, _khata_error)


def invoice_data(order_id):
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
    lines = []
    for entry in snapshots:
        value = entry.to_dict() or {}
        if (value.get("customer_id"), value.get("vendor_id")) != (order.get("customer_id"), order.get("vendor_id")):
            raise KhataError("Bill contains inconsistent parties", 409)
        total = _money_paise(value.get("total_price", 0), allow_zero=True)
        discount = _money_paise(value.get("discount_amount", 0), allow_zero=True)
        subtotal = _money_paise(value.get("subtotal", (total + discount) / 100), allow_zero=True)
        due = _money_paise(value.get("due_amount", 0 if value.get("payment_status") == "paid" else total / 100), allow_zero=True)
        lines.append({"order_id": entry.id, "name": value.get("item_name") or "Product",
                      "quantity": value.get("quantity", 1), "unit_price": value.get("item_unit_price", 0),
                      "subtotal": subtotal / 100, "discount": discount / 100, "total": total / 100,
                      "due": due / 100, "status": value.get("status"),
                      "payment_status": value.get("payment_status", "pending")})
    lines.sort(key=lambda value: value["order_id"])
    return {"invoice_number": f"LS-{batch_id or order_id}", "created_at": order.get("created_at"),
            "customer_name": order.get("customer_name") or "Customer", "shop_name": order.get("vendor_name") or "Shop",
            "payment_method": order.get("payment_method"), "lines": lines,
            **{field: sum(round(line[key] * 100) for line in lines) / 100
               for field, key in (("subtotal", "subtotal"), ("discount", "discount"), ("total", "total"), ("due", "due"))}}


@billing_bp.get("/orders/<order_id>/invoice")
@require_auth
def get_invoice(order_id):
    return jsonify(invoice_data(order_id))


def render_invoice(invoice):
    # Pango shapes Indian scripts; ReportLab's core fonts cover the ASCII path.
    names = [invoice.get('shop_name', ''), invoice.get('customer_name', '')] + [line['name'] for line in invoice['lines']]
    if any(not str(name).isascii() for name in names):
        from weasyprint import HTML
        rows = ''.join('<tr>' + ''.join(f'<td>{escape(str(cell))}</td>' for cell in (
            line['name'], line['quantity'], f"{line['subtotal']:.2f}", f"{line['discount']:.2f}",
            f"{line['total']:.2f}", f"{line['status']} / {line['payment_status']}")) + '</tr>' for line in invoice['lines'])
        details = ''.join(f'<p>{label}: {escape(str(invoice.get(key) or "-"))}</p>' for label, key in (
            ('Bill', 'invoice_number'), ('Date', 'created_at'), ('Shop', 'shop_name'), ('Customer', 'customer_name'), ('Payment', 'payment_method')))
        totals = ''.join(f'<p>{field.title()} (INR): {invoice[field]:.2f}</p>' for field in ('subtotal', 'discount', 'total', 'due'))
        return HTML(string=f'''<html><head><meta charset="utf-8"><style>
            @page {{ size:A4; margin:18mm; }}
            body {{ font-family:"Noto Sans", "Noto Sans Kannada", "Noto Sans Devanagari", sans-serif; font-size:10pt; }}
            h1 {{ text-align:center; font-size:18pt; }}
            table {{ border-collapse:collapse; width:100%; margin:16pt 0; }}
            th,td {{ border:1px solid #999; padding:5pt; overflow-wrap:anywhere; }}
            th {{ background:#e8f5e9; }} thead {{ display:table-header-group; }}
            </style></head><body><h1>LocalShop Order Bill</h1>{details}
            <table><thead><tr><th>Product</th><th>Qty</th><th>Subtotal</th><th>Discount</th><th>Payable</th><th>Status</th></tr></thead><tbody>{rows}</tbody></table>
            {totals}<p>An order bill is not proof of payment. Payment status and amount due are shown above.</p></body></html>''').write_pdf()
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    stream = BytesIO()
    styles = getSampleStyleSheet()
    para = lambda text: Paragraph(escape(str(text)), styles["BodyText"])
    story = [Paragraph("LocalShop Order Bill", styles["Title"]), Spacer(1, 12)]
    for label, key in (("Bill", "invoice_number"), ("Date", "created_at"), ("Shop", "shop_name"), ("Customer", "customer_name"), ("Payment method", "payment_method")):
        story.append(para(f"{label}: {invoice.get(key) or '-'}"))
    story.append(Spacer(1, 18))
    rows = [["Product", "Qty", "Subtotal", "Discount", "Payable", "Status"]]
    for line in invoice["lines"]:
        rows.append([para(line["name"]), str(line["quantity"]), f"{line['subtotal']:.2f}",
                     f"{line['discount']:.2f}", f"{line['total']:.2f}", para(f"{line['status']} / {line['payment_status']}")])
    table = Table(rows, colWidths=[145, 35, 65, 65, 65, 110], repeatRows=1)
    table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8f5e9")),
                              ("GRID", (0, 0), (-1, -1), .4, colors.grey),
                              ("VALIGN", (0, 0), (-1, -1), "TOP"), ("FONTSIZE", (0, 0), (-1, -1), 9)]))
    story.extend([table, Spacer(1, 18)])
    for field in ("subtotal", "discount", "total", "due"):
        story.append(para(f"{field.title()} (INR): {invoice[field]:.2f}"))
    story.append(Spacer(1, 12))
    story.append(para("An order bill is not proof of payment. Payment status and amount due are shown above."))
    SimpleDocTemplate(stream, pagesize=A4, leftMargin=35, rightMargin=35).build(story)
    return stream.getvalue()


@billing_bp.get("/orders/<order_id>/invoice.pdf")
@require_auth
def get_invoice_pdf(order_id):
    invoice = invoice_data(order_id)
    return send_file(BytesIO(render_invoice(invoice)), mimetype="application/pdf", as_attachment=True,
                     download_name=f"{invoice['invoice_number']}.pdf", max_age=0)


@billing_bp.put("/vendors/orders/<order_id>/discount")
@require_role("vendor")
def discount_order(order_id):
    payload = _payload()
    amount = _money_paise(payload.get("amount"), allow_zero=True)
    ref = doc(CUSTOMER_ORDERS, _identifier(order_id, "order_id"))

    @firestore.transactional
    def update(tx):
        snap = ref.get(transaction=tx)
        if not snap.exists:
            raise KhataError("Order not found", 404)
        order = snap.to_dict() or {}
        if order.get("vendor_id") != g.user_id:
            raise KhataError("Not your order", 403)
        if order.get("payment_method") != "cash" or order.get("payment_status") != "pending" or order.get("status") not in {"pending", "confirmed", "packed"}:
            raise KhataError("Discounts can be changed only on uncollected cash orders", 409)
        subtotal = _money_paise(order.get("subtotal", order["total_price"]), allow_zero=True)
        if amount >= subtotal:
            raise KhataError("Discount must be less than the subtotal")
        total = subtotal - amount
        tx.update(ref, {"subtotal": subtotal / 100, "discount_amount": amount / 100,
                        "total_price": total / 100, "total_paise": total,
                        "due_amount": total / 100, "updated_at": now_iso()})
    update(db().transaction())
    return jsonify(invoice_data(order_id))
