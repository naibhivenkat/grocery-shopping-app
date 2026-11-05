"""HTTP/storage-call contracts against synthetic doubles, no live IO."""
import copy
import unittest
from unittest.mock import patch, MagicMock
from flask import Flask
from google.api_core.exceptions import AlreadyExists, ServiceUnavailable
import auth_utils
import db as storage
from routes import favorites, shops, services
from tests.test_saved_addresses import Reference, Collection


class FavoriteReference(Reference):
    def create(self, value):
        if self.path in self.data:
            raise AlreadyExists('synthetic duplicate')
        self.data[self.path] = copy.deepcopy(value)


class FavoriteCollection(Collection):
    def __init__(self, data, path, filters=()):
        super().__init__(data, path)
        self.filters = filters
    def document(self, identifier):
        return FavoriteReference(self.data, self.path + (identifier,))
    def where(self, *, filter):
        return FavoriteCollection(self.data, self.path, self.filters + ((filter.field_path, filter.value),))
    def stream(self):
        return [s for s in super().stream() if all((s.to_dict() or {}).get(k) == v for k,v in self.filters)]


class TypedFavoritesTests(unittest.TestCase):
    def setUp(self):
        self.data={('users','alice'):{'role':'customer'},('users','bob'):{'role':'customer'},
            ('users','shared'):{'role':'vendor','shop_name':'Synthetic shop','full_name':'Synthetic provider','password_hash':'private'},
            ('provider_profiles','shared'):{'is_active':True},('shop_items','shared'):{'name':'Synthetic product','price':10}}
        for module in (storage,favorites,shops,services):
            for attr,value in [('doc',lambda c,i:FavoriteReference(self.data,(c,i))),('col',lambda c:FavoriteCollection(self.data,(c,)))]:
                p=patch.object(module,attr,value);p.start();self.addCleanup(p.stop)
        p=patch.object(auth_utils,'decode_token',lambda t:{'sub':t});p.start();self.addCleanup(p.stop)
        self.client=self.new_app().test_client()
    def new_app(self):
        app=Flask(__name__);app.config['TESTING']=True
        app.register_blueprint(shops.shops_bp);app.register_blueprint(services.services_bp)
        return app
    def call(self,method='GET',suffix='',body=None,user='alice'):
        return self.client.open('/favorites'+suffix,method=method,json=body,headers={} if user is None else {'Authorization':'Bearer '+user})
    def add(self,kind,entity='shared'):
        return self.call('POST',body={'kind':kind,'entity_id':entity})
    def test_identical_ids_all_kinds_and_replays(self):
        for k in favorites.KINDS:self.assertEqual(self.add(k).status_code,200)
        before=copy.deepcopy(self.data)
        for k in favorites.KINDS:
            self.assertEqual(self.add(k).status_code,200)
            self.assertTrue(self.call(suffix='/'+k+'/shared/check').json['is_favorite'])
        self.assertEqual(before,self.data)
        self.assertEqual(len(self.call().json['favorites']),3)
        self.assertEqual(len(self.call(suffix='?kind=shop').json['favorites']),1)
        for k in favorites.KINDS:
            for _ in range(2):self.assertEqual(self.call('DELETE','/'+k+'/shared').status_code,200)
            self.assertFalse(self.call(suffix='/'+k+'/shared/check').json['is_favorite'])
        self.assertEqual(self.call().json,{'favorites':[]})
    def test_scope_auth_and_private_fields(self):
        self.add('shop');before=copy.deepcopy(self.data)
        self.assertEqual(self.call(user='bob').json,{'favorites':[]})
        self.assertFalse(self.call(suffix='/shop/shared/check',user='bob').json['is_favorite'])
        self.call('DELETE','/shop/shared',user='bob');self.assertEqual(before,self.data)
        for verb,suffix,body in [('GET','',None),('POST','',{'kind':'shop','entity_id':'shared'}),('DELETE','/shop/shared',None),('GET','/shop/shared/check',None)]:
            for user in (None,'absent'):self.assertEqual(self.call(verb,suffix,body,user).status_code,401)
        self.data['users','bob']['is_suspended']=True
        self.assertEqual(self.call(user='bob').status_code,403)
        self.assertNotIn('password_hash',str(self.call().json))
        self.assertEqual(self.call(suffix='?user_id=bob').status_code,422)
        self.assertEqual(self.call('POST',body={'kind':'shop','entity_id':'shared','user_id':'bob'}).status_code,422)
    def test_strict_validation_no_writes(self):
        before=copy.deepcopy(self.data)
        bad=[None,[],True,{}, {'kind':'shop'},{'kind':'shop','entity_id':'shared','extra':1}]
        for v in (None,[],{},True,12,'','unknown'):bad.append({'kind':v,'entity_id':'shared'})
        for v in (None,[],{},True,12,'','a/b','..','__reserved__',' x','x\n','é'*129,'\ud800'):bad.append({'kind':'shop','entity_id':v})
        for b in bad:
            with self.subTest(body=b):self.assertEqual(self.call('POST',body=b).status_code,422)
        for raw in ('null','[]','{"bad":'):
            self.assertEqual(self.client.post('/favorites',data=raw,content_type='application/json',headers={'Authorization':'Bearer alice'}).status_code,422)
        for k in favorites.KINDS:self.assertEqual(self.add(k,'missing').status_code,404)
        self.assertEqual(before,self.data)
        for suffix in ('?kind=no','?kind=shop&kind=product','?user_id=alice','/unknown/shared/check'):
            self.assertEqual(self.call(suffix=suffix).status_code,422)
    def test_actual_target_models_and_unavailable_removal(self):
        self.assertEqual(self.add('shop','alice').status_code,404)
        self.assertEqual(self.add('provider','alice').status_code,404)
        self.add('provider');self.data['provider_profiles','shared']['is_active']=False
        self.assertEqual(self.add('provider').status_code,404)
        self.assertFalse(self.call().json['favorites'][0]['available'])
        self.assertIsNone(self.call().json['favorites'][0]['name'])
        self.call('DELETE','/provider/shared')
        self.add('product');del self.data['shop_items','shared']
        self.assertTrue(self.call(suffix='/product/shared/check').json['is_favorite'])
        self.assertFalse(self.call().json['favorites'][0]['available'])
        self.call('DELETE','/product/shared')
        self.data['shop_items','shared']={'disabled_by_admin':True}
        self.assertEqual(self.add('product').status_code,404)
    def test_legacy_union_dedup_and_shapes(self):
        h={'Authorization':'Bearer alice'}
        self.assertEqual(self.client.post('/shops/favorites',json={'shop_item_id':'shared'},headers=h).status_code,201)
        self.assertEqual(self.client.post('/services/favourites/add',json={'provider_id':'shared'},headers=h).status_code,200)
        before=copy.deepcopy(self.data)
        for k in ('product','provider'):
            self.assertTrue(self.call(suffix='/'+k+'/shared/check').json['is_favorite']);self.add(k)
        self.assertEqual(before,self.data)
        self.add('shop')
        self.assertEqual(len(self.call().json['favorites']),3)
        self.assertTrue(all('kind' not in r for r in self.client.get('/shops/favorites',headers=h).json))
        self.assertEqual(len(self.client.get('/services/favourites',headers=h).json['providers']),1)
        self.data['user_favorites',favorites.key('alice','product','shared')]={'user_id':'alice','kind':'product','entity_id':'shared'}
        self.assertEqual(len(self.call().json['favorites']),3)
        for k in ('product','provider'):
            self.call('DELETE','/'+k+'/shared');self.assertFalse(self.call(suffix='/'+k+'/shared/check').json['is_favorite'])
        self.assertEqual(len(self.call().json['favorites']),1)
    def test_legacy_separator_collision_owner_protection(self):
        self.data['user_favorites','alice__bob__shared']={'user_id':'alice__bob','shop_item_id':'shared'}
        before=copy.deepcopy(self.data)
        self.assertFalse(self.call(suffix='/product/bob__shared/check').json['is_favorite'])
        self.call('DELETE','/product/bob__shared');self.assertEqual(before,self.data)
        self.assertNotEqual(favorites.key('alice','product','bob__shared'),favorites.key('alice__bob','product','shared'))
    def test_fresh_app_and_real_storage_namespace_helper(self):
        self.add('shop')
        self.assertEqual(len(self.new_app().test_client().get('/favorites',headers={'Authorization':'Bearer alice'}).json['favorites']),1)
        import importlib.util
        from firebase_admin import firestore
        spec=importlib.util.spec_from_file_location('isolated_storage',storage.__file__)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        client=MagicMock()
        with patch.object(firestore,'client',return_value=client):module.doc('user_favorites','synthetic')
        client.collection.assert_called_once_with('localshop')
        client.collection.return_value.document.assert_called_once_with('v1')
        client.collection.return_value.document.return_value.collection.assert_called_once_with('user_favorites')
    def test_conflicting_storage_record_is_not_success(self):
        self.data['user_favorites',favorites.key('alice','shop','shared')]={'user_id':'bob','provider_id':'shared'}
        before=copy.deepcopy(self.data)
        self.assertEqual(self.add('shop').status_code,409)
        self.assertEqual(before,self.data)

    def test_create_race_and_storage_failure(self):
        original=FavoriteReference.create
        def concurrent(ref,value):
            original(ref,value);raise AlreadyExists('another request won')
        with patch.object(FavoriteReference,'create',concurrent):self.assertEqual(self.add('shop').status_code,200)
        with patch.object(FavoriteReference,'create',side_effect=ServiceUnavailable('synthetic failure')):
            with self.assertRaises(ServiceUnavailable):self.add('product')
        self.assertFalse(self.call(suffix='/product/shared/check').json['is_favorite'])


if __name__=='__main__':unittest.main()
