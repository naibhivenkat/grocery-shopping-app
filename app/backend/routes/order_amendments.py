"""Customer-approved, revisioned order changes and durable adjustment refunds.

Money remains integer paise. Provider operations run only after committed jobs;
refund reservations share the original payment's global quota.
"""
import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone

from firebase_admin import firestore
from flask import Blueprint, g, jsonify, request
from google.cloud.firestore_v1.base_query import FieldFilter

from auth_utils import require_auth, require_role
from db import CUSTOMER_ORDERS, KHATA_LEDGERS, KHATA_TRANSACTIONS, NOTIFICATIONS, SHOP_ITEMS, USERS, col, db, doc, now_iso, to_dict
from notification_delivery import notification_data, deliver_push
from routes.khata import KhataError, _khata_error, _identifier, _money_paise, _payload, _text, _MAX_PAISE, _parties_txn
from routes.measurement import metadata, explicit, acknowledge, line_paise, quantity_label, same_base
from routes.discounts import allocate, rules
from decimal import Decimal, ROUND_HALF_UP

order_amendments_bp = Blueprint('order_amendments', __name__)
order_amendments_bp.register_error_handler(KhataError, _khata_error)
AMENDMENTS = 'order_amendments'
REFUNDS = 'order_amendment_refunds'
QUOTAS = 'payment_refund_quotas'
OPEN = {'pending', 'awaiting_payment'}
ACTIVE = {'pending', 'confirmed', 'packed'}


def _expired(proposal):
    try:
        return datetime.fromisoformat(proposal['expires_at']) <= datetime.now(timezone.utc)
    except (KeyError, ValueError, TypeError):
        return True


def _integer(value, label, zero=False):
    if type(value) is not int or not (0 if zero else 1) <= value <= 10000000:
        raise KhataError(f'{label} must be a canonical integer up to 10000000')
    return value


def _revision(value):
    if type(value) is not int or value < 0:
        raise KhataError('A nonnegative pricing revision is required')
    return value


def _load_group(tx, anchor):
    anchor_ref = doc(CUSTOMER_ORDERS, _identifier(anchor, 'order_id'))
    snapshot = anchor_ref.get(transaction=tx)
    if not snapshot.exists:
        raise KhataError('Order not found', 404)
    order = snapshot.to_dict() or {}
    batch_id = order.get('batch_id')
    rows = list(tx.get(col(CUSTOMER_ORDERS).where(filter=FieldFilter('batch_id', '==', batch_id)))) if batch_id else [snapshot]
    if not rows or len(rows) > 1000:
        raise KhataError('Order group requires reconciliation', 409)
    for row in rows:
        data = row.to_dict() or {}
        if (data.get('customer_id'), data.get('vendor_id')) != (order.get('customer_id'), order.get('vendor_id')):
            raise KhataError('Order group contains inconsistent parties', 409)
    batch_ref = doc('order_batches', batch_id or 'single_' + anchor)
    batch_snap = batch_ref.get(transaction=tx)
    batch = batch_snap.to_dict() or {}
    active = [row for row in rows if (row.to_dict() or {}).get('status') not in {'removed', 'cancelled', 'rejected'}]
    if len(active) > 100:
        raise KhataError('Order exceeds the supported active line limit', 409)
    revision = _revision(batch.get('pricing_revision', 0))
    if any((row.to_dict() or {}).get('pricing_revision', 0) != revision for row in active):
        raise KhataError('Order revisions require reconciliation', 409)
    return {'anchor': anchor, 'order': order, 'rows': rows, 'active': active, 'batch': batch,
            'batch_ref': batch_ref, 'batch_id': batch_ref.id, 'revision': revision,
            'customer_id': order.get('customer_id'), 'vendor_id': order.get('vendor_id')}


def _ensure_actor(tx, ctx, owner):
    if g.user_id != ctx[owner + '_id']:
        raise KhataError('This order belongs to another account', 403)
    _parties_txn(tx, ctx['vendor_id'], ctx['customer_id'])


def guard_order_mutation(tx, order, *, lookup=None):
    """Call before legacy order writes; blocks proposal/payment/refund races."""
    lookup = lookup or doc
    current = order.get('current_amendment_id') or order.get('pending_amendment_id')
    if current:
        proposal = lookup(AMENDMENTS, current).get(transaction=tx)
        if proposal.exists and (proposal.to_dict() or {}).get('status') in OPEN:
            raise KhataError('Resolve or refresh the pending order amendment first', 409)
    batch_id = order.get('batch_id')
    if not batch_id:
        return
    snap = lookup('order_batches', batch_id).get(transaction=tx)
    batch = snap.to_dict() or {}
    if batch.get('payment_review_required'):
        raise KhataError('An amendment payment needs reconciliation before changing this order', 409)
    identifier = batch.get('active_amendment_id')
    if identifier:
        proposal = lookup(AMENDMENTS, identifier).get(transaction=tx)
        if proposal.exists and (proposal.to_dict() or {}).get('status') in OPEN:
            raise KhataError('Resolve or refresh the pending order amendment first', 409)


def _current_lines(ctx):
    result = []
    for row in ctx['active']:
        data = row.to_dict() or {}
        result.append({**data, 'uid': row.id, 'line_id': row.id,
                       'quantity_unit': metadata(data)['stock_unit'], 'quantity_label': quantity_label(data.get('quantity', 1), data),
                       'total': data.get('total_price', 0)})
    return result


