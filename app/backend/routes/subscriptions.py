"""Server-priced vendor subscriptions; paid activation requires verified billing."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from flask import Blueprint, g, jsonify, request
from google.cloud.firestore_v1.base_query import FieldFilter
from auth_utils import require_auth, require_role
from db import SUBSCRIPTION_PLANS, VENDOR_SUBSCRIPTIONS, col, doc, now_iso, to_dict

subscriptions_bp = Blueprint("subscriptions", __name__)


def plan_terms(plan):
    try:
        price = Decimal(str(plan.get("price")))
        if not price.is_finite() or price < 0 or price > 10_000_000:
            raise ValueError("Invalid subscription price")
        paise = int((price * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
        duration = plan.get("duration_days", 30)
        max_items = plan.get("max_items", 10)
        if (isinstance(duration, bool) or isinstance(max_items, bool)
            or str(duration) != str(int(duration)) or str(max_items) != str(int(max_items))
            or not 1 <= int(duration) <= 3660 or not 1 <= int(max_items) <= 100000):
            raise ValueError("Invalid subscription plan limits")
        return paise, int(duration), int(max_items)
    except (InvalidOperation, TypeError, ValueError, OverflowError):
        raise ValueError("Invalid subscription plan configuration")


def active_subscription(data, now=None):
    if data.get('status') != 'active':
        return False
    try:
        end = datetime.fromisoformat(str(data.get('end_date') or '').replace('Z', '+00:00'))
        start = datetime.fromisoformat(str(data.get('start_date') or '').replace('Z', '+00:00'))
        current = now or datetime.now(timezone.utc)
        return start.tzinfo is not None and end.tzinfo is not None and start <= current < end
    except (TypeError, ValueError):
        return False


@subscriptions_bp.get('/subscriptions/plans')
def list_plans():
    return jsonify([to_dict(d) for d in col(SUBSCRIPTION_PLANS).stream()])


@subscriptions_bp.get('/subscriptions/me')
@require_auth
def my_subscription():
    # Single-field query avoids a required composite Firestore index.
    snapshots = col(VENDOR_SUBSCRIPTIONS).where(filter=FieldFilter('vendor_id', '==', g.user_id)).stream()
    valid = [to_dict(s) for s in snapshots if active_subscription(s.to_dict() or {})]
    valid.sort(key=lambda item: (item.get('start_date') or '', item['uid']), reverse=True)
    if not valid:
        return jsonify({'detail': 'No active subscription'}), 404
    return jsonify(valid[0])


@subscriptions_bp.post('/subscriptions/subscribe')
@require_role('vendor')
def subscribe():
    payload = request.get_json(silent=True) or {}
    plan_id = payload.get('plan_id') if isinstance(payload, dict) else None
    if not isinstance(plan_id, str) or not plan_id or '/' in plan_id or len(plan_id) > 128:
        return jsonify({'detail': 'Valid plan_id is required'}), 422
    snap = doc(SUBSCRIPTION_PLANS, plan_id).get()
    if not snap.exists:
        return jsonify({'detail': 'Plan not found'}), 404
    plan = snap.to_dict() or {}
    if plan.get('is_active') is False:
        return jsonify({'detail': 'Plan is unavailable'}), 409
    try:
        paise, duration, max_items = plan_terms(plan)
    except ValueError as exc:
        return jsonify({'detail': str(exc)}), 422
    now = datetime.now(timezone.utc)
    ref = col(VENDOR_SUBSCRIPTIONS).document()
    ref.set({'vendor_id': g.user_id, 'plan_id': plan_id, 'plan': plan.get('name') or 'basic',
        'max_items': max_items, 'amount': paise / 100, 'amount_paise': paise,
        'duration_days': duration, 'currency': 'INR',
        'status': 'active' if paise == 0 else 'pending',
        'payment_status': 'not_required' if paise == 0 else 'pending',
        'start_date': now.isoformat(), 'end_date': (now + timedelta(days=duration)).isoformat(),
        'created_at': now_iso()})
    return jsonify(to_dict(ref.get())), 201
