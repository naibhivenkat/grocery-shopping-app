"""Canonical quantity, client acknowledgment and financial rounding regressions."""
import copy
import unittest
from routes import measurement as units
from routes import billing, vendors, inventory, ai, product_import
from unittest.mock import patch
import db as storage
import test_orders_api as orders_fixture
import test_core_routes as core_fixture
import test_service_catalog_security as ai_fixture
import test_order_refunds as refund_fixture
import test_admin_referrals as admin_fixture
from routes import order_refunds

KG = {'selling_unit': 'kg', 'pricing_quantity': 1000, 'stock_unit': 'g'}


class MeasurementHelpersTests(unittest.TestCase):
    def test_conversion_labels_and_round_once(self):
        self.assertEqual(units.line_paise(1235, 250, KG), 309)
        self.assertEqual(units.line_paise(1, 500, KG), 1)
        self.assertEqual(units.quantity_label(250, KG), '0.25 kg')
        self.assertEqual(units.quantity_label(750, {'selling_unit': 'l', 'pricing_quantity': 1000, 'stock_unit': 'ml'}), '0.75 l')
        self.assertEqual(units.line_paise(1200, 3, {}), 3600)
        for item in ({**KG, 'stock_unit': 'ml'}, {**KG, 'pricing_quantity': True}, {'selling_unit': 'kg'}):
            with self.assertRaises(ValueError):
                units.metadata(item)
        with self.assertRaises(ValueError):
            units.line_paise(1, 1, KG)

    def test_import_optional_units_and_legacy(self):
        result = product_import.parse_products(b'name,price,stock_quantity,selling_unit,pricing_quantity,stock_unit\nRice,60,10000,kg,1000,g\n', 'units.csv')
        self.assertEqual(result[0]['pricing_quantity'], 1000)
        self.assertEqual(result[0]['stock_quantity'], 10000)
        legacy = product_import.parse_products(b'name,price,stock_quantity\nRice,60,20\n', 'old.csv')
        self.assertNotIn('selling_unit', legacy[0])
        with self.assertRaises(ValueError):
            product_import.parse_products(b'name,price,stock_quantity,selling_unit\nRice,60,1000,kg\n', 'bad.csv')


class MeasurementOrderTests(unittest.TestCase):
    setUp = orders_fixture.OrdersTests.setUp
    post = orders_fixture.OrdersTests.post
    order = orders_fixture.OrdersTests.order
    values = orders_fixture.OrdersTests.values
    stock = orders_fixture.OrdersTests.stock
    cancel = orders_fixture.OrdersTests.cancel
    ledger = orders_fixture.OrdersTests.ledger

    def measured(self):
        self.store.data[(storage.SHOP_ITEMS, 'rice')].update({**KG, 'stock_quantity': 20000})

    def test_unit_ack_pricing_snapshot_cancel_and_retry(self):
        self.measured()
        before = copy.deepcopy(self.store.data)
        self.assertEqual(self.order(quantity=250).status_code, 422)
        self.assertEqual(self.order(quantity=250, quantity_unit='kg').status_code, 422)
        self.assertEqual(self.store.data, before)
        response = self.order(quantity=250, quantity_unit='g', idempotency_key='measured-key')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json['total_price'], 3.09)
        entry = self.values(storage.CUSTOMER_ORDERS)[0]
        self.assertEqual(entry['item_selling_price'], 12.35)
        self.assertEqual(entry['pricing_quantity'], 1000)
        self.assertEqual(entry['quantity'], 250)
        self.assertEqual(entry['stock_unit'], 'g')
        self.assertEqual(self.order(quantity=250, quantity_unit='g', idempotency_key='measured-key').json, response.json)
        self.assertEqual(self.order(quantity=250, idempotency_key='measured-key').status_code, 422)
        self.assertEqual(self.stock(), 19750)
        self.assertEqual(self.cancel(response).status_code, 200)
        self.assertEqual(self.stock(), 20000)

    def test_khata_records_purchased_item_quantity_and_date(self):
        self.measured()
        self.ledger()
        response = self.order(method='khata', quantity=250, quantity_unit='g')
        self.assertEqual(response.status_code, 201)
        entry = self.values(storage.KHATA_TRANSACTIONS)[0]
        self.assertEqual(entry['item_name'], 'Rice')
        self.assertEqual(entry['quantity_label'], '0.25 kg')
        self.assertEqual(entry['description'], 'Rice · 0.25 kg')
        self.assertEqual(entry['batch_id'], response.json['batch_id'])
        self.assertTrue(entry['created_at'])

    def test_large_canonical_and_stock_dimension_restore_guard(self):
        self.measured()
        response = self.order(quantity=12000, quantity_unit='g')
        self.assertEqual(response.status_code, 201)
        self.store.data[(storage.SHOP_ITEMS, 'rice')].update({'selling_unit': 'l', 'stock_unit': 'ml'})
        before = copy.deepcopy(self.store.data)
        self.assertEqual(self.cancel(response).status_code, 409)
        self.assertEqual(self.store.data, before)

    def test_invoice_uses_snapshot_quantity_not_current_catalog(self):
        self.measured()
        response = self.order(quantity=250, quantity_unit='g')
        with self.app.test_request_context():
            from flask import g
            g.user_id = 'customer'
            with patch.object(billing, 'doc', self.store.doc), patch.object(billing, 'col', self.store.col):
                invoice = billing.invoice_data(response.json['order_id'])
        self.assertEqual(invoice['lines'][0]['quantity_label'], '0.25 kg')
        self.assertEqual(invoice['total'], 3.09)
        self.assertEqual(invoice['lines'][0]['price_basis'], 'INR 12.35 / 1 kg')
        self.assertTrue(billing.render_invoice(invoice).startswith(b'%PDF'))


