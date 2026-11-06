"""Synthetic HTTP regressions for provider role and profile boundaries."""
import copy
import unittest
from unittest.mock import patch
import test_service_catalog_security as fixtures
from routes import availability


class ProviderBoundaryTests(unittest.TestCase):
    setUp = fixtures.ServiceCatalogSecurityTests.setUp
    put = fixtures.ServiceCatalogSecurityTests.put
    data = fixtures.ServiceCatalogSecurityTests.data
    call = fixtures.ServiceCatalogSecurityTests.call

    def test_non_service_legacy_profiles_cannot_use_own_provider_capabilities(self):
        self.app.register_blueprint(availability.availability_bp)
        for identity in ('customer', 'vendor', 'admin'):
            self.put('provider_profiles', identity, {'is_active': True})
            self.put('provider_services', identity, {**self.service, 'provider_id': identity, 'is_deleted': False})
            before = copy.deepcopy(self.store.collections['provider_services'].records)
            for path, method, body in (
                ('/provider/profile', 'GET', None), ('/provider/profile', 'PUT', {'location': 'x'}),
                ('/provider/services', 'GET', None), ('/provider/services', 'POST', self.service),
                (f'/provider/services/{identity}', 'PUT', {'title': 'changed'}),
                (f'/provider/services/{identity}', 'DELETE', None),
                ('/provider/availability?date=2030-01-01', 'GET', None),
                ('/provider/availability', 'PUT', {'date': '2030-01-01', 'updates': []}),
            ):
                self.assertEqual(self.call(path, body, method, identity).status_code, 403, (identity, path))
            self.assertEqual(self.store.collections['provider_services'].records, before)
            self.assertEqual(self.client.get(f'/providers/{identity}/services').json, [])
        self.assertEqual(len(self.client.get('/providers/provider/services').json), 1)
        self.assertEqual(self.client.get('/provider/profile').status_code, 401)

    def test_saved_favourites_filter_legacy_and_unavailable_without_deletion(self):
        for identity in ('customer', 'vendor', 'admin'):
            self.put('provider_profiles', identity, {'is_active': True})
        for identity in ('provider', 'customer', 'vendor', 'admin'):
            self.put('user_favorites', 'saved-' + identity, {'user_id': 'other', 'provider_id': identity})
        before = copy.deepcopy(self.store.collections['user_favorites'].records)
        response = self.call('/services/favourites', method='GET', user='other')
        self.assertEqual([p['id'] for p in response.json['providers']], ['provider'])
        self.data('users', 'provider')['is_suspended'] = True
        self.assertEqual(self.call('/services/favourites', method='GET', user='other').json['providers'], [])
        self.data('users', 'provider')['is_suspended'] = False
        self.data('provider_profiles', 'provider')['is_active'] = False
        self.assertEqual(self.call('/services/favourites', method='GET', user='other').json['providers'], [])
        self.assertEqual(self.store.collections['user_favorites'].records, before)
        self.assertEqual(self.call('/services/favourites/remove', {'provider_id': 'vendor'}, user='other').status_code, 200)

    def test_service_onboarding_active_profile_and_ownership(self):
        self.app.register_blueprint(availability.availability_bp)
        self.assertEqual(self.call('/provider/profile', {'location': 'here'}, 'PUT').status_code, 200)
        self.assertEqual(self.call('/provider/services', self.service).status_code, 201)
        self.assertEqual(self.call('/provider/services/service-a', {'title': 'x'}, 'PUT', 'other').status_code, 403)
        self.data('provider_profiles', 'provider')['is_active'] = False
        for path, method, body in (('/provider/services', 'GET', None), ('/provider/services/service-a', 'DELETE', None),
                                   ('/provider/availability?date=2030-01-01', 'GET', None)):
            self.assertEqual(self.call(path, body, method).status_code, 403)
        self.assertEqual(self.call('/provider/profile', {'is_active': True}, 'PUT').status_code, 200)
        self.data('users', 'provider')['is_suspended'] = True
        self.assertEqual(self.call('/provider/profile', method='GET').status_code, 403)
        self.store.collections['provider_profiles'].records.pop('provider')
        self.data('users', 'provider')['is_suspended'] = False
        self.assertEqual(self.call('/provider/services', method='GET').status_code, 403)


class AvailabilityBoundaryTests(unittest.TestCase):
    def setUp(self):
        import test_booking_transactions as fixtures
        fixtures.BookingTransactionTests.setUp(self)
        self.store.put("users", "provider-a", {"role": "service"})

    def test_active_provider_calendar_and_booked_slot_integrity(self):
        headers = {"Authorization": "Bearer " + __import__("auth_utils").create_token("provider-a", "service")}
        path = "/provider/availability"
        self.assertEqual(self.client.get(path, query_string={"date": self.date}, headers=headers).status_code, 200)
        payload = {"date": self.date, "updates": [{"time": "10:00", "status": "blocked"}]}
        self.assertEqual(self.client.put(path, json=payload, headers=headers).status_code, 200)
        calendar_id = f"provider-a:{self.date}"
        calendar = self.store.data("provider_availability", calendar_id)
        next(slot for slot in calendar["slots"] if slot["time"] == "10:00").update(status="booked", booking_id="booking-a")
        self.store.put("provider_availability", calendar_id, calendar)
        before = copy.deepcopy(self.store.data("provider_availability", calendar_id))
        self.assertEqual(self.client.put(path, json=payload, headers=headers).status_code, 409)
        self.assertEqual(self.store.data("provider_availability", calendar_id), before)
        self.assertEqual(self.client.get(f"/providers/provider-a/availability?date={self.date}").status_code, 200)
        self.store.put("users", "provider-a", {"role": "vendor"})
        self.assertEqual(self.client.get(f"/providers/provider-a/availability?date={self.date}").status_code, 404)
