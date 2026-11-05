"""Typed favorites; storage is exclusively the configured Firestore collection.

Legacy product/provider memberships are read without migrating their documents.
"""
import hashlib
import json
import unicodedata

from flask import g, jsonify, request
from google.api_core.exceptions import AlreadyExists
from google.cloud.firestore_v1.base_query import FieldFilter

from auth_utils import require_auth
from db import USERS, SHOP_ITEMS, USER_FAVORITES, col, doc, now_iso

KINDS = ('shop', 'provider', 'product')


class FavoriteError(ValueError):
    def __init__(self, detail, status=422):
        super().__init__(detail)
        self.status = status


def identity(kind, entity_id):
    if not isinstance(kind, str) or kind not in KINDS:
        raise FavoriteError('kind must be shop, provider or product')
    try:
        byte_length = len(entity_id.encode('utf-8')) if isinstance(entity_id, str) else 0
    except UnicodeError:
        raise FavoriteError('entity_id must be valid UTF-8')
    if (not isinstance(entity_id, str) or not entity_id or
            byte_length > 256 or entity_id.strip() != entity_id or
            '/' in entity_id or entity_id in ('.', '..') or
            (entity_id.startswith('__') and entity_id.endswith('__')) or
            any(unicodedata.category(c).startswith('C') for c in entity_id)):
        raise FavoriteError('entity_id must be a valid document ID of at most 256 bytes')
    return kind, entity_id


def key(user, kind, entity_id):
    raw = json.dumps([user, kind, entity_id], ensure_ascii=True, separators=(',', ':'))
    return 'v2_' + hashlib.sha256(raw.encode()).hexdigest()


def legacy_key(user, kind, entity_id):
    if kind == 'product':
        return f'{user}__{entity_id}'
    if kind == 'provider':
        return f'{user}_{entity_id}'
    return None


def row_identity(row):
    # Typed rows must never be mistaken for legacy item/provider rows.
    if 'kind' in row:
        return identity(row.get('kind'), row.get('entity_id'))
    if row.get('shop_item_id'):
        return identity('product', row['shop_item_id'])
    if row.get('provider_id'):
        return identity('provider', row['provider_id'])
    raise FavoriteError('Unrecognized favorite')


def owned(ref, kind, entity_id):
    snap = ref.get()
    row = snap.to_dict() or {} if snap.exists else {}
    if row.get('user_id') != g.user_id:
        return False
    try:
        return row_identity(row) == (kind, entity_id)
    except FavoriteError:
        return False


def references(kind, entity_id):
    refs = [doc(USER_FAVORITES, key(g.user_id, kind, entity_id))]
    old = legacy_key(g.user_id, kind, entity_id)
    if old:
        refs.append(doc(USER_FAVORITES, old))
    return refs


def member(kind, entity_id):
    return any(owned(ref, kind, entity_id) for ref in references(kind, entity_id))


def display(kind, entity_id):
    snap = doc(SHOP_ITEMS if kind == 'product' else USERS, entity_id).get()
    data = snap.to_dict() or {} if snap.exists else {}
    available = snap.exists and not data.get('is_suspended') and not data.get('disabled_by_admin')
    if kind == 'shop':
        available = available and data.get('role') == 'vendor'
    elif kind == 'provider':
        profile = doc('provider_profiles', entity_id).get()
        available = available and profile.exists and (profile.to_dict() or {}).get('is_active') is not False
    if kind == 'product':
        name = data.get('name')
        images = data.get('image_urls')
        image = (images[0] if isinstance(images, list) and images else None) or data.get('image_url')
    else:
        name = (data.get('shop_name') if kind == 'shop' else None) or data.get('full_name') or data.get('username')
        image = data.get('avatar_url')
    return {'kind': kind, 'entity_id': entity_id, 'available': bool(available),
            'name': name if available and isinstance(name, str) else None,
            'image_url': image if available and isinstance(image, str) else None}


def no_extra_query(allowed=()):
    if set(request.args) - set(allowed) or any(len(request.args.getlist(k)) != 1 for k in request.args):
        raise FavoriteError('Unsupported query parameters')


def register_favorites(bp):
    """Attach to the existing registered blueprint, preserving its API prefixes."""
    @bp.errorhandler(FavoriteError)
    def favorite_error(error):
        return jsonify({'detail': str(error)}), error.status

    @bp.get('/favorites')
    @require_auth
    def typed_list_favorites():
        no_extra_query(('kind',))
        kind_filter = request.args.get('kind')
        if kind_filter is not None and kind_filter not in KINDS:
            raise FavoriteError('kind must be shop, provider or product')
        identities = set()
        for snapshot in col(USER_FAVORITES).where(filter=FieldFilter('user_id', '==', g.user_id)).stream():
            row = snapshot.to_dict() or {}
            if row.get('user_id') != g.user_id:
                continue
            try:
                kind, entity_id = row_identity(row)
            except FavoriteError:
                continue
            if kind_filter is None or kind_filter == kind:
                identities.add((kind, entity_id))
        return jsonify({'favorites': [display(k, i) for k, i in sorted(identities)]})

    @bp.post('/favorites')
    @require_auth
    def typed_add_favorite():
        no_extra_query()
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or set(payload) != {'kind', 'entity_id'}:
            raise FavoriteError('Exactly kind and entity_id are required')
        kind, entity_id = identity(payload['kind'], payload['entity_id'])
        if not display(kind, entity_id)['available']:
            raise FavoriteError('Favorite target not available', 404)
        if not member(kind, entity_id):
            try:
                references(kind, entity_id)[0].create({'user_id': g.user_id, 'kind': kind,
                    'entity_id': entity_id, 'created_at': now_iso()})
            except AlreadyExists:
                # Only an equal membership is a successful replay. Legacy keys
                # share this collection and must never authorize another owner.
                if not owned(references(kind, entity_id)[0], kind, entity_id):
                    raise FavoriteError('Favorite storage identity conflict', 409)
        return jsonify({'ok': True, 'kind': kind, 'entity_id': entity_id, 'is_favorite': True})

    @bp.delete('/favorites/<kind>/<entity_id>')
    @require_auth
    def typed_remove_favorite(kind, entity_id):
        no_extra_query()
        identity(kind, entity_id)
        for ref in references(kind, entity_id):
            if owned(ref, kind, entity_id):
                ref.delete()
        return jsonify({'ok': True, 'kind': kind, 'entity_id': entity_id, 'is_favorite': False})

    @bp.get('/favorites/<kind>/<entity_id>/check')
    @require_auth
    def typed_check_favorite(kind, entity_id):
        no_extra_query()
        identity(kind, entity_id)
        return jsonify({'kind': kind, 'entity_id': entity_id, 'is_favorite': member(kind, entity_id)})
