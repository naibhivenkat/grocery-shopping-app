"""Durable, original-payment refunds for vendor-owned grocery order lines.

Provider calls are outside Firestore transactions. A persisted request, provider
idempotency header and fenced lease make ambiguous response-loss retries safe.
"""
from datetime import datetime, timedelta, timezone
from routes.measurement import same_base
from routes.order_amendments import guard_order_mutation, cancel_group_with_refunds
from decimal import Decimal, InvalidOperation
import hashlib
import uuid
from flask import Blueprint, g, jsonify, request
from google.cloud import firestore
from auth_utils import require_role
from db import CUSTOMER_ORDERS, SHOP_ITEMS, USERS, doc, db, now_iso
from razorpay_config import get_razorpay_client
from routes.razorpay_api import PAYMENT_ORDERS, captured_payment_matches

order_refunds_bp = Blueprint('order_refunds', __name__)
REFUNDS = 'order_refunds'
QUOTAS = 'payment_refund_quotas'


def _exact_paise(order):
    amount = order.get('total_paise')
    if amount is not None:
        if type(amount) is not int or not 0 < amount <= 10_000_000_00:
            raise ValueError('Invalid original order amount')
        return amount
    try:
        value = Decimal(str(order.get('total_price'))) * 100
        if not value.is_finite() or value != value.to_integral_value() or not 0 < value <= 10_000_000_00:
            raise ValueError('Invalid original order amount')
        return int(value)
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError('Invalid original order amount')


def _quantity(value, allow_zero=False):
    if type(value) is not int or value < (0 if allow_zero else 1):
        raise ValueError('Invalid stock quantity; inventory reconciliation required')
    return value