def _financials(tx, ctx):
    method = ctx['order'].get('payment_method')
    if method not in {'cash', 'khata', 'razorpay', 'upi'}:
        raise KhataError('This order payment method needs reconciliation', 409)
    result = {'method': method, 'captures': [], 'funded': 0}
    if method == 'cash':
        received = ctx['batch'].get('cash_received_paise')
        if received is None:
            received = sum(_money_paise((row.to_dict() or {}).get('partial_amount_paid', 0), allow_zero=True) for row in ctx['rows'])
        reserved = ctx['batch'].get('cash_refund_reserved_paise', 0)
        if type(received) is not int or type(reserved) is not int or not 0 <= reserved <= received <= _MAX_PAISE:
            raise KhataError('Cash receipts require reconciliation', 409)
        result.update({'received': received, 'reserved': reserved, 'funded': received - reserved})
    elif method in {'razorpay', 'upi'}:
        intent_ids = set(ctx['batch'].get('capture_intent_ids') or [])
        intent_ids.update((row.to_dict() or {}).get('payment_intent_id') for row in ctx['rows'] if (row.to_dict() or {}).get('payment_intent_id'))
        for identifier in sorted(intent_ids):
            _identifier(identifier, 'payment_intent_id')
            snap = doc('payment_orders', identifier).get(transaction=tx)
            intent = snap.to_dict() or {}
            if not snap.exists or intent.get('user_id') != ctx['customer_id']:
                raise KhataError('Original payment requires reconciliation', 409)
            if intent.get('status') != 'paid':
                if intent.get('status') != 'creation_failed':
                    raise KhataError('Reconcile the existing checkout before changing the order', 409)
                continue
            if intent.get('settlement_status', 'settled') != 'settled' or intent.get('currency') != 'INR':
                raise KhataError('Captured payment requires reconciliation', 409)
            if intent.get('purpose') == 'order':
                targets = intent.get('target_ids') or [intent.get('reference_id')]
                if not targets or not set(targets).issubset({row.id for row in ctx['rows']}):
                    raise KhataError('Capture does not belong to this entire shop order', 409)
            elif intent.get('purpose') == 'order_amendment':
                prior = doc(AMENDMENTS, _identifier(intent.get('reference_id'), 'reference_id')).get(transaction=tx)
                prior_data = prior.to_dict() or {}
                if not prior.exists or prior_data.get('batch_id') != ctx['batch_id'] or prior_data.get('status') != 'applied':
                    raise KhataError('Additional capture requires reconciliation', 409)
            else:
                raise KhataError('Unexpected payment purpose', 409)
            amount = intent.get('amount_paise')
            payment_id = intent.get('payment_id')
            if type(amount) is not int or not 0 < amount <= _MAX_PAISE or not isinstance(payment_id, str) or not payment_id.startswith('pay_') or '/' in payment_id:
                raise KhataError('Invalid captured payment metadata', 409)
            if any(capture['payment_id'] == payment_id for capture in result['captures']):
                raise KhataError('Duplicate capture references require reconciliation', 409)
            quota_ref = doc(QUOTAS, payment_id)
            quota_snap = quota_ref.get(transaction=tx)
            quota = quota_snap.to_dict() or {}
            reserved = quota.get('reserved_paise', 0)
            if (type(reserved) is not int or not 0 <= reserved <= amount
                    or (quota and (quota.get('payment_intent_id') != identifier or quota.get('captured_paise') != amount))):
                raise KhataError('Capture refund quota requires reconciliation', 409)
            result['captures'].append({'intent_id': identifier, 'payment_id': payment_id, 'captured_paise': amount,
                                       'reserved_paise': reserved, 'quota_ref': quota_ref,
                                       'razorpay_order_id': intent.get('razorpay_order_id')})
            result['funded'] += amount - reserved
        if result['funded'] > _MAX_PAISE:
            raise KhataError('Captured order balance exceeds the supported limit', 409)
        old_total = sum(_money_paise((row.to_dict() or {}).get('total_price', 0), allow_zero=True) for row in ctx['active'])
        if old_total and not intent_ids and any((row.to_dict() or {}).get('payment_status') == 'paid' for row in ctx['active']):
            raise KhataError('Captured payment is missing; reconciliation required', 409)
    return result


