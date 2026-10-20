"""Strict atomic amendment state/stock/money proof using provider doubles only."""
import copy
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch
import unittest

import db as storage
import razorpay_config
from routes import order_amendments as amendments, razorpay_api, vendors, billing, order_refunds, admin
from test_khata import Ref
import test_orders_api as fixture
from test_core_routes import CoreTransaction


class AmendmentTests(unittest.TestCase):
    post = fixture.OrdersTests.post
    order = fixture.OrdersTests.order
    batch = fixture.OrdersTests.batch
    values = fixture.OrdersTests.values
    stock = fixture.OrdersTests.stock
    ledger = fixture.OrdersTests.ledger

    def setUp(self):
        fixture.OrdersTests.setUp(self)
        current = patch.object(self.store, 'transaction', lambda: CoreTransaction(self.store))
        current.start()
        self.addCleanup(current.stop)
        current = patch.object(admin, 'log_admin_action')
        current.start()
        self.addCleanup(current.stop)
        for module in (amendments, razorpay_api, vendors, billing, admin):
            self.app.register_blueprint(getattr(module, {'order_amendments': 'order_amendments_bp', 'razorpay_api': 'razorpay_api_bp', 'vendors': 'vendors_bp', 'billing': 'billing_bp', 'admin': 'admin_bp'}[module.__name__.split('.')[-1]]))
            for name, value in (('doc', self.store.doc), ('col', self.store.col), ('db', lambda: self.store)):
                current = patch.object(module, name, value)
                current.start()
                self.addCleanup(current.stop)
        for name, value in (('doc', self.store.doc), ('db', lambda: self.store)):
            current = patch.object(order_refunds, name, value)
            current.start()
            self.addCleanup(current.stop)
        current = patch.object(Ref, 'update', lambda ref, data: ref.store.data[ref.key].update(copy.deepcopy(data)), create=True)
        current.start()
        self.addCleanup(current.stop)
        self.provider = MagicMock()
        self.provider.order.create.side_effect = lambda body: {'id': 'order_extra_' + str(body['amount'])}
        self.captures = {}
        self.provider.payment.fetch.side_effect = lambda identifier, **kwargs: copy.deepcopy(self.captures[identifier])
        self.provider.payment.refund.side_effect = lambda identifier, body, **kwargs: {
            'id': 'rfnd_' + kwargs['headers']['X-Refund-Idempotency'][-15:], 'payment_id': identifier,
            'amount': body['amount'], 'currency': 'INR', 'status': 'processed'}
        for current in (patch.object(razorpay_config, 'get_razorpay_client', return_value=self.provider),
                        patch.object(razorpay_api, 'get_razorpay_client', return_value=self.provider),
                        patch.object(razorpay_api, 'get_razorpay_key_id', return_value='test-key')):
            current.start()
            self.addCleanup(current.stop)
        self.next_key = 0

    def place(self, method='cash', quantity=10, paid=False):
        response = self.order(method=method, quantity=quantity)
        self.assertEqual(response.status_code, 201, response.json)
        self.anchor = response.json['order_id']
        self.batch_id = response.json['batch_id']
        if paid:
            row = self.store.data[(storage.CUSTOMER_ORDERS, self.anchor)]
            row.update({'payment_status': 'paid', 'partial_amount_paid': row['total_price'], 'due_amount': 0})
            if method == 'razorpay':
                row.update({'payment_intent_id': 'original_intent', 'razorpay_payment_id': 'pay_original'})
                self.store.data[('payment_orders', 'original_intent')] = {
                    'purpose': 'order', 'user_id': 'customer', 'status': 'paid', 'currency': 'INR',
                    'target_ids': [self.anchor], 'amount_paise': row['total_paise'], 'payment_id': 'pay_original',
                    'razorpay_order_id': 'order_original'}
                self.captures['pay_original'] = {'id': 'pay_original', 'order_id': 'order_original', 'amount': row['total_paise'],
                                                 'currency': 'INR', 'status': 'captured', 'captured': True}
        return response

    def desired(self, quantity=7, restock=False, item='rice'):
        return {'item_id': item, 'quantity': quantity, 'quantity_unit': 'piece', 'restock_removed': restock}

    def propose(self, lines=None, revision=0, user='vendor', key=None):
        self.next_key += 1
        return self.post(f'/vendors/orders/{self.anchor}/amendments',
                         {'revision': revision, 'reason': 'Only these quantities are available',
                          'lines': [self.desired()] if lines is None else lines}, user=user,
                         key=key or 'proposal-key-' + str(self.next_key))

    def decide(self, proposal, decision='accepted', user='customer', revision=None):
        data = proposal.json if hasattr(proposal, 'json') else proposal
        return self.post('/order-amendments/' + data['uid'] + '/decision',
                         {'decision': decision, 'revision': data['revision'] if revision is None else revision}, user=user)

    def row(self):
        return self.store.data[(storage.CUSTOMER_ORDERS, self.anchor)]

    def test_unpaid_ten_to_seven_changes_only_after_accept_without_phantom_stock(self):
        self.place()
        proposal = self.propose()
        self.assertEqual(proposal.status_code, 201, proposal.json)
        self.assertEqual(self.row()['quantity'], 10)
        self.assertEqual(self.stock(), 0)
        self.assertTrue(self.row()['amendment_pending'])
        result = self.decide(proposal)
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(result.json['status'], 'applied')
        self.assertEqual(self.row()['quantity'], 7)
        self.assertEqual(self.row()['total_price'], 86.45)
        self.assertEqual(self.row()['due_amount'], 86.45)
        self.assertEqual(self.stock(), 0)
        self.assertEqual(self.row()['pricing_revision'], 1)
        self.assertFalse(self.row()['amendment_pending'])
        self.assertEqual(self.decide(proposal).json, result.json)

    def test_paid_decrease_durable_original_refund_and_exact_retry(self):
        self.place('razorpay', paid=True)
        proposal = self.propose()
        result = self.decide(proposal)
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(result.json['refund_due'], 37.05)
        self.assertEqual(result.json['refund_status'], 'completed')
        self.assertEqual(self.row()['partial_amount_paid'], 86.45)
        self.assertEqual(self.stock(), 0)
        self.assertEqual(self.store.data[(amendments.QUOTAS, 'pay_original')]['reserved_paise'], 3705)
        result = self.post('/order-amendments/' + proposal.json['uid'] + '/refund', user='vendor')
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(result.json['status'], 'completed')
        self.assertEqual(self.provider.payment.refund.call_args.args[1]['amount'], 3705)
        self.assertEqual(self.post('/order-amendments/' + proposal.json['uid'] + '/refund', user='vendor').status_code, 200)
        self.provider.payment.refund.assert_called_once()

    def test_cash_overpayment_requires_actual_manual_repayment(self):
        self.place('cash', paid=True)
        proposal = self.propose()
        result = self.decide(proposal)
        self.assertEqual(result.json['cash_refund_amount'], 37.05)
        self.assertEqual(result.json['cash_refund_status'], 'pending')
        self.assertEqual(result.json['original_lines'][0]['partial_amount_paid'], 123.5)
        path = '/order-amendments/' + proposal.json['uid'] + '/cash-refund'
        self.assertEqual(self.post(path, {'reference': 'cash repaid in person'}, user='other_vendor').status_code, 403)
        self.assertEqual(self.post(path, {'reference': ''}, user='vendor').status_code, 422)
        result = self.post(path, {'reference': 'cash repaid in person'}, user='vendor')
        self.assertEqual(result.json['cash_refund_status'], 'completed')
        self.assertEqual(self.post(path, {'reference': 'retry'}, user='vendor').json, result.json)
        self.provider.payment.refund.assert_not_called()

    def test_authorization_stale_revision_and_idempotency(self):
        self.place()
        self.assertEqual(self.propose(user='other_vendor').status_code, 403)
        self.assertEqual(self.propose(user='customer').status_code, 403)
        proposal = self.propose(key='same-proposal')
        self.assertEqual(self.propose(key='same-proposal').json, proposal.json)
        self.assertEqual(self.propose([self.desired(8)], key='same-proposal').status_code, 409)
        self.assertEqual(self.propose().status_code, 409)
        self.assertEqual(self.decide(proposal, user='vendor').status_code, 403)
        self.assertEqual(self.decide(proposal, user='other_customer').status_code, 403)
        self.assertEqual(self.decide(proposal, revision=1).status_code, 409)
        self.assertEqual(self.decide(proposal).status_code, 200)
        self.assertEqual(self.propose(revision=0).status_code, 409)
        self.assertEqual(self.propose([self.desired(6)], revision=1).status_code, 201)

    def test_pending_proposal_blocks_fulfillment_discount_cancel_and_checkout(self):
        self.place('razorpay')
        proposal = self.propose()
        response = self.client.put(f'/vendors/orders/{self.anchor}/status', json={'status': 'confirmed'}, headers={'Authorization': 'Bearer vendor'})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.post(f'/orders/{self.anchor}/cancel').status_code, 409)
        self.assertEqual(self.post('/razorpayApi/orders', {'purpose': 'order', 'reference_id': self.anchor}).status_code, 409)
        self.assertEqual(self.decide(proposal, decision='rejected').status_code, 200)
        self.assertFalse(self.row()['amendment_pending'])

    def test_missing_item_reduction_and_explicit_removed_restock(self):
        self.place()
        del self.store.data[(storage.SHOP_ITEMS, 'rice')]
        self.assertEqual(self.decide(self.propose()).status_code, 200)
        self.assertEqual(self.row()['quantity'], 7)
        self.store.data[(storage.SHOP_ITEMS, 'rice')] = {'vendor_id': 'vendor', 'price': 12.35, 'stock_quantity': 0}
        result = self.decide(self.propose([self.desired(5, restock=True)], revision=1))
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(self.stock(), 2)

    def test_substitution_reserves_new_product_and_tombstones_old(self):
        self.store.data[(storage.USERS, 'vendor')]['phone'] = 'shop-contact'
        self.place()
        result = self.decide(self.propose([self.desired(2, item='milk')]))
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(self.row()['status'], 'removed')
        self.assertEqual(self.stock(), 0)
        self.assertEqual(self.stock('milk'), 3)
        current = self.store.data[('order_batches', self.batch_id)]['response']['order_ids']
        self.assertEqual(len(current), 1)
        self.assertEqual(self.store.data[(storage.CUSTOMER_ORDERS, current[0])]['item_id'], 'milk')
        self.assertEqual(self.store.data[(storage.CUSTOMER_ORDERS, current[0])]['vendor_phone'], 'shop-contact')

    def test_online_increase_reserves_then_applies_only_after_capture(self):
        self.place('razorpay', quantity=2, paid=True)
        proposal = self.propose([self.desired(4)])
        accepted = self.decide(proposal)
        self.assertEqual(accepted.status_code, 200, accepted.json)
        self.assertEqual(accepted.json['status'], 'awaiting_payment')
        self.assertEqual(accepted.json['amount_due'], 24.7)
        self.assertEqual(self.row()['quantity'], 2)
        self.assertEqual(self.stock(), 6)
        checkout = self.post('/razorpayApi/orders', {'purpose': 'order_amendment', 'reference_id': proposal.json['uid'], 'amount': 24.7})
        self.assertEqual(checkout.status_code, 201, checkout.json)
        intent_id = checkout.json['backend_order_id']
        result = razorpay_api.settle_payment_order(intent_id, 'pay_extra')
        self.assertEqual(result['settlement_status'], 'settled', result)
        self.assertEqual(self.row()['quantity'], 4)
        self.assertEqual(self.row()['partial_amount_paid'], 49.4)
        self.assertEqual(self.stock(), 6)
        self.assertEqual(razorpay_api.settle_payment_order(intent_id, 'pay_extra')['status'], 'already_paid')
        proposal_status = self.client.get('/order-amendments/' + proposal.json['uid'], headers={'Authorization': 'Bearer customer'}).json
        self.assertEqual(proposal_status['status'], 'applied')

    def test_online_withdraw_releases_extra_and_late_capture_requires_review(self):
        self.place('razorpay', quantity=2, paid=True)
        proposal = self.propose([self.desired(4)])
        self.decide(proposal)
        checkout = self.post('/razorpayApi/orders', {'purpose': 'order_amendment', 'reference_id': proposal.json['uid']})
        self.assertEqual(checkout.status_code, 201, checkout.json)
        result = self.post('/order-amendments/' + proposal.json['uid'] + '/withdraw', user='vendor')
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(self.stock(), 8)
        self.assertEqual(self.row()['quantity'], 2)
        settled = razorpay_api.settle_payment_order(checkout.json['backend_order_id'], 'pay_late')
        self.assertEqual(settled['settlement_status'], 'requires_review')
        self.assertEqual(self.row()['quantity'], 2)
        self.assertEqual(self.stock(), 8)
        self.assertEqual(self.store.data[('order_batches', self.batch_id)]['payment_review_required'], True)

    def test_expiry_releases_reservation_without_payment_intent(self):
        self.place('razorpay', quantity=2, paid=True)
        proposal = self.propose([self.desired(4)])
        self.decide(proposal)
        self.store.data[(amendments.AMENDMENTS, proposal.json['uid'])]['expires_at'] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        history = self.client.get(f'/orders/{self.anchor}/amendments', headers={'Authorization': 'Bearer customer'})
        self.assertEqual(history.status_code, 200, history.json)
        self.assertEqual(history.json[0]['status'], 'expired')
        self.assertEqual(self.stock(), 8)
        self.assertFalse(self.row()['amendment_pending'])

    def test_khata_delta_and_overpaid_manual_refund(self):
        self.ledger(balance=0)
        self.place('khata')
        self.store.data[(storage.KHATA_LEDGERS, 'legacy')]['balance'] = 10
        result = self.decide(self.propose())
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(self.store.data[(storage.KHATA_LEDGERS, 'legacy')]['balance'], 0)
        self.assertEqual(result.json['cash_refund_amount'], 27.05)
        self.assertEqual(result.json['amount_due'], 0)
        self.assertEqual(self.row()['due_amount'], 0)
        self.assertEqual(self.row()['partial_amount_paid'], 0)
        adjustments = [row for row in self.values(storage.KHATA_TRANSACTIONS) if row.get('amendment_id')]
        self.assertEqual(adjustments[0]['amount'], 10)
        self.assertEqual(adjustments[0]['type'], 'debit')

    def test_rollback_accept_changes_neither_stock_balance_nor_history(self):
        self.place(quantity=2)
        proposal = self.propose([self.desired(4)])
        before = copy.deepcopy(self.store.data)
        self.store.fail_commit = True
        with self.assertRaisesRegex(RuntimeError, 'simulated write failure'):
            self.decide(proposal)
        self.assertEqual(self.store.data, before)

    def test_duplicate_concurrent_accept_applies_once(self):
        self.place()
        proposal = self.propose()
        def accept(_):
            with self.app.test_client() as client:
                return client.post('/order-amendments/' + proposal.json['uid'] + '/decision', json={'decision': 'accepted', 'revision': 0},
                                   headers={'Authorization': 'Bearer customer'}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(list(pool.map(accept, range(2))), [200, 200])
        self.assertEqual(self.row()['pricing_revision'], 1)
        self.assertEqual(self.stock(), 0)

    def test_frozen_promotion_threshold_loss_does_not_choose_a_new_promotion(self):
        now = datetime.now(timezone.utc)
        self.store.data[('promotions', 'original')] = {'vendor_id': 'vendor', 'shop_id': 'vendor', 'target_type': 'shop',
            'status': 'approved', 'revision': 1, 'approved_revision': 1, 'discount_type': 'percentage', 'discount_value': 10,
            'minimum_order_amount': 100, 'starts_at': (now - timedelta(days=1)).isoformat(), 'ends_at': (now + timedelta(days=1)).isoformat()}
        self.place('cash')
        self.assertEqual(self.row()['total_price'], 111.15)
        self.store.data[('promotions', 'original')]['discount_value'] = 90
        self.store.data[('promotions', 'original')]['ends_at'] = (now - timedelta(seconds=1)).isoformat()
        proposal = self.propose()
        self.assertEqual(proposal.json['new_total'], 86.45)
        self.assertEqual(proposal.json['lines'][0]['discount_amount'], 0)
        self.assertEqual(proposal.json['lines'][0]['promotion_revision'], 1)
        self.assertEqual(self.decide(proposal).status_code, 200)

    def test_multiple_revisions_captures_and_full_refund_use_all_remaining_quotas(self):
        self.place('razorpay', paid=True)
        first = self.propose()
        self.assertEqual(self.decide(first).json['refund_status'], 'completed')
        self.store.data[(storage.SHOP_ITEMS, 'rice')].update({'stock_quantity': 5, 'is_available': True})
        second = self.propose([self.desired(9)], revision=1)
        self.assertEqual(self.decide(second).json['status'], 'awaiting_payment')
        checkout = self.post('/razorpayApi/orders', {'purpose': 'order_amendment', 'reference_id': second.json['uid']})
        self.assertEqual(checkout.status_code, 201, checkout.json)
        intent = self.store.data[('payment_orders', checkout.json['backend_order_id'])]
        self.captures['pay_extra'] = {'id': 'pay_extra', 'order_id': intent['razorpay_order_id'], 'amount': 2470,
                                       'currency': 'INR', 'status': 'captured', 'captured': True}
        self.assertEqual(razorpay_api.settle_payment_order(checkout.json['backend_order_id'], 'pay_extra')['settlement_status'], 'settled')
        third = self.propose([self.desired(6)], revision=2)
        self.assertEqual(self.decide(third).json['refund_status'], 'completed')
        self.assertEqual(self.row()['total_price'], 74.1)
        cancelled = order_refunds.refund_order(self.anchor, 'vendor')
        self.assertEqual(cancelled['status'], 'completed', cancelled)
        self.assertEqual(self.row()['status'], 'cancelled')
        self.assertEqual(self.store.data[(amendments.QUOTAS, 'pay_original')]['reserved_paise'], 12350)
        self.assertEqual(self.store.data[(amendments.QUOTAS, 'pay_extra')]['reserved_paise'], 2470)
        total_refunded = sum(call.args[1]['amount'] for call in self.provider.payment.refund.call_args_list)
        self.assertEqual(total_refunded, 14820)
        count = self.provider.payment.refund.call_count
        self.assertEqual(order_refunds.refund_order(self.anchor, 'vendor')['status'], 'completed')
        self.assertEqual(self.provider.payment.refund.call_count, count)

    def test_provider_timeout_leaves_applied_retryable_with_stable_request_and_no_duplicate_accept(self):
        self.place('razorpay', paid=True)
        self.provider.payment.refund.side_effect = TimeoutError('response lost')
        proposal = self.propose()
        accepted = self.decide(proposal)
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(accepted.json['status'], 'applied')
        self.assertEqual(accepted.json['refund_status'], 'retryable')
        first_call = self.provider.payment.refund.call_args
        self.assertEqual(self.decide(proposal).json['refund_status'], 'retryable')
        self.provider.payment.refund.assert_called_once()
        self.provider.payment.refund.side_effect = lambda payment_id, body, **kwargs: {
            'id': 'rfnd_recovered', 'payment_id': payment_id, 'amount': body['amount'], 'currency': 'INR', 'status': 'processed'}
        response = self.post('/order-amendments/' + proposal.json['uid'] + '/refund', user='vendor')
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(first_call, self.provider.payment.refund.call_args)
        self.assertEqual(self.store.data[(amendments.QUOTAS, 'pay_original')]['reserved_paise'], 3705)

    def test_concurrent_refund_retries_share_a_lease(self):
        import threading
        self.place('razorpay', paid=True)
        self.provider.payment.refund.side_effect = TimeoutError()
        proposal = self.propose()
        self.decide(proposal)
        entered, release = threading.Event(), threading.Event()
        def provider(payment_id, body, **kwargs):
            entered.set()
            release.wait(5)
            return {'id': 'rfnd_once', 'payment_id': payment_id, 'amount': body['amount'], 'currency': 'INR', 'status': 'processed'}
        self.provider.payment.refund.side_effect = provider
        job_id = self.store.data[(amendments.AMENDMENTS, proposal.json['uid'])]['refund_job_ids'][0]
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(amendments.process_refund_job, job_id, 'vendor')
            self.assertTrue(entered.wait(5))
            second = amendments.process_refund_job(job_id, 'vendor')
            self.assertEqual(second['status'], 'processing')
            release.set()
            self.assertEqual(first.result()['status'], 'completed')
        self.assertEqual(self.provider.payment.refund.call_count, 2)  # initial timeout plus one leased retry

    def test_reserved_new_item_cannot_be_deleted_and_missing_inventory_capture_needs_review(self):
        self.place('razorpay', quantity=2, paid=True)
        proposal = self.propose([self.desired(2), self.desired(1, item='milk')])
        self.assertEqual(self.decide(proposal).json['status'], 'awaiting_payment')
        response = self.client.delete('/vendors/items/milk', headers={'Authorization': 'Bearer vendor'})
        self.assertEqual(response.status_code, 409)
        checkout = self.post('/razorpayApi/orders', {'purpose': 'order_amendment', 'reference_id': proposal.json['uid']})
        del self.store.data[(storage.SHOP_ITEMS, 'milk')]
        result = razorpay_api.settle_payment_order(checkout.json['backend_order_id'], 'pay_missing_inventory')
        self.assertEqual(result['settlement_status'], 'requires_review')
        self.assertEqual(self.row()['quantity'], 2)
        self.assertEqual(len(self.values(storage.CUSTOMER_ORDERS)), 1)
        self.assertEqual(self.store.data[(amendments.AMENDMENTS, proposal.json['uid'])]['status'], 'requires_review')
        self.store.data[(storage.SHOP_ITEMS, 'milk')] = {'vendor_id': 'vendor', 'price': 20, 'stock_quantity': 4}
        self.assertEqual(self.client.delete('/vendors/items/milk', headers={'Authorization': 'Bearer vendor'}).status_code, 409)

    def test_admin_cannot_delete_pending_or_reserved_amendment_product(self):
        self.store.data[(storage.USERS, 'admin')] = {'role': 'admin'}
        self.place('razorpay', quantity=2, paid=True)
        proposal = self.propose([self.desired(2), self.desired(1, item='milk')])
        self.assertEqual(proposal.status_code, 201, proposal.json)
        for status in ('pending', 'awaiting_payment', 'requires_review'):
            if status == 'awaiting_payment':
                self.assertEqual(self.decide(proposal).json['status'], 'awaiting_payment')
            elif status == 'requires_review':
                self.store.data[(amendments.AMENDMENTS, proposal.json['uid'])]['status'] = status
            before = copy.deepcopy(self.store.data)
            with self.subTest(status=status):
                try:
                    response = self.client.delete('/admin/products/milk', headers={'Authorization': 'Bearer admin'})
                    self.assertEqual(response.status_code, 409, response.json)
                    self.assertEqual(self.store.data, before)
                    admin.log_admin_action.assert_not_called()
                finally:
                    self.store.data = before

    def test_admin_can_delete_after_amendment_withdrawal_releases_reservation(self):
        self.store.data[(storage.USERS, 'admin')] = {'role': 'admin'}
        self.place('razorpay', quantity=2, paid=True)
        proposal = self.propose([self.desired(2), self.desired(1, item='milk')])
        self.assertEqual(self.decide(proposal).json['status'], 'awaiting_payment')
        self.assertEqual(self.stock('milk'), 4)
        withdrawn = self.post('/order-amendments/' + proposal.json['uid'] + '/withdraw', user='vendor')
        self.assertEqual(withdrawn.status_code, 200, withdrawn.json)
        self.assertEqual(self.stock('milk'), 5)
        response = self.client.delete('/admin/products/milk', headers={'Authorization': 'Bearer admin'})
        self.assertEqual(response.status_code, 200, response.json)
        self.assertNotIn((storage.SHOP_ITEMS, 'milk'), self.store.data)
        admin.log_admin_action.assert_called_once()

    def test_legacy_unbatched_checkout_review_blocks_all_mutations(self):
        for paid in (False, True):
            with self.subTest(paid=paid):
                self.place('razorpay', quantity=2, paid=paid)
                self.store.data.pop(('order_batches', self.batch_id))
                self.row().pop('batch_id')
                original_id = self.anchor
                proposal = self.propose([self.desired(4)])
                self.assertEqual(proposal.status_code, 201, proposal.json)
                self.assertEqual(self.decide(proposal).json['status'], 'awaiting_payment')
                checkout = self.post('/razorpayApi/orders', {'purpose': 'order_amendment', 'reference_id': proposal.json['uid']})
                self.assertEqual(checkout.status_code, 201, checkout.json)
                withdrawn = self.post('/order-amendments/' + proposal.json['uid'] + '/withdraw', user='vendor')
                self.assertEqual(withdrawn.status_code, 200, withdrawn.json)
                self.assertTrue(self.store.data[('order_batches', 'single_' + original_id)]['payment_review_required'])
                for method, suffix, payload in (
                        ('PUT', '/status', {'status': 'confirmed'}),
                        ('POST', '/payment/confirm', None),
                        ('PUT', '/discount', {'amount': 0})):
                    before = copy.deepcopy(self.store.data)
                    response = self.client.open('/vendors/orders/' + original_id + suffix, method=method, json=payload,
                                                headers={'Authorization': 'Bearer vendor'})
                    self.assertEqual(response.status_code, 409, response.json)
                    self.assertIn('needs reconciliation', response.json['detail'])
                    self.assertEqual(self.store.data, before)
                before = copy.deepcopy(self.store.data)
                cancelled = self.post('/orders/' + original_id + '/cancel')
                self.assertEqual(cancelled.status_code, 409, cancelled.json)
                self.assertEqual(self.store.data, before)
                new_proposal = self.propose([self.desired(3)])
                self.assertEqual(new_proposal.status_code, 409, new_proposal.json)
                self.assertIn('needs reconciliation', new_proposal.json['detail'])
                self.assertEqual(self.row()['batch_id'], 'single_' + original_id)
                self.assertEqual(self.row()['quantity'], 2)
                self.assertEqual(self.row()['status'], 'pending')

    def test_legacy_first_proposal_preserves_raw_id_and_current_bill_group(self):
        self.place('cash', quantity=2)
        original_id = self.anchor
        original_created = self.row()['created_at']
        self.store.data.pop(('order_batches', self.batch_id))
        self.row().pop('batch_id')
        proposal = self.propose([self.desired(1)])
        self.assertEqual(proposal.status_code, 201, proposal.json)
        self.assertEqual(self.row()['batch_id'], 'single_' + original_id)
        self.assertEqual(proposal.json['original_lines'][0]['line_id'], original_id)
        self.assertEqual(self.decide(proposal).status_code, 200)
        self.assertEqual(self.row()['batch_id'], 'single_' + original_id)
        self.assertEqual(self.row()['created_at'], original_created)
        self.assertEqual(self.row()['pricing_revision'], 1)
        bill = self.client.get('/orders/' + original_id + '/invoice', headers={'Authorization': 'Bearer customer'})
        self.assertEqual(bill.status_code, 200, bill.json)
        self.assertEqual([line['order_id'] for line in bill.json['lines']], [original_id])
        self.assertEqual(bill.json['total'], 12.35)
        self.assertEqual(len(self.values(storage.CUSTOMER_ORDERS)), 1)

    def test_zero_order_change_never_creates_zero_payment_or_refund(self):
        self.place('cash')
        proposal = self.propose(lines=[])
        result = self.decide(proposal)
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(result.json['new_total'], 0)
        self.assertEqual(result.json['amount_due'], 0)
        self.assertEqual(result.json['refund_status'], 'none')
        self.assertEqual(self.row()['status'], 'removed')
        self.provider.order.create.assert_not_called()
        self.provider.payment.refund.assert_not_called()
