"""Ownership-checked subscription payment submission and atomic moderation."""
from datetime import datetime, timedelta, timezone
from flask import Blueprint, g, jsonify, request
from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter
from auth_utils import require_auth, require_role
from db import NOTIFICATIONS, SUBSCRIPTION_PAYMENTS, VENDOR_SUBSCRIPTIONS, SUBSCRIPTION_PLANS, col, doc, db, now_iso, to_dict
from routes.razorpay_api import _amount_paise
from routes.subscriptions import plan_terms

payments_bp = Blueprint('payments', __name__)


def _expected_terms(subscription, tx=None):
    if subscription.get('amount_paise') is not None:
        price = subscription.get('amount_paise')
        if type(price) is not int or not 0 < price <= 10_000_000_00:
            raise ValueError('Invalid subscription amount')
        days = subscription.get('duration_days')
        if type(days) is not int or not 1 <= days <= 3660:
            raise ValueError('Invalid subscription duration')
        return price, days
    plan_id = subscription.get('plan_id')
    if not isinstance(plan_id, str) or not plan_id or '/' in plan_id:
        raise ValueError('Subscription plan not found')
    snap = doc(SUBSCRIPTION_PLANS, plan_id).get(transaction=tx)
    if not snap.exists:
        raise ValueError('Subscription plan not found')
    paise, duration, _ = plan_terms(snap.to_dict() or {})
    if paise <= 0:
        raise ValueError('Free subscriptions do not require payment')
    return paise, duration


@payments_bp.post('/payments')
@require_role('vendor')
def submit_payment():
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify({'detail':'JSON object required'}), 422
    sid, tid = payload.get('subscription_id'), payload.get('transaction_id')
    if (not isinstance(sid, str) or not sid or '/' in sid or len(sid) > 128
        or not isinstance(tid, str) or not 3 <= len(tid.strip()) <= 128):
        return jsonify({'detail':'Valid subscription_id and transaction_id required'}), 422
    amount = _amount_paise(payload.get('amount'))
    if amount is None:
        return jsonify({'detail':'Valid positive amount required'}), 422
    method = payload.get('method') or 'upi'
    if method not in {'upi', 'bank_transfer'}:
        return jsonify({'detail':'Unsupported payment method'}), 422
    ref = col(SUBSCRIPTION_PAYMENTS).document()
    @firestore.transactional
    def submit(tx):
        sub_ref = doc(VENDOR_SUBSCRIPTIONS, sid)
        snap = sub_ref.get(transaction=tx)
        sub = snap.to_dict() or {}
        if not snap.exists:
            raise ValueError('Subscription not found')
        if sub.get('vendor_id') != g.user_id:
            raise PermissionError('Not your subscription')
        if sub.get('status') != 'pending':
            raise ValueError('Subscription is no longer awaiting payment')
        expected, duration = _expected_terms(sub, tx)
        if amount != expected:
            raise ValueError('Payment amount does not match subscription price')
        tx.create(ref, {'vendor_id':g.user_id, 'subscription_id':sid,
            'amount':expected / 100, 'amount_paise':expected, 'duration_days':duration,
            'currency':'INR', 'method':method, 'transaction_id':tid.strip(),
            'upi_screenshot_url':payload.get('upi_screenshot_url'), 'status':'pending', 'created_at':now_iso()})
    try:
        submit(db().transaction())
        return jsonify(to_dict(ref.get())), 201
    except PermissionError as exc:
        return jsonify({'detail':str(exc)}), 403
    except ValueError as exc:
        return jsonify({'detail':str(exc)}), 409


@payments_bp.get('/payments')
@require_auth
def list_my_payments():
    items = [to_dict(s) for s in col(SUBSCRIPTION_PAYMENTS).where(filter=FieldFilter('vendor_id', '==', g.user_id)).stream()]
    items.sort(key=lambda p:p.get('created_at') or '', reverse=True)
    return jsonify(items)


@payments_bp.get('/payments/all')
@require_role('admin', 'super_admin')
def list_all_payments():
    return jsonify([to_dict(s) for s in col(SUBSCRIPTION_PAYMENTS).where(filter=FieldFilter('status', '==', 'pending')).stream()])


def _moderate(payment_id, approve):
    if not payment_id or '/' in payment_id or len(payment_id) > 128:
        return jsonify({'detail':'Invalid payment ID'}), 422
    ref = doc(SUBSCRIPTION_PAYMENTS, payment_id)
    notification = col(NOTIFICATIONS).document()
    @firestore.transactional
    def moderate(tx):
        snap = ref.get(transaction=tx)
        payment = snap.to_dict() or {}
        if not snap.exists:
            raise ValueError('Payment not found')
        wanted = 'verified' if approve else 'rejected'
        if payment.get('status') == wanted:
            return
        if payment.get('status') != 'pending':
            raise ValueError('Payment has already been moderated')
        sid = payment.get('subscription_id')
        if not isinstance(sid, str) or not sid or '/' in sid:
            raise ValueError('Invalid subscription reference')
        sub_ref = doc(VENDOR_SUBSCRIPTIONS, sid)
        sub_snap = sub_ref.get(transaction=tx)
        sub = sub_snap.to_dict() or {}
        if not sub_snap.exists or sub.get('vendor_id') != payment.get('vendor_id'):
            raise ValueError('Payment owner does not match subscription owner')
        if sub.get('status') != 'pending':
            raise ValueError('Subscription is no longer awaiting payment')
        expected, duration = _expected_terms(sub, tx)
        if (_amount_paise(payment.get('amount')) != expected
            or (payment.get('amount_paise') is not None and payment.get('amount_paise') != expected)
            or payment.get('currency', 'INR') != 'INR'):
            raise ValueError('Payment amount does not match subscription price')
        tx.update(ref, {'status':wanted, 'moderated_by':g.user_id,
            'verified_at' if approve else 'rejected_at':now_iso()})
        if approve:
            now = datetime.now(timezone.utc)
            tx.update(sub_ref, {'status':'active','payment_status':'paid', 'activated_at':now.isoformat(),
                'start_date':now.isoformat(), 'end_date':(now+timedelta(days=duration)).isoformat(),
                'payment_id':payment_id})
        tx.create(notification, {'user_id':payment['vendor_id'], 'type':'payment_approved' if approve else 'payment_rejected',
            'title':'Payment verified' if approve else 'Payment rejected',
            'body':'Your subscription is now active.' if approve else 'Please retry with a valid transaction.',
            'is_read':False, 'reference_id':payment_id, 'created_at':now_iso()})
    try:
        moderate(db().transaction())
        return jsonify({'ok':True})
    except ValueError as exc:
        return jsonify({'detail':str(exc)}), 409


@payments_bp.post('/payments/<payment_id>/verify')
@require_role('admin', 'super_admin')
def verify_payment(payment_id):
    return _moderate(payment_id, True)


@payments_bp.post('/payments/<payment_id>/reject')
@require_role('admin', 'super_admin')
def reject_payment(payment_id):
    return _moderate(payment_id, False)