def refund_order(order_id, actor_id, allow_admin=False):
    if not isinstance(order_id, str) or not order_id or '/' in order_id or len(order_id) > 128:
        raise ValueError('Invalid order ID')
    initial_snap = doc(CUSTOMER_ORDERS, order_id).get()
    initial = initial_snap.to_dict() or {}
    if initial.get('status') != 'cancelled' and (initial.get('total_paise') == 0 or initial.get('total_price') == 0):
        raise ValueError('No payment was collected for this line; use an order amendment for group changes')
    if initial.get('pricing_revision', 0) > 0 or (initial.get('batch_id') and initial.get('discount_amount', 0)):
        if allow_admin:
            raise ValueError('Revised shop orders must be cancelled through the owning shop amendment workflow')
        return cancel_group_with_refunds(order_id, actor_id)
    order_ref = doc(CUSTOMER_ORDERS, order_id)
    refund_ref = doc(REFUNDS, order_id)
    lease_token = uuid.uuid4().hex

    @firestore.transactional
    def acquire(tx):
        order_snap = order_ref.get(transaction=tx)
        refund_snap = refund_ref.get(transaction=tx)
        if not order_snap.exists:
            raise ValueError('Order not found')
        order = order_snap.to_dict() or {}
        if allow_admin:
            actor_snap = doc(USERS, actor_id).get(transaction=tx)
            actor = actor_snap.to_dict() or {}
            if (not actor_snap.exists or actor.get('is_suspended')
                or actor.get('role') not in {'admin', 'super_admin'}):
                raise PermissionError('Current administrative permissions required')
        elif order.get('vendor_id') != actor_id:
            raise PermissionError('Not your order')
        guard_order_mutation(tx, order, lookup=doc)
        if order.get("pricing_revision", 0) > 0 or (order.get("batch_id") and order.get("discount_amount", 0)):
            raise ValueError("Order changed; retry the refund through the group cancellation workflow")
        existing = refund_snap.to_dict() or {}
        status = existing.get('status')
        if status in {'completed', 'requires_review'}:
            return {'skip': True, **existing}
        if status == 'processing':
            try:
                started = datetime.fromisoformat(existing.get('started_at') or '')
                if started > datetime.now(timezone.utc) - timedelta(minutes=5):
                    return {'skip': True, **existing}
            except (TypeError, ValueError):
                raise ValueError('Invalid refund lease; reconciliation required')
        if order.get('status') not in {'pending', 'confirmed', 'cancelled'}:
            raise ValueError('Only unfulfilled or cancelled orders can be refunded')
        intent_id = order.get('payment_intent_id')
        if not isinstance(intent_id, str) or not intent_id or '/' in intent_id:
            raise ValueError('Original captured payment intent is required')
        intent_snap = doc(PAYMENT_ORDERS, intent_id).get(transaction=tx)
        intent = intent_snap.to_dict() or {}
        targets = intent.get('target_ids') or [intent.get('reference_id')]
        if (not intent_snap.exists or intent.get('status') != 'paid' or intent.get('purpose') != 'order'
            or intent.get('user_id') != order.get('customer_id') or order_id not in targets
            or intent.get('currency') != 'INR'):
            raise ValueError('Captured payment does not belong to this order')
        payment_id = intent.get('payment_id')
        if not isinstance(payment_id, str) or not payment_id.startswith('pay_') or '/' in payment_id:
            raise ValueError('Invalid original captured payment ID')
        if order.get('razorpay_payment_id') and order['razorpay_payment_id'] != payment_id:
            raise ValueError('Original payment metadata mismatch')
        if order.get('status') != 'cancelled':
            _quantity(order.get('quantity'))
            item_id = order.get('item_id')
            if not isinstance(item_id,str) or not item_id or '/' in item_id:
                raise ValueError('Invalid original item; inventory reconciliation required')
            inventory_snap = doc(SHOP_ITEMS,item_id).get(transaction=tx)
            inventory = inventory_snap.to_dict() or {}
            if inventory_snap.exists:
                same_base(order, inventory)
            if inventory_snap.exists and inventory.get('stock_quantity') is not None:
                _quantity(inventory['stock_quantity'],allow_zero=True)
        amount = _exact_paise(order)
        captured = intent.get('amount_paise')
        if type(captured) is not int or not 0 < amount <= captured:
            raise ValueError('Refund amount exceeds original capture')
        immutable = {'payment_id': payment_id, 'amount_paise': amount,
            'captured_paise': captured, 'razorpay_order_id': intent.get('razorpay_order_id'),
            'currency': 'INR', 'customer_id': order['customer_id'], 'payment_intent_id': intent_id,
            'idempotency_key': 'order-refund-' + hashlib.sha256(order_id.encode()).hexdigest()[:40],
            'body': {'amount': amount, 'speed': 'normal', 'notes': {'order_id': order_id, 'reason': 'cancelled_order'}}}
        original = existing.get('request')
        if original and original != immutable:
            raise ValueError('Original refund request changed; reconciliation required')
        quota_ref = doc(QUOTAS, payment_id)
        quota_snap = quota_ref.get(transaction=tx)
        quota = quota_snap.to_dict() or {}
        reserved = quota.get('reserved_paise', 0)
        if type(reserved) is not int or reserved < 0 or reserved > captured:
            raise ValueError('Invalid capture refund quota')
        if quota and (quota.get('payment_intent_id') != intent_id or quota.get('captured_paise') != captured):
            raise ValueError('Capture refund quota metadata mismatch')
        if not original and reserved + amount > captured:
            raise ValueError('Refund reservations exceed captured amount')
        # Every document, including the shared capture quota, was read first.
        if not original:
            tx.set(quota_ref, {'payment_id':payment_id, 'payment_intent_id':intent_id,
                'captured_paise':captured, 'reserved_paise':reserved + amount, 'updated_at':now_iso()})
        tx.set(refund_ref, {**existing, 'order_id':order_id, 'vendor_id':order['vendor_id'], 'requested_by':actor_id,
            'request':immutable, 'status':'processing', 'lease_token':lease_token,
            'started_at':now_iso(), 'created_at':existing.get('created_at') or now_iso(), 'updated_at':now_iso()})
        tx.update(order_ref, {'refund_status':'processing', 'refund_requested_at':order.get('refund_requested_at') or now_iso()})
        return {'request':immutable, 'refund_id':existing.get('refund_id')}

    acquired = acquire(db().transaction())
    if acquired.get('skip'):
        return {'status':acquired['status'], 'refund_id':acquired.get('refund_id')}
    original = acquired['request']
    try:
        client = get_razorpay_client()
        if acquired.get('refund_id'):
            provider_refund = client.refund.fetch(acquired['refund_id'], timeout=30)
        else:
            payment = client.payment.fetch(original['payment_id'], timeout=30)
            expected = {'razorpay_order_id':original['razorpay_order_id'], 'amount_paise':original['captured_paise'], 'currency':'INR'}
            if not captured_payment_matches(expected, payment) or payment.get('id') != original['payment_id']:
                raise ValueError('Provider capture metadata does not match original payment')
            provider_refund = client.payment.refund(original['payment_id'], original['body'],
                headers={'X-Refund-Idempotency':original['idempotency_key']}, timeout=30)
        refund_id = provider_refund.get('id')
        provider_status = provider_refund.get('status')
        if (not isinstance(refund_id,str) or not refund_id.startswith('rfnd_')
            or provider_refund.get('payment_id') != original['payment_id']
            or type(provider_refund.get('amount')) is not int or provider_refund.get('amount') != original['amount_paise']
            or provider_refund.get('currency') != 'INR' or provider_status not in {'pending','processed','failed'}):
            raise ValueError('Provider refund response does not match persisted request')
    except Exception as exc:
        @firestore.transactional
        def retry(tx):
            snap = refund_ref.get(transaction=tx)
            current = snap.to_dict() or {}
            if current.get('lease_token') != lease_token or current.get('status') != 'processing':
                return {'status':current.get('status','requires_review'), 'refund_id':current.get('refund_id')}
            status = 'requires_review' if isinstance(exc, ValueError) else 'retryable'
            tx.update(refund_ref, {'status':status, 'error':'Provider refund could not be confirmed', 'updated_at':now_iso()})
            tx.update(order_ref, {'refund_status':status})
            return {'status':status}
        return retry(db().transaction())

    @firestore.transactional
    def finalize(tx):
        refund_snap = refund_ref.get(transaction=tx)
        order_snap = order_ref.get(transaction=tx)
        current = refund_snap.to_dict() or {}
        order = order_snap.to_dict() or {}
        if current.get('status') == 'completed':
            return {'status':'completed', 'refund_id':current.get('refund_id')}
        if current.get('lease_token') != lease_token or current.get('request') != original:
            return {'status':current.get('status','requires_review'), 'refund_id':current.get('refund_id')}
        status = {'pending':'submitted', 'processed':'completed', 'failed':'requires_review'}[provider_status]
        item_ref = None
        restore = None
        inventory_error = None
        eligible_state = order.get('status') in {'pending','confirmed','cancelled'}
        if status in {'submitted','completed'} and not eligible_state:
            inventory_error = 'Order progressed during refund; fulfillment reconciliation required'
        if (status in {'submitted','completed'} and eligible_state
            and order.get('status') != 'cancelled' and not order.get('refund_stock_restored_at')):
            item_id = order.get('item_id')
            if not isinstance(item_id,str) or not item_id or '/' in item_id:
                inventory_error = 'Original item is invalid; inventory reconciliation required'
            else:
                item_ref = doc(SHOP_ITEMS,item_id)
                item_snap = item_ref.get(transaction=tx)
                item = item_snap.to_dict() or {}
                if not item_snap.exists:
                    inventory_error = 'Original item is missing; inventory reconciliation required'
                elif item.get('stock_quantity') is not None:
                    try:
                        same_base(order, item)
                        restore = _quantity(item['stock_quantity'],allow_zero=True) + _quantity(order.get('quantity'))
                    except ValueError:
                        inventory_error = 'Stock metadata changed; inventory reconciliation required'
        timestamp=now_iso()
        tx.update(refund_ref, {'status':status,'refund_id':refund_id,'provider_status':provider_status,
            'error':None if status != 'requires_review' else 'Provider reports refund failed; reconciliation required', 'updated_at':timestamp})
        updates={'refund_status':status,'refund_id':refund_id,'updated_at':timestamp}
        if inventory_error:
            updates['refund_reconciliation_required'] = inventory_error
        if status in {'submitted','completed'}:
            updates.update({'due_amount':0, 'payment_status':'refunded' if status == 'completed' else 'refund_pending'})
            if eligible_state:
                updates.update({'status':'cancelled','cancelled_at':order.get('cancelled_at') or timestamp})
            if eligible_state and order.get('status') != 'cancelled' and not inventory_error:
                updates['refund_stock_restored_at']=timestamp
        if status == 'completed': updates['refunded_at']=timestamp
        tx.update(order_ref,updates)
        if restore is not None:
            tx.update(item_ref,{'stock_quantity':restore,'is_available':restore > 0 and item.get('disabled_by_admin') is not True,'updated_at':timestamp})
        return {'status':status,'refund_id':refund_id,'amount_paise':original['amount_paise'],
            **({'reconciliation_required':inventory_error} if inventory_error else {})}
    return finalize(db().transaction())


@order_refunds_bp.post('/vendors/orders/<order_id>/refund')
@require_role('vendor')
def request_order_refund(order_id):
    payload=request.get_json(silent=True)
    if payload is not None and (not isinstance(payload,dict) or payload):
        return jsonify({'detail':'Refund amount and payment details are determined by the server; send an empty object'}),422
    try:
        result=refund_order(order_id,g.user_id)
        status={'completed':200,'submitted':202,'processing':202,'pending':202,'retryable':503,'requires_review':409}[result['status']]
        return jsonify({'success':result['status'] in {'submitted','completed'},'refund':result}),status
    except PermissionError as exc:
        return jsonify({'detail':str(exc)}),403
    except ValueError as exc:
        return jsonify({'detail':str(exc)}),409
