"""Server-priced vendor subscriptions; paid activation requires verified billing."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from flask import Blueprint, g, jsonify, request
from google.cloud.firestore_v1.base_query import FieldFilter
from auth_utils import require_auth, require_role
from db import SUBSCRIPTION_PLANS, VENDOR_SUBSCRIPTIONS, col, doc, now_iso, to_dict
import subscription_service as service

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


@subscriptions_bp.errorhandler(service.SubscriptionError)
def subscription_error(error):
    return jsonify({'detail': error.detail, 'code': error.code}), error.status


def _payload():
    value = request.get_json(silent=True)
    if not isinstance(value, dict):
        raise service.SubscriptionError('JSON object required')
    return value


def _limit(name='limit'):
    value = request.args.get(name, '25')
    if not value.isdigit():
        raise service.SubscriptionError('limit must be an integer')
    return service._integer(int(value), 'limit', 1, 100)


def _result(value):
    body, status = value
    return jsonify(body), status


@subscriptions_bp.get('/subscriptions/plans')
def list_plans():
    return jsonify(service.public_plans())


@subscriptions_bp.get('/subscriptions/entitlements')
@require_role('vendor')
def vendor_entitlements():
    return jsonify(service.entitlements(g.user_id))


@subscriptions_bp.get('/subscriptions/me')
@require_role('vendor')
def my_subscription():
    value = service.entitlements(g.user_id)
    if value['status'] not in {'active', 'grace', 'legacy_unrestricted'}:
        return jsonify({'detail': 'No active subscription', 'code': 'SUBSCRIPTION_REQUIRED'}), 404
    return jsonify({**value, 'uid': value['current_grant_id'], 'plan': value['plan_name'],
                    'max_items': value['usage']['max_items'], 'start_date': value['starts_at'], 'end_date': value['ends_at']})


@subscriptions_bp.post('/subscriptions/subscribe')
@require_role('vendor')
def subscribe():
    payload = _payload()
    required = {'plan_id', 'plan_version_id', 'request_kind', 'expected_account_revision'}
    if set(payload) != required:
        return jsonify({'detail': 'Refresh the app and request an exact plan version for admin review',
                        'code': 'SUBSCRIPTION_REVIEW_REQUIRED'}), 409
    return _result(service.create_request(g.user_id, request.headers.get('Idempotency-Key'), payload))


@subscriptions_bp.get('/subscriptions/requests')
@require_role('vendor')
def own_requests():
    return jsonify(service.list_requests(g.user_id, request.args.get('status'), _limit(), request.args.get('cursor')))


@subscriptions_bp.post('/subscriptions/requests')
@require_role('vendor')
def request_subscription():
    return _result(service.create_request(g.user_id, request.headers.get('Idempotency-Key'), _payload()))


@subscriptions_bp.post('/subscriptions/requests/<identifier>/cancel')
@require_role('vendor')
def cancel_request(identifier):
    return _result(service.cancel_request(g.user_id, identifier, request.headers.get('Idempotency-Key'), _payload()))


@subscriptions_bp.get('/admin/subscription-plans')
@require_role('admin', 'super_admin')
def admin_plans():
    return jsonify(service.list_admin_plans(_limit(), request.args.get('cursor')))


@subscriptions_bp.post('/admin/subscription-plans')
@require_role('admin', 'super_admin')
def admin_create_plan():
    return _result(service.plan_mutation(g.user_id, request.headers.get('Idempotency-Key'), _payload(), action='create'))


@subscriptions_bp.get('/admin/subscription-plans/<plan_id>')
@require_role('admin', 'super_admin')
def admin_plan(plan_id):
    return jsonify(service.get_plan(plan_id))


@subscriptions_bp.put('/admin/subscription-plans/<plan_id>')
@require_role('admin', 'super_admin')
def admin_update_plan(plan_id):
    return _result(service.plan_mutation(g.user_id, request.headers.get('Idempotency-Key'), _payload(), plan_id))


@subscriptions_bp.delete('/admin/subscription-plans/<plan_id>')
@require_role('admin', 'super_admin')
def admin_delete_plan(plan_id):
    return _result(service.plan_mutation(g.user_id, request.headers.get('Idempotency-Key'), _payload(), plan_id, 'delete'))


@subscriptions_bp.post('/admin/subscription-plans/<plan_id>/archive')
@require_role('admin', 'super_admin')
def admin_archive_plan(plan_id):
    return _result(service.plan_mutation(g.user_id, request.headers.get('Idempotency-Key'), _payload(), plan_id, 'archive'))


@subscriptions_bp.get('/admin/subscription-plans/<plan_id>/versions')
@require_role('admin', 'super_admin')
def admin_versions(plan_id):
    return jsonify(service.list_versions(plan_id, _limit(), request.args.get('cursor')))


@subscriptions_bp.get('/admin/subscriptions')
@require_role('admin', 'super_admin')
def admin_subscriptions():
    return jsonify(service.list_accounts(_limit(), request.args.get('cursor'), request.args.get('q', ''), request.args.get('status')))


@subscriptions_bp.get('/admin/vendors/<vendor_id>/subscription')
@require_role('admin', 'super_admin')
def admin_vendor_subscription(vendor_id):
    return jsonify(service.account_detail(vendor_id, _limit('history_limit'), request.args.get('history_cursor')))


@subscriptions_bp.post('/admin/vendors/<vendor_id>/subscription')
@require_role('admin', 'super_admin')
def admin_vendor_action(vendor_id):
    return _result(service.account_action(g.user_id, vendor_id, request.headers.get('Idempotency-Key'), _payload()))


@subscriptions_bp.get('/admin/subscription-requests')
@require_role('admin', 'super_admin')
def admin_requests():
    return jsonify(service.list_requests(request.args.get('vendor_id'), request.args.get('status'), _limit(), request.args.get('cursor')))


@subscriptions_bp.post('/admin/subscription-requests/<identifier>/decision')
@require_role('admin', 'super_admin')
def admin_decide(identifier):
    return _result(service.decide_request(g.user_id, identifier, request.headers.get('Idempotency-Key'), _payload()))


@subscriptions_bp.post('/admin/subscriptions/<sub_id>/activate')
@subscriptions_bp.post('/admin/subscriptions/<sub_id>/suspend')
@require_role('admin', 'super_admin')
def legacy_admin_activation(sub_id):
    snapshot = doc(VENDOR_SUBSCRIPTIONS, service._id(sub_id, 'subscription_id')).get()
    if not snapshot.exists:
        return jsonify({'detail': 'Historical subscription not found'}), 404
    return jsonify({'detail': 'Historical records cannot authorize access; use the reviewed vendor subscription controls',
                    'code': 'SUBSCRIPTION_REVIEW_REQUIRED'}), 409


@subscriptions_bp.get('/admin/subscriptions/rollout')
@require_role('admin', 'super_admin')
def admin_rollout_status():
    from firebase_admin import firestore
    @firestore.transactional
    def read(tx):
        return service.settings_tx(tx)
    return jsonify(read(service.db().transaction()))


@subscriptions_bp.post('/admin/subscriptions/rollout')
@require_role('admin', 'super_admin')
def admin_rollout_action():
    return _result(service.rollout_action(g.user_id, request.headers.get('Idempotency-Key'), _payload()))


@subscriptions_bp.post('/admin/vendors/<vendor_id>/subscription/reconciliation')
@require_role('admin', 'super_admin')
def admin_reconcile(vendor_id):
    return _result(service.reconciliation(g.user_id, vendor_id, request.headers.get('Idempotency-Key'), _payload()))
