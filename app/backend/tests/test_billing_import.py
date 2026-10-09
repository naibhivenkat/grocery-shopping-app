"""HTTP, PDF and real XLSX parsing with mocked atomic Firestore writes."""
import copy
import io
import unittest
from unittest.mock import patch

from flask import Flask
from openpyxl import Workbook
import auth_utils
import db as storage
from routes import billing, product_import, vendors
from test_orders_api import OrderStore


class BillingImportTests(unittest.TestCase):
    def setUp(self):
        self.store = OrderStore()
        self.store.data = {
            (storage.USERS, 'customer'): {'role': 'customer'},
            (storage.USERS, 'vendor'): {'role': 'vendor', 'shop_name': 'Test Shop'},
            (storage.USERS, 'other'): {'role': 'vendor'},
        }
        for identifier, name, price in (('rice', 'Rice', 120), ('milk', 'Milk', 40)):
            self.store.data[(storage.CUSTOMER_ORDERS, identifier)] = {
                'vendor_id': 'vendor', 'customer_id': 'customer', 'vendor_name': 'Test Shop',
                'customer_name': 'Test Customer', 'batch_id': 'test-batch', 'item_name': name,
                'quantity': 2, 'item_unit_price': price / 2, 'total_price': price,
                'due_amount': price, 'status': 'pending', 'payment_status': 'pending',
                'payment_method': 'cash', 'created_at': '2026-10-09T10:00:00Z',
            }
        patches = [patch.object(storage, 'doc', self.store.doc),
                   patch.object(auth_utils, 'decode_token', lambda token: {'sub': token, 'role': 'customer'})]
        for module in (billing, product_import, vendors):
            patches.extend([patch.object(module, 'doc', self.store.doc),
                            patch.object(module, 'col', self.store.col),
                            patch.object(module, 'db', lambda: self.store),
                            patch.object(module.firestore, 'transactional', self.store.transactional)])
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        app = Flask(__name__)
        app.config['TESTING'] = True
        app.register_blueprint(billing.billing_bp)
        app.register_blueprint(product_import.product_import_bp)
        self.client = app.test_client()

    def headers(self, user='vendor'):
        return {'Authorization': 'Bearer ' + user}

    def discount(self, amount, user='vendor'):
        return self.client.put('/vendors/orders/rice/discount', json={'amount': amount}, headers=self.headers(user))

    def upload(self, contents=b'name,price,stock_quantity\nRice,60,20\n', filename='products.csv', preview=False, user='vendor'):
        return self.client.post('/vendors/items/import' + ('?preview=true' if preview else ''),
                                data={'file': (io.BytesIO(contents), filename)}, headers=self.headers(user))

    def test_both_parties_get_identical_full_batch_and_pdf(self):
        customer = self.client.get('/orders/rice/invoice', headers=self.headers('customer'))
        vendor = self.client.get('/orders/milk/invoice', headers=self.headers())
        self.assertEqual(customer.status_code, 200)
        self.assertEqual(customer.json, vendor.json)
        self.assertEqual(customer.json['total'], 160)
        self.assertEqual(len(customer.json['lines']), 2)
        pdf = self.client.get('/orders/rice/invoice.pdf', headers=self.headers('customer'))
        self.assertEqual(pdf.status_code, 200)
        self.assertTrue(pdf.data.startswith(b'%PDF'))
        self.assertEqual(pdf.mimetype, 'application/pdf')
        self.assertEqual(self.client.get('/orders/rice/invoice', headers=self.headers('other')).status_code, 403)
        self.assertEqual(self.client.get('/orders/rice/invoice').status_code, 401)

    def test_discount_is_replacement_atomic_and_updates_payable(self):
        self.assertEqual(self.discount(10).json['total'], 150)
        self.assertEqual(self.discount(5).json['total'], 155)
        self.assertEqual(self.discount(0).json['total'], 160)
        self.assertEqual(self.discount(120).status_code, 422)
        self.assertEqual(self.discount('NaN').status_code, 422)
        self.assertEqual(self.discount(10, 'other').status_code, 403)
        self.assertEqual(self.discount(10, 'customer').status_code, 403)
        before = copy.deepcopy(self.store.data)
        self.store.fail_commit = True
        with self.assertRaises(RuntimeError):
            self.discount(10)
        self.assertEqual(self.store.data, before)

    def test_paid_online_khata_cancelled_discounts_blocked(self):
        order = self.store.data[(storage.CUSTOMER_ORDERS, 'rice')]
        for changes in ({'payment_method': 'razorpay'}, {'payment_method': 'khata'},
                        {'payment_method': 'cash', 'payment_status': 'paid'},
                        {'payment_status': 'pending', 'status': 'cancelled'}):
            order.update(changes)
            self.assertEqual(self.discount(5).status_code, 409)

    def test_preview_no_write_and_repeat_file_does_not_duplicate(self):
        before = copy.deepcopy(self.store.data)
        preview = self.upload(preview=True)
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.json['products'][0]['price'], 60)
        self.assertEqual(self.store.data, before)
        first, second = self.upload(), self.upload()
        self.assertEqual(first.status_code, 201)
        self.assertEqual(first.json, second.json)
        products = [value for (name, _), value in self.store.data.items() if name == storage.SHOP_ITEMS]
        self.assertEqual(len(products), 1)
        self.assertEqual(products[0]['vendor_id'], 'vendor')
        self.assertEqual(self.upload(user='customer').status_code, 403)

    def test_invalid_row_or_commit_failure_never_partially_imports(self):
        before = copy.deepcopy(self.store.data)
        for contents in (b'name,price,stock_quantity\nRice,60,20\nMilk,NaN,10\n',
                         b'name,price,stock_quantity\nRice,60,20\nRice,60,20\n',
                         b'name,price,stock_quantity\nRice,60,-1\n',
                         b'name,price,stock_quantity,vendor_id\nRice,60,1,other\n'):
            self.assertEqual(self.upload(contents).status_code, 422)
            self.assertEqual(self.store.data, before)
        self.store.fail_commit = True
        with self.assertRaises(RuntimeError):
            self.upload()
        self.assertEqual(self.store.data, before)

    def test_real_excel_and_formula_size_row_limits(self):
        workbook = Workbook()
        workbook.active.append(['name', 'price', 'stock_quantity'])
        workbook.active.append(['Rice', 60, 20])
        stream = io.BytesIO()
        workbook.save(stream)
        self.assertEqual(self.upload(stream.getvalue(), 'products.xlsx', True).status_code, 200)
        workbook.active['B2'] = '=1+1'
        stream = io.BytesIO()
        workbook.save(stream)
        self.assertEqual(self.upload(stream.getvalue(), 'products.xlsx').status_code, 422)
        self.assertEqual(self.upload(b'broken', 'products.xlsx').status_code, 422)
        self.assertEqual(self.upload(b'x' * (product_import.MAX_BYTES + 1)).status_code, 422)
        rows = b'name,price,stock_quantity\n' + b'Rice,60,20\n' * 201
        self.assertEqual(self.upload(rows).status_code, 422)


if __name__ == '__main__':
    unittest.main()
