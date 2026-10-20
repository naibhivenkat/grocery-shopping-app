"""Admin-managed global advertisements, separate from vendor promotions.

The authenticated feed returns one scheduled advertisement. Session display
frequency belongs to the client; no customer identifiers or impressions persist.
"""
from datetime import datetime, timezone

from firebase_admin import firestore
from flask import Blueprint, g, jsonify

from auth_utils import require_role
from db import AUDIT_LOGS, USERS, col, db, doc, now_iso, to_dict
from routes.khata import KhataError, _khata_error, _payload
from routes.promotions import PromotionError, _date, _id, _image, _text

advertisements_bp = Blueprint('advertisements', __name__)
advertisements_bp.register_error_handler(KhataError, _khata_error)
advertisements_bp.register_error_handler(PromotionError, lambda error: (jsonify({'detail': error.detail}), error.status))
ADVERTISEMENTS = 'advertisements'
FIELDS = {'title', 'body', 'image_url', 'starts_at', 'ends_at', 'is_active', 'priority'}
PUBLIC_FIELDS = {'uid', 'title', 'body', 'image_url', 'starts_at', 'ends_at', 'priority', 'revision'}


def _admin(tx):
    snapshot = doc(USERS, g.user_id).get(transaction=tx)
    account = snapshot.to_dict() or {}
    if not snapshot.exists or account.get('is_suspended') or account.get('role') not in {'admin', 'super_admin'}:
        raise KhataError('Current administrator permissions required', 403)


def _content(payload):
    starts = _date(payload.get('starts_at'), 'starts_at')
    ends = _date(payload.get('ends_at'), 'ends_at')
    if ends <= starts:
        raise KhataError('ends_at must be after starts_at')
    active = payload.get('is_active', False)
    priority = payload.get('priority', 0)
    if type(active) is not bool:
        raise KhataError('is_active must be true or false')
    if type(priority) is not int or not 0 <= priority <= 1000:
        raise KhataError('priority must be an integer from 0 to 1000')
    image = _image(payload.get('image_url'))
    if image is None:
        raise KhataError('An advertisement image is required')
    return {'title': _text(payload.get('title'), 'title', 100, required=True),
            'body': _text(payload.get('body'), 'body', 1000), 'image_url': image,
            'starts_at': starts.isoformat(), 'ends_at': ends.isoformat(), 'is_active': active, 'priority': priority}


def _revision(payload):
    revision = payload.get('revision')
    if type(revision) is not int or revision < 1:
        raise KhataError('The reviewed advertisement revision is required')
    return revision


@advertisements_bp.get('/advertisements/active')
@require_role('customer', 'vendor', 'service')
def active_advertisement():
    now = datetime.now(timezone.utc)
    candidates = []
    for snapshot in col(ADVERTISEMENTS).stream():
        data = to_dict(snapshot)
        if data.get('is_active') is not True or data.get('deleted_at'):
            continue
        try:
            # Validate persisted data too: malformed legacy/admin records never
            # become a broken popup or an unsafe image URL in the active feed.
            value = _content(data)
            if not _date(value['starts_at'], 'starts_at') <= now < _date(value['ends_at'], 'ends_at'):
                continue
            if type(data.get('revision')) is not int or data['revision'] < 1:
                continue
        except (KhataError, PromotionError):
            continue
        candidates.append({key: {**data, **value}.get(key) for key in PUBLIC_FIELDS})
    candidates.sort(key=lambda value: (-value['priority'], value['uid']))
    return jsonify(candidates[0] if candidates else None)


@advertisements_bp.get('/admin/advertisements')
@require_role('admin', 'super_admin')
def list_advertisements():
    values = [to_dict(snapshot) for snapshot in col(ADVERTISEMENTS).stream()
              if not (snapshot.to_dict() or {}).get('deleted_at')]
    values.sort(key=lambda value: (value.get('updated_at') or '', value['uid']), reverse=True)
    return jsonify(values)


