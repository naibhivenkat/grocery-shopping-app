"""Canonical vendor access. Legacy subscription/payment documents are history only.

All writes are server-authorized and serialized on one per-vendor account.
Published terms/grants and audit events are immutable. No provider network I/O.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import base64
import hashlib
import json
import re

from firebase_admin import firestore
from google.cloud.firestore_v1.base_query import FieldFilter
from db import USERS, SHOP_ITEMS, AUDIT_LOGS, NOTIFICATIONS, col, doc, db, now_iso, to_dict
from notification_delivery import notification_data, deliver_push

PLANS = 'subscription_plans'
VERSIONS = 'subscription_plan_versions'
ACCOUNTS = 'vendor_subscription_accounts'
GRANTS = 'subscription_grants'
REQUESTS = 'subscription_requests'
OPERATIONS = 'subscription_operations'
SETTINGS = 'subscription_settings'
MIGRATIONS = 'subscription_migrations'
CAPABILITIES = ('catalog_growth', 'product_import', 'promotions')
TERM_FIELDS = {'price_paise', 'currency', 'duration_days', 'trial_days', 'grace_days', 'renewal_rule', 'entitlements', 'google_play'}
IDENTITY_FIELDS = {'name', 'description', 'is_active', 'is_visible'}
UNRESOLVED = {'pending', 'approved_checkout'}


class SubscriptionError(ValueError):
    def __init__(self, detail, status=422, code='INVALID_SUBSCRIPTION_REQUEST'):
        super().__init__(detail)
        self.detail, self.status, self.code = detail, status, code


def _now():
    return datetime.now(timezone.utc)


def _id(value, label='id'):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', value) or value in {'.', '..'}:
        raise SubscriptionError(f'Valid {label} is required')
    return value


def _integer(value, label, minimum=0, maximum=1000000000):
    if type(value) is not int or not minimum <= value <= maximum:
        raise SubscriptionError(f'{label} must be an integer from {minimum} to {maximum}')
    return value


def _text(value, label, maximum=1000, required=True):
    if not isinstance(value, str) or len(value.strip()) > maximum or (required and not value.strip()):
        raise SubscriptionError(f'{label} must contain {1 if required else 0} to {maximum} characters')
    return value.strip()


def _date(value, label='date'):
    if not isinstance(value, str) or len(value) > 64:
        raise SubscriptionError(f'{label} requires a UTC/offset timestamp')
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if result.tzinfo is None or result.utcoffset() is None:
            raise ValueError()
        return result.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        raise SubscriptionError(f'{label} requires a UTC/offset timestamp') from None


def _terms(payload):
    data = {name: payload.get(name) for name in TERM_FIELDS}
    data['price_paise'] = _integer(data['price_paise'], 'price_paise')
    if data.get('currency', 'INR') not in (None, 'INR'):
        raise SubscriptionError('Only INR is supported')
    data['currency'] = 'INR'
    data['duration_days'] = _integer(data['duration_days'], 'duration_days', 1, 3660)
    data['trial_days'] = _integer(0 if data.get('trial_days') is None else data['trial_days'], 'trial_days', 0, 3660)
    data['grace_days'] = _integer(0 if data.get('grace_days') is None else data['grace_days'], 'grace_days', 0, 366)
    data['renewal_rule'] = data.get('renewal_rule') or 'manual'
    if data['renewal_rule'] not in {'manual', 'store'}:
        raise SubscriptionError('renewal_rule must be manual or store')
    features = data['entitlements']
    if not isinstance(features, dict) or set(features) != {'max_items', *CAPABILITIES}:
        raise SubscriptionError('Supply max_items and all supported capabilities')
    _integer(features['max_items'], 'max_items', 1, 100000)
    if any(type(features[name]) is not bool for name in CAPABILITIES):
        raise SubscriptionError('Capabilities must be true or false')
    data['entitlements'] = deepcopy(features)
    mapping = data.get('google_play')
    if mapping is not None:
        if not isinstance(mapping, dict) or set(mapping) != {'product_id', 'base_plan_id'}:
            raise SubscriptionError('google_play requires product_id and base_plan_id')
        data['google_play'] = {name: _id(value, name) for name, value in mapping.items()}
    return data


def _actor(tx, identifier, roles=('admin', 'super_admin')):
    snap = doc(USERS, _id(identifier, 'actor_id')).get(transaction=tx)
    data = snap.to_dict() or {}
    if not snap.exists or data.get('role') not in roles or data.get('is_suspended'):
        raise SubscriptionError('Current account permissions required', 403, 'FORBIDDEN')
    return data


def _vendor(tx, identifier):
    snap = doc(USERS, _id(identifier, 'vendor_id')).get(transaction=tx)
    data = snap.to_dict() or {}
    if not snap.exists or data.get('role') != 'vendor':
        raise SubscriptionError('Vendor not found', 404, 'VENDOR_NOT_FOUND')
    return data


def _check_revision(actual, expected):
    _integer(expected, 'expected revision')
    if actual != expected:
        raise SubscriptionError('State changed; refresh before continuing', 409, 'REVISION_CONFLICT')


def settings_tx(tx):
    snap = doc(SETTINGS, 'control').get(transaction=tx)
    data = snap.to_dict() or {}
    return {**data, 'phase': data.get('phase', 'preparing'), 'enforcement_enabled': data.get('enforcement_enabled') is True,
            'revision': data.get('revision', 0)}


def _empty_account(vendor_id):
    return {'vendor_id': vendor_id, 'schema_version': 1, 'revision': 0, 'current_grant_id': None,
            'access_state': 'active', 'pending_request_id': None, 'scheduled_change': None,
            'usage': {'product_count': 0, 'initialized': False, 'schema_version': 1}, 'quota_fence': None}


def _live_store_access(ctx):
    return bool((ctx['account'].get('store_purchase_fingerprint') or (ctx.get('grant') or {}).get('kind') == 'google_play')
                and ctx['account'].get('provider_state') not in {'expired', 'revoked'})


def _complimentary_live(grant):
    return bool(grant and grant.get('kind') == 'complimentary' and grant.get('ends_at')
                and _date(grant.get('grace_ends_at') or grant['ends_at']) > _now())


def _legacy_cohort(ctx, control):
    """Normalize private historical timestamps without relaxing API dates."""
    raw = ctx['profile'].get('created_at')
    created, status = None, 'missing' if raw is None or raw == '' else 'invalid'
    try:
        if isinstance(raw, datetime):
            if raw.tzinfo is None or raw.utcoffset() is None:
                raise ValueError()
            created = raw.astimezone(timezone.utc)
        elif isinstance(raw, str) and raw:
            created = _date(raw, 'legacy created_at')
        if created:
            status = 'valid'
    except (SubscriptionError, ValueError, OverflowError):
        created = None
    account = ctx['account']
    if account.get('activation_mode') == 'enforced':
        eligible, basis, review = False, 'server_enforced_activation', False
    elif account.get('activation_mode') == 'preparing' and account.get('legacy_baseline_migrated'):
        eligible, basis, review = True, 'canonical_pre_enforcement_activation', False
    elif (account.get('legacy_cohort_reviewed') is True
          and type(account.get('legacy_cohort_eligible')) is bool
          and account.get('legacy_cohort_manifest_id')
          and account.get('legacy_cohort_basis') in {'validated_created_at', 'admin_reviewed_preexisting', 'admin_reviewed_post_cutoff',
                                                   'canonical_pre_enforcement_activation', 'server_enforced_activation'}):
        # A completed, audited classification survives missing/changed legacy
        # profile fields. Counting again never reauthorizes a baseline grant.
        eligible, basis, review = account['legacy_cohort_eligible'], account['legacy_cohort_basis'], False
    elif created:
        eligible, basis, review = created <= _date(control['cutoff_at']), 'validated_created_at', False
    else:
        eligible, basis, review = False, 'unresolved_legacy_date', True
    return {'legacy_baseline_eligible': eligible, 'cohort_date_status': status,
            'cohort_created_at': created.isoformat() if created else None,
            'cohort_basis': basis, 'cohort_review_required': review,
            'cohort_review_reference': account.get('legacy_cohort_manifest_id') if account.get('legacy_cohort_reviewed') else None}


def _context(tx, vendor_id, profile=None):
    vendor_id = _id(vendor_id, 'vendor_id')
    profile = profile if profile is not None else _vendor(tx, vendor_id)
    ref = doc(ACCOUNTS, vendor_id)
    snap = ref.get(transaction=tx)
    account = snap.to_dict() or _empty_account(vendor_id)
    if account.get('vendor_id') != vendor_id or type(account.get('revision')) is not int:
        raise SubscriptionError('Subscription account needs reconciliation', 409, 'SUBSCRIPTION_MIGRATION_REQUIRED')
    grant = None
    if account.get('current_grant_id'):
        grant_snap = doc(GRANTS, _id(account['current_grant_id'], 'grant_id')).get(transaction=tx)
        grant = to_dict(grant_snap) if grant_snap.exists else None
        if not grant or grant.get('vendor_id') != vendor_id:
            raise SubscriptionError('Grant ownership needs reconciliation', 409, 'SUBSCRIPTION_MIGRATION_REQUIRED')
    scheduled = account.get('scheduled_change')
    future = None
    if scheduled and scheduled.get('grant_id'):
        future_snap = doc(GRANTS, _id(scheduled['grant_id'], 'grant_id')).get(transaction=tx)
        future = to_dict(future_snap) if future_snap.exists else None
        if not future or future.get('vendor_id') != vendor_id:
            raise SubscriptionError('Scheduled grant needs reconciliation', 409, 'SUBSCRIPTION_MIGRATION_REQUIRED')
    request_data = None
    if account.get('pending_request_id'):
        request_snap = doc(REQUESTS, _id(account['pending_request_id'], 'request_id')).get(transaction=tx)
        request_data = to_dict(request_snap) if request_snap.exists else None
        if not request_data or request_data.get('vendor_id') != vendor_id:
            raise SubscriptionError('Subscription request needs reconciliation', 409, 'SUBSCRIPTION_MIGRATION_REQUIRED')
    ctx = {'vendor_id': vendor_id, 'ref': ref, 'exists': snap.exists, 'account': deepcopy(account),
           'grant': grant, 'profile': profile, 'request': request_data, 'scheduled_applied': None, 'store_restored': None, 'before_account': deepcopy(account)}
    store_grant = None
    if account.get('store_grant_id') and account.get('store_grant_id') != account.get('current_grant_id'):
        store_snap = doc(GRANTS, _id(account['store_grant_id'], 'store_grant_id')).get(transaction=tx)
        store_grant = to_dict(store_snap) if store_snap.exists else None
        if not store_grant or store_grant.get('vendor_id') != vendor_id or store_grant.get('kind') != 'google_play':
            raise SubscriptionError('Store grant needs reconciliation', 409, 'SUBSCRIPTION_MIGRATION_REQUIRED')
    scheduled_due = bool(scheduled and _date(scheduled.get('effective_at'), 'effective_at') <= _now())
    ctx['store_grant'] = store_grant or (grant if (grant or {}).get('kind') == 'google_play' else None)
    if (grant and grant.get('kind') == 'complimentary' and store_grant and not scheduled_due
            and not _complimentary_live(grant)):
        ctx['account'].update(current_grant_id=store_grant['uid'], revision=account['revision'] + 1, updated_at=now_iso())
        ctx['grant'], ctx['store_restored'] = store_grant, grant['uid']
    if scheduled_due:
        comp_cancel = bool(scheduled.get('action') == 'cancel' and (grant or {}).get('kind') == 'complimentary' and store_grant)
        if (_live_store_access(ctx) and (
                scheduled.get('action') == 'change' and (future or {}).get('kind') in {'free', 'trial'}
                or scheduled.get('action') == 'cancel' and not comp_cancel)):
            # A schedule created before a later paid purchase cannot silently
            # replace the subscription Google still bills. Keep its history.
            future = ctx['grant']
            if (future or {}).get('kind') == 'complimentary' and store_grant and not _complimentary_live(future):
                future = store_grant
                ctx['store_restored'] = grant['uid']
            scheduled = {**scheduled, 'blocked_reason': 'STORE_MANAGED'}
        elif comp_cancel:
            future = store_grant
        ctx['account'].update(current_grant_id=(future or {}).get('uid'), scheduled_change=None,
                              revision=ctx['account']['revision'] + 1, updated_at=now_iso())
        if scheduled.get('blocked_reason'):
            ctx['account']['blocked_scheduled_change'] = {**scheduled, 'status': 'blocked', 'blocked_at': now_iso()}
        ctx['grant'] = future
        ctx['scheduled_applied'] = scheduled
    return ctx


def _audit(tx, operation_id, actor_id, action, vendor_id=None, before=None, after=None, reason=None):
    tx.create(doc(AUDIT_LOGS, 'subscription_' + operation_id), {'action': action, 'actor_id': actor_id,
              'vendor_id': vendor_id, 'operation_id': operation_id, 'reason': reason,
              'before': deepcopy(before), 'after': deepcopy(after), 'created_at': now_iso()})


def _flush(tx, ctx):
    tx.set(ctx['ref'], ctx['account'])
    if ctx.get('store_restored'):
        _audit(tx, ctx['store_restored'] + '_store_restored', 'system', 'subscription_store_restored', ctx['vendor_id'],
               before=ctx['before_account'], after=ctx['account'], reason='Bounded complimentary override expired; verified store state resumes.')
    if ctx.get('scheduled_applied'):
        scheduled = ctx['scheduled_applied']
        blocked = scheduled.get('blocked_reason') == 'STORE_MANAGED'
        _audit(tx, scheduled['uid'] + '_applied', scheduled.get('created_by', 'system'),
               'subscription_schedule_blocked_store_managed' if blocked else 'subscription_schedule_applied', ctx['vendor_id'],
               before=ctx['before_account'], after=ctx['account'],
               reason=scheduled.get('reason'))


def _notice(tx, vendor_id, operation_id, action):
    event = notification_data(vendor_id, 'subscription_changed', 'Subscription updated', action, vendor_id)
    event['reference_type'] = 'vendor_subscription'
    tx.create(doc(NOTIFICATIONS, 'subscription_' + operation_id), event)
    return event


def _aggregate(ctx):
    account, grant, profile = ctx['account'], ctx['grant'], ctx['profile']
    store_grant = ctx.get('store_grant')
    store_terms = (store_grant or {}).get('terms_snapshot') or {}
    now = _now()
    terms = (grant or {}).get('terms_snapshot') or {}
    features = terms.get('entitlements') or {}
    status = 'none'
    starts = _date(grant['starts_at']) if grant and grant.get('starts_at') else None
    ends = _date(grant['ends_at']) if grant and grant.get('ends_at') else None
    grace = _date(grant['grace_ends_at']) if grant and grant.get('grace_ends_at') else None
    if grant:
        if grant.get('kind') == 'legacy_unrestricted':
            status = 'legacy_unrestricted'
        elif starts and starts <= now and ends and now < ends:
            status = 'active'
        elif starts and starts <= now and grace and now < grace:
            status = 'grace'
        else:
            status = 'expired'
    if profile.get('is_suspended') or account.get('access_state') == 'suspended':
        status = 'suspended'
    if account.get('provider_state') == 'grace' and (grant or {}).get('kind') == 'google_play' and status == 'active':
        status = 'grace'
    if account.get('provider_state') in {'hold', 'paused', 'expired', 'revoked'} and (grant or {}).get('kind') == 'google_play':
        status = 'suspended' if account['provider_state'] in {'hold', 'paused'} else 'expired'
    allowed = status in {'active', 'grace', 'legacy_unrestricted'}
    usage = account.get('usage') or {}
    count = usage.get('product_count', 0)
    maximum = features.get('max_items')
    capabilities = {name: bool(allowed and features.get(name) is True) for name in CAPABILITIES}
    capabilities['product_import'] = capabilities['product_import'] and capabilities['catalog_growth']
    if maximum is not None and count >= maximum:
        capabilities['catalog_growth'] = False
        capabilities['product_import'] = False
    return {'vendor_id': ctx['vendor_id'], 'revision': account['revision'], 'status': status,
            'access_state': account.get('access_state'), 'trial_used': bool(account.get('trial_used')),
            'store_managed': bool(account.get('store_purchase_fingerprint')), 'store_state': account.get('provider_state'),
            'billing_provider': 'google_play' if account.get('store_purchase_fingerprint') else None,
            'store_subscription': {'provider_state': account.get('provider_state'), 'ends_at': store_grant.get('ends_at'),
                                   'product_id': (store_terms.get('google_play') or {}).get('product_id')} if store_grant else None,
            'grant_kind': (grant or {}).get('kind'), 'current_grant_id': (grant or {}).get('uid'),
            'plan_id': (grant or {}).get('plan_id'), 'plan_version_id': (grant or {}).get('plan_version_id'),
            'plan_name': (grant or {}).get('plan_name'), 'starts_at': (grant or {}).get('starts_at'),
            'ends_at': (grant or {}).get('ends_at'), 'grace_ends_at': (grant or {}).get('grace_ends_at'),
            'remaining_days': max(0, int(((ends or now) - now).total_seconds() + 86399) // 86400) if ends else None,
            'payment_state': (grant or {}).get('payment_state', 'none'),
            'usage': {'product_count': count, 'max_items': maximum, 'remaining_items': max(0, maximum - count) if maximum is not None else None,
                      'initialized': usage.get('initialized') is True}, 'capabilities': capabilities,
            'pending_request': ctx.get('request'), 'scheduled_change': account.get('scheduled_change'),
            'blocked_scheduled_change': deepcopy(account.get('blocked_scheduled_change')),
            'message': 'Legacy access preserved; this is not evidence of payment.' if status == 'legacy_unrestricted' else
                       ('Access is available.' if allowed else 'Request or review a subscription to add products or promotions.'),
            'available_actions': ['view_plans', 'view_history'] + ([] if account.get('pending_request_id') else ['request_subscription']),
            'vendor_name': profile.get('full_name') or profile.get('username') or 'Vendor',
            'shop_name': profile.get('shop_name') or profile.get('full_name') or 'Shop',
            'email': profile.get('email'), 'phone': profile.get('phone'), 'is_suspended': bool(profile.get('is_suspended'))}


def entitlements(vendor_id):
    @firestore.transactional
    def read(tx):
        ctx = _context(tx, vendor_id)
        result = _aggregate(ctx)
        if ctx['scheduled_applied'] or ctx.get('store_restored'):
            _flush(tx, ctx)
        return result
    return read(db().transaction())


def _operation(actor_id, operation, key, payload, callback, roles=('admin', 'super_admin'), persist=True):
    if not isinstance(key, str) or not 8 <= len(key) <= 200:
        raise SubscriptionError('Idempotency-Key must contain 8 to 200 characters')
    identifier = hashlib.sha256(f'{actor_id}:{operation}:{key}'.encode()).hexdigest()
    try:
        fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    except (TypeError, ValueError):
        raise SubscriptionError('Request values must be finite JSON data') from None
    ref = doc(OPERATIONS, identifier)
    @firestore.transactional
    def run(tx):
        profile = _actor(tx, actor_id, roles)
        previous = ref.get(transaction=tx)
        if previous.exists:
            saved = previous.to_dict() or {}
            if saved.get('fingerprint') != fingerprint:
                raise SubscriptionError('Idempotency key belongs to another operation', 409, 'IDEMPOTENCY_CONFLICT')
            return saved['response'], saved['http_status'], None
        result, status, event = callback(tx, identifier, profile)
        if persist:
            tx.create(ref, {'actor_id': actor_id, 'operation': operation, 'fingerprint': fingerprint,
                            'response': result, 'http_status': status, 'created_at': now_iso()})
        return result, status, event
    result, status, event = run(db().transaction())
    deliver_push(event, lookup=doc)
    return result, status


def _version_tx(tx, plan_id, version_id, *, current=False):
    identity = doc(PLANS, _id(plan_id, 'plan_id')).get(transaction=tx)
    version = doc(VERSIONS, _id(version_id, 'plan_version_id')).get(transaction=tx)
    plan, terms = identity.to_dict() or {}, version.to_dict() or {}
    if not identity.exists or not version.exists or terms.get('plan_id') != plan_id or plan.get('deleted_at'):
        raise SubscriptionError('Plan version not found', 404, 'PLAN_NOT_FOUND')
    if current and (plan.get('current_version_id') != version_id or plan.get('is_active') is not True or plan.get('archived_at')):
        raise SubscriptionError('Plan changed or is unavailable', 409, 'PLAN_CHANGED')
    return {**plan, 'uid': plan_id}, {**terms, 'uid': version_id}


def _plan_view(plan, version):
    return {**plan, **{name: version.get(name) for name in TERM_FIELDS}, 'current_version': version,
            'price': version.get('price_paise', 0) / 100, 'max_items': (version.get('entitlements') or {}).get('max_items')}


def plan_mutation(actor_id, key, payload, plan_id=None, action='update'):
    if not isinstance(payload, dict):
        raise SubscriptionError('JSON object required')
    reason = _text(payload.get('reason'), 'reason')
    allowed = IDENTITY_FIELDS | TERM_FIELDS | {'revision', 'reason'}
    if set(payload) - allowed:
        raise SubscriptionError('Unsupported plan fields')
    def apply(tx, operation_id, actor):
        identifier = _id(plan_id, 'plan_id') if plan_id else 'plan_' + operation_id[:32]
        ref = doc(PLANS, identifier)
        snapshot = ref.get(transaction=tx)
        old = snapshot.to_dict() or {}
        if plan_id and (not snapshot.exists or old.get('deleted_at')):
            raise SubscriptionError('Plan not found', 404, 'PLAN_NOT_FOUND')
        if plan_id:
            _check_revision(old.get('revision'), payload.get('revision'))
        elif snapshot.exists:
            raise SubscriptionError('Plan identity collision', 409)
        old_version = {}
        if old.get('current_version_id'):
            version_snap = doc(VERSIONS, old['current_version_id']).get(transaction=tx)
            old_version = version_snap.to_dict() or {}
        if action == 'delete':
            grant_refs = list(tx.get(col(GRANTS).where(filter=FieldFilter('plan_id', '==', identifier))))
            request_refs = list(tx.get(col(REQUESTS).where(filter=FieldFilter('plan_id', '==', identifier))))
            if old.get('reference_count', 0) or grant_refs or request_refs:
                raise SubscriptionError('Referenced plans must be archived, not deleted', 409, 'PLAN_REFERENCED')
            changed = {**old, 'deleted_at': now_iso(), 'is_active': False, 'is_visible': False, 'revision': old['revision'] + 1}
            tx.set(ref, changed)
            result = {'uid': identifier, 'deleted': True, 'revision': changed['revision'], 'operation_id': operation_id}
        else:
            if old.get('archived_at') and action != 'archive':
                raise SubscriptionError('Archived plans cannot be changed', 409, 'PLAN_ARCHIVED')
            revision = old.get('revision', 0) + 1
            identity = {name: payload.get(name, old.get(name, True if name in {'is_active', 'is_visible'} else '')) for name in IDENTITY_FIELDS}
            identity['name'] = _text(identity['name'], 'name', 120)
            identity['description'] = _text(identity['description'], 'description', 2000, required=False)
            if any(type(identity[name]) is not bool for name in ('is_active', 'is_visible')):
                raise SubscriptionError('is_active and is_visible must be boolean')
            changed = {**old, **identity, 'revision': revision, 'created_at': old.get('created_at') or now_iso(),
                       'updated_at': now_iso(), 'updated_by': actor_id, 'archived_at': old.get('archived_at'),
                       'reference_count': old.get('reference_count', 0)}
            if action == 'archive':
                changed.update(archived_at=now_iso(), is_active=False, is_visible=False)
            terms_changed = not snapshot.exists or bool(set(payload) & TERM_FIELDS)
            version = {**old_version, 'uid': old.get('current_version_id')}
            if terms_changed:
                normalized = _terms({**old_version, **{name: payload[name] for name in TERM_FIELDS if name in payload}})
                number = old_version.get('version', 0) + 1
                version_id = 'version_' + hashlib.sha256(f'{identifier}:{number}'.encode()).hexdigest()[:40]
                version = {**normalized, 'uid': version_id, 'plan_id': identifier, 'version': number,
                           'created_by': actor_id, 'created_at': now_iso()}
                changed['current_version_id'] = version_id
                tx.create(doc(VERSIONS, version_id), {name: value for name, value in version.items() if name != 'uid'})
            tx.set(ref, changed)
            result = {**_plan_view({**changed, 'uid': identifier}, version), 'operation_id': operation_id}
        _audit(tx, operation_id, actor_id, 'subscription_plan_' + action, before=old or None, after=changed, reason=reason)
        return result, 201 if not plan_id else 200, None
    return _operation(actor_id, 'plan_' + action + ':' + (plan_id or 'new'), key, payload, apply)


def get_plan(plan_id):
    @firestore.transactional
    def read(tx):
        snap = doc(PLANS, _id(plan_id, 'plan_id')).get(transaction=tx)
        value = snap.to_dict() or {}
        if not snap.exists or value.get('deleted_at'):
            raise SubscriptionError('Plan not found', 404, 'PLAN_NOT_FOUND')
        version = doc(VERSIONS, _id(value.get('current_version_id'), 'plan_version_id')).get(transaction=tx)
        if not version.exists:
            raise SubscriptionError('Plan requires canonical version setup', 409, 'PLAN_CHANGED')
        return _plan_view(to_dict(snap), to_dict(version))
    return read(db().transaction())


def public_plans():
    values = []
    for snapshot in col(PLANS).stream():
        item = snapshot.to_dict() or {}
        if item.get('is_active') is True and item.get('is_visible') is True and not item.get('archived_at') and not item.get('deleted_at') and item.get('current_version_id'):
            value = get_plan(snapshot.id)
            value = {name: data for name, data in value.items() if name not in {'created_by', 'updated_by'}}
            value['current_version'] = {name: data for name, data in value['current_version'].items() if name != 'created_by'}
            values.append(value)
    return sorted(values, key=lambda item: (item['name'].casefold(), item['uid']))


def _new_grant(ctx, version, plan_name, kind, grant_id, actor_id, reason, starts=None, ends=None, source_request_id=None):
    if kind not in {'free', 'trial', 'complimentary'}:
        raise SubscriptionError('Choose free, trial or complimentary access')
    if kind == 'free' and version['price_paise'] != 0:
        raise SubscriptionError('Paid plan access needs verified store purchase or explicit complimentary override', 409, 'STORE_BILLING_REQUIRED')
    starts = starts or _now()
    if kind in {'trial', 'complimentary'} and ends is None:
        raise SubscriptionError('Explicit expiry is required for trial/complimentary access')
    ends = ends or starts + timedelta(days=version['duration_days'])
    if ends <= starts or ends > starts + timedelta(days=3660):
        raise SubscriptionError('Expiry must follow the start and be within 3660 days')
    if kind == 'trial':
        if ctx['account'].get('trial_used'):
            raise SubscriptionError('This vendor has already used its lifetime trial', 409, 'TRIAL_ALREADY_USED')
        days = version.get('trial_days', 0)
        if not days or ends > starts + timedelta(days=days):
            raise SubscriptionError('Trial expiry exceeds the configured trial period', 409, 'PLAN_CHANGED')
        ctx['account']['trial_used'] = True
    terms = {name: deepcopy(version.get(name)) for name in TERM_FIELDS}
    return {'uid': grant_id, 'vendor_id': ctx['vendor_id'], 'kind': kind, 'plan_id': version['plan_id'],
            'plan_version_id': version['uid'], 'plan_name': plan_name, 'terms_snapshot': terms,
            'starts_at': starts.isoformat(), 'ends_at': ends.isoformat(),
            'grace_ends_at': (ends + timedelta(days=version.get('grace_days', 0))).isoformat(),
            'payment_state': 'not_required' if kind == 'free' else 'not_charged', 'reason': reason,
            'source_request_id': source_request_id, 'created_by': actor_id, 'created_at': now_iso()}


def _reference_plan(tx, plan):
    count = _integer(plan.get('reference_count', 0), 'plan reference_count', 0, 1000000000)
    tx.update(doc(PLANS, plan['uid']), {'reference_count': count + 1, 'references_updated_at': now_iso()})


def _store_grant(tx, ctx, grant):
    if grant.get('kind') in {'free', 'trial'} and _live_store_access(ctx):
        raise SubscriptionError('Replacing Google access requires an explicit complimentary override', 409, 'STORE_MANAGED')
    tx.create(doc(GRANTS, grant['uid']), {name: value for name, value in grant.items() if name != 'uid'})
    ctx['grant'] = grant
    ctx['account'].update(current_grant_id=grant['uid'], scheduled_change=None,
                          updated_at=now_iso())


def account_action(actor_id, vendor_id, key, payload):
    allowed = {'action', 'expected_account_revision', 'reason', 'plan_id', 'plan_version_id', 'kind', 'ends_at', 'effective_at'}
    if not isinstance(payload, dict) or set(payload) - allowed:
        raise SubscriptionError('Unsupported subscription action fields')
    action = payload.get('action')
    if action not in {'assign', 'renew', 'extend', 'suspend', 'reactivate', 'schedule_cancel', 'schedule_change', 'cancel_scheduled'}:
        raise SubscriptionError('Choose a supported subscription action')
    reason = _text(payload.get('reason'), 'reason')
    def apply(tx, operation_id, actor):
        ctx = _context(tx, vendor_id)
        before = deepcopy(ctx['account'])
        _check_revision(ctx['account']['revision'], payload.get('expected_account_revision'))
        grant = ctx['grant']
        google = (grant or {}).get('kind') == 'google_play'
        if google and action in {'renew', 'extend', 'schedule_cancel'}:
            raise SubscriptionError('Google manages this billing period; use store controls or explicit complimentary access', 409, 'STORE_MANAGED')
        if action in {'assign', 'renew', 'schedule_change'}:
            plan, version = _version_tx(tx, payload.get('plan_id'), payload.get('plan_version_id'), current=True)
            kind = payload.get('kind')
            if _live_store_access(ctx) and kind != 'complimentary':
                raise SubscriptionError('Replacing Google access requires an explicit complimentary override', 409, 'STORE_MANAGED')
            start = _now()
            if action == 'renew':
                if (grant or {}).get('kind') == 'trial' or kind == 'trial':
                    raise SubscriptionError('A lifetime trial cannot be renewed', 409, 'TRIAL_ALREADY_USED')
                if grant and grant.get('ends_at'):
                    start = max(start, _date(grant['ends_at']))
            if action == 'schedule_change':
                start = _date(payload.get('effective_at'), 'effective_at')
                if start <= _now():
                    raise SubscriptionError('Scheduled change must be in the future')
            end = _date(payload['ends_at'], 'ends_at') if payload.get('ends_at') else None
            new = _new_grant(ctx, version, plan['name'], kind, 'grant_' + operation_id[:40], actor_id, reason, start, end)
            if action == 'schedule_change' or (action == 'renew' and start > _now()):
                if ctx['account'].get('scheduled_change'):
                    raise SubscriptionError('Cancel the existing scheduled change first', 409, 'SCHEDULE_EXISTS')
                ctx['account']['scheduled_change'] = {'uid': 'schedule_' + operation_id[:40], 'action': 'change',
                    'grant_id': new['uid'], 'effective_at': start.isoformat(), 'reason': reason, 'created_by': actor_id}
                _reference_plan(tx, plan)
                tx.create(doc(GRANTS, new['uid']), {name: value for name, value in new.items() if name != 'uid'})
            else:
                _reference_plan(tx, plan)
                _store_grant(tx, ctx, new)
        elif action == 'extend':
            if not grant or grant.get('kind') in {'legacy_unrestricted', 'trial'}:
                raise SubscriptionError('This grant cannot be extended', 409)
            end = _date(payload.get('ends_at'), 'ends_at')
            if end <= max(_now(), _date(grant['ends_at'])) or end > _now() + timedelta(days=3660):
                raise SubscriptionError('New expiry must extend the current period within 3660 days')
            old_plan = doc(PLANS, grant['plan_id']).get(transaction=tx)
            if not old_plan.exists:
                raise SubscriptionError('Plan identity is missing', 409, 'PLAN_CHANGED')
            extended = {**deepcopy(grant), 'uid': 'grant_' + operation_id[:40], 'ends_at': end.isoformat(),
                        'grace_ends_at': (end + timedelta(days=grant['terms_snapshot'].get('grace_days', 0))).isoformat(),
                        'reason': reason, 'created_by': actor_id, 'created_at': now_iso(), 'previous_grant_id': grant['uid']}
            _reference_plan(tx, to_dict(old_plan))
            _store_grant(tx, ctx, extended)
        elif action == 'suspend':
            ctx['account'].update(access_state='suspended', scheduled_change=None)
        elif action == 'reactivate':
            if not grant:
                raise SubscriptionError('Assign an approved grant first', 409, 'SUBSCRIPTION_REQUIRED')
            if grant.get('ends_at') and _date(grant.get('grace_ends_at') or grant['ends_at']) <= _now():
                raise SubscriptionError('Expired access requires a new grant', 409, 'SUBSCRIPTION_REQUIRED')
            ctx['account']['access_state'] = 'active'
        elif action == 'schedule_cancel':
            if not grant or grant.get('kind') == 'legacy_unrestricted':
                raise SubscriptionError('No bounded grant is available to cancel', 409)
            effective = _date(payload.get('effective_at'), 'effective_at')
            if effective <= _now():
                raise SubscriptionError('Cancellation must be scheduled in the future')
            if ctx['account'].get('scheduled_change'):
                raise SubscriptionError('Cancel the existing scheduled change first', 409, 'SCHEDULE_EXISTS')
            ctx['account']['scheduled_change'] = {'uid': 'schedule_' + operation_id[:40], 'action': 'cancel', 'grant_id': None,
                'effective_at': effective.isoformat(), 'reason': reason, 'created_by': actor_id}
        elif action == 'cancel_scheduled':
            if not ctx['account'].get('scheduled_change'):
                raise SubscriptionError('No scheduled change exists', 409, 'SCHEDULE_NOT_FOUND')
            ctx['account']['scheduled_change'] = None
        ctx['account'].update(revision=ctx['account']['revision'] + 1, updated_at=now_iso())
        result = {**_aggregate(ctx), 'operation_id': operation_id}
        _flush(tx, ctx)
        _audit(tx, operation_id, actor_id, 'subscription_' + action, vendor_id, before, ctx['account'], reason)
        event = _notice(tx, vendor_id, operation_id, 'Your shop subscription access was updated. Review its current status.')
        return result, 200, event
    return _operation(actor_id, 'account:' + _id(vendor_id, 'vendor_id'), key, payload, apply)


def create_request(actor_id, key, payload):
    allowed = {'plan_id', 'plan_version_id', 'request_kind', 'expected_account_revision'}
    if not isinstance(payload, dict) or set(payload) != allowed:
        raise SubscriptionError('Supply plan, exact version, request_kind and expected_account_revision')
    kind = payload.get('request_kind')
    if kind not in {'subscription', 'renewal', 'upgrade', 'trial'}:
        raise SubscriptionError('Choose subscription, renewal, upgrade or trial')
    def apply(tx, operation_id, actor):
        ctx = _context(tx, actor_id, actor)
        _check_revision(ctx['account']['revision'], payload['expected_account_revision'])
        if ctx['account'].get('pending_request_id'):
            raise SubscriptionError('Resolve or cancel the existing request first', 409, 'REQUEST_EXISTS')
        plan, version = _version_tx(tx, payload['plan_id'], payload['plan_version_id'], current=True)
        if not plan.get('is_visible'):
            raise SubscriptionError('Plan is not available to request', 409, 'PLAN_CHANGED')
        if kind == 'trial' and (ctx['account'].get('trial_used') or not version.get('trial_days')):
            raise SubscriptionError('A trial is unavailable or already used', 409, 'TRIAL_ALREADY_USED')
        identifier = 'request_' + operation_id[:40]
        before = deepcopy(ctx['account'])
        ctx['account'].update(pending_request_id=identifier, revision=ctx['account']['revision'] + 1, updated_at=now_iso())
        data = {'uid': identifier, 'vendor_id': actor_id, 'plan_id': plan['uid'], 'plan_name': plan['name'],
                'plan_version_id': version['uid'], 'terms_snapshot': deepcopy(version), 'request_kind': kind,
                'status': 'pending', 'revision': 1, 'account_revision': ctx['account']['revision'],
                'created_at': now_iso(), 'updated_at': now_iso()}
        ctx['request'] = data
        _reference_plan(tx, plan)
        tx.create(doc(REQUESTS, identifier), {name: value for name, value in data.items() if name != 'uid'})
        _flush(tx, ctx)
        _audit(tx, operation_id, actor_id, 'subscription_requested', actor_id, before, data, kind)
        return data, 201, None
    return _operation(actor_id, 'request_create', key, payload, apply, roles=('vendor',))


def cancel_request(actor_id, identifier, key, payload):
    if not isinstance(payload, dict) or set(payload) != {'revision', 'expected_account_revision'}:
        raise SubscriptionError('Supply request revision and expected_account_revision')
    def apply(tx, operation_id, actor):
        snap = doc(REQUESTS, _id(identifier, 'request_id')).get(transaction=tx)
        data = snap.to_dict() or {}
        if not snap.exists or data.get('vendor_id') != actor_id:
            raise SubscriptionError('Request not found', 404, 'REQUEST_NOT_FOUND')
        ctx = _context(tx, actor_id, actor)
        _check_revision(data['revision'], payload['revision'])
        _check_revision(ctx['account']['revision'], payload['expected_account_revision'])
        if data['status'] not in UNRESOLVED or ctx['account'].get('pending_request_id') != identifier:
            raise SubscriptionError('Request is no longer pending', 409, 'REVISION_CONFLICT')
        changed = {**data, 'uid': identifier, 'status': 'cancelled', 'revision': data['revision'] + 1, 'updated_at': now_iso()}
        ctx['account'].update(pending_request_id=None, revision=ctx['account']['revision'] + 1, updated_at=now_iso())
        ctx['request'] = None
        changed['account_revision'] = ctx['account']['revision']
        tx.update(snap.reference, {name: value for name, value in changed.items() if name != 'uid'})
        _flush(tx, ctx)
        _audit(tx, operation_id, actor_id, 'subscription_request_cancelled', actor_id, data, changed, 'Vendor cancelled request')
        return changed, 200, None
    return _operation(actor_id, 'request_cancel:' + _id(identifier), key, payload, apply, roles=('vendor',))


def decide_request(actor_id, identifier, key, payload):
    allowed = {'decision', 'revision', 'expected_account_revision', 'reason'}
    if not isinstance(payload, dict) or set(payload) != allowed or payload.get('decision') not in {'approved', 'rejected'}:
        raise SubscriptionError('Supply decision, reviewed revisions and reason')
    reason = _text(payload['reason'], 'reason')
    def apply(tx, operation_id, actor):
        ref = doc(REQUESTS, _id(identifier, 'request_id'))
        snap = ref.get(transaction=tx)
        request = snap.to_dict() or {}
        if not snap.exists:
            raise SubscriptionError('Request not found', 404, 'REQUEST_NOT_FOUND')
        ctx = _context(tx, request['vendor_id'])
        _check_revision(request['revision'], payload['revision'])
        _check_revision(ctx['account']['revision'], payload['expected_account_revision'])
        if request['status'] != 'pending' or ctx['account'].get('pending_request_id') != identifier:
            raise SubscriptionError('Request has already been decided', 409, 'REVISION_CONFLICT')
        before = deepcopy(ctx['account'])
        status = 'rejected'
        changed = {**request, 'uid': identifier, 'revision': request['revision'] + 1, 'reason': reason,
                   'reviewed_by': actor_id, 'reviewed_at': now_iso(), 'updated_at': now_iso()}
        if payload['decision'] == 'approved':
            # Only approval needs currently available terms; stale requests must
            # remain rejectable after a plan is archived or deactivated.
            plan, version = _version_tx(tx, request['plan_id'], request['plan_version_id'])
            if plan.get('archived_at') or not plan.get('is_active'):
                raise SubscriptionError('Plan is no longer available', 409, 'PLAN_CHANGED')
            trial = request['request_kind'] == 'trial'
            if trial or version['price_paise'] == 0:
                end = _now() + timedelta(days=version['trial_days']) if trial else None
                grant = _new_grant(ctx, version, request['plan_name'], 'trial' if trial else 'free',
                                   'grant_' + operation_id[:40], actor_id, reason, ends=end, source_request_id=identifier)
                _reference_plan(tx, plan)
                _store_grant(tx, ctx, grant)
                changed['grant_id'] = grant['uid']
                status = 'fulfilled'
            else:
                status = 'approved_checkout'
        changed['status'] = status
        if status != 'approved_checkout':
            ctx['account']['pending_request_id'] = None
            ctx['request'] = None
        else:
            ctx['request'] = changed
        ctx['account'].update(revision=ctx['account']['revision'] + 1, updated_at=now_iso())
        changed['account_revision'] = ctx['account']['revision']
        result = {'request': changed, 'subscription': _aggregate(ctx), 'operation_id': operation_id}
        tx.update(ref, {name: value for name, value in changed.items() if name != 'uid'})
        _flush(tx, ctx)
        _audit(tx, operation_id, actor_id, 'subscription_request_' + status, ctx['vendor_id'], before, changed, reason)
        event = _notice(tx, ctx['vendor_id'], operation_id, 'Your subscription request was reviewed. Open Subscription for its status.')
        return result, 200, event
    return _operation(actor_id, 'request_decision:' + _id(identifier), key, payload, apply)


def _cursor_encode(scope, last):
    return base64.urlsafe_b64encode(json.dumps({'scope': scope, 'last': last}, separators=(',', ':')).encode()).decode().rstrip('=')


def _cursor_decode(cursor, scope):
    if not cursor:
        return None
    try:
        if not isinstance(cursor, str) or len(cursor) > 1500:
            raise ValueError()
        value = json.loads(base64.urlsafe_b64decode(cursor + '=' * (-len(cursor) % 4)))
        if value.get('scope') != scope:
            raise ValueError()
        return _id(value['last'])
    except (ValueError, TypeError, KeyError, UnicodeDecodeError):
        raise SubscriptionError('Invalid pagination cursor') from None


def page(collection, limit=25, cursor=None, filters=()):
    limit = _integer(limit, 'limit', 1, 100)
    scope = collection + ':' + json.dumps(filters, separators=(',', ':'))
    last = _cursor_decode(cursor, scope)
    query = col(collection)
    for field, value in filters:
        query = query.where(filter=FieldFilter(field, '==', value))
    query = query.order_by('__name__')
    if last:
        query = query.start_after({'__name__': doc(collection, last)})
    snapshots = list(query.limit(limit + 1).stream())
    values = [to_dict(snapshot) for snapshot in snapshots[:limit]]
    return values, _cursor_encode(scope, snapshots[limit - 1].id) if len(snapshots) > limit else None


def list_admin_plans(limit=25, cursor=None):
    values, next_cursor = page(PLANS, limit, cursor)
    legacy = [value for value in values if not value.get('deleted_at') and not value.get('current_version_id')]
    items = [get_plan(value['uid']) for value in values if not value.get('deleted_at') and value.get('current_version_id')]
    return {'items': items, 'next_cursor': next_cursor, 'legacy_records_on_page': len(legacy)}


def list_versions(plan_id, limit=25, cursor=None):
    get_plan(plan_id)
    items, next_cursor = page(VERSIONS, limit, cursor, (('plan_id', plan_id),))
    return {'items': items, 'next_cursor': next_cursor}


def list_requests(vendor_id=None, status=None, limit=25, cursor=None):
    filters = (('vendor_id', _id(vendor_id)),) if vendor_id else ()
    items, next_cursor = page(REQUESTS, limit, cursor, filters)
    if status:
        if status not in UNRESOLVED | {'fulfilled', 'rejected', 'cancelled'}:
            raise SubscriptionError('Invalid request status')
        items = [item for item in items if item.get('status') == status]
    return {'items': items, 'next_cursor': next_cursor}


def list_accounts(limit=25, cursor=None, q='', status=None):
    limit = _integer(limit, 'limit', 1, 100)
    q = _text(q, 'q', 200, required=False).casefold()
    if status and status not in {'none', 'active', 'grace', 'expired', 'suspended', 'legacy_unrestricted'}:
        raise SubscriptionError('Invalid subscription status')
    scope = 'admin_subscription_accounts:' + json.dumps({'q': q, 'status': status or None}, sort_keys=True)
    last = _cursor_decode(cursor, scope)
    items, scanned, exhausted = [], 0, False
    budget = 500
    while len(items) < limit and scanned < budget:
        batch_size = min(100, budget - scanned)
        query = col(USERS).where(filter=FieldFilter('role', '==', 'vendor')).order_by('__name__')
        if last:
            query = query.start_after({'__name__': doc(USERS, last)})
        snapshots = list(query.limit(batch_size + 1).stream())
        batch = snapshots[:batch_size]
        if not batch:
            exhausted = True
            break
        for index, snapshot in enumerate(batch):
            profile = snapshot.to_dict() or {}
            last, scanned = snapshot.id, scanned + 1
            # Cheap profile filtering precedes all entitlement transactions.
            searchable = ' '.join(str(value or '') for value in (snapshot.id, profile.get('full_name'),
                profile.get('username'), profile.get('shop_name'), profile.get('email'), profile.get('phone'))).casefold()
            if not q or q in searchable:
                value = entitlements(snapshot.id)
                if not status or value['status'] == status:
                    items.append(value)
            if len(items) == limit:
                exhausted = index == len(batch) - 1 and len(snapshots) <= batch_size
                break
        else:
            exhausted = len(snapshots) <= batch_size
        if exhausted:
            break
    return {'items': items, 'next_cursor': _cursor_encode(scope, last) if last and not exhausted else None,
            'scanned_count': scanned, 'scan_limit': budget, 'search_incomplete': bool(not exhausted and scanned >= budget)}


def account_detail(vendor_id, limit=25, cursor=None):
    aggregate = entitlements(vendor_id)
    sources = ((GRANTS, 'grants'), (REQUESTS, 'requests'), ('subscription_payments', 'payments'), (AUDIT_LOGS, 'audit'), ('vendor_subscriptions', 'legacy_subscriptions'))
    source_index, source_cursor = 0, None
    if cursor:
        try:
            data = json.loads(base64.urlsafe_b64decode(cursor + '=' * (-len(cursor) % 4)))
            if data.get('vendor_id') != vendor_id or type(data.get('source')) is not int or not 0 <= data['source'] < len(sources):
                raise ValueError()
            source_index, source_cursor = data['source'], data.get('cursor')
        except (ValueError, TypeError, KeyError, UnicodeDecodeError):
            raise SubscriptionError('Invalid history cursor') from None
    collection, record_type = sources[source_index]
    records, next_cursor = page(collection, limit, source_cursor, (('vendor_id', vendor_id),))
    next_page = None
    if next_cursor or source_index + 1 < len(sources):
        next_page = base64.urlsafe_b64encode(json.dumps({'vendor_id': vendor_id,
            'source': source_index if next_cursor else source_index + 1, 'cursor': next_cursor}).encode()).decode().rstrip('=')
    aggregate['history'] = {'items': [{**item, 'record_type': record_type} for item in records], 'next_cursor': next_page}
    actions = ['assign', 'schedule_change']
    if aggregate['access_state'] != 'suspended':
        actions.append('suspend')
    elif aggregate['current_grant_id']:
        actions.append('reactivate')
    if aggregate['grant_kind'] in {'free', 'complimentary'}:
        actions.extend(['renew', 'extend', 'schedule_cancel'])
    if aggregate['scheduled_change']:
        actions.append('cancel_scheduled')
    aggregate['admin_available_actions'] = actions
    account_snap = doc(ACCOUNTS, vendor_id).get()
    fence = (account_snap.to_dict() or {}).get('quota_fence')
    job_snap = doc(MIGRATIONS, fence).get() if fence else None
    aggregate['reconciliation_job'] = to_dict(job_snap) if job_snap and job_snap.exists else None
    return aggregate


def prepare_google_play_checkout(vendor_id, request_id):
    @firestore.transactional
    def prepare(tx):
        profile = _actor(tx, vendor_id, ('vendor',))
        snap = doc(REQUESTS, _id(request_id, 'request_id')).get(transaction=tx)
        request_data = to_dict(snap) if snap.exists else {}
        ctx = _context(tx, vendor_id, profile)
        if not snap.exists or request_data.get('vendor_id') != vendor_id:
            raise SubscriptionError('Request not found', 404, 'REQUEST_NOT_FOUND')
        if request_data.get('status') != 'approved_checkout' or ctx['account'].get('pending_request_id') != request_id:
            raise SubscriptionError('A paid request must be approved before checkout', 409, 'REQUEST_NOT_APPROVED')
        plan, version = _version_tx(tx, request_data['plan_id'], request_data['plan_version_id'])
        if version['price_paise'] <= 0 or not version.get('google_play') or plan.get('archived_at') or not plan.get('is_active'):
            raise SubscriptionError('Store product mapping is unavailable', 409, 'STORE_BILLING_REQUIRED')
        return {'request': request_data, 'plan_version': version,
                'billing_account_id': hashlib.sha256(('alllocal:vendor-billing:' + vendor_id).encode()).hexdigest()}
    return prepare(db().transaction())


def apply_verified_store_state(vendor_id, *, event_id, provider_state, plan_version_id, starts_at, ends_at,
                               purchase_fingerprint, source_revision, grace_ends_at=None, request_id=None,
                               linked_purchase_fingerprint=None, acknowledgement_state=None, test_purchase=False):
    """Trusted Google adapter only. Never called with raw client claims.

    Provider token ownership/verification/leases live in the adapter. This final
    authority also serializes request fulfillment and access across replacements.
    """
    if provider_state not in {'active', 'grace', 'canceled', 'hold', 'paused', 'expired', 'revoked'}:
        raise SubscriptionError('Invalid verified provider state')
    event_id = _text(event_id, 'event_id', 300)
    purchase_fingerprint = _id(purchase_fingerprint, 'purchase_fingerprint')
    if linked_purchase_fingerprint:
        _id(linked_purchase_fingerprint, 'linked_purchase_fingerprint')
    _integer(source_revision, 'source_revision', 1, 1000000000)
    if type(test_purchase) is not bool:
        raise SubscriptionError('test_purchase must be boolean')
    start, end = _date(starts_at, 'starts_at'), _date(ends_at, 'ends_at')
    grace = _date(grace_ends_at, 'grace_ends_at') if grace_ends_at else end
    if end <= start or grace < end:
        raise SubscriptionError('Invalid verified store period')
    operation_id = hashlib.sha256(('google:' + event_id).encode()).hexdigest()
    marker = doc(OPERATIONS, operation_id)
    values = {'vendor_id': vendor_id, 'event_id': event_id, 'provider_state': provider_state, 'plan_version_id': plan_version_id,
              'starts_at': starts_at, 'ends_at': ends_at, 'grace_ends_at': grace_ends_at, 'purchase_fingerprint': purchase_fingerprint,
              'source_revision': source_revision, 'request_id': request_id, 'linked_purchase_fingerprint': linked_purchase_fingerprint,
              'acknowledgement_state': acknowledgement_state, 'test_purchase': test_purchase}
    fingerprint = hashlib.sha256(json.dumps(values, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    @firestore.transactional
    def apply(tx):
        previous = marker.get(transaction=tx)
        ctx = _context(tx, vendor_id)
        if previous.exists:
            saved = previous.to_dict() or {}
            if saved.get('fingerprint') != fingerprint:
                raise SubscriptionError('Provider event identity changed', 409, 'IDEMPOTENCY_CONFLICT')
            return saved['response'], None
        old_fingerprint = ctx['account'].get('store_purchase_fingerprint')
        old_revision = ctx['account'].get('store_source_revision', 0)
        same = old_fingerprint == purchase_fingerprint
        request_data = None
        if request_id:
            snapshot = doc(REQUESTS, _id(request_id, 'request_id')).get(transaction=tx)
            request_data = to_dict(snapshot) if snapshot.exists else None
            if not request_data or request_data.get('vendor_id') != vendor_id:
                raise SubscriptionError('Verified purchase request belongs to another account', 403, 'FORBIDDEN')
        stale = same and source_revision <= old_revision
        replacement = bool(old_fingerprint and linked_purchase_fingerprint == old_fingerprint)
        current_request = bool(request_data and request_data.get('status') == 'approved_checkout'
                               and ctx['account'].get('pending_request_id') == request_id
                               and request_data.get('plan_version_id') == plan_version_id)
        if (old_fingerprint and not same and not replacement and current_request
                and ctx['account'].get('provider_state') not in {'expired', 'revoked'}
                and provider_state not in {'expired', 'revoked'}):
            raise SubscriptionError('Use a verified linked replacement to avoid a second subscription', 409, 'STORE_REPLACEMENT_REQUIRED')
        ignored = stale or bool(old_fingerprint and not same and not replacement and not current_request)
        if not old_fingerprint and not current_request:
            raise SubscriptionError('Initial paid access requires an approved exact-version request', 409, 'REQUEST_NOT_APPROVED')
        if ignored:
            result = _aggregate(ctx)
            if ctx['scheduled_applied'] or ctx.get('store_restored'):
                _flush(tx, ctx)
            tx.create(marker, {'operation': 'google_store_state_ignored', 'fingerprint': fingerprint,
                               'response': result, 'created_at': now_iso()})
            return result, None
        version_snap = doc(VERSIONS, _id(plan_version_id, 'plan_version_id')).get(transaction=tx)
        version = to_dict(version_snap) if version_snap.exists else None
        if not version or not version.get('google_play') or version.get('price_paise', 0) <= 0:
            raise SubscriptionError('Verified product has no paid plan mapping', 409, 'PLAN_CHANGED')
        plan_snap = doc(PLANS, version['plan_id']).get(transaction=tx)
        plan = plan_snap.to_dict() or {}
        if not plan_snap.exists:
            raise SubscriptionError('Plan identity is missing', 409, 'PLAN_CHANGED')
        before = deepcopy(ctx['account'])
        grant = {'uid': 'grant_' + operation_id[:40], 'vendor_id': vendor_id, 'kind': 'google_play',
                 'plan_id': version['plan_id'], 'plan_version_id': plan_version_id, 'plan_name': plan.get('name'),
                 'terms_snapshot': {name: deepcopy(version.get(name)) for name in TERM_FIELDS},
                 'starts_at': start.isoformat(), 'ends_at': end.isoformat(), 'grace_ends_at': grace.isoformat(),
                 'payment_state': 'store_verified', 'source_request_id': request_id, 'created_by': 'google_play',
                 'created_at': now_iso(), 'provider_state': provider_state, 'purchase_fingerprint': purchase_fingerprint,
                 'source_revision': source_revision, 'acknowledgement_state': acknowledgement_state, 'test_purchase': test_purchase}
        current = ctx['grant']
        override = _complimentary_live(current)
        _reference_plan(tx, {**plan, 'uid': version['plan_id']})
        tx.create(doc(GRANTS, grant['uid']), {name: value for name, value in grant.items() if name != 'uid'})
        ctx['account'].update(store_purchase_fingerprint=purchase_fingerprint, store_source_revision=source_revision,
                              store_grant_id=grant['uid'], provider_state=provider_state,
                              revision=ctx['account']['revision'] + 1, updated_at=now_iso())
        ctx['store_grant'] = grant
        if not override:
            ctx['grant'] = grant
            ctx['account']['current_grant_id'] = grant['uid']
        if current_request:
            completed = {**request_data, 'status': 'fulfilled', 'revision': request_data['revision'] + 1,
                         'grant_id': grant['uid'], 'updated_at': now_iso(), 'account_revision': ctx['account']['revision']}
            tx.update(doc(REQUESTS, request_id), {name: value for name, value in completed.items() if name != 'uid'})
            ctx['account']['pending_request_id'] = None
            ctx['request'] = None
        _flush(tx, ctx)
        _audit(tx, operation_id, 'google_play', 'subscription_store_state', vendor_id, before, ctx['account'], 'Verified Google Play lifecycle state')
        result = _aggregate(ctx)
        tx.create(marker, {'operation': 'google_store_state', 'fingerprint': fingerprint, 'response': result, 'created_at': now_iso()})
        event = _notice(tx, vendor_id, operation_id, 'Google Play subscription status was verified. Review your shop access.')
        return result, event
    result, event = apply(db().transaction())
    deliver_push(event, lookup=doc)
    return result


# These plans perform every read before returning a write closure. Callers must
# invoke the closure only after their own validation/reads, in the same transaction.
def catalog_change_plan(tx, vendor_id, *, delta=0, capability='catalog_growth', lookup=None):
    lookup = lookup or doc
    control_snap = lookup(SETTINGS, 'control').get(transaction=tx)
    if not control_snap.exists:
        # Additive deployment is inert until the reviewed rollout is prepared.
        return lambda: None
    control = control_snap.to_dict() or {}
    _integer(abs(delta), 'catalog change', 0, 200)
    if type(delta) is not int or capability not in CAPABILITIES:
        raise SubscriptionError('Invalid catalog operation')
    ctx = _context(tx, vendor_id)
    if ctx['account'].get('quota_fence'):
        raise SubscriptionError('Catalog reconciliation is in progress; retry shortly', 409, 'SUBSCRIPTION_MIGRATION_REQUIRED')
    usage = ctx['account'].get('usage') or {}
    initialized = usage.get('initialized') is True
    if control.get('enforcement_enabled') is True:
        if not ctx['exists'] or not initialized:
            raise SubscriptionError('Catalog count needs migration before growth', 409, 'SUBSCRIPTION_MIGRATION_REQUIRED')
        if delta >= 0:
            aggregate = _aggregate(ctx)
            features = (ctx.get('grant') or {}).get('terms_snapshot', {}).get('entitlements', {})
            if (aggregate['status'] not in {'active', 'grace', 'legacy_unrestricted'} or features.get(capability) is not True
                    or capability == 'product_import' and features.get('catalog_growth') is not True):
                raise SubscriptionError('An approved subscription is required for this action', 403, 'SUBSCRIPTION_REQUIRED')
            maximum = features.get('max_items')
            if delta > 0 and maximum is not None and usage['product_count'] + delta > maximum:
                raise SubscriptionError('This operation exceeds the plan product limit', 409, 'PRODUCT_LIMIT_REACHED')
    if initialized and delta:
        current = _integer(usage.get('product_count'), 'product_count', 0, 1000000000)
        if current + delta < 0:
            raise SubscriptionError('Catalog count needs reconciliation', 409, 'SUBSCRIPTION_MIGRATION_REQUIRED')
        ctx['account']['usage'] = {**usage, 'product_count': current + delta}
        ctx['account'].update(revision=ctx['account']['revision'] + 1, updated_at=now_iso())
    changed = bool(initialized and delta or ctx['scheduled_applied'] or ctx.get('store_restored'))
    return (lambda: _flush(tx, ctx)) if changed else (lambda: None)


def _legacy_grant(vendor_id, grant_id, actor_id, reason):
    return {'uid': grant_id, 'vendor_id': vendor_id, 'kind': 'legacy_unrestricted', 'plan_id': None,
            'plan_version_id': None, 'plan_name': 'Legacy access',
            'terms_snapshot': {'entitlements': {'max_items': None, **{name: True for name in CAPABILITIES}}},
            'starts_at': _now().isoformat(), 'ends_at': None, 'grace_ends_at': None,
            'payment_state': 'not_attested', 'created_at': now_iso(), 'created_by': actor_id, 'reason': reason}


def vendor_activation_plan(tx, vendor_id, actor_id, *, lookup=None):
    lookup = lookup or doc
    settings = lookup(SETTINGS, 'control').get(transaction=tx)
    if not settings.exists:
        return lambda: None
    control = settings.to_dict() or {}
    account_ref = doc(ACCOUNTS, vendor_id)
    previous = account_ref.get(transaction=tx)
    if previous.exists:
        return lambda: None  # A role change never erases prior access/history.
    products = list(tx.get(col(SHOP_ITEMS).where(filter=FieldFilter('vendor_id', '==', vendor_id))))
    account = _empty_account(vendor_id)
    account.update(revision=1, activated_at=now_iso(), activation_mode='enforced' if control.get('ever_enforced') else 'preparing',
                   legacy_baseline_migrated=not bool(control.get('ever_enforced')),
                   usage={'product_count': len(products), 'initialized': True, 'schema_version': 1}, updated_at=now_iso())
    grant = None if control.get('ever_enforced') else _legacy_grant(vendor_id, 'legacy_' + vendor_id, actor_id,
                'Vendor activated before first subscription enforcement; payment is not attested.')
    if grant:
        account['current_grant_id'] = grant['uid']
    def write():
        if grant:
            tx.create(doc(GRANTS, grant['uid']), {name: value for name, value in grant.items() if name != 'uid'})
        tx.create(account_ref, account)
        _audit(tx, 'activation_' + vendor_id, actor_id, 'subscription_vendor_activated', vendor_id,
               None, account, 'Initialize canonical access at vendor role activation.')
    return write


def rollout_action(actor_id, key, payload):
    action = payload.get('action')
    allowed = {'action', 'revision', 'reason', 'cutoff_at', 'security_rules_proof', 'client_compatibility_proof'}
    if set(payload) - allowed or action not in {'prepare', 'enable', 'pause'}:
        raise SubscriptionError('Choose prepare, enable or pause with reviewed rollout fields')
    reason = _text(payload.get('reason'), 'reason')
    def change(tx, operation_id, actor):
        control = settings_tx(tx)
        _check_revision(control['revision'], payload.get('revision'))
        before = deepcopy(control)
        if action == 'prepare':
            cutoff = _date(payload.get('cutoff_at'), 'cutoff_at')
            if cutoff > _now():
                raise SubscriptionError('Migration cutoff cannot be in the future')
            if control.get('cutoff_at') and _date(control['cutoff_at']) != cutoff:
                raise SubscriptionError('Reviewed migration cutoff is immutable', 409, 'REVISION_CONFLICT')
            if control.get('ever_enforced'):
                raise SubscriptionError('A completed rollout cannot be prepared again', 409)
            control.update(phase='preparing', enforcement_enabled=False, cutoff_at=cutoff.isoformat())
        elif action == 'pause':
            control.update(phase='paused', enforcement_enabled=False)
        else:
            if not control.get('cutoff_at'):
                raise SubscriptionError('Prepare and complete migration first', 409, 'SUBSCRIPTION_MIGRATION_REQUIRED')
            rules_proof = _text(payload.get('security_rules_proof'), 'security_rules_proof', 2000)
            client_proof = _text(payload.get('client_compatibility_proof'), 'client_compatibility_proof', 2000)
            vendors = list(tx.get(col(USERS).where(filter=FieldFilter('role', '==', 'vendor')).limit(2001)))
            if len(vendors) > 2000:
                raise SubscriptionError('Use a reviewed batched rollout for more than 2000 vendors', 409, 'SUBSCRIPTION_MIGRATION_REQUIRED')
            accounts = [doc(ACCOUNTS, row.id).get(transaction=tx) for row in vendors]
            for row in accounts:
                account = row.to_dict() or {}
                if not row.exists or not account.get('usage', {}).get('initialized') or account.get('quota_fence'):
                    raise SubscriptionError('Every vendor must have reconciled catalog coverage', 409, 'SUBSCRIPTION_MIGRATION_REQUIRED')
                if not (account.get('legacy_baseline_migrated') or account.get('legacy_cohort_reviewed')
                        or account.get('activation_mode') == 'enforced'):
                    raise SubscriptionError('Every preexisting vendor needs reviewed baseline coverage', 409, 'SUBSCRIPTION_MIGRATION_REQUIRED')
            control.update(phase='enforced', enforcement_enabled=True, ever_enforced=True,
                           security_rules_proof=rules_proof, client_compatibility_proof=client_proof, covered_vendors=len(vendors))
        control.update(revision=control['revision'] + 1, updated_at=now_iso(), updated_by=actor_id)
        tx.set(doc(SETTINGS, 'control'), control)
        _audit(tx, operation_id, actor_id, 'subscription_rollout_' + action, None, before, control, reason)
        return {**control, 'operation_id': operation_id}, 200, None
    return _operation(actor_id, 'rollout_' + str(action), key, payload, change)


def reconciliation(actor_id, vendor_id, key, payload):
    action = payload.get('action')
    if set(payload) - {'action', 'reason', 'expected_account_revision', 'job_id', 'revision', 'limit', 'cohort_review'} or action not in {'start', 'scan', 'finish', 'dry_run'}:
        raise SubscriptionError('Choose bounded reconciliation start, scan, finish or dry_run')
    if 'cohort_review' in payload and (action != 'start' or payload['cohort_review'] not in {'preexisting', 'post_cutoff'}):
        raise SubscriptionError('cohort_review is only accepted on start as preexisting or post_cutoff')
    reason = _text(payload.get('reason'), 'reason')
    limit = _integer(payload.get('limit', 100), 'limit', 1, 100)
    def run(tx, operation_id, actor):
        control = settings_tx(tx)
        if not control.get('cutoff_at'):
            raise SubscriptionError('Prepare a reviewed migration cutoff first', 409, 'SUBSCRIPTION_MIGRATION_REQUIRED')
        ctx = _context(tx, vendor_id)
        account = ctx['account']
        if action in {'start', 'dry_run'}:
            _check_revision(account['revision'], payload.get('expected_account_revision'))
            if account.get('quota_fence'):
                raise SubscriptionError('A reconciliation is already in progress', 409, 'SUBSCRIPTION_MIGRATION_REQUIRED')
            cohort = _legacy_cohort(ctx, control)
            reviewed = payload.get('cohort_review')
            if reviewed:
                if not cohort['cohort_review_required'] or control.get('ever_enforced'):
                    raise SubscriptionError('Only unresolved legacy dates may be reviewed before first enforcement', 409, 'SUBSCRIPTION_COHORT_REVIEW_REQUIRED')
                cohort.update(legacy_baseline_eligible=reviewed == 'preexisting', cohort_review_required=False,
                              cohort_basis='admin_reviewed_' + reviewed, cohort_reviewed_by=actor_id,
                              cohort_reviewed_at=now_iso())
            if action == 'start' and cohort['cohort_review_required']:
                raise SubscriptionError('Review this vendor legacy date cohort before starting migration', 409, 'SUBSCRIPTION_COHORT_REVIEW_REQUIRED')
            eligible = cohort['legacy_baseline_eligible']
            prior_grants = list(tx.get(col(GRANTS).where(filter=FieldFilter('vendor_id', '==', vendor_id)).limit(1)))
            if action == 'dry_run':
                sampled = list(tx.get(col(SHOP_ITEMS).where(filter=FieldFilter('vendor_id', '==', vendor_id)).limit(limit + 1)))
                return {'observed_product_count': min(len(sampled), limit), 'product_count_is_complete': len(sampled) <= limit,
                        'sample_limit': limit, 'count_is_fenced': False, 'vendor_id': vendor_id, 'account_revision': account['revision'], **cohort,
                        'would_grant_legacy': bool(eligible and not prior_grants and not account.get('legacy_baseline_migrated')),
                        'usage_initialized': bool(account.get('usage', {}).get('initialized')), 'writes_business_state': False}, 200, None
            job_id = 'reconcile_' + operation_id[:40]
            job = {'vendor_id': vendor_id, 'revision': 1, 'status': 'scanning', 'product_count': 0, 'last_product_id': None,
                   **cohort, 'grant_baseline': bool(eligible and not prior_grants and not account.get('legacy_baseline_migrated')),
                   'cutoff_at': control['cutoff_at'], 'reason': reason, 'created_by': actor_id, 'created_at': now_iso()}
            account.update(quota_fence=job_id, revision=account['revision'] + 1, updated_at=now_iso())
            tx.create(doc(MIGRATIONS, job_id), job)
            _flush(tx, ctx)
            _audit(tx, operation_id, actor_id, 'subscription_reconciliation_start', vendor_id, ctx['before_account'], account, reason)
            return {**job, 'uid': job_id, 'account_revision': account['revision'], 'operation_id': operation_id}, 201, None
        job_id = _id(payload.get('job_id'), 'job_id')
        job_ref = doc(MIGRATIONS, job_id)
        snap = job_ref.get(transaction=tx)
        job = snap.to_dict() or {}
        if not snap.exists or job.get('vendor_id') != vendor_id:
            raise SubscriptionError('Reconciliation job not found', 404)
        _check_revision(job.get('revision'), payload.get('revision'))
        if account.get('quota_fence') != job_id:
            raise SubscriptionError('Reconciliation fence changed', 409, 'REVISION_CONFLICT')
        if action == 'scan':
            if job.get('status') != 'scanning':
                raise SubscriptionError('Reconciliation scan is complete', 409)
            query = col(SHOP_ITEMS).where(filter=FieldFilter('vendor_id', '==', vendor_id)).order_by('__name__')
            if job.get('last_product_id'):
                query = query.start_after({'__name__': doc(SHOP_ITEMS, job['last_product_id'])})
            products = list(tx.get(query.limit(limit + 1)))
            chosen = products[:limit]
            before_job = deepcopy(job)
            job.update(product_count=job['product_count'] + len(chosen), last_product_id=chosen[-1].id if chosen else job.get('last_product_id'),
                       status='scanning' if len(products) > limit else 'scanned', revision=job['revision'] + 1, updated_at=now_iso())
            tx.set(job_ref, job)
            _audit(tx, operation_id, actor_id, 'subscription_reconciliation_scan', vendor_id, before_job, job, reason)
            return {**job, 'uid': job_id, 'operation_id': operation_id}, 200, None
        if job.get('status') != 'scanned':
            raise SubscriptionError('Finish the complete fenced scan first', 409)
        before = deepcopy(account)
        prior_grants = list(tx.get(col(GRANTS).where(filter=FieldFilter('vendor_id', '==', vendor_id)).limit(1)))
        baseline = _legacy_grant(vendor_id, 'legacy_' + vendor_id, actor_id, job['reason']) if job.get('grant_baseline') and not prior_grants and not account.get('legacy_baseline_migrated') else None
        if baseline:
            tx.create(doc(GRANTS, baseline['uid']), {name: value for name, value in baseline.items() if name != 'uid'})
            ctx['grant'] = baseline
            account['current_grant_id'] = baseline['uid']
        account.update(usage={'product_count': job['product_count'], 'initialized': True, 'schema_version': 1},
                       quota_fence=None, legacy_baseline_migrated=bool(account.get('legacy_baseline_migrated') or job['legacy_baseline_eligible']),
                       legacy_cohort_reviewed=not job.get('cohort_review_required', True), legacy_cohort_basis=job.get('cohort_basis'),
                       legacy_cohort_date_status=job.get('cohort_date_status'),
                       legacy_cohort_eligible=job['legacy_baseline_eligible'], legacy_cohort_manifest_id=job_id,
                       revision=account['revision'] + 1, updated_at=now_iso())
        job.update(status='completed', revision=job['revision'] + 1, completed_at=now_iso(), account_revision=account['revision'])
        tx.set(job_ref, job)
        _flush(tx, ctx)
        _audit(tx, operation_id, actor_id, 'subscription_reconciliation_completed', vendor_id, before, account, reason)
        return {'job': {**job, 'uid': job_id}, 'subscription': _aggregate(ctx), 'operation_id': operation_id}, 200, None
    return _operation(actor_id, 'reconciliation_' + str(action) + ':' + vendor_id, key, payload, run, persist=action != 'dry_run')
