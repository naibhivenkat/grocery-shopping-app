"""Endpoint regression for raw discovery metadata and legacy fields."""
from test_service_catalog_security import ServiceCatalogSecurityTests


class DiscoveryPresenceTests(ServiceCatalogSecurityTests):
    def item(self):
        response = self.client.get('/services/available')
        self.assertEqual(response.status_code, 200)
        return response.json[0]

    def test_raw_presence_and_rating_precedence(self):
        service = self.data('provider_services', 'service-a')
        user = self.data('users', 'provider')
        profile = self.data('provider_profiles', 'provider')
        for value, expected in ((None, None), ('', None), (0, 0), (42, 42)):
            service['hourly_price'] = value
            item = self.item()
            self.assertEqual(item['discovery_metadata']['hourly_price'], expected)
            self.assertEqual(item['hourly_price'], expected or 0)
        service.pop('hourly_price')
        self.assertIsNone(self.item()['discovery_metadata']['hourly_price'])
        for value in ('bad', -1, True, 'NaN'):
            service['hourly_price'] = value
            self.assertEqual(self.client.get('/services/available').json, [])
        service.pop('hourly_price')
        profile['rating'] = 4
        for value, expected in ((None, 4), ('bad', 4), (0, 0), (3, 3)):
            user['rating'] = value
            self.assertEqual(self.item()['discovery_metadata']['rating'], expected)
        profile.pop('rating')
        user.pop('rating')
        self.assertIsNone(self.item()['discovery_metadata']['rating'])
        for value, expected in ((True, True), ('invalid', None), (None, None)):
            profile['is_active'] = value
            self.assertEqual(self.item()['discovery_metadata']['is_active'], expected)
        profile.pop('is_active')
        self.assertIsNone(self.item()['discovery_metadata']['is_active'])
        profile['is_active'] = False
        self.assertEqual(self.client.get('/services/available').json, [])

    def test_pricing_bases_and_legacy_payload(self):
        service = self.data('provider_services', 'service-a')
        for kind, prices, field, amount in (
            ('fixed', {'fixed_price': 100}, 'fixed_price', 100),
            ('visit', {'inspection_charge': 80}, 'inspection_charge', 80),
            ('hourly', {'hourly_price': 120}, 'hourly_price', 120),
            ('per_30min', {'per_30min_price': 75}, 'per_30min_price', 75),
            ('time_based', {'hourly_price': 90}, 'hourly_price', 90),
        ):
            for key in ('fixed_price', 'hourly_price', 'per_30min_price', 'inspection_charge'):
                service.pop(key, None)
            service.update(pricing_type=kind, **prices)
            item = self.item()
            self.assertEqual(item['pricing_type'], kind)
            self.assertEqual(item[field], amount)
            self.assertEqual(item['discovery_metadata'][field], amount)
