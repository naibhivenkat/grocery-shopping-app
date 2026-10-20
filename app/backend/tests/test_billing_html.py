"""Restored invoice presentation/security proof; no live data or provider calls."""
import copy
from html.parser import HTMLParser
import unittest
from routes import billing
import db as storage
import test_billing_import as fixture


class Document(HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.tags, self.text = [], []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def handle_data(self, value):
        self.text.append(value)


def synthetic_invoice(count=3):
    """Sanitized selected-line fixture shared with browser/print QA."""
    variants = (
        ('ಅಕ್ಕಿ / Rice (sample)', 'INR 60.00 / 1 kg', '1500 g', 90, 9),
        ('Milk & curd (sample)', 'INR 30.00 / 500 ml', '2 L', 120, 12),
        ('Soap pack (sample)', 'INR 25.00 / 1 pack', '2 pack', 50, 5),
    )
    lines = []
    for number in range(count):
        name, basis, quantity, subtotal, discount = variants[number % len(variants)]
        lines.append({'order_id':f'demo_line_{number:03}', 'name':name, 'price_basis':basis,
            'quantity_label':quantity, 'subtotal':subtotal, 'discount':discount, 'total':subtotal-discount,
            'due':subtotal-discount, 'status':'pending','payment_status':'pending','payment_exempt':False})
    return {'invoice_number':'LS-DEMO-20261020-SELECTED', 'created_at':'2026-10-09T10:00:00Z',
            'customer_name':'Demo customer (synthetic)', 'shop_name':'Demo Market & Supplies',
            'payment_method':'razorpay', 'selection':True, 'amendment_pending':False, 'lines':lines,
            **{field:sum(line[field] for line in lines) for field in ('subtotal','discount','total','due')}}


class BillingHtmlTests(unittest.TestCase):
    setUp = fixture.BillingImportTests.setUp
    headers = fixture.BillingImportTests.headers
    discount = fixture.BillingImportTests.discount

    def html(self, order='rice', query='', user='vendor'):
        return self.client.get('/orders/'+order+'/invoice.html'+query, headers=self.headers(user))

    def test_green_reference_layout_and_embedded_policy_preserve_endpoint_security(self):
        response = self.html()
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.mimetype,'text/html')
        self.assertEqual(response.headers['Cache-Control'],'no-store')
        self.assertEqual(response.headers['X-Content-Type-Options'],'nosniff')
        document = Document(response.get_data(as_text=True))
        policy = next(attrs['content'] for tag,attrs in document.tags if tag=='meta' and attrs.get('http-equiv')=='Content-Security-Policy')
        self.assertEqual(policy,response.headers['Content-Security-Policy'])
        button = next(attrs for tag,attrs in document.tags if tag=='button')
        self.assertEqual((button['id'],button['onclick']),('print-bill','window.print()'))
        self.assertIn('ALL LOCAL',' '.join(document.text))
        self.assertIn('linear-gradient(135deg, #4caf50, #2e7d32)',response.get_data(as_text=True))
        self.assertNotIn('script',[tag for tag,_ in document.tags])
        self.assertFalse(any('src' in attrs or 'href' in attrs for _,attrs in document.tags))
        self.assertEqual(self.html(user='other').status_code,403)
        self.assertEqual(self.client.get('/orders/rice/invoice.html').status_code,401)

    def test_selected_allocations_actual_date_and_dues_are_not_recomputed_or_taxed(self):
        self.assertEqual(self.discount(16).status_code,200)
        response = self.html(query='?line_id=milk')
        text = ' '.join(Document(response.get_data(as_text=True)).text)
        self.assertIn('Selected items only',text)
        self.assertIn('Milk',text)
        self.assertNotIn('Rice',text)
        self.assertIn('2026-10-09T10:00:00Z',text)
        self.assertIn('₹40.00',text)
        self.assertIn('₹4.00',text)
        self.assertIn('₹36.00',text)
        self.assertNotIn('GST',text)
        self.assertNotIn('Taxable',text)
        self.assertEqual(response.get_data(),self.html(order='milk',query='?line_id=milk',user='customer').get_data())

    def test_online_method_does_not_claim_paid_and_mixed_lines_remain_explicit(self):
        for (collection,_),value in self.store.data.items():
            if collection==storage.CUSTOMER_ORDERS:value['payment_method']='razorpay'
        source=self.html().get_data(as_text=True)
        self.assertIn('Payment pending',source)
        self.assertNotIn('>Paid<',source)
        order=self.store.data[(storage.CUSTOMER_ORDERS,'rice')]
        order.update(payment_status='paid',due_amount=0,partial_amount_paid=120)
        source=self.html().get_data(as_text=True)
        self.assertIn('Mixed payment status',source)
        self.assertIn('Payment: Paid',source)
        self.assertIn('Payment: Pending',source)
        self.assertIn('₹40.00',source)

    def test_settled_and_payment_exempt_states_never_invent_collections(self):
        orders=[value for (name,_),value in self.store.data.items() if name==storage.CUSTOMER_ORDERS]
        for row in orders:row.update(payment_status='paid',due_amount=0)
        self.assertIn('>Paid</span>',self.html().get_data(as_text=True))
        for row in orders:row.update(payment_exempt=True,subtotal=row['total_price'],discount_amount=row['total_price'],total_price=0)
        html=self.html().get_data(as_text=True)
        self.assertIn('No payment required',html)
        self.assertNotIn('>Paid</span>',html)
        self.assertIn('An order bill is not proof of payment.',html)

    def test_all_stored_content_is_text_only_even_when_headers_are_lost(self):
        row=self.store.data[(storage.CUSTOMER_ORDERS,'rice')]
        attack='</span><img src="https://invalid.example/x" onerror="alert(1)"><script>bad()</script><svg/onload=bad()>'
        row.update(item_name=attack,customer_name=attack,vendor_name=attack,created_at=attack,
                   payment_method=attack,status=attack,payment_status=attack,batch_id=attack)
        source=self.html().get_data(as_text=True)
        document=Document(source)
        self.assertFalse({'img','script','svg','iframe','object','link','form','base'} & {tag for tag,_ in document.tags})
        handlers=[(tag,key,value) for tag,attrs in document.tags for key,value in attrs.items() if key.startswith('on')]
        self.assertEqual(handlers,[('button','onclick','window.print()')])
        self.assertIn('&lt;img',source)
        self.assertIn("default-src 'none'",source)

    def test_multi_page_a4_render_uses_local_assets_and_keeps_input_amounts(self):
        from weasyprint import HTML
        invoice=synthetic_invoice(45)
        before=copy.deepcopy(invoice)
        source=billing.invoice_html(invoice)
        self.assertEqual(invoice,before)
        def forbid_remote(url, *args, **kwargs):
            raise AssertionError('Invoice must not fetch external resources')
        document=HTML(string=source,url_fetcher=forbid_remote).render()
        self.assertGreaterEqual(len(document.pages),2)
        self.assertLessEqual(len(document.pages),5)
        for page in document.pages:
            self.assertAlmostEqual(page.width,210/25.4*96,delta=1)
            self.assertAlmostEqual(page.height,297/25.4*96,delta=1)
        self.assertIn('display: table-header-group',source)
        self.assertIn('An order bill is not proof of payment.',source)


if __name__=='__main__':unittest.main()