@advertisements_bp.post('/admin/advertisements')
@require_role('admin', 'super_admin')
def create_advertisement():
    payload = _payload()
    if set(payload) - FIELDS:
        raise KhataError('Unsupported advertisement fields')
    content = _content(payload)
    ref, audit_ref = col(ADVERTISEMENTS).document(), col(AUDIT_LOGS).document()

    @firestore.transactional
    def create(tx):
        _admin(tx)
        timestamp = now_iso()
        data = {**content, 'revision': 1, 'created_by': g.user_id, 'updated_by': g.user_id,
                'created_at': timestamp, 'updated_at': timestamp, 'deleted_at': None}
        tx.create(ref, data)
        tx.set(audit_ref, {'action': 'advertisement_created', 'advertisement_id': ref.id,
                           'actor_id': g.user_id, 'revision': 1, 'created_at': timestamp})
        return {**data, 'uid': ref.id}

    return jsonify(create(db().transaction())), 201


@advertisements_bp.put('/admin/advertisements/<advertisement_id>')
@require_role('admin', 'super_admin')
def update_advertisement(advertisement_id):
    payload = _payload()
    if set(payload) - (FIELDS | {'revision'}) or not (set(payload) & FIELDS):
        raise KhataError('Supply revision and advertisement fields to update')
    revision = _revision(payload)
    ref = doc(ADVERTISEMENTS, _id(advertisement_id, 'advertisement_id'))
    audit_ref = col(AUDIT_LOGS).document()

    @firestore.transactional
    def update(tx):
        _admin(tx)
        snapshot = ref.get(transaction=tx)
        data = snapshot.to_dict() or {}
        if not snapshot.exists or data.get('deleted_at'):
            raise KhataError('Advertisement not found', 404)
        if data.get('revision') != revision:
            raise KhataError('Advertisement changed; review the latest revision', 409)
        content = _content({**data, **{key: value for key, value in payload.items() if key in FIELDS}})
        timestamp = now_iso()
        changes = {**content, 'revision': revision + 1, 'updated_at': timestamp, 'updated_by': g.user_id}
        tx.update(ref, changes)
        tx.set(audit_ref, {'action': 'advertisement_updated', 'advertisement_id': ref.id,
                           'actor_id': g.user_id, 'revision': revision + 1, 'created_at': timestamp})
        return {**data, **changes, 'uid': ref.id}

    return jsonify(update(db().transaction()))


@advertisements_bp.delete('/admin/advertisements/<advertisement_id>')
@require_role('admin', 'super_admin')
def delete_advertisement(advertisement_id):
    payload = _payload()
    if set(payload) != {'revision'}:
        raise KhataError('Supply the advertisement revision only')
    revision = _revision(payload)
    ref = doc(ADVERTISEMENTS, _id(advertisement_id, 'advertisement_id'))
    audit_ref = col(AUDIT_LOGS).document()

    @firestore.transactional
    def remove(tx):
        _admin(tx)
        snapshot = ref.get(transaction=tx)
        data = snapshot.to_dict() or {}
        if not snapshot.exists:
            raise KhataError('Advertisement not found', 404)
        if data.get('deleted_at') and data.get('revision') == revision + 1:
            return {'uid': ref.id, 'deleted': True, 'revision': data['revision']}
        if data.get('revision') != revision or data.get('deleted_at'):
            raise KhataError('Advertisement changed; review the latest revision', 409)
        timestamp = now_iso()
        tx.update(ref, {'deleted_at': timestamp, 'is_active': False, 'revision': revision + 1,
                        'updated_at': timestamp, 'updated_by': g.user_id})
        tx.set(audit_ref, {'action': 'advertisement_deleted', 'advertisement_id': ref.id,
                           'actor_id': g.user_id, 'revision': revision + 1, 'created_at': timestamp})
        return {'uid': ref.id, 'deleted': True, 'revision': revision + 1}

    return jsonify(remove(db().transaction()))
