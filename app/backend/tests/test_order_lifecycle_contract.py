import unittest

from services.order_lifecycle import action_for, legacy_patch, native_lifecycle, project, transition


class LifecycleFoundationTests(unittest.TestCase):
    def test_sequence_and_truthful_legacy_projection(self):
        legacy = {"status": "confirmed"}
        projected = project(legacy)
        self.assertEqual(projected, {"version": 2, "stage": "accepted", "revision": 0,
                                     "provenance": "legacy_unknown"})
        self.assertNotIn("lifecycle", legacy)
        state = native_lifecycle()
        for action, stage, status in [("accept", "accepted", "confirmed"),
                                      ("start_preparing", "preparing", "confirmed"),
                                      ("mark_ready", "ready", "packed")]:
            self.assertEqual(action_for({"lifecycle": state}), action)
            state, actual_status = transition(state, action)
            self.assertEqual((state["stage"], actual_status), (stage, status))
        self.assertEqual(state["revision"], 3)
        with self.assertRaises(ValueError):
            transition(state, "accept")

    def test_legacy_reconciliation_preserves_intermediate_and_receipts(self):
        order = {"lifecycle": {"version": 2, "stage": "preparing", "revision": 4,
                               "provenance": "native", "extra": "preserved"},
                 "lifecycle_receipts": {"key": {"result": "original"}}}
        patch = legacy_patch(order, {"status": "confirmed"})
        self.assertEqual(patch["lifecycle"]["stage"], "preparing")
        self.assertEqual(patch["lifecycle"]["revision"], 5)
        self.assertEqual(patch["lifecycle"]["extra"], "preserved")
        self.assertNotIn("lifecycle_receipts", patch)
        self.assertEqual(order["lifecycle"]["revision"], 4)
        self.assertEqual(legacy_patch({"status": "pending"}, {"status": "cancelled"}),
                         {"status": "cancelled"})
        self.assertEqual(legacy_patch(order, {"status": "cancelled"})["lifecycle"]["stage"], "cancelled")