class MeasurementStockTests(unittest.TestCase):
    setUp = core_fixture.CoreRoutesTests.setUp
    call = core_fixture.CoreRoutesTests.call

    def test_vendor_units_stock_ack_and_ownership(self):
        response = self.call('/vendors/items', {'name': 'Measured', 'price': 60, 'stock_quantity': 10000, **KG})
        self.assertEqual(response.status_code, 201)
        identifier = response.json['uid']
        path = '/vendors/items/' + identifier
        self.assertEqual(self.call(path, {'stock_quantity': 20000}, method='PUT').status_code, 422)
        self.assertEqual(self.call(path, {'stock_quantity': 20000, 'stock_unit': 'g'}, method='PUT').status_code, 200)
        self.assertEqual(self.call(path, {'selling_unit': 'l', 'stock_unit': 'ml', 'pricing_quantity': 1000}, method='PUT').status_code, 409)
        self.assertEqual(self.call('/vendors/items/rice', KG, method='PUT').status_code, 409)
        self.assertEqual(self.call(path, {'stock_quantity': 3, 'stock_unit': 'g'}, method='PUT', user='other_vendor').status_code, 403)
        stock_path = '/inventory/' + identifier + '/stock'
        self.assertEqual(self.call(stock_path, {'quantity': 1000}, method='PUT').status_code, 422)
        self.assertEqual(self.call(stock_path, {'quantity': 1000, 'stock_unit': 'g'}, method='PUT').status_code, 200)
        self.assertEqual(self.call('/inventory/bulk-update', {'items': [{'item_id': identifier, 'quantity': 2000}]}).status_code, 422)
        self.assertEqual(self.call('/inventory/bulk-update', {'items': [{'item_id': identifier, 'quantity': 2000, 'stock_unit': 'g'}]}).status_code, 200)


class MeasurementAITests(unittest.TestCase):
    setUp = ai_fixture.ServiceCatalogSecurityTests.setUp
    put = ai_fixture.ServiceCatalogSecurityTests.put
    data = ai_fixture.ServiceCatalogSecurityTests.data
    call = ai_fixture.ServiceCatalogSecurityTests.call

    def test_budget_requires_full_priced_quantity_and_emits_units(self):
        self.data('shop_items', 'rice').update({**KG, 'stock_quantity': 500})
        result = self.call('/ai/budget-plan', {'budget': 5}, user='customer')
        self.assertEqual(result.status_code, 200)
        self.assertNotIn('rice', [item['item_id'] for item in result.json['suggested_items']])
        self.data('shop_items', 'rice')['stock_quantity'] = 2000
        result = self.call('/ai/budget-plan', {'budget': 5}, user='customer')
        rice = next(item for item in result.json['suggested_items'] if item['item_id'] == 'rice')
        self.assertEqual(rice['quantity'], 1000)
        self.assertEqual(rice['quantity_unit'], 'g')
        self.assertEqual(rice['price'], 0.1)


class MeasurementRefundTests(unittest.TestCase):
    setUp = refund_fixture.OrderRefundTests.setUp
    entity = refund_fixture.OrderRefundTests.entity

    def test_refund_cannot_restore_different_base_unit(self):
        self.store.data[('customer_orders', 'a')].update(KG)
        before = copy.deepcopy(self.store.data)
        with self.assertRaisesRegex(ValueError, 'measurement changed'):
            order_refunds.refund_order('a', 'vendor')
        self.assertEqual(self.store.data, before)
        self.provider.payment.refund.assert_not_called()


class MeasurementAdminTests(unittest.TestCase):
    setUp = admin_fixture.AdminReferralTests.setUp
    call = admin_fixture.AdminReferralTests.call

    def test_admin_partial_stock_ack_preserves_metadata(self):
        self.store.data[(storage.SHOP_ITEMS, 'rice')].update(KG)
        before = copy.deepcopy(self.store.data)
        self.assertEqual(self.call('/admin/products/rice', {'stock_quantity': 20000}, 'PUT').status_code, 422)
        self.assertEqual(self.store.data, before)
        self.assertEqual(self.call('/admin/products/rice', {'stock_quantity': 20000, 'stock_unit': 'g'}, 'PUT').status_code, 200)
        item = self.store.data[(storage.SHOP_ITEMS, 'rice')]
        self.assertEqual(item['pricing_quantity'], 1000)
        self.assertEqual(item['selling_unit'], 'kg')
        self.assertEqual(item['stock_quantity'], 20000)
        self.assertEqual(self.call('/admin/products/rice', {'selling_unit': 'l', 'stock_unit': 'ml'}, 'PUT').status_code, 409)
        self.assertEqual(self.call('/admin/products/rice', {'stock_quantity': 5, 'stock_unit': 'g'}, 'PUT', 'customer').status_code, 403)
