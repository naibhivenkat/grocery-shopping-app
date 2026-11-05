"""Saved-address HTTP contract with isolated Firestore doubles; no live writes."""
import copy
import unittest
from unittest.mock import patch
from flask import Flask
from google.api_core.exceptions import NotFound
import auth_utils
import db as storage
from routes import profile


class Snapshot:
    def __init__(self, ref):
        self.id = ref.path[-1]
        self.exists = ref.path in ref.data
        self.value = copy.deepcopy(ref.data.get(ref.path))
    def to_dict(self):
        return self.value


class Reference:
    def __init__(self, data, path):
        self.data, self.path = data, path
    def collection(self, name):
        return Collection(self.data, self.path + (name,))
    def get(self):
        return Snapshot(self)
    def create(self, value):
        assert self.path not in self.data
        self.data[self.path] = copy.deepcopy(value)
    def set(self, value, merge=False):
        self.data[self.path] = {**self.data.get(self.path, {}), **copy.deepcopy(value)} if merge else copy.deepcopy(value)
    def update(self, value):
        if self.path not in self.data:
            raise NotFound('deleted')
        self.data[self.path].update(copy.deepcopy(value))
    def delete(self):
        self.data.pop(self.path, None)


class Collection:
    def __init__(self, data, path):
        self.data, self.path = data, path
    def document(self, identifier):
        return Reference(self.data, self.path + (identifier,))
    def stream(self):
        return [Snapshot(Reference(self.data, p)) for p in self.data if p[:-1] == self.path]


class SavedAddressTests(unittest.TestCase):
    def setUp(self):
        self.data = {('users', 'alice'): {'address': 'Legacy fixture', 'full_name': 'Alice', 'password_hash': 'private'}, ('users', 'bob'): {'role': 'customer'}}
        self.app = Flask(__name__)
        self.app.config['TESTING'] = True
        self.app.register_blueprint(profile.profile_bp)
        for p in (patch.object(storage, 'doc', lambda c, i: Reference(self.data, (c, i))),
                  patch.object(profile, 'doc', lambda c, i: Reference(self.data, (c, i))),
                  patch.object(auth_utils, 'decode_token', lambda token: {'sub': token})):
            p.start()
            self.addCleanup(p.stop)
        self.client = self.app.test_client()
    def call(self, method='GET', identifier='', body=None, user='alice'):
        return self.client.open('/profile/addresses'+('/'+identifier if identifier else ''), method=method,
                                json=body, headers={'Authorization': 'Bearer '+user})
    def create(self, label='Home'):
        r = self.call('POST', body={'label': label, 'address': ' Synthetic address '})
        self.assertEqual(r.status_code, 201)
        return r.json['id']
    def test_two_addresses_independent_crud_and_legacy_profile(self):
        before = self.client.get('/profile', headers={'Authorization': 'Bearer alice'}).json
        a, b = self.create(), self.create('Office')
        self.assertNotEqual(a, b)
        self.assertEqual(len(self.call().json['addresses']), 2)
        self.assertEqual(self.call(identifier=a).json['address'], 'Synthetic address')
        created = self.call(identifier=a).json['created_at']
        r = self.call('PUT', a, {'label': 'New', 'address': 'Replacement fixture'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json['created_at'], created)
        self.assertEqual(self.call(identifier=b).json['label'], 'Office')
        self.assertEqual(self.call('DELETE', a).status_code, 200)
        self.assertEqual(self.call(identifier=a).status_code, 404)
        self.assertEqual(len(self.call().json['addresses']), 1)
        self.assertEqual(self.client.get('/profile', headers={'Authorization': 'Bearer alice'}).json, before)
        self.assertNotIn('password_hash', before)
        r = self.client.put('/profile', json={'address': 'Changed legacy'}, headers={'Authorization': 'Bearer alice'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.call(identifier=b).json['label'], 'Office')
    def test_cross_user_missing_stale_and_malformed_ids(self):
        a = self.create()
        before = copy.deepcopy(self.data)
        for verb in ('GET', 'PUT', 'DELETE'):
            for identifier, user in ((a, 'bob'), ('0'*32, 'alice')):
                self.assertEqual(self.call(verb, identifier, {'label': 'X', 'address': 'Y'}, user).status_code, 404)
            self.assertEqual(self.call(verb, 'invalid', {'label': 'X', 'address': 'Y'}).status_code, 422)
        self.assertEqual(self.call(user='bob').json, {'addresses': []})
        self.assertEqual(before, self.data)
        self.call('DELETE', a)
        self.assertEqual(self.call('PUT', a, {'label': 'X', 'address': 'Y'}).status_code, 404)
        self.assertEqual(self.call('DELETE', a).status_code, 404)
    def test_strict_payload_validation_without_writes(self):
        a = self.create()
        bad = [None, [], 'bad', {}, {'label': 'Home'}, {'label': 'Home', 'address': 'A', 'user_id': 'bob'},
               {'label': 'Home', 'address': 'A', 'id': a}, {'label': 'Home', 'address': 'A', 'is_default': True}]
        for key, limit in (('label', 80), ('address', 1000)):
            for value in (' ', '', 1, True, [], {}, None, 'x'*(limit+1)):
                bad.append({'label': 'Home', 'address': 'A', key: value})
        before = copy.deepcopy(self.data)
        for verb, identifier in (('POST', ''), ('PUT', a)):
            for body in bad:
                with self.subTest(verb=verb, body=body):
                    self.assertEqual(self.call(verb, identifier, body).status_code, 422)
        self.assertEqual(self.data, before)
    def test_boundaries_invalid_json_and_account_state(self):
        r = self.call('POST', body={'label': 'L'*80, 'address': 'A'*1000})
        self.assertEqual(r.status_code, 201)
        identifier = r.json['id']
        for method, suffix in (('POST', ''), ('PUT', '/'+identifier)):
            for raw in ('{"bad":', 'null', '[]', 'false'):
                self.assertEqual(self.client.open('/profile/addresses'+suffix, method=method,
                    data=raw, content_type='application/json',
                    headers={'Authorization': 'Bearer alice'}).status_code, 422)
        self.assertEqual(self.call(user='missing').status_code, 401)
        self.data[('users', 'alice')]['is_suspended'] = True
        self.assertEqual(self.call().status_code, 403)

    def test_authentication_required_on_every_method(self):
        for method, path in (('GET', ''), ('POST', ''), ('GET', '/'+ '0'*32), ('PUT', '/'+ '0'*32), ('DELETE', '/'+ '0'*32)):
            self.assertEqual(self.client.open('/profile/addresses'+path, method=method).status_code, 401)
    def test_update_racing_delete_does_not_resurrect(self):
        a = self.create()
        def deleted(ref, value):
            ref.delete()
            raise NotFound('deleted concurrently')
        with patch.object(Reference, 'update', deleted):
            self.assertEqual(self.call('PUT', a, {'label': 'X', 'address': 'Y'}).status_code, 404)
        self.assertEqual(self.call(identifier=a).status_code, 404)


if __name__ == '__main__':
    unittest.main()