class LifecycleRouteTests(unittest.TestCase):
    def setUp(self):
        from test_order_amendments import AmendmentTests
        self.harness = AmendmentTests('test_unpaid_ten_to_seven_changes_only_after_accept_without_phantom_stock')
        self.harness.setUp()
        self.addCleanup(self.harness.doCleanups)
        self.harness.place()

    def test_route_sequence_replay_guard_and_legacy_write(self):
        import copy
        h = self.harness
        path = f'/vendors/orders/{h.anchor}/lifecycle-actions'
        def act(action, revision, key, user='vendor'):
            return h.post(path, {'action': action, 'expected_revision': revision, 'request_id': key}, user=user)
        before = copy.deepcopy(h.store.data)
        self.assertEqual(act('accept', 0, 'foreign', user='other_vendor').status_code, 403)
        self.assertEqual(h.store.data, before)
        self.assertEqual(act('mark_ready', 0, 'skip').status_code, 409)
        self.assertEqual(h.store.data, before)
        first = act('accept', 0, 'one')
        self.assertEqual(first.status_code, 200, first.json)
        self.assertEqual(first.json['lifecycle']['revision'], 1)
        after = copy.deepcopy(h.store.data)
        self.assertEqual(act('accept', 0, 'one').json, first.json)
        self.assertEqual(h.store.data, after)
        h.row()['refund_status'] = 'processing'
        locked = copy.deepcopy(h.store.data)
        self.assertEqual(act('accept', 0, 'one').status_code, 409)
        self.assertEqual(h.store.data, locked)
        del h.row()['refund_status']
        self.assertEqual(act('start_preparing', 1, 'one').status_code, 409)
        self.assertEqual(act('start_preparing', 0, 'two').status_code, 409)
        second = act('start_preparing', 1, 'two')
        self.assertEqual(second.status_code, 200, second.json)
        third = act('mark_ready', 2, 'three')
        self.assertEqual(third.status_code, 200, third.json)
        self.assertEqual((third.json['status'], third.json['lifecycle']['revision']), ('packed', 3))
        self.assertEqual(h.stock(), 0)
        self.assertEqual(h.row()['total_price'], 123.5)

    def test_amendment_keeps_current_receipts_and_revision(self):
        h = self.harness
        path = f'/vendors/orders/{h.anchor}/lifecycle-actions'
        first = h.post(path, {'action': 'accept', 'expected_revision': 0, 'request_id': 'one'}, user='vendor')
        self.assertEqual(first.status_code, 200, first.json)
        proposal = h.propose()
        self.assertEqual(proposal.status_code, 201, proposal.json)
        self.assertEqual(h.row()['lifecycle']['revision'], 2)
        receipts = dict(h.row()['lifecycle_receipts'])
        decision = h.decide(proposal)
        self.assertEqual(decision.status_code, 200, decision.json)
        self.assertEqual(h.row()['lifecycle']['revision'], 3)
        self.assertEqual(h.row()['lifecycle_receipts'], receipts)

    def test_guards_and_projections(self):
        import copy
        h = self.harness
        path = f'/vendors/orders/{h.anchor}/lifecycle-actions'
        headers = {'Authorization': 'Bearer vendor'}
        listing = h.client.get('/vendors/orders', headers=headers)
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.json[0]['allowed_actions'], ['accept'])
        customer = h.client.get('/orders', headers={'Authorization': 'Bearer customer'})
        self.assertEqual(customer.json[0]['allowed_actions'], [])
        self.assertNotIn('lifecycle_receipts', listing.json[0])
        h.row().update(payment_method='razorpay', payment_status='pending')
        before = copy.deepcopy(h.store.data)
        request = {'action': 'accept', 'expected_revision': 0, 'request_id': 'unpaid'}
        self.assertEqual(h.post(path, request, user='vendor').status_code, 409)
        self.assertEqual(h.store.data, before)
        self.assertEqual(h.client.get('/vendors/orders', headers=headers).json[0]['allowed_actions'], [])
        self.assertEqual(h.post('/vendors/orders/missing/lifecycle-actions', request, user='vendor').status_code, 404)
        self.assertEqual(h.post(path, {'action': 'accept'}, user='vendor').status_code, 422)
        h.row().update(payment_method='cash', payment_status='pending')
        proposal = h.propose()
        self.assertEqual(proposal.status_code, 201)
        before = copy.deepcopy(h.store.data)
        self.assertEqual(h.post(path, request, user='vendor').status_code, 409)
        self.assertEqual(h.store.data, before)

    def test_group_cancel_increments_once_and_preserves_receipts(self):
        h = self.harness
        path = f'/vendors/orders/{h.anchor}/lifecycle-actions'
        first = h.post(path, {'action': 'accept', 'expected_revision': 0, 'request_id': 'one'}, user='vendor')
        self.assertEqual(first.status_code, 200)
        receipts = dict(h.row()['lifecycle_receipts'])
        from routes.order_amendments import cancel_group_with_refunds
        with h.app.test_request_context():
            result = cancel_group_with_refunds(h.anchor, 'vendor')
        self.assertEqual(h.row()['status'], 'cancelled')
        self.assertEqual(h.row()['lifecycle']['stage'], 'cancelled')
        self.assertEqual(h.row()['lifecycle']['revision'], 2)
        self.assertEqual(h.row()['lifecycle_receipts'], receipts)


