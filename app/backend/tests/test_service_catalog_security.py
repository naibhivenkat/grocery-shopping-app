"""HTTP proof for service prices, provider profiles, private cities and budgets."""

import copy
import unittest
from unittest.mock import patch

from flask import Flask

from auth_utils import create_token
from routes import services, provider_profiles, cities, ai
from test_promotions_api import Store, Reference


def set_document(reference, data, merge=False):
    if merge:
        reference.collection.records.setdefault(reference.id, {}).update(copy.deepcopy(data))
    else:
        reference.collection.records[reference.id] = copy.deepcopy(data)


class ServiceCatalogSecurityTests(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        modules = (services, provider_profiles, cities, ai)
        self.app = Flask(__name__)
        self.app.config["TESTING"] = True
        for module in modules:
            self.app.register_blueprint(getattr(module, module.__name__.split(".")[-1] + "_bp"))
        patches = [patch("db.col", self.store.col), patch.object(Reference, "set", set_document),
                   patch.object(Reference, "delete", lambda reference: reference.collection.records.pop(reference.id, None), create=True)]
        for module in modules:
            if hasattr(module, "col"):
                patches.append(patch.object(module, "col", self.store.col))
        for current in patches:
            current.start()
            self.addCleanup(current.stop)
        self.client = self.app.test_client()
        for identity, role in (("provider", "service"), ("customer", "customer"), ("other", "customer"), ("admin", "admin"), ("vendor", "vendor")):
            self.put("users", identity, {"role": role, "full_name": identity, "city_id": "city-a", "addresses": ["private home"], "password_hash": "private", "rating": "bad-rating"})
        self.put("provider_profiles", "provider", {"is_active": True, "location": "City center", "bank": {"account": "private-account"}})
        self.service = {"title": "Plumbing", "description": "Fix taps", "pricing_type": "fixed", "fixed_price": 100, "is_active": True}
        self.put("provider_services", "service-a", {**self.service, "provider_id": "provider", "is_deleted": False, "created_at": "original"})
        self.put("cities", "city-a", {"name": "Bangalore", "is_active": True, "latitude": 12, "longitude": 77, "created_at": "original"})
        self.put("cities", "city-off", {"name": "Off", "is_active": False})
        for identity, price in (("rice", 0.1), ("milk", 0.2)):
            self.put("shop_items", identity, {"name": identity, "vendor_id": "vendor", "vendor_name": "Grocer", "city_id": "city-a", "price": price, "stock_quantity": 10, "category": "Food", "average_rating": "NaN"})

    def put(self, name, identity, data):
        self.store.col(name).document(identity).set(data)

    def data(self, name, identity):
        return self.store.col(name).records[identity]

    def call(self, path, payload=None, method="POST", user="provider"):
        headers = {"Authorization": "Bearer " + create_token(user, self.data("users", user)["role"])} if user else {}
        return self.client.open(path, method=method, json=payload, headers=headers)

    def test_service_creation_price_fields_and_read_only_identity(self):
        response = self.call("/provider/services", self.service)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json["provider_id"], "provider")
        for fields in ({"fixed_price": "NaN"}, {"hourly_price": "Infinity"}, {"fixed_price": -1}, {"fixed_price": True},
                       {"fixed_price": 0.001}, {"title": []}, {"title": ""}, {"service_category_id": []}, {"is_active": "false"}, {"provider_id": "other"}, {"is_deleted": True}, {"created_at": "fake"}):
            self.assertEqual(self.call("/provider/services", {**self.service, **fields}).status_code, 422, fields)
        self.assertEqual(self.call("/provider/services", self.service, user="customer").status_code, 403)

    def test_service_update_ownership_allowlist_and_atomic_validation(self):
        original = copy.deepcopy(self.data("provider_services", "service-a"))
        for payload in ({"provider_id": "other"}, {"fixed_price": "NaN"}, {"is_deleted": False}, {"is_active": "false"}, {"title": []}):
            self.assertEqual(self.call("/provider/services/service-a", payload, "PUT").status_code, 422)
            self.assertEqual(self.data("provider_services", "service-a"), original)
        self.assertEqual(self.call("/provider/services/service-a", {"title": "Hijacked"}, "PUT", "other").status_code, 403)
        self.assertEqual(self.call("/provider/services/service-a", {"fixed_price": 125}, "PUT").status_code, 200)
        self.assertEqual(self.data("provider_services", "service-a")["created_at"], "original")
        self.data("provider_services", "service-a")["is_deleted"] = True
        self.assertEqual(self.call("/provider/services/service-a", {"title": "Revive"}, "PUT").status_code, 404)

    def test_price_quote_matches_booking_tax_and_validates_duration(self):
        response = self.call("/services/calculate-price", {"service_id": "service-a", "duration": 60}, user=None)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["total_cost"], 123.9)
        self.assertEqual(response.json["tax"], 18.9)
        for duration in (0, -1, True, 60.5, "bad", 31, 510):
            self.assertEqual(self.call("/services/calculate-price", {"service_id": "service-a", "duration": duration}, user=None).status_code, 422)
        self.data("provider_services", "service-a")["is_active"] = False
        self.assertEqual(self.call("/services/calculate-price", {"service_id": "service-a"}, user=None).status_code, 404)

    def test_public_service_discovery_filters_unavailable_and_never_exposes_bank(self):
        self.assertEqual(len(self.client.get("/services/available").json), 1)
        response = self.client.get("/services/service-a")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("bank", response.json)
        self.assertNotIn("password_hash", response.json)
        for name, identity, field in (("provider_services", "service-a", "is_active"), ("provider_profiles", "provider", "is_active")):
            self.data(name, identity)[field] = False
            self.assertEqual(self.client.get("/services/available").json, [])
            self.assertEqual(self.client.get("/providers/provider/services").json, [])
            self.assertEqual(self.client.get("/services/service-a").status_code, 404)
            self.data(name, identity)[field] = True
        self.data("users", "provider")["is_suspended"] = True
        self.assertEqual(self.client.get("/services/available").json, [])

    def test_provider_profile_valid_schedule_and_server_fields(self):
        response = self.call("/provider/profile", {"working_schedule": {"Mon": {"from": "09:00 AM", "to": "06:00 PM"}}, "is_active": True}, "PUT")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["working_schedule"]["Mon"]["from"], "09:00 AM")
        for fields in ({"working_schedule": []}, {"working_schedule": {"Mon": None}}, {"working_schedule": {"Foo": {}}},
                       {"working_schedule": {"Mon": {"from": "09:15 AM", "to": "06:00 PM"}}}, {"is_active": "false"},
                       {"working_schedule": {"Mon": {"closed": "true"}}}, {"is_verified": True}, {"rating": 5}, {"bank": []}, {"service_category_ids": "not-list"}, {"location": {"latitude": "NaN", "longitude": 77}}):
            self.assertEqual(self.call("/provider/profile", fields, "PUT").status_code, 422, fields)

    def test_saved_addresses_and_current_city_are_private(self):
        for path in ("/cities/current/customer", "/services/addresses?customer_id=customer"):
            self.assertEqual(self.client.get(path).status_code, 401)
            self.assertEqual(self.call(path, method="GET", user="other").status_code, 403)
            self.assertEqual(self.call(path, method="GET", user="customer").status_code, 200)
            self.assertEqual(self.call(path, method="GET", user="admin").status_code, 200)

    def test_current_city_requires_existing_active_city_or_explicit_clear(self):
        for city in ("missing", "city-off"):
            self.assertEqual(self.call("/cities/current", {"city_id": city}, "PUT", "customer").status_code, 404)
        self.assertEqual(self.call("/cities/current", {"city_id": []}, "PUT", "customer").status_code, 422)
        self.assertEqual(self.call("/cities/current", {}, "PUT", "customer").status_code, 422)
        self.assertEqual(self.call("/cities/current", {"city_id": None}, "PUT", "customer").status_code, 200)
        self.assertIsNone(self.data("users", "customer")["city_id"])

    def test_city_admin_validation_and_no_partial_missing_city_updates(self):
        self.assertEqual(self.call("/cities", {"name": "New city"}, user="customer").status_code, 403)
        for fields in ({"name": []}, {"latitude": "NaN"}, {"longitude": 190}, {"is_active": "false"}):
            self.assertEqual(self.call("/cities", {"name": "New city", **fields}, user="admin").status_code, 422)
        self.assertEqual(self.call("/cities/missing", {"name": "Fake city"}, "PUT", "admin").status_code, 404)
        self.assertEqual(self.call("/cities/city-a", {"name": "Bengaluru", "created_at": "fake", "id": "forged"}, "PUT", "admin").status_code, 200)
        self.assertEqual(self.data("cities", "city-a")["created_at"], "original")

    def test_public_summaries_never_include_private_budget_documents(self):
        self.put("ai_summaries", "budget__customer", {"user_id": "customer", "budget": 200, "city_id": "city-a", "suggested_items": [{"private": "items"}]})
        response = self.client.get("/ai/summary")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json)
        self.assertTrue(all("user_id" not in result and "budget" not in result for result in response.json))
        self.put("ai_summaries", "public", {"area": "Center", "summary": "Public summary", "city_id": "city-a", "avg_rating": "NaN", "secret": "private"})
        response = self.client.get("/ai/summary?city_id=city-a")
        self.assertEqual(len(response.json), 1)
        self.assertNotIn("secret", response.json[0])
        self.assertEqual(response.json[0]["avg_rating"], 0)

    def test_budget_finite_money_categories_and_unavailable_inventory(self):
        for fields in ({"budget": "NaN"}, {"budget": "Infinity"}, {"budget": -1}, {"budget": True}, {"city_id": []}, {"city_id": False}, {"preferred_categories": "Food"}, {"preferred_categories": [{}]}):
            self.assertEqual(self.call("/ai/budget-plan", {"budget": 1, **fields}, user="customer").status_code, 422)
        for identity, fields in (("off", {"is_available": False}), ("admin-disabled", {"disabled_by_admin": True, "is_available": True}), ("empty", {"stock_quantity": 0}), ("bad", {"price": "NaN"}), ("fractional", {"stock_quantity": 1.2})):
            self.put("shop_items", identity, {"vendor_id": "vendor", "name": identity, "price": 0.01, "stock_quantity": 10, **fields})
        response = self.call("/ai/budget-plan", {"budget": 0.3, "preferred_categories": ["Food"]}, user="customer")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["total_cost"], 0.3)
        self.assertEqual({item["item_id"] for item in response.json["suggested_items"]}, {"rice", "milk"})
        self.data("users", "vendor")["is_suspended"] = True
        response = self.call("/ai/budget-plan", {"budget": 100}, user="customer")
        self.assertEqual(response.json["suggested_items"], [])

    def test_arrays_malformed_json_and_oversized_json_are_bounded_errors(self):
        for path, method, user in (("/provider/services", "POST", "provider"), ("/provider/profile", "PUT", "provider"), ("/ai/budget-plan", "POST", "customer"), ("/cities", "POST", "admin")):
            self.assertEqual(self.call(path, [], method, user).status_code, 422)
        response = self.call("/provider/profile", {"location": "x" * 70_000}, "PUT")
        self.assertEqual(response.status_code, 413)


if __name__ == "__main__":
    unittest.main()