def _frozen_discount(ctx, lines):
    original = _current_lines(ctx)
    first = original[0] if original else {}
    monetary = [(line['item_id'], line['gross_paise']) for line in lines]
    if ctx['batch'].get('discount_source') == 'manual' or any(line.get('discount_source') == 'manual' for line in original):
        amount = ctx['batch'].get('manual_discount_paise', sum(_money_paise(line.get('discount_amount', 0), allow_zero=True) for line in original))
        if type(amount) is not int or amount < 0:
            raise KhataError('Manual discount requires reconciliation', 409)
        amount = min(amount, sum(value for _, value in monetary))
        return allocate(monetary, amount), {'promotion_id': None, 'promotion_revision': None, 'promotion_rules': None,
                                            'discount_source': 'manual', 'manual_discount_paise': amount}
    frozen = first.get('promotion_rules')
    snapshot = {key: first.get(key) for key in ('promotion_id', 'promotion_revision', 'promotion_rules')}
    if not frozen or not first.get('promotion_id'):
        return {}, snapshot
    normalized = rules(frozen)
    eligible = monetary if frozen.get('target_type') == 'shop' else [line for line in monetary if line[0] == frozen.get('product_id')]
    gross = sum(value for _, value in eligible)
    if gross < _money_paise(normalized['minimum_order_amount'], allow_zero=True):
        return {}, snapshot
    if normalized['discount_type'] == 'percentage':
        amount = int((Decimal(gross) * Decimal(str(normalized['discount_value'])) / 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    elif normalized['discount_type'] == 'fixed':
        amount = _money_paise(normalized['discount_value'])
    else:
        amount = 0
    if normalized['maximum_discount_amount'] is not None:
        amount = min(amount, _money_paise(normalized['maximum_discount_amount']))
    return allocate(eligible, min(amount, gross)), snapshot


def _proposed_lines(tx, ctx, desired):
    if not isinstance(desired, list) or len(desired) > 100:
        raise KhataError('lines must contain at most 100 desired products')
    old = {line['item_id']: line for line in _current_lines(ctx)}
    seen, lines, removed_flags = set(), [], {}
    for entry in desired:
        if not isinstance(entry, dict) or set(entry) - {'item_id', 'quantity', 'quantity_unit', 'restock_removed'}:
            raise KhataError('Each line requires item_id, canonical quantity and quantity_unit')
        identifier = _identifier(entry.get('item_id'), 'item_id')
        if identifier in seen:
            raise KhataError('Each desired product must be unique')
        seen.add(identifier)
        quantity = _integer(entry.get('quantity'), 'quantity', zero=True)
        restock = entry.get('restock_removed', False)
        if type(restock) is not bool:
            raise KhataError('restock_removed must be boolean')
        removed_flags[identifier] = restock
        original = old.get(identifier)
        if not quantity and original is None:
            raise KhataError('A new product cannot have zero quantity')
        product_snap = doc(SHOP_ITEMS, identifier).get(transaction=tx)
        product = product_snap.to_dict() or {}
        if product_snap.exists and product.get('vendor_id') != ctx['vendor_id']:
            raise KhataError('Only products from this shop may be included', 403)
        basis = original if original else product
        acknowledge(basis, entry.get('quantity_unit'))
        if original and product_snap.exists:
            same_base(original, product)
        increase = quantity > (original or {}).get('quantity', 0)
        if increase and (not product_snap.exists or product.get('is_available') is False or product.get('disabled_by_admin')):
            raise KhataError('New or increased product quantity is unavailable', 409)
        if not quantity:
            continue
        price = _money_paise(basis.get('item_selling_price', basis.get('item_unit_price')) if original else product.get('price'))
        gross = line_paise(price, quantity, basis)
        units = metadata(basis)
        line_id = original['uid'] if original else col(CUSTOMER_ORDERS).document().id
        data = {key: value for key, value in (original or {}).items() if key not in {'uid', 'line_id', 'total', 'quantity_label'}}
        data.update({'uid': line_id, 'line_id': line_id, 'item_id': identifier, 'item_name': basis.get('item_name') or product.get('name') or 'Product',
                     'item_description': basis.get('item_description') or product.get('description'),
                     'item_image_urls': basis.get('item_image_urls') or product.get('image_urls') or [],
                     'quantity': quantity, 'quantity_unit': units['stock_unit'], 'quantity_label': quantity_label(quantity, basis),
                     **units, 'item_selling_price': price / 100, 'item_unit_price': price / (100 * units['pricing_quantity']),
                     'gross_paise': gross, 'restock_removed': restock})
        lines.append(data)
    shares, discount_snapshot = _frozen_discount(ctx, lines)
    for line in lines:
        share = shares.get(line['item_id'], 0)
        net = line['gross_paise'] - share
        line.update({'subtotal': line['gross_paise'] / 100, 'discount_amount': share / 100,
                     'total_price': net / 100, 'total': net / 100, 'total_paise': net, **discount_snapshot})
    return lines, removed_flags


def _notice(tx, recipient, kind, title, proposal_id, anchor):
    event = notification_data(recipient, kind, title, 'Review the updated order details.', anchor)
    event['amendment_id'] = proposal_id
    tx.set(col(NOTIFICATIONS).document(), event)
    return event


def _hold_writes(tx, ctx, identifier):
    for row in ctx['active']:
        # Bind legacy single-line orders to the same durable batch that holds
        # their payment review fence, including after proposal markers clear.
        tx.update(row.reference, {'batch_id': ctx['batch_id'],
                                  'amendment_pending': bool(identifier), 'current_amendment_id': identifier,
                                  'pending_amendment_id': identifier, 'updated_at': now_iso()})
    tx.set(ctx['batch_ref'], {'active_amendment_id': identifier, 'pricing_revision': ctx['revision'],
                               'updated_at': now_iso()}, merge=True)


def _inventory_plan(tx, ctx, proposal, reserve_only=False, releasing=False):
    old = {line['item_id']: line for line in proposal['original_lines']}
    desired = {line['item_id']: line for line in proposal['lines']}
    writes, reservations = [], []
    if proposal.get('stock_reserved') and not releasing:
        for reservation in proposal.get('reserved_stock', []):
            snapshot = doc(SHOP_ITEMS, reservation['item_id']).get(transaction=tx)
            product = snapshot.to_dict() or {}
            if not snapshot.exists or product.get('vendor_id') != ctx['vendor_id']:
                raise KhataError('Reserved product is missing; inventory reconciliation required', 409)
            same_base(desired[reservation['item_id']], product)
    identifiers = sorted(set(old) | set(desired))
    for identifier in identifiers:
        before = old.get(identifier, {}).get('quantity', 0)
        after = desired.get(identifier, {}).get('quantity', 0)
        extra = max(after - before, 0)
        returned = max(before - after, 0) if proposal.get('restock_removed', {}).get(identifier, False) else 0
        if releasing:
            returned = next((line['quantity'] for line in proposal.get('reserved_stock', []) if line['item_id'] == identifier and line.get('tracked')), 0)
            extra = 0
        elif proposal.get('stock_reserved'):
            extra = 0
        if reserve_only:
            returned = 0
        if not extra and not returned:
            continue
        ref = doc(SHOP_ITEMS, identifier)
        snap = ref.get(transaction=tx)
        product = snap.to_dict() or {}
        if not snap.exists or product.get('vendor_id') != ctx['vendor_id']:
            raise KhataError('Inventory requires shop owner reconciliation', 409)
        same_base(desired.get(identifier) or old[identifier], product)
        if extra and (product.get('is_available') is False or product.get('disabled_by_admin')):
            raise KhataError('Increased quantity is unavailable', 409)
        stock = product.get('stock_quantity')
        if stock is None:
            if extra:
                reservations.append({'item_id': identifier, 'quantity': extra, 'tracked': False})
            continue
        stock = _integer(stock, 'stock_quantity', zero=True)
        updated = stock - extra + returned
        if not 0 <= updated <= 10000000:
            raise KhataError('Insufficient stock or invalid restock amount', 409)
        writes.append((ref, {'stock_quantity': updated, 'is_available': updated > 0 and product.get('disabled_by_admin') is not True,
                             'updated_at': now_iso()}))
        if extra:
            reservations.append({'item_id': identifier, 'quantity': extra, 'tracked': True})
    return writes, reservations


def _ledger_plan(tx, ctx, delta, proposal_id):
    ledgers = {line.get('khata_ledger_id') for line in _current_lines(ctx) if line.get('khata_ledger_id')}
    if len(ledgers) != 1:
        raise KhataError('The original Khata ledger needs reconciliation', 409)
    ref = doc(KHATA_LEDGERS, next(iter(ledgers)))
    snap = ref.get(transaction=tx)
    ledger = snap.to_dict() or {}
    if not snap.exists or (ledger.get('vendor_id'), ledger.get('customer_id')) != (ctx['vendor_id'], ctx['customer_id']):
        raise KhataError('Khata ledger parties require reconciliation', 409)
    balance = _money_paise(ledger.get('balance', 0), allow_zero=True)
    updated = balance + delta
    repayment = max(-updated, 0)
    updated = max(updated, 0)
    if updated > _MAX_PAISE:
        raise KhataError('Khata balance exceeds the supported limit', 409)
    pending = list(tx.get(col(KHATA_TRANSACTIONS).where(filter=FieldFilter('ledger_id', '==', ref.id))))
    pending_total = sum(_money_paise((row.to_dict() or {}).get('amount')) for row in pending if (row.to_dict() or {}).get('status') == 'pending')
    if pending_total > updated:
        raise KhataError('Review pending Khata payments before accepting this adjustment', 409)
    amount = abs(updated - balance)
    entry = {'ledger_id': ref.id, 'vendor_id': ctx['vendor_id'], 'customer_id': ctx['customer_id'],
             'type': 'credit' if delta > 0 else 'debit', 'amount': amount / 100, 'status': 'confirmed',
             'recorded_by': ctx['customer_id'], 'order_id': ctx['anchor'], 'batch_id': ctx['batch_id'],
             'amendment_id': proposal_id, 'description': 'Customer-approved order adjustment', 'created_at': now_iso()}
    return {'ref': ref, 'updates': {'balance': updated / 100, 'status': 'active', 'updated_at': now_iso()},
            'entry': entry if amount else None, 'repayment': repayment}


def _refund_plan(financials, amount, proposal_id, ctx):
    plans, remaining = [], amount
    for capture in financials['captures']:
        available = capture['captured_paise'] - capture['reserved_paise']
        portion = min(remaining, available)
        if not portion:
            continue
        job_id = hashlib.sha256(f'{proposal_id}:{capture["intent_id"]}'.encode()).hexdigest()
        plans.append({'ref': doc(REFUNDS, job_id), 'capture': capture, 'amount': portion,
                      'data': {'amendment_id': proposal_id, 'batch_id': ctx['batch_id'], 'vendor_id': ctx['vendor_id'],
                               'customer_id': ctx['customer_id'], 'status': 'pending', 'amount_paise': portion,
                               'payment_id': capture['payment_id'], 'payment_intent_id': capture['intent_id'],
                               'captured_paise': capture['captured_paise'], 'razorpay_order_id': capture['razorpay_order_id'],
                               'idempotency_key': 'amendment-refund-' + job_id[:40], 'created_at': now_iso()}})
        remaining -= portion
    if remaining:
        raise KhataError('Refund exceeds original captures; reconciliation required', 409)
    return plans


def _apply(tx, ctx, proposal_id, proposal, financials, inventory_writes, ledger_plan=None, captured_intent=None):
    """Writes only: every inventory, payment, quota and ledger read precedes this."""
    old_total = _money_paise(proposal['old_total'], allow_zero=True)
    new_total = _money_paise(proposal['new_total'], allow_zero=True)
    method = financials['method']
    funded = financials['funded']
    refund_amount = max(funded - new_total, 0) if method in {'razorpay', 'upi'} else 0
    jobs = _refund_plan(financials, refund_amount, proposal_id, ctx)
    estimated_writes = len(ctx['active']) + len(proposal['lines']) + len(inventory_writes) + 2 * len(jobs) + 6
    if estimated_writes > 450:
        raise KhataError('Split this change into smaller revisions to stay within transaction limits', 409)
    manual = max(funded - new_total, 0) if method == 'cash' else (ledger_plan or {}).get('repayment', 0)
    due = max(new_total - funded, 0) if method == 'cash' else (min(new_total, _money_paise(ledger_plan['updates']['balance'], allow_zero=True)) if method == 'khata' else 0)
    revision = ctx['revision'] + 1
    lines = proposal['lines']
    paid_shares = allocate([(line['line_id'], line['total_paise']) for line in lines], min(funded, new_total)) if method != 'khata' else {}
    khata_due = allocate([(line['line_id'], line['total_paise']) for line in lines], due) if method == 'khata' else {}
    desired_ids = {line['line_id'] for line in lines}
    timestamp = now_iso()
    original_map = {row.id: row.to_dict() or {} for row in ctx['rows']}
    for row in ctx['active']:
        if row.id not in desired_ids:
            tx.update(row.reference, {'status': 'removed', 'quantity_before_removal': (row.to_dict() or {}).get('quantity'),
                                     'quantity': 0, 'total_price': 0, 'total_paise': 0, 'due_amount': 0,
                                     'partial_amount_paid': 0, 'pricing_revision': revision, 'amendment_pending': False,
                                     'current_amendment_id': None, 'pending_amendment_id': None, 'updated_at': timestamp})
    for line in lines:
        data = {key: value for key, value in line.items() if key not in {'uid', 'line_id', 'total', 'gross_paise', 'restock_removed'}}
        existing = original_map.get(line['line_id'], {})
        net = line['total_paise']
        paid = paid_shares.get(line['line_id'], 0)
        status = existing.get('status', 'pending')
        data.update({'vendor_id': ctx['vendor_id'], 'customer_id': ctx['customer_id'], 'batch_id': ctx['order'].get('batch_id') or ctx['batch_id'],
                     'vendor_name': ctx['order'].get('vendor_name'), 'customer_name': ctx['order'].get('customer_name'),
                     **{key: ctx['order'].get(key) for key in ('vendor_owner_name', 'vendor_phone', 'vendor_email', 'vendor_shop_description')},
                     'payment_method': ctx['order'].get('payment_method'), 'payment_exempt': net == 0,
                     'payment_status': 'paid' if method in {'razorpay', 'upi'} or (method == 'cash' and due == 0) or net == 0 else 'pending',
                     'partial_amount_paid': paid / 100 if method != 'khata' else 0,
                     'due_amount': khata_due.get(line['line_id'], 0) / 100 if method == 'khata' else (net - paid) / 100,
                     'pricing_revision': revision, 'amendment_pending': False, 'current_amendment_id': None,
                     'pending_amendment_id': None, 'status': status, 'created_at': existing.get('created_at') or timestamp,
                     'updated_at': timestamp, 'last_amendment_id': proposal_id,
                     'adjustment_refund_amount': refund_amount / 100})
        if method == 'khata':
            data['khata_ledger_id'] = ledger_plan['ref'].id
        tx.set(doc(CUSTOMER_ORDERS, line['line_id']), data)
    for ref, data in inventory_writes:
        tx.update(ref, data)
    if ledger_plan:
        tx.update(ledger_plan['ref'], ledger_plan['updates'])
        if ledger_plan['entry']:
            tx.set(doc(KHATA_TRANSACTIONS, 'amendment_' + proposal_id), ledger_plan['entry'])
    for job in jobs:
        capture = job['capture']
        tx.set(capture['quota_ref'], {'payment_id': capture['payment_id'], 'payment_intent_id': capture['intent_id'],
                                      'captured_paise': capture['captured_paise'], 'reserved_paise': capture['reserved_paise'] + job['amount'],
                                      'updated_at': timestamp})
        tx.set(job['ref'], job['data'])
    response = {**ctx['batch'].get('response', {}), 'batch_id': ctx['batch_id'], 'order_ids': [line['line_id'] for line in lines],
                'order_id': lines[-1]['line_id'] if lines else ctx['anchor'], 'uid': lines[-1]['line_id'] if lines else ctx['anchor'],
                'count': len(lines), 'total_price': new_total / 100, 'payment_exempt': new_total == 0}
    batch_changes = {'pricing_revision': revision, 'active_amendment_id': None, 'response': response,
                     'capture_intent_ids': sorted({capture['intent_id'] for capture in financials['captures']}), 'updated_at': timestamp}
    if captured_intent:
        batch_changes['capture_intent_ids'] = sorted(set(batch_changes['capture_intent_ids']) | {captured_intent})
    if method == 'cash':
        batch_changes.update({'cash_received_paise': financials['received'],
                              'cash_refund_reserved_paise': financials['reserved'] + manual})
    tx.set(ctx['batch_ref'], batch_changes, merge=True)
    changes = {'status': 'applied', 'accepted_by': proposal.get('accepted_by') or ctx['customer_id'],
               'accepted_at': proposal.get('accepted_at') or timestamp, 'applied_revision': revision, 'applied_at': timestamp, 'updated_at': timestamp,
               'refund_due': (refund_amount + manual) / 100, 'refund_status': 'pending' if jobs else 'none',
               'refund_method': 'original_payment' if jobs else ('manual' if manual else None),
               'refund_job_ids': [job['ref'].id for job in jobs], 'cash_refund_amount': manual / 100,
               'cash_refund_status': 'pending' if manual else 'none', 'amount_due': due / 100,
               'stock_reserved': False}
    tx.set(doc(AMENDMENTS, proposal_id), changes, merge=True)
    event = _notice(tx, ctx['vendor_id'], 'order_amendment_applied', 'Order changes accepted', proposal_id, ctx['anchor'])
    return {**proposal, **changes, 'uid': proposal_id}, event


@order_amendments_bp.post('/vendors/orders/<anchor>/amendments')
@require_role('vendor')
def propose(anchor):
    cleanup_expired(anchor)
    payload = _payload()
    if set(payload) - {'revision', 'reason', 'lines'}:
        raise KhataError('Supply revision, reason and desired lines only')
    revision = _revision(payload.get('revision', 0))
    reason = _text(payload.get('reason'), 'reason', 1000)
    if not reason:
        raise KhataError('A reason is required')
    key = request.headers.get('Idempotency-Key')
    if not isinstance(key, str) or not 8 <= len(key) <= 128:
        raise KhataError('Idempotency-Key must contain 8 to 128 characters')
    fingerprint = hashlib.sha256(json.dumps({'anchor': anchor, **payload}, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    identifier = hashlib.sha256(f'{g.user_id}:{key}'.encode()).hexdigest()
    ref = doc(AMENDMENTS, identifier)

    @firestore.transactional
    def create(tx):
        previous = ref.get(transaction=tx)
        ctx = _load_group(tx, anchor)
        _ensure_actor(tx, ctx, 'vendor')
        if previous.exists:
            data = previous.to_dict() or {}
            if data.get('fingerprint') != fingerprint:
                raise KhataError('Idempotency key already belongs to another modification', 409)
            return {**data, 'uid': identifier}, None, 200
        guard_order_mutation(tx, ctx['order'])
        if ctx['revision'] != revision:
            raise KhataError('Order changed; refresh its pricing revision', 409)
        if not ctx['active'] or any((row.to_dict() or {}).get('status') not in ACTIVE for row in ctx['active']):
            raise KhataError('Only orders before delivery may be modified', 409)
        if any((row.to_dict() or {}).get('refund_status') for row in ctx['active']):
            raise KhataError('Resolve the existing cancellation refund first', 409)
        lines, restock = _proposed_lines(tx, ctx, payload.get('lines'))
        finances = _financials(tx, ctx)
        old = sum(_money_paise(line.get('total_price', 0), allow_zero=True) for line in _current_lines(ctx))
        new = sum(line['total_paise'] for line in lines)
        if new > _MAX_PAISE:
            raise KhataError('Revised total exceeds supported limit')
        due = max(new - finances['funded'], 0) if finances['method'] != 'khata' else max(new - old, 0)
        refund = max(finances['funded'] - new, 0) if finances['method'] != 'khata' else 0
        ledger_preview = _ledger_plan(tx, ctx, new - old, identifier) if finances['method'] == 'khata' else None
        if ledger_preview:
            refund = ledger_preview['repayment']
            due = min(new, _money_paise(ledger_preview['updates']['balance'], allow_zero=True))
        timestamp = now_iso()
        data = {'anchor_order_id': anchor, 'batch_id': ctx['batch_id'], 'vendor_id': ctx['vendor_id'], 'customer_id': ctx['customer_id'],
                'revision': revision, 'status': 'pending', 'reason': reason, 'idempotency_key': key, 'fingerprint': fingerprint,
                'created_at': timestamp, 'updated_at': timestamp, 'expires_at': (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(),
                'old_total': old / 100, 'new_total': new / 100, 'amount_due': due / 100, 'refund_due': refund / 100,
                'refund_method': 'manual' if refund and finances['method'] in {'cash', 'khata'} else ('original_payment' if refund else None),
                'refund_status': 'none', 'cash_refund_amount': refund / 100 if finances['method'] in {'cash', 'khata'} else 0, 'cash_refund_status': 'none',
                'lines': lines, 'original_lines': _current_lines(ctx), 'restock_removed': restock, 'stock_reserved': False}
        tx.set(ref, data)
        _hold_writes(tx, ctx, identifier)
        event = _notice(tx, ctx['customer_id'], 'order_amendment_proposed', 'Order changes need your approval', identifier, anchor)
        return {**data, 'uid': identifier}, event, 201
    body, event, status = create(db().transaction())
    deliver_push(event, lookup=doc)
    return jsonify(body), status


def _release(identifier, actor=None, status='expired'):
    ref = doc(AMENDMENTS, identifier)
    @firestore.transactional
    def release(tx):
        snap = ref.get(transaction=tx)
        if not snap.exists:
            raise KhataError('Amendment not found', 404)
        proposal = snap.to_dict() or {}
        ctx = _load_group(tx, proposal['anchor_order_id'])
        if actor:
            _ensure_actor(tx, ctx, actor)
        if proposal.get('status') == status:
            return {**proposal, 'uid': identifier}, None
        if proposal.get('status') not in OPEN:
            raise KhataError('This amendment is no longer open', 409)
        if status == 'expired' and not _expired(proposal):
            return {**proposal, 'uid': identifier}, None
        writes, _ = _inventory_plan(tx, ctx, proposal, releasing=True) if proposal.get('stock_reserved') else ([], [])
        for stock_ref, changes in writes:
            tx.update(stock_ref, changes)
        changes = {'status': status, 'stock_reserved': False, 'updated_at': now_iso()}
        tx.set(ref, changes, merge=True)
        _hold_writes(tx, ctx, None)
        if proposal.get('payment_intent_id'):
            tx.set(ctx['batch_ref'], {'payment_review_required': True, 'review_amendment_id': identifier}, merge=True)
        recipient = ctx['customer_id'] if actor == 'vendor' else ctx['vendor_id']
        event = _notice(tx, recipient, 'order_amendment_' + status, 'Order amendment ' + status, identifier, ctx['anchor'])
        return {**proposal, **changes, 'uid': identifier}, event
    body, event = release(db().transaction())
    deliver_push(event, lookup=doc)
    return body


def cleanup_expired(anchor):
    snapshot = doc(CUSTOMER_ORDERS, _identifier(anchor, 'order_id')).get()
    if not snapshot.exists:
        return
    order = snapshot.to_dict() or {}
    if g.user_id not in {order.get('vendor_id'), order.get('customer_id')}:
        raise KhataError('This order belongs to another account', 403)
    batch = doc('order_batches', order.get('batch_id') or 'single_' + anchor).get()
    identifier = (batch.to_dict() or {}).get('active_amendment_id')
    if identifier:
        proposal = doc(AMENDMENTS, identifier).get()
        data = proposal.to_dict() or {}
        if proposal.exists and data.get('status') in OPEN and _expired(data):
            _release(identifier)


@order_amendments_bp.get('/orders/<anchor>/amendments')
@require_auth
def history(anchor):
    snap = doc(CUSTOMER_ORDERS, _identifier(anchor, 'order_id')).get()
    if not snap.exists:
        raise KhataError('Order not found', 404)
    order = snap.to_dict() or {}
    if g.user_id not in {order.get('vendor_id'), order.get('customer_id')}:
        raise KhataError('This order belongs to another account', 403)
    cleanup_expired(anchor)
    batch_id = order.get('batch_id') or 'single_' + anchor
    result = [to_dict(row) for row in col(AMENDMENTS).where(filter=FieldFilter('batch_id', '==', batch_id)).stream()]
    if any((row.get('vendor_id'), row.get('customer_id')) != (order.get('vendor_id'), order.get('customer_id')) for row in result):
        raise KhataError('Amendment parties require reconciliation', 409)
    result.sort(key=lambda row: row.get('created_at', ''), reverse=True)
    return jsonify(result)


@order_amendments_bp.get('/order-amendments/<identifier>')
@require_auth
def get_amendment(identifier):
    ref = doc(AMENDMENTS, _identifier(identifier, 'amendment_id'))
    snap = ref.get()
    proposal = snap.to_dict() or {}
    if not snap.exists:
        raise KhataError('Amendment not found', 404)
    if g.user_id not in {proposal.get('vendor_id'), proposal.get('customer_id')}:
        raise KhataError('This amendment belongs to another account', 403)
    cleanup_expired(proposal['anchor_order_id'])
    return jsonify(to_dict(ref.get()))


@order_amendments_bp.post('/order-amendments/<identifier>/withdraw')
@require_role('vendor')
def withdraw(identifier):
    return jsonify(_release(_identifier(identifier, 'amendment_id'), 'vendor', 'withdrawn'))


@order_amendments_bp.post('/order-amendments/<identifier>/decision')
@require_auth
def decide(identifier):
    payload = _payload()
    if set(payload) - {'decision', 'revision'} or (not isinstance(payload.get('decision'), str) or payload.get('decision') not in {'accepted', 'rejected'}):
        raise KhataError('Choose accepted or rejected and the reviewed revision')
    revision = _revision(payload.get('revision'))
    ref = doc(AMENDMENTS, _identifier(identifier, 'amendment_id'))
    snapshot = ref.get()
    if not snapshot.exists:
        raise KhataError('Amendment not found', 404)
    preview = snapshot.to_dict() or {}
    if g.user_id != preview.get('customer_id'):
        raise KhataError('Only the order customer can decide', 403)
    if preview.get('revision') != revision:
        raise KhataError('Amendment revision changed', 409)
    cleanup_expired(preview['anchor_order_id'])
    if payload['decision'] == 'rejected':
        return jsonify(_release(identifier, 'customer', 'rejected'))

    @firestore.transactional
    def accept(tx):
        snap = ref.get(transaction=tx)
        proposal = snap.to_dict() or {}
        ctx = _load_group(tx, proposal['anchor_order_id'])
        _ensure_actor(tx, ctx, 'customer')
        if proposal.get('revision') != revision:
            raise KhataError('Amendment revision changed', 409)
        if proposal.get('status') in {'applied', 'awaiting_payment'}:
            return {**proposal, 'uid': identifier}, None
        if proposal.get('status') != 'pending' or _expired(proposal):
            raise KhataError('Amendment expired or is no longer pending', 409)
        if ctx['revision'] != revision or ctx['batch'].get('active_amendment_id') != identifier:
            raise KhataError('Order changed; request a new proposal', 409)
        if any((row.to_dict() or {}).get('status') not in ACTIVE for row in ctx['active']):
            raise KhataError('Order progressed; reconciliation required', 409)
        finances = _financials(tx, ctx)
        new = _money_paise(proposal['new_total'], allow_zero=True)
        extra = max(new - finances['funded'], 0) if finances['method'] in {'razorpay', 'upi'} else 0
        inventory_writes, reservations = _inventory_plan(tx, ctx, proposal, reserve_only=extra > 0)
        if extra:
            for stock_ref, changes in inventory_writes:
                tx.update(stock_ref, changes)
            changes = {'status': 'awaiting_payment', 'amount_due': extra / 100, 'accepted_at': now_iso(),
                       'accepted_by': g.user_id, 'stock_reserved': True, 'reserved_stock': reservations, 'updated_at': now_iso()}
            tx.set(ref, changes, merge=True)
            event = _notice(tx, ctx['vendor_id'], 'order_amendment_awaiting_payment', 'Order changes await additional payment', identifier, ctx['anchor'])
            return {**proposal, **changes, 'uid': identifier}, event
        delta = new - _money_paise(proposal['old_total'], allow_zero=True)
        ledger = _ledger_plan(tx, ctx, delta, identifier) if finances['method'] == 'khata' else None
        return _apply(tx, ctx, identifier, proposal, finances, inventory_writes, ledger)
    body, event = accept(db().transaction())
    deliver_push(event, lookup=doc)
    if body.get('status') == 'applied' and event and body.get('refund_job_ids'):
        for job_id in body['refund_job_ids']:
            process_refund_job(job_id, body['vendor_id'])
        body = to_dict(ref.get())
    return jsonify(body)


def validate_amendment_payment(tx, proposal, proposal_id, customer_id):
    if proposal.get('customer_id') != customer_id:
        raise PermissionError('Amendment belongs to another account')
    ctx = _load_group(tx, proposal['anchor_order_id'])
    if (proposal.get('status') != 'awaiting_payment' or _expired(proposal)
            or ctx['revision'] != proposal.get('revision') or ctx['batch'].get('active_amendment_id') != proposal_id
            or ctx['batch'].get('payment_review_required')):
        raise KhataError('Amendment is no longer payable; refresh its status', 409)
    return ctx


def _capture_review(tx, ctx, proposal, identifier, payment_id, reason):
    try:
        writes, _ = _inventory_plan(tx, ctx, proposal, releasing=True) if proposal.get('stock_reserved') else ([], [])
        stock_reserved = False
    except KhataError:
        writes, stock_reserved = [], bool(proposal.get('stock_reserved'))
    for stock_ref, changes in writes:
        tx.update(stock_ref, changes)
    tx.set(doc(AMENDMENTS, identifier), {'status': 'requires_review', 'stock_reserved': stock_reserved,
           'captured_payment_id': payment_id, 'capture_review_reason': reason, 'updated_at': now_iso()}, merge=True)
    _hold_writes(tx, ctx, None)
    tx.set(ctx['batch_ref'], {'payment_review_required': True, 'review_amendment_id': identifier,
                             'updated_at': now_iso()}, merge=True)
    event = _notice(tx, ctx['customer_id'], 'order_amendment_payment_review', 'Order payment needs review', identifier, ctx['anchor'])
    return {'settlement_status': 'requires_review', 'events': [event]}


def settle_captured_amendment(tx, intent, payment_id, intent_id):
    identifier = _identifier(intent.get('reference_id'), 'reference_id')
    ref = doc(AMENDMENTS, identifier)
    snap = ref.get(transaction=tx)
    proposal = snap.to_dict() or {}
    if not snap.exists:
        return {'settlement_status': 'requires_review', 'events': []}
    ctx = _load_group(tx, proposal['anchor_order_id'])
    expected = _money_paise(proposal.get('amount_due'), allow_zero=True)
    valid = (proposal.get('customer_id') == intent.get('user_id') and proposal.get('payment_intent_id') == intent_id
             and proposal.get('status') == 'awaiting_payment' and not _expired(proposal)
             and ctx['revision'] == proposal.get('revision') and ctx['batch'].get('active_amendment_id') == identifier
             and intent.get('amount_paise') == expected and expected > 0
             and all((row.to_dict() or {}).get('status') in ACTIVE for row in ctx['active']))
    if not valid:
        return _capture_review(tx, ctx, proposal, identifier, payment_id,
                               'Payment arrived after the approved revision stopped being payable')
    try:
        finances = _financials(tx, ctx)
        new = _money_paise(proposal['new_total'], allow_zero=True)
        if new - finances['funded'] != expected:
            raise KhataError('Additional capture no longer matches the revised order', 409)
        quota_ref = doc(QUOTAS, payment_id)
        quota_snap = quota_ref.get(transaction=tx)
        if quota_snap.exists:
            raise KhataError('Additional capture quota already exists', 409)
        inventory, _ = _inventory_plan(tx, ctx, proposal)
    except KhataError as error:
        return _capture_review(tx, ctx, proposal, identifier, payment_id, error.detail)
    finances['funded'] += expected
    finances['captures'].append({'intent_id': intent_id, 'payment_id': payment_id, 'captured_paise': expected,
                                 'reserved_paise': 0, 'quota_ref': quota_ref, 'razorpay_order_id': intent.get('razorpay_order_id')})
    body, event = _apply(tx, ctx, identifier, proposal, finances, inventory, captured_intent=intent_id)
    return {'settlement_status': 'settled', 'events': [event], 'amendment': body}


def _job_statuses(tx, proposal_id, override_id=None, override=None):
    snapshots = list(tx.get(col(REFUNDS).where(filter=FieldFilter('amendment_id', '==', proposal_id))))
    statuses = [(override if row.id == override_id else (row.to_dict() or {}).get('status')) for row in snapshots]
    if not statuses:
        return 'none'
    if all(status == 'completed' for status in statuses):
        return 'completed'
    for status in ('requires_review', 'retryable', 'processing', 'submitted', 'pending'):
        if status in statuses:
            return status
    return 'requires_review'


def process_refund_job(job_id, actor_id):
    from razorpay_config import get_razorpay_client
    from routes.razorpay_api import captured_payment_matches
    ref = doc(REFUNDS, job_id)
    token = uuid.uuid4().hex
    @firestore.transactional
    def acquire(tx):
        snap = ref.get(transaction=tx)
        if not snap.exists:
            raise KhataError('Refund job not found', 404)
        job = snap.to_dict() or {}
        if job.get('vendor_id') != actor_id:
            raise KhataError('Not your adjustment refund', 403)
        _parties_txn(tx, job['vendor_id'], job['customer_id'])
        if job.get('status') in {'completed', 'requires_review'}:
            return {**job, 'skip': True}
        if job.get('status') == 'processing':
            try:
                if datetime.fromisoformat(job['started_at']) > datetime.now(timezone.utc) - timedelta(minutes=5):
                    return {**job, 'skip': True}
            except (ValueError, TypeError, KeyError):
                raise KhataError('Refund lease requires reconciliation', 409)
        amount = job.get('amount_paise')
        if type(amount) is not int or not 0 < amount <= job.get('captured_paise', 0):
            raise KhataError('Invalid adjustment refund amount', 409)
        intent_snap = doc('payment_orders', job['payment_intent_id']).get(transaction=tx)
        intent = intent_snap.to_dict() or {}
        quota_snap = doc(QUOTAS, job['payment_id']).get(transaction=tx)
        quota = quota_snap.to_dict() or {}
        if (not intent_snap.exists or intent.get('status') != 'paid' or intent.get('payment_id') != job['payment_id']
                or intent.get('user_id') != job['customer_id'] or intent.get('currency') != 'INR'
                or intent.get('amount_paise') != job['captured_paise']
                or quota.get('payment_intent_id') != job['payment_intent_id']
                or quota.get('captured_paise') != job['captured_paise']
                or type(quota.get('reserved_paise')) is not int or not amount <= quota['reserved_paise'] <= job['captured_paise']):
            raise KhataError('Original capture reservation requires reconciliation', 409)
        aggregate = _job_statuses(tx, job['amendment_id'], job_id, 'processing')
        tx.update(ref, {'status': 'processing', 'lease_token': token, 'started_at': now_iso(), 'updated_at': now_iso()})
        tx.set(doc(AMENDMENTS, job['amendment_id']), {'refund_status': aggregate, 'updated_at': now_iso()}, merge=True)
        return job
    job = acquire(db().transaction())
    if job.get('skip'):
        return {'status': job['status'], 'refund_id': job.get('refund_id')}
    try:
        client = get_razorpay_client()
        if job.get('refund_id'):
            entity = client.refund.fetch(job['refund_id'], timeout=30)
        else:
            payment = client.payment.fetch(job['payment_id'], timeout=30)
            if payment.get('id') != job['payment_id'] or not captured_payment_matches(
                    {'razorpay_order_id': job['razorpay_order_id'], 'amount_paise': job['captured_paise'], 'currency': 'INR'}, payment):
                raise ValueError('Captured payment metadata mismatch')
            entity = client.payment.refund(job['payment_id'], {'amount': job['amount_paise'], 'speed': 'normal',
                        'notes': {'amendment_id': job['amendment_id'], 'reason': 'approved_order_adjustment'}},
                        headers={'X-Refund-Idempotency': job['idempotency_key']}, timeout=30)
        if (not isinstance(entity.get('id'), str) or not entity['id'].startswith('rfnd_')
                or entity.get('payment_id') != job['payment_id'] or type(entity.get('amount')) is not int
                or entity['amount'] != job['amount_paise'] or entity.get('currency') != 'INR'
                or entity.get('status') not in {'pending', 'processed', 'failed'}):
            raise ValueError('Refund response metadata mismatch')
        status = {'pending': 'submitted', 'processed': 'completed', 'failed': 'requires_review'}[entity['status']]
        error = None if status != 'requires_review' else 'Provider reports refund failure; reconcile before retrying'
    except Exception as exc:
        entity = None
        status = 'requires_review' if isinstance(exc, ValueError) else 'retryable'
        error = 'Original-payment refund could not be confirmed'
    @firestore.transactional
    def finalize(tx):
        snap = ref.get(transaction=tx)
        current = snap.to_dict() or {}
        if current.get('lease_token') != token or current.get('status') != 'processing':
            return {'status': current.get('status', 'requires_review'), 'refund_id': current.get('refund_id')}
        aggregate = _job_statuses(tx, job['amendment_id'], job_id, status)
        proposal_snap = doc(AMENDMENTS, job['amendment_id']).get(transaction=tx)
        proposal = proposal_snap.to_dict() or {}
        changes = {'status': status, 'error': error, 'updated_at': now_iso()}
        if entity:
            changes.update({'refund_id': entity['id'], 'provider_status': entity['status']})
        tx.update(ref, changes)
        tx.set(doc(AMENDMENTS, job['amendment_id']), {'refund_status': aggregate, 'updated_at': now_iso()}, merge=True)
        event = None
        if status != job.get('status'):
            event = _notice(tx, job['customer_id'], 'order_amendment_refund', 'Order refund ' + status, job['amendment_id'], proposal.get('anchor_order_id', job['amendment_id']))
        return {'status': status, 'refund_id': entity['id'] if entity else current.get('refund_id'), 'amount_paise': job['amount_paise'], '_event': event}
    result = finalize(db().transaction())
    deliver_push(result.pop('_event', None), lookup=doc)
    return result


@order_amendments_bp.post('/order-amendments/<identifier>/refund')
@require_role('vendor')
def retry_refund(identifier):
    snap = doc(AMENDMENTS, _identifier(identifier, 'amendment_id')).get()
    proposal = snap.to_dict() or {}
    if not snap.exists:
        raise KhataError('Amendment not found', 404)
    if proposal.get('vendor_id') != g.user_id:
        raise KhataError('Not your amendment', 403)
    if proposal.get('status') != 'applied':
        raise KhataError('Only an applied adjustment can be refunded', 409)
    results = [process_refund_job(job, g.user_id) for job in proposal.get('refund_job_ids', [])]
    latest = to_dict(doc(AMENDMENTS, identifier).get())
    status = latest.get('refund_status', 'none')
    code = 503 if status == 'retryable' else (409 if status == 'requires_review' else (202 if status in {'pending', 'processing', 'submitted'} else 200))
    return jsonify({'amendment': latest, 'refunds': results, 'status': status}), code


@order_amendments_bp.post('/order-amendments/<identifier>/cash-refund')
@require_role('vendor')
def confirm_manual_refund(identifier):
    payload = _payload()
    if set(payload) != {'reference'}:
        raise KhataError('A repayment reference is required')
    reference = _text(payload.get('reference'), 'reference', 200)
    if not reference:
        raise KhataError('Record the actual repayment reference')
    ref = doc(AMENDMENTS, _identifier(identifier, 'amendment_id'))
    @firestore.transactional
    def confirm(tx):
        snap = ref.get(transaction=tx)
        if not snap.exists:
            raise KhataError('Amendment not found', 404)
        proposal = snap.to_dict() or {}
        ctx = _load_group(tx, proposal['anchor_order_id'])
        _ensure_actor(tx, ctx, 'vendor')
        if proposal.get('cash_refund_status') == 'completed':
            return {**proposal, 'uid': identifier}, None
        if proposal.get('status') != 'applied' or proposal.get('cash_refund_status') != 'pending':
            raise KhataError('No manual repayment is pending', 409)
        changes = {'cash_refund_status': 'completed', 'cash_refund_reference': reference, 'cash_refunded_by': g.user_id,
                   'cash_refunded_at': now_iso(), 'updated_at': now_iso()}
        tx.update(ref, changes)
        event = _notice(tx, ctx['customer_id'], 'order_amendment_cash_refunded', 'Shop recorded your repayment', identifier, ctx['anchor'])
        return {**proposal, **changes, 'uid': identifier}, event
    body, event = confirm(db().transaction())
    deliver_push(event, lookup=doc)
    return jsonify(body)


def cash_collection_plan(tx, order, *, lookup=None, collection=None):
    """Return writes for newly received cash, retaining the original receipt trail."""
    batch_id = order.get('batch_id')
    if not batch_id:
        return []
    batch_ref = (lookup or doc)('order_batches', batch_id)
    snapshot = batch_ref.get(transaction=tx)
    batch = snapshot.to_dict() or {}
    rows = list(tx.get((collection or col)(CUSTOMER_ORDERS).where(filter=FieldFilter('batch_id', '==', batch_id))))
    received = batch.get('cash_received_paise')
    if received is None:
        received = sum(_money_paise((row.to_dict() or {}).get('partial_amount_paid', 0), allow_zero=True) for row in rows)
    current = _money_paise(order.get('partial_amount_paid', 0), allow_zero=True)
    total = _money_paise(order.get('total_price', 0), allow_zero=True)
    extra = max(total - current, 0)
    if not extra:
        return []
    if type(received) is not int or not 0 <= received + extra <= _MAX_PAISE:
        raise KhataError('Cash receipts require reconciliation', 409)
    receipts = list(batch.get('cash_receipts') or [])
    receipts.append({'amount_paise': extra, 'recorded_at': now_iso(), 'pricing_revision': order.get('pricing_revision', 0)})
    return [(batch_ref, {'cash_received_paise': received + extra, 'cash_receipts': receipts, 'updated_at': now_iso()})]


def cancel_group_with_refunds(anchor, actor_id):
    """Cancel the revised group using remaining capture quotas, never its first line alone."""
    @firestore.transactional
    def cancel(tx):
        ctx = _load_group(tx, anchor)
        if ctx['vendor_id'] != actor_id:
            raise KhataError('Not your order', 403)
        _parties_txn(tx, ctx['vendor_id'], ctx['customer_id'])
        previous_id = ctx['batch'].get('cancel_amendment_id')
        if previous_id:
            previous = doc(AMENDMENTS, previous_id).get(transaction=tx)
            if previous.exists:
                return {**previous.to_dict(), 'uid': previous_id}, None
        guard_order_mutation(tx, ctx['order'])
        if not ctx['active'] or any((row.to_dict() or {}).get('status') not in ACTIVE for row in ctx['active']):
            raise KhataError('This order can no longer be cancelled', 409)
        if any((row.to_dict() or {}).get('refund_status') for row in ctx['rows']):
            raise KhataError('Resolve the existing line refund before group cancellation', 409)
        finances = _financials(tx, ctx)
        identifier = 'cancel_' + hashlib.sha256(f'{ctx["batch_id"]}:{ctx["revision"]}'.encode()).hexdigest()
        old = sum(_money_paise(line.get('total_price', 0), allow_zero=True) for line in _current_lines(ctx))
        proposal = {'anchor_order_id': anchor, 'batch_id': ctx['batch_id'], 'vendor_id': ctx['vendor_id'], 'customer_id': ctx['customer_id'],
                    'revision': ctx['revision'], 'status': 'pending', 'kind': 'cancellation', 'reason': 'Shop cancelled the entire order',
                    'old_total': old / 100, 'new_total': 0, 'lines': [], 'original_lines': _current_lines(ctx),
                    'restock_removed': {line['item_id']: True for line in _current_lines(ctx)},
                    'created_at': now_iso(), 'expires_at': (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()}
        inventory, _ = _inventory_plan(tx, ctx, proposal)
        ledger = _ledger_plan(tx, ctx, -old, identifier) if finances['method'] == 'khata' else None
        tx.set(doc(AMENDMENTS, identifier), proposal)
        body, event = _apply(tx, ctx, identifier, proposal, finances, inventory, ledger)
        for row in ctx['active']:
            tx.update(row.reference, {'status': 'cancelled', 'cancelled_at': now_iso()})
        tx.set(ctx['batch_ref'], {'cancel_amendment_id': identifier}, merge=True)
        return body, event
    proposal, event = cancel(db().transaction())
    deliver_push(event, lookup=doc)
    jobs = list(col(REFUNDS).where(filter=FieldFilter('batch_id', '==', proposal['batch_id'])).stream())
    results = [process_refund_job(job.id, actor_id) for job in jobs]
    latest = doc(AMENDMENTS, proposal['uid']).get().to_dict() or proposal
    status = latest.get('refund_status', 'none')
    for pending_status in ('requires_review', 'retryable', 'processing', 'submitted', 'pending'):
        if any(result.get('status') == pending_status for result in results):
            status = pending_status
            break
    if latest.get('cash_refund_status') == 'pending':
        status = 'submitted'
    return {'status': 'completed' if status == 'none' else status,
            'amount_paise': _money_paise(latest.get('refund_due', 0), allow_zero=True),
            'amendment_id': proposal['uid'], 'refund_method': latest.get('refund_method')}
