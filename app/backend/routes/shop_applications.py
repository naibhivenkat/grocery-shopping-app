"""Customer shop applications with revision-checked administrative approval."""
from firebase_admin import firestore
from flask import Blueprint, g, jsonify

from auth_utils import require_auth, require_role
from db import AUDIT_LOGS, CITIES, NOTIFICATIONS, USERS, col, db, doc, now_iso, to_dict
from notification_delivery import deliver_push, notification_data
from routes.khata import KhataError, _identifier, _khata_error, _payload, _text

shop_applications_bp = Blueprint('shop_applications', __name__)
shop_applications_bp.register_error_handler(KhataError, _khata_error)
APPLICATIONS = 'shop_applications'
FIELDS = {'shop_name', 'address', 'phone', 'city_id'}


def _account(tx, identifier, roles):
    snapshot = doc(USERS, identifier).get(transaction=tx)
    account = snapshot.to_dict() or {}
    if not snapshot.exists or account.get('is_suspended') or account.get('role') not in roles:
        raise KhataError('Current account permissions required', 403)
    return account


def _content(payload):
    if set(payload) != FIELDS:
        raise KhataError('Supply shop_name, address, phone and city_id only')
    result = {field: _text(payload[field], field, limit) for field, limit in (
        ('shop_name', 200), ('address', 1000), ('phone', 40))}
    if not all(result.values()):
        raise KhataError('Shop name, address and phone are required')
    result['city_id'] = _identifier(payload['city_id'], 'city_id')
    return result


@shop_applications_bp.get('/shop-applications/mine')
@require_auth
def mine():
    snapshot = doc(APPLICATIONS, g.user_id).get()
    return jsonify(to_dict(snapshot) if snapshot.exists else None)


@shop_applications_bp.post('/shop-applications')
@require_role('customer', 'vendor')
def apply():
    content = _content(_payload())
    ref = doc(APPLICATIONS, g.user_id)
    audit_ref = col(AUDIT_LOGS).document()

    @firestore.transactional
    def submit(tx):
        account = _account(tx, g.user_id, {'customer', 'vendor'})
        snap = ref.get(transaction=tx)
        existing = snap.to_dict() or {}
        if account['role'] == 'vendor':
            if existing.get('status') == 'approved':
                return {**existing, 'uid': ref.id}, 200
            raise KhataError('This account already has a shop', 409)
        if existing.get('status') == 'pending':
            if all(existing.get(field) == value for field, value in content.items()):
                return {**existing, 'uid': ref.id}, 200
            raise KhataError('An application is already awaiting review', 409)
        if existing and existing.get('status') != 'rejected':
            raise KhataError('Application requires administrative reconciliation', 409)
        city = doc(CITIES, content['city_id']).get(transaction=tx)
        if not city.exists or (city.to_dict() or {}).get('is_active') is False:
            raise KhataError('Choose an available city')
        timestamp = now_iso()
        data = {**content, 'applicant_id': g.user_id, 'status': 'pending',
                'revision': existing.get('revision', 0) + 1, 'reason': None,
                'reviewed_by': None, 'reviewed_at': None,
                'created_at': existing.get('created_at') or timestamp, 'updated_at': timestamp}
        tx.set(ref, data)
        tx.set(audit_ref, {'action': 'shop_application_submitted', 'actor_id': g.user_id,
                          'application_id': ref.id, 'revision': data['revision'], 'created_at': timestamp})
        return {**data, 'uid': ref.id}, 201

    body, status = submit(db().transaction())
    return jsonify(body), status


@shop_applications_bp.get('/admin/shop-applications')
@require_role('admin', 'super_admin')
def applications():
    items = [to_dict(snapshot) for snapshot in col(APPLICATIONS).stream()]
    items.sort(key=lambda value: value.get('updated_at') or '', reverse=True)
    return jsonify(items)


@shop_applications_bp.post('/admin/shop-applications/<application_id>/decision')
@require_role('admin', 'super_admin')
def decide(application_id):
    payload = _payload()
    if set(payload) - {'decision', 'reason', 'revision'}:
        raise KhataError('Supply decision, reason and revision only')
    decision = payload.get('decision')
    if not isinstance(decision, str) or decision not in {'approved', 'rejected'}:
        raise KhataError('Decision must be approved or rejected')
    revision = payload.get('revision')
    if type(revision) is not int or revision < 1:
        raise KhataError('A positive reviewed revision is required')
    reason = _text(payload.get('reason'), 'reason', 500)
    if decision == 'rejected' and not reason:
        raise KhataError('A rejection reason is required')
    applicant_id = _identifier(application_id, 'application_id')
    ref = doc(APPLICATIONS, applicant_id)
    user_ref = doc(USERS, applicant_id)
    audit_ref = col(AUDIT_LOGS).document()
    notification_ref = col(NOTIFICATIONS).document()

    @firestore.transactional
    def review(tx):
        _account(tx, g.user_id, {'admin', 'super_admin'})
        snap = ref.get(transaction=tx)
        if not snap.exists:
            raise KhataError('Application not found', 404)
        application = snap.to_dict() or {}
        applicant = _account(tx, applicant_id, {'customer', 'vendor'})
        if application.get('applicant_id') != applicant_id:
            raise KhataError('Application applicant mismatch', 409)
        if application.get('revision') != revision:
            raise KhataError('Application changed; review the latest revision', 409)
        if application.get('status') != 'pending':
            if (application.get('status') == decision and application.get('reason') == (reason or None)
                    and application.get('reviewed_by') == g.user_id):
                return {**application, 'uid': ref.id}, None
            raise KhataError('Application has already been reviewed', 409)
        if applicant.get('role') != 'customer':
            raise KhataError('Applicant is no longer a customer', 409)
        city = doc(CITIES, _identifier(application.get('city_id'), 'city_id')).get(transaction=tx)
        if decision == 'approved' and (not city.exists or (city.to_dict() or {}).get('is_active') is False):
            raise KhataError('Application city is unavailable', 409)
        timestamp = now_iso()
        changes = {'status': decision, 'reason': reason or None, 'reviewed_by': g.user_id,
                   'reviewed_at': timestamp, 'updated_at': timestamp}
        tx.set(ref, changes, merge=True)
        if decision == 'approved':
            tx.set(user_ref, {'role': 'vendor', 'shop_name': application['shop_name'],
                             'shop_address': application['address'], 'phone': application['phone'],
                             'city_id': application['city_id'], 'shop_approval_status': 'approved',
                             'updated_at': timestamp}, merge=True)
        tx.set(audit_ref, {'action': 'shop_application_' + decision, 'actor_id': g.user_id,
                          'application_id': ref.id, 'revision': revision, 'reason': reason or None,
                          'created_at': timestamp})
        event = notification_data(applicant_id, 'shop_application_' + decision,
                                  'Shop application ' + decision,
                                  'Your shop application was ' + decision + '.', applicant_id)
        tx.set(notification_ref, event)
        return {**application, **changes, 'uid': ref.id}, event

    body, event = review(db().transaction())
    deliver_push(event, lookup=doc)
    return jsonify(body)