class LifecycleFinancialWriterTests(unittest.TestCase):
    def test_settlement_bumps_only_effective_writes_and_keeps_receipts(self):
        from test_payment_security import PaymentSecurityTests
        from routes.razorpay_api import settle_payment_order
        h = PaymentSecurityTests('test_batch_paid_atomically_and_replay_no_duplicate_changes')
        h.setUp()
        self.addCleanup(h.doCleanups)
        for identifier in ('a', 'b'):
            h.store.data['customer_orders', identifier].update(
                lifecycle=native_lifecycle(), lifecycle_receipts={'existing': {'actor_id': 'vendor'}})
        self.assertEqual(settle_payment_order('i', 'pay_1')['settlement_status'], 'settled')
        for identifier in ('a', 'b'):
            row = h.store.data['customer_orders', identifier]
            self.assertEqual(row['lifecycle']['revision'], 1)
            self.assertEqual(row['lifecycle_receipts'], {'existing': {'actor_id': 'vendor'}})
        settle_payment_order('i', 'pay_1')
        self.assertEqual(h.store.data['customer_orders', 'a']['lifecycle']['revision'], 1)

    def test_refund_retry_uses_current_snapshot_and_preserves_stock(self):
        from test_order_refunds import OrderRefundTests
        from routes.order_refunds import refund_order
        h = OrderRefundTests('test_ambiguous_timeout_retries_exact_persisted_body_and_key_without_stock_changes')
        h.setUp()
        self.addCleanup(h.doCleanups)
        row = h.store.data['customer_orders', 'a']
        row.update(lifecycle=native_lifecycle(), lifecycle_receipts={'existing': {'actor_id': 'vendor'}})
        h.provider.payment.refund.side_effect = TimeoutError('lost response')
        self.assertEqual(refund_order('a', 'vendor')['status'], 'retryable')
        row = h.store.data['customer_orders', 'a']
        self.assertEqual(row['lifecycle']['revision'], 2)
        self.assertEqual(row['lifecycle_receipts'], {'existing': {'actor_id': 'vendor'}})
        self.assertEqual(h.store.data['shop_items', 'item']['stock_quantity'], 8)

    def test_discount_reconciles_each_order_once(self):
        from test_billing_import import BillingImportTests
        h = BillingImportTests('test_discount_is_replacement_atomic_and_updates_payable')
        h.setUp()
        self.addCleanup(h.doCleanups)
        for identifier in ('rice', 'milk'):
            h.store.data['customer_orders', identifier].update(lifecycle=native_lifecycle(), lifecycle_receipts={'x': {'result': 'saved'}})
        self.assertEqual(h.discount(10).status_code, 200)
        for identifier in ('rice', 'milk'):
            row = h.store.data['customer_orders', identifier]
            self.assertEqual(row['lifecycle']['revision'], 1)
            self.assertEqual(row['lifecycle_receipts'], {'x': {'result': 'saved'}})

    def test_checkout_abandon_reconciles_once_on_replay(self):
        from test_checkout_abandon import CheckoutAbandonTests
        h = CheckoutAbandonTests('test_created_first_missing_second_tombstone_replay_and_late_creation')
        h.setUp()
        self.addCleanup(h.doCleanups)
        identifier = h.create().json['order_id']
        self.assertEqual(h.call().status_code, 200)
        row = h.store.data['customer_orders', identifier]
        self.assertEqual((row['lifecycle']['stage'], row['lifecycle']['revision']), ('cancelled', 1))
        self.assertEqual(h.call().status_code, 200)
        self.assertEqual(h.store.data['customer_orders', identifier]['lifecycle']['revision'], 1)

    def test_failed_payment_reservation_release_uses_new_revision(self):
        from types import SimpleNamespace
        from unittest.mock import MagicMock, patch
        from flask import g
        from test_payment_security import PaymentSecurityTests
        import routes.razorpay_api as api
        h = PaymentSecurityTests('test_server_checkout_and_reopen_reuse_same_provider_order')
        h.setUp()
        self.addCleanup(h.doCleanups)
        row = h.store.data['customer_orders', 'a']
        row.update(payment_method='razorpay', lifecycle=native_lifecycle(), lifecycle_receipts={'x': {'result': 'saved'}})
        provider = MagicMock()
        provider.order.create.side_effect = RuntimeError('provider unavailable')
        collection = SimpleNamespace(document=lambda: h.store.doc('payment_orders', 'new_i'))
        with patch.object(api, 'get_razorpay_client', return_value=provider), patch.object(api, 'col', return_value=collection):
            with h._app().test_request_context('/razorpayApi/orders', json={'purpose': 'order', 'reference_id': 'a'}):
                g.user_id = 'u'
                response = api.create_razorpay_order.__wrapped__()
        self.assertEqual(response[1], 503)
        row = h.store.data['customer_orders', 'a']
        self.assertEqual(row['lifecycle']['revision'], 2)
        self.assertIsNone(row['payment_intent_id'])
        self.assertEqual(row['lifecycle_receipts'], {'x': {'result': 'saved'}})

    def test_legacy_status_cash_and_cancel_reconcile_once(self):
        from test_core_routes import CoreRoutesTests
        h = CoreRoutesTests('test_order_transitions_aliases_and_cash_delivery_confirmation')
        h.setUp()
        self.addCleanup(h.doCleanups)
        row = h.store.data['customer_orders', 'order']
        row.update(lifecycle=native_lifecycle(), lifecycle_receipts={'x': {'result': 'saved'}})
        path = '/vendors/orders/order/status'
        for expected, status in enumerate(('accepted', 'packed', 'completed'), 1):
            self.assertEqual(h.call(path, {'status': status}, 'PUT').status_code, 200)
            row = h.store.data['customer_orders', 'order']
            self.assertEqual(row['lifecycle']['revision'], expected)
            self.assertEqual(row['lifecycle_receipts'], {'x': {'result': 'saved'}})
        self.assertEqual(row['payment_status'], 'paid')
        self.assertEqual(h.call(path, {'status': 'completed'}, 'PUT').status_code, 200)
        self.assertEqual(h.store.data['customer_orders', 'order']['lifecycle']['revision'], 3)

    def test_cash_confirmation_zero_positive_and_replay(self):
        from test_core_routes import CoreRoutesTests
        for zero in (False, True):
            with self.subTest(zero=zero):
                h = CoreRoutesTests('test_order_transitions_aliases_and_cash_delivery_confirmation')
                h.setUp()
                try:
                    row = h.store.data['customer_orders', 'order']
                    row['lifecycle'] = native_lifecycle()
                    if zero:
                        row.update(total_price=0, payment_exempt=True)
                    path = '/vendors/orders/order/payment/confirm'
                    self.assertEqual(h.call(path, {}, 'POST').status_code, 200)
                    self.assertEqual(h.store.data['customer_orders', 'order']['lifecycle']['revision'], 1)
                    self.assertEqual(h.call(path, {}, 'POST').status_code, 200)
                    self.assertEqual(h.store.data['customer_orders', 'order']['lifecycle']['revision'], 1)
                finally:
                    h.doCleanups()

    def test_customer_cancel_restores_stock_once_and_bumps_revision(self):
        from test_orders_api import OrdersTests
        h = OrdersTests('test_cash_exact_price_and_stock_reservation')
        h.setUp()
        self.addCleanup(h.doCleanups)
        created = h.order()
        identifier = created.json['order_id']
        self.assertEqual(h.cancel(created).status_code, 200)
        row = h.store.data['customer_orders', identifier]
        self.assertEqual((row['lifecycle']['stage'], row['lifecycle']['revision']), ('cancelled', 1))
        self.assertEqual(h.cancel(created).status_code, 200)
        self.assertEqual(h.store.data['customer_orders', identifier]['lifecycle']['revision'], 1)
        self.assertEqual(h.stock(), 10)

    def test_new_amendment_child_does_not_inherit_receipts(self):
        from test_order_amendments import AmendmentTests
        import db as storage
        h = AmendmentTests('test_unpaid_ten_to_seven_changes_only_after_accept_without_phantom_stock')
        h.setUp()
        self.addCleanup(h.doCleanups)
        h.place()
        h.row()['lifecycle_receipts'] = {'old': {'result': 'private'}}
        proposal = h.propose(lines=[h.desired(quantity=1, item='milk')])
        self.assertEqual(proposal.status_code, 201, proposal.json)
        decision = h.decide(proposal)
        self.assertEqual(decision.status_code, 200, decision.json)
        children = [value for (collection, identifier), value in h.store.data.items()
                    if collection == storage.CUSTOMER_ORDERS and identifier != h.anchor]
        self.assertEqual(len(children), 1)
        self.assertNotIn('lifecycle_receipts', children[0])
        self.assertEqual(children[0]['lifecycle'], native_lifecycle())
        self.assertEqual(h.row()['lifecycle_receipts'], {'old': {'result': 'private'}})

    def test_legacy_write_invalidates_observed_revision(self):
        from test_order_amendments import AmendmentTests
        h = AmendmentTests('test_unpaid_ten_to_seven_changes_only_after_accept_without_phantom_stock')
        h.setUp()
        self.addCleanup(h.doCleanups)
        h.place()
        path = f'/vendors/orders/{h.anchor}/lifecycle-actions'
        legacy = h.client.put(f'/vendors/orders/{h.anchor}/status', json={'status': 'accepted'},
                              headers={'Authorization': 'Bearer vendor'})
        self.assertEqual(legacy.status_code, 200)
        stale = h.post(path, {'action': 'start_preparing', 'expected_revision': 0, 'request_id': 'stale'}, user='vendor')
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(h.row()['lifecycle']['revision'], 1)
        current = h.post(path, {'action': 'start_preparing', 'expected_revision': 1, 'request_id': 'current'}, user='vendor')
        self.assertEqual(current.status_code, 200, current.json)

    def test_amendment_hold_and_rejection_each_increment_once(self):
        from test_order_amendments import AmendmentTests
        h = AmendmentTests('test_unpaid_ten_to_seven_changes_only_after_accept_without_phantom_stock')
        h.setUp()
        self.addCleanup(h.doCleanups)
        h.place()
        proposal = h.propose()
        self.assertEqual(proposal.status_code, 201)
        self.assertEqual(h.row()['lifecycle']['revision'], 1)
        result = h.decide(proposal, decision='rejected')
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(h.row()['lifecycle']['revision'], 2)
        self.assertFalse(h.row()['amendment_pending'])

    def test_refund_finalize_bumps_each_commit_and_replay_is_noop(self):
        from test_order_refunds import OrderRefundTests
        from routes.order_refunds import refund_order
        h = OrderRefundTests('test_pending_refund_is_submitted_cancels_and_restores_stock_once')
        h.setUp()
        self.addCleanup(h.doCleanups)
        h.store.data['customer_orders', 'a'].update(lifecycle=native_lifecycle(), lifecycle_receipts={'x': {'result': 'saved'}})
        self.assertEqual(refund_order('a', 'vendor')['status'], 'submitted')
        row = h.store.data['customer_orders', 'a']
        self.assertEqual((row['lifecycle']['stage'], row['lifecycle']['revision']), ('cancelled', 2))
        self.assertEqual(row['lifecycle_receipts'], {'x': {'result': 'saved'}})
        self.assertEqual(h.store.data['shop_items', 'item']['stock_quantity'], 10)
        h.provider.refund.fetch.return_value = h.entity('pending')
        refund_order('a', 'vendor')
        self.assertEqual(h.store.data['shop_items', 'item']['stock_quantity'], 10)

    def test_expiry_get_releases_hold_with_revision(self):
        from datetime import datetime, timedelta, timezone
        from test_order_amendments import AmendmentTests
        from routes.order_amendments import AMENDMENTS
        h = AmendmentTests('test_expiry_releases_reservation_without_payment_intent')
        h.setUp()
        self.addCleanup(h.doCleanups)
        h.place('razorpay', quantity=2, paid=True)
        h.row()['lifecycle_receipts'] = {'x': {'result': 'saved'}}
        proposal = h.propose([h.desired(4)])
        self.assertEqual(h.row()['lifecycle']['revision'], 1)
        self.assertEqual(h.decide(proposal).status_code, 200)
        h.store.data[AMENDMENTS, proposal.json['uid']]['expires_at'] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        history = h.client.get(f'/orders/{h.anchor}/amendments', headers={'Authorization': 'Bearer customer'})
        self.assertEqual(history.status_code, 200)
        self.assertEqual(history.json[0]['status'], 'expired')
        self.assertEqual(h.row()['lifecycle']['revision'], 2)
        self.assertEqual(h.row()['lifecycle_receipts'], {'x': {'result': 'saved'}})
        self.assertEqual(h.stock(), 8)
