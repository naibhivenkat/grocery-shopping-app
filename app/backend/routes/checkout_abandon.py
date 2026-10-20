"""Atomically abandon buyer checkout keys, including batches not yet created.

Missing-key tombstones race on the same document as order creation. The order
creator must reject an ``abandoned`` batch before reading its saved response.
Captured purchases are retained; an unresolved payment is never cancelled here.
"""
import hashlib

from firebase_admin import firestore
from flask import Blueprint, g, jsonify
from google.cloud.firestore_v1.base_query import FieldFilter

from auth_utils import require_role
from db import CUSTOMER_ORDERS, KHATA_LEDGERS, KHATA_TRANSACTIONS, NOTIFICATIONS, SHOP_ITEMS, USERS, col, db, doc, now_iso
from notification_delivery import deliver_push, notification_data
from routes.khata import KhataError, _identifier, _khata_error, _money_paise, _payload
from routes.measurement import same_base

checkout_abandon_bp = Blueprint('checkout_abandon', __name__)
checkout_abandon_bp.register_error_handler(KhataError, _khata_error)


def _whole(value):
    if isinstance(value, bool) or not isinstance(value, (int, str)) or not str(value).isdigit():
        raise KhataError('Invalid inventory quantity; reconciliation required', 409)
    number = int(value)
    if number > 1000000000:
        raise KhataError('Invalid inventory quantity; reconciliation required', 409)
    return number


@checkout_abandon_bp.post('/orders/checkout/abandon')
@require_role('customer', 'vendor', 'service')
def abandon_checkout():
    payload = _payload()
    keys = payload.get('keys')
    if (set(payload) != {'keys'} or not isinstance(keys, list) or not 1 <= len(keys) <= 20
            or any(not isinstance(key, str) or not 8 <= len(key) <= 200 for key in keys)
            or len(set(keys)) != len(keys)):
        raise KhataError('Supply 1 to 20 unique checkout keys of 8 to 200 characters')
    refs = [doc('order_batches', hashlib.sha256(f'{g.user_id}:{key}'.encode()).hexdigest()) for key in keys]

    @firestore.transactional
    def abandon(tx):
        batches = [(ref, ref.get(transaction=tx)) for ref in refs]
        buyer = doc(USERS, g.user_id).get(transaction=tx)
        buyer_data = buyer.to_dict() or {}
        if (not buyer.exists or buyer_data.get('role') not in {'customer', 'vendor', 'service'}
                or buyer_data.get('is_suspended')):
            raise KhataError('Current buyer account permissions required', 403)
        orders = []
        for ref, snapshot in batches:
            if not snapshot.exists:
                continue
            batch = snapshot.to_dict() or {}
            if any(batch.get(field) not in (None, g.user_id) for field in ('user_id', 'customer_id')):
                raise KhataError('Checkout does not belong to this account', 403)
            if batch.get('active_amendment_id') or batch.get('payment_review_required'):
                raise KhataError('Resolve the order modification before abandoning checkout', 409)
            response = batch.get('response') or {}
            if not isinstance(response, dict):
                raise KhataError('Invalid saved checkout; reconciliation required', 409)
            identifiers = response.get('order_ids', [])
            if (not isinstance(identifiers, list)
                    or len(identifiers) > 100 or any(not isinstance(value, str) or not value or '/' in value for value in identifiers)
                    or len(set(identifiers)) != len(identifiers)):
                raise KhataError('Invalid saved checkout; reconciliation required', 409)
            members = list(tx.get(col(CUSTOMER_ORDERS).where(filter=FieldFilter('batch_id', '==', ref.id))))
            if len(orders) + len(members) > 100:
                raise KhataError('Abandon at most 100 checkout lines at once; contact support for this checkout', 422)
            if {entry.id for entry in members} != set(identifiers):
                raise KhataError('Checkout lines changed; reconciliation required', 409)
            if not identifiers and batch.get('abandoned') is not True:
                raise KhataError('Checkout has no saved lines; reconciliation required', 409)
            values = [entry.to_dict() or {} for entry in members]
            if any(value.get('pricing_revision', 0) for value in values) or batch.get('pricing_revision', 0):
                raise KhataError('Revised orders require shop reconciliation before cancellation', 409)
            if (any(value.get('payment_status') == 'paid' for value in values)
                    and any(value.get('payment_status') != 'paid' and value.get('status') != 'cancelled' for value in values)
                    and any(value.get('promotion_id') or _money_paise(value.get('discount_amount', 0), allow_zero=True) for value in values)):
                raise KhataError('Partly collected discounted orders require shop reconciliation', 409)
            for entry in members:
                value = entry.to_dict() or {}
                if value.get('customer_id') != g.user_id:
                    raise KhataError('Checkout does not belong to this account', 403)
                orders.append((entry.reference, value))
        # Read all referenced state before planning any writes. Reading inventory
        # and ledger documents serializes with fulfilment, amendments and payments.
        vendors, inventory, ledgers, intents = {}, {}, {}, {}
        for _, order in orders:
            vendor_id = _identifier(order.get('vendor_id'), 'vendor_id')
            if vendor_id not in vendors:
                vendors[vendor_id] = doc(USERS, vendor_id).get(transaction=tx)
            item_id = _identifier(order.get('item_id'), 'item_id')
            if item_id not in inventory:
                inventory[item_id] = doc(SHOP_ITEMS, item_id).get(transaction=tx)
            ledger_id = order.get('khata_ledger_id')
            if ledger_id and ledger_id not in ledgers:
                ledger_id = _identifier(ledger_id, 'khata_ledger_id')
                ledger_snap = doc(KHATA_LEDGERS, ledger_id).get(transaction=tx)
                entries = list(tx.get(col(KHATA_TRANSACTIONS).where(filter=FieldFilter('ledger_id', '==', ledger_id))))
                ledgers[ledger_id] = (ledger_snap, entries)
            intent_id = order.get('payment_intent_id')
            if intent_id and intent_id not in intents:
                intent_id = _identifier(intent_id, 'payment_intent_id')
                intents[intent_id] = doc('payment_orders', intent_id).get(transaction=tx)
        cancelled, kept, stock_additions, debt_reductions = [], [], {}, {}
        changes = []
        for ref, order in orders:
            intent_id = order.get('payment_intent_id')
            intent = (intents[intent_id].to_dict() or {}) if intent_id else {}
            if (order.get('refund_status') or order.get('refund_reconciliation_required')
                    or order.get('pending_amendment_id') or order.get('amendment_pending') or order.get('current_amendment_id')
                    or order.get('amendment_status') in {'pending', 'processing', 'requires_review', 'awaiting_payment'}
                    or order.get('settlement_status') == 'requires_review'
                    or intent.get('settlement_status') == 'requires_review'):
                raise KhataError('Resolve the order payment, refund or modification before abandoning checkout', 409)
            total = _money_paise(order.get('total_price'), allow_zero=True)
            paid = order.get('payment_status') == 'paid'
            if paid:
                if total == 0 and order.get('payment_exempt') is not True:
                    raise KhataError('Invalid free order; reconciliation required', 409)
                if intent_id and (not intents[intent_id].exists or intent.get('status') != 'paid'):
                    raise KhataError('Payment confirmation requires reconciliation', 409)
                kept.append(ref.id)
                continue
            if (order.get('payment_status', 'pending') != 'pending'
                    or intent_id or order.get('payment_id') or order.get('razorpay_payment_id')
                    or order.get('paid_at') or _money_paise(order.get('partial_amount_paid', 0), allow_zero=True)):
                raise KhataError('Resolve or finish this order before abandoning checkout', 409)
            if order.get('status') == 'cancelled':
                cancelled.append(ref.id)
                continue
            if order.get('status') not in {'pending', 'confirmed'}:
                raise KhataError('Resolve or finish this order before abandoning checkout', 409)
            vendor = vendors[order['vendor_id']]
            if not vendor.exists or (vendor.to_dict() or {}).get('role') != 'vendor':
                raise KhataError('Shop account requires reconciliation', 409)
            item = inventory[order['item_id']]
            item_data = item.to_dict() or {}
            if not item.exists or item_data.get('vendor_id') != order['vendor_id']:
                raise KhataError('Inventory requires reconciliation', 409)
            same_base(order, item_data)
            quantity = _whole(order.get('quantity'))
            if not quantity:
                raise KhataError('Invalid ordered quantity', 409)
            if item_data.get('stock_quantity') is not None:
                stock_additions[order['item_id']] = stock_additions.get(order['item_id'], 0) + quantity
            ledger_id = order.get('khata_ledger_id')
            if order.get('payment_method') == 'khata' and not ledger_id:
                raise KhataError('Khata ledger requires reconciliation', 409)
            if ledger_id:
                snap, _ = ledgers[ledger_id]
                ledger = snap.to_dict() or {}
                if (not snap.exists or ledger.get('vendor_id') != order['vendor_id']
                        or ledger.get('customer_id') != g.user_id):
                    raise KhataError('Khata ledger parties do not match', 409)
                debt_reductions[ledger_id] = debt_reductions.get(ledger_id, 0) + total
            changes.append((ref, order))
            cancelled.append(ref.id)
        stock_updates, ledger_updates = {}, {}
        for item_id, addition in stock_additions.items():
            item = inventory[item_id].to_dict() or {}
            stock_updates[item_id] = _whole(_whole(item['stock_quantity']) + addition)
        for ledger_id, reduction in debt_reductions.items():
            snapshot, entries = ledgers[ledger_id]
            balance = _money_paise((snapshot.to_dict() or {}).get('balance', 0), allow_zero=True)
            pending = sum(_money_paise((entry.to_dict() or {}).get('amount')) for entry in entries
                          if (entry.to_dict() or {}).get('status') == 'pending')
            if balance < reduction or pending > balance - reduction:
                raise KhataError('Review Khata payments before cancelling these orders', 409)
            ledger_updates[ledger_id] = (balance - reduction) / 100
        timestamp, events = now_iso(), []
        for ref, order in changes:
            tx.update(ref, {'status': 'cancelled', 'due_amount': 0, 'updated_at': timestamp,
                            'checkout_abandoned_at': timestamp})
            if order.get('khata_ledger_id') and _money_paise(order['total_price'], allow_zero=True):
                tx.create(doc(KHATA_TRANSACTIONS, f'cancel_{ref.id}'), {
                    'ledger_id': order['khata_ledger_id'], 'vendor_id': order['vendor_id'],
                    'customer_id': g.user_id, 'type': 'debit', 'amount': order['total_price'],
                    'order_id': ref.id, 'description': 'Cancelled Khata order', 'created_at': timestamp})
            event = notification_data(order['vendor_id'], 'order_status', 'Order cancelled',
                                      'The customer abandoned this unpaid checkout.', ref.id)
            tx.set(col(NOTIFICATIONS).document(), event)
            events.append(event)
        for item_id, quantity in stock_updates.items():
            item = inventory[item_id].to_dict() or {}
            tx.update(inventory[item_id].reference, {'stock_quantity': quantity,
                'is_available': quantity > 0 and item.get('disabled_by_admin') is not True, 'updated_at': timestamp})
        for ledger_id, balance in ledger_updates.items():
            tx.update(ledgers[ledger_id][0].reference, {'balance': balance, 'updated_at': timestamp})
        for ref, snapshot in batches:
            tx.set(ref, {'abandoned': True, 'customer_id': g.user_id, 'user_id': g.user_id,
                         'abandoned_at': (snapshot.to_dict() or {}).get('abandoned_at') or timestamp}, merge=True)
        return {'cancelled_order_ids': sorted(cancelled), 'kept_order_ids': sorted(kept)}, events

    body, events = abandon(db().transaction())
    for event in events:
        deliver_push(event, lookup=doc)
    return jsonify(body)
