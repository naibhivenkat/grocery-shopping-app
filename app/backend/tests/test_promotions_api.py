"""Promotion HTTP authorization/validation tests with an in-memory Firestore.

These prove Flask behavior and revision checks, not provider transactions or
deployed Firestore permissions/indexes. No Firebase credentials are required.
"""

import copy
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from flask import Flask

from auth_utils import create_token
from routes.promotions import promotions_bp


class Snapshot:
    def __init__(self, reference):
        self.reference = reference
        self.id = reference.id
        self.exists = reference.id in reference.collection.records
        self.data = copy.deepcopy(reference.collection.records.get(reference.id))

    def to_dict(self):
        return copy.deepcopy(self.data)


class Reference:
    def __init__(self, collection, identity):
        self.collection = collection
        self.id = identity

    def get(self, transaction=None):
        return Snapshot(self)

    def set(self, data):
        self.collection.records[self.id] = copy.deepcopy(data)

    def update(self, data):
        self.collection.records[self.id].update(copy.deepcopy(data))


class Query:
    def __init__(self, collection, filters=()):
        self.collection = collection
        self.filters = filters

    def where(self, *, filter):
        return Query(self.collection, self.filters + (filter,))

    def stream(self):
        for identity, data in list(self.collection.records.items()):
            if all(data.get(condition.field_path) == condition.value for condition in self.filters):
                yield self.collection.document(identity).get()


class Collection(Query):
    def __init__(self):
        self.records = {}
        super().__init__(self)

    def document(self, identity=None):
        return Reference(self, identity or f"campaign-{len(self.records) + 1}")


class Store:
    def __init__(self):
        self.collections = {}

    def col(self, name):
        return self.collections.setdefault(name, Collection())

    def transaction(self):
        return self

    def update(self, ref, data):
        ref.update(data)


class PromotionsApiTests(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        self.patches = [
            patch("db.col", self.store.col),
            patch("routes.promotions.col", self.store.col),
            patch("routes.promotions.db", return_value=self.store),
            patch("routes.promotions.firestore.transactional", side_effect=lambda fn: fn),
        ]
        for current in self.patches:
            current.start()
            self.addCleanup(current.stop)
        for identity, role, city in (
            ("vendor-a", "vendor", "city-a"), ("vendor-b", "vendor", "city-b"),
            ("admin-a", "admin", "city-a"), ("superadmin-a", "super_admin", "city-a"),
            ("customer-a", "customer", "city-a"),
        ):
            self.store.col("users").document(identity).set({
                "role": role, "shop_name": identity + " shop", "city_id": city,
                "email": "private@example.com", "phone": "private-phone",
            })
        self.store.col("shop_items").document("product-a").set({
            "vendor_id": "vendor-a", "name": "Rice", "city_id": "city-a",
            "is_available": True, "stock_quantity": 10,
        })
        self.store.col("shop_items").document("product-b").set({
            "vendor_id": "vendor-b", "name": "Flour", "city_id": "city-b",
        })
        app = Flask(__name__)
        app.config["TESTING"] = True
        app.register_blueprint(promotions_bp)
        self.client = app.test_client()
        now = datetime.now(timezone.utc)
        self.content = {
            "target_type": "shop", "title": "Fresh groceries", "body": "Visit our shop",
            "image_url": "https://example.com/groceries.jpg",
            "starts_at": (now - timedelta(minutes=5)).isoformat(),
            "ends_at": (now + timedelta(days=7)).isoformat(),
        }

    def headers(self, identity="vendor-a", token_role=None):
        account = self.store.col("users").records.get(identity, {})
        role = token_role or account.get("role", "vendor")
        return {"Authorization": "Bearer " + create_token(identity, role)}

    def create(self, content=None, identity="vendor-a"):
        return self.client.post("/promotions", json=content or self.content, headers=self.headers(identity))

    def moderate(self, identity, revision=1, decision="approved", reason=None, admin="admin-a"):
        return self.client.post(
            f"/promotions/{identity}/moderation",
            json={"decision": decision, "revision": revision, "reason": reason},
            headers=self.headers(admin),
        )

    def test_create_is_free_pending_and_uses_own_shop_city(self):
        response = self.create()
        self.assertEqual(response.status_code, 201)
        campaign = response.json
        self.assertEqual(campaign["status"], "pending")
        self.assertEqual(campaign["price_paise"], 0)
        self.assertEqual(campaign["revision"], 1)
        self.assertEqual(campaign["shop_id"], "vendor-a")
        self.assertEqual(campaign["city_id"], "city-a")
        self.assertEqual(self.client.get("/promotions").json, [])

    def test_create_product_and_forbid_another_vendor_targets(self):
        product = {**self.content, "target_type": "product", "product_id": "product-a"}
        response = self.create(product)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json["target_name"], "Rice")
        self.assertEqual(self.create({**product, "product_id": "product-b"}).status_code, 403)
        self.assertEqual(self.create({**self.content, "shop_id": "vendor-b"}).status_code, 403)
        self.assertEqual(self.create({**product, "product_id": "missing"}).status_code, 404)

    def test_moderation_public_city_filter_and_private_fields(self):
        campaign = self.create().json
        campaign_b = self.create(identity="vendor-b").json
        self.assertEqual(self.moderate(campaign["uid"]).status_code, 200)
        self.assertEqual(self.moderate(campaign_b["uid"], admin="superadmin-a").status_code, 200)
        response = self.client.get("/promotions?city_id=city-a")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json), 1)
        public = response.json[0]
        self.assertEqual(public["shop_id"], "vendor-a")
        for private in ("email", "phone", "moderated_by", "moderation_reason", "vendor_id", "price_paise"):
            self.assertNotIn(private, public)
        self.assertEqual(self.client.get("/promotions?limit=1").json[0]["uid"], campaign["uid"])

    def test_edit_resets_approval_and_stale_review_cannot_approve(self):
        campaign = self.create().json
        self.assertEqual(self.moderate(campaign["uid"]).status_code, 200)
        response = self.client.put(
            f"/promotions/{campaign['uid']}", json={"title": "New offer"}, headers=self.headers(),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["status"], "pending")
        self.assertEqual(response.json["revision"], 2)
        self.assertIsNone(response.json["moderated_by"])
        self.assertEqual(self.client.get("/promotions").json, [])
        self.assertEqual(self.moderate(campaign["uid"], revision=1).status_code, 409)
        self.assertEqual(self.moderate(campaign["uid"], revision=2).status_code, 200)

    def test_rejection_requires_reason_and_vendor_can_resubmit(self):
        campaign = self.create().json
        self.assertEqual(self.moderate(campaign["uid"], decision="rejected").status_code, 422)
        response = self.moderate(campaign["uid"], decision="rejected", reason="Misleading claim")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["moderation_reason"], "Misleading claim")
        self.assertEqual(self.moderate(campaign["uid"]).status_code, 409)
        mine = self.client.get("/promotions/mine", headers=self.headers()).json
        self.assertEqual(mine[0]["status"], "rejected")
        response = self.client.put(
            f"/promotions/{campaign['uid']}", json={"body": "Corrected claim"}, headers=self.headers(),
        )
        self.assertEqual(response.json["status"], "pending")

    def test_pause_is_strict_boolean_and_preserves_approval(self):
        campaign = self.create().json
        self.moderate(campaign["uid"])
        url = f"/promotions/{campaign['uid']}/pause"
        self.assertEqual(self.client.patch(url, json={"is_paused": "false"}, headers=self.headers()).status_code, 422)
        response = self.client.patch(url, json={"is_paused": True}, headers=self.headers())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["status"], "approved")
        self.assertEqual(self.client.get("/promotions").json, [])
        self.client.patch(url, json={"is_paused": False}, headers=self.headers())
        self.assertEqual(len(self.client.get("/promotions").json), 1)

    def test_vendor_cannot_edit_or_pause_another_vendor_campaign(self):
        campaign = self.create().json
        response = self.client.put(
            f"/promotions/{campaign['uid']}", json={"title": "Hijacked"}, headers=self.headers("vendor-b"),
        )
        self.assertEqual(response.status_code, 403)
        response = self.client.patch(
            f"/promotions/{campaign['uid']}/pause", json={"is_paused": True}, headers=self.headers("vendor-b"),
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.get("/promotions/mine", headers=self.headers("vendor-b")).json, [])

    def test_role_and_account_authorization(self):
        self.assertEqual(self.client.post("/promotions", json=self.content).status_code, 401)
        for identity in ("customer-a", "admin-a"):
            self.assertEqual(self.create(identity=identity).status_code, 403)
        campaign = self.create().json
        self.assertEqual(self.moderate(campaign["uid"], admin="vendor-a").status_code, 403)
        self.assertEqual(self.client.get("/promotions/admin", headers=self.headers("customer-a")).status_code, 403)
        self.assertEqual(self.client.get("/promotions/admin", headers=self.headers("admin-a")).status_code, 200)
        self.store.col("users").records["vendor-a"]["is_suspended"] = True
        self.assertEqual(self.create().status_code, 403)
        del self.store.col("users").records["vendor-a"]
        self.assertEqual(self.create().status_code, 401)
        stale_admin = self.headers("deleted-admin", token_role="admin")
        self.assertEqual(self.client.get("/promotions/admin", headers=stale_admin).status_code, 401)
        self.assertEqual(self.client.get("/promotions/admin", headers=self.headers("customer-a", "admin")).status_code, 403)

    def test_invalid_body_field_types_unknown_fields_ids_and_urls(self):
        cases = [
            {"title": ""}, {"title": 42}, {"title": "x" * 101}, {"body": "x" * 1001},
            {"target_type": []}, {"target_type": "service"}, {"status": "approved"},
            {"vendor_id": "vendor-b"}, {"price_paise": 999}, {"city_id": "city-b"},
            {"shop_id": "../vendor-b"}, {"shop_id": []},
            {"target_type": "product", "product_id": "../product-a"},
            {"product_id": "product-a"},
            {"image_url": "http://example.com/image.jpg"},
            {"image_url": "https://name:password@example.com/image.jpg"},
            {"image_url": "https://example.com:invalid/image.jpg"},
            {"image_url": "https://example.com/image.jpg#fragment"},
            {"image_url": "https://example.com/with space.jpg"}, {"image_url": []},
        ]
        for invalid in cases:
            with self.subTest(invalid=invalid):
                self.assertEqual(self.create({**self.content, **invalid}).status_code, 422)
        response = self.client.post("/promotions", json=[self.content], headers=self.headers())
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.client.post("/promotions", data="{bad", content_type="application/json", headers=self.headers()).status_code, 422)
        self.assertEqual(self.client.put("/promotions/missing", json={"title": "Valid"}, headers=self.headers()).status_code, 404)
        self.assertEqual(self.store.col("promotions").records, {})

    def test_schedule_validation_and_timezone_normalization(self):
        now = datetime.now(timezone.utc)
        invalid = [
            {"starts_at": "2026-10-01T00:00:00"}, {"starts_at": "invalid"},
            {"ends_at": self.content["starts_at"]},
            {"ends_at": (now - timedelta(minutes=1)).isoformat()},
            {"ends_at": (now + timedelta(days=91)).isoformat()},
        ]
        for fields in invalid:
            with self.subTest(fields=fields):
                self.assertEqual(self.create({**self.content, **fields}).status_code, 422)
        start = now.astimezone(timezone(timedelta(hours=5, minutes=30)))
        response = self.create({**self.content, "starts_at": start.isoformat()})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(datetime.fromisoformat(response.json["starts_at"]), now)
        self.assertTrue(response.json["starts_at"].endswith("+00:00"))

    def test_public_hides_future_expired_suspended_missing_or_unavailable_targets(self):
        campaign = self.create({**self.content, "target_type": "product", "product_id": "product-a"}).json
        self.moderate(campaign["uid"])
        self.assertEqual(len(self.client.get("/promotions").json), 1)
        self.store.col("users").records["vendor-a"]["is_suspended"] = True
        self.assertEqual(self.client.get("/promotions").json, [])
        self.store.col("users").records["vendor-a"]["is_suspended"] = False
        product = self.store.col("shop_items").records["product-a"]
        for change in ({"is_available": False}, {"stock_quantity": 0}, {"vendor_id": "vendor-b"}):
            original = copy.deepcopy(product)
            product.update(change)
            self.assertEqual(self.client.get("/promotions").json, [])
            product.clear()
            product.update(original)
        record = self.store.col("promotions").records[campaign["uid"]]
        original = copy.deepcopy(record)
        now = datetime.now(timezone.utc)
        for change in (
            {"starts_at": (now + timedelta(days=1)).isoformat()},
            {"ends_at": (now - timedelta(seconds=1)).isoformat()}, {"starts_at": "invalid"},
        ):
            record.update(change)
            self.assertEqual(self.client.get("/promotions").json, [])
            record.clear()
            record.update(original)
        del self.store.col("shop_items").records["product-a"]
        self.assertEqual(self.client.get("/promotions").json, [])

    def test_admin_cannot_approve_expired_or_unavailable_campaign(self):
        campaign = self.create().json
        self.store.col("promotions").records[campaign["uid"]]["ends_at"] = (
            datetime.now(timezone.utc) - timedelta(seconds=1)
        ).isoformat()
        self.assertEqual(self.moderate(campaign["uid"]).status_code, 409)
        product = self.create({**self.content, "target_type": "product", "product_id": "product-a"}).json
        self.store.col("shop_items").records["product-a"]["is_available"] = False
        self.assertEqual(self.moderate(product["uid"]).status_code, 409)

    def test_admin_disabled_product_cannot_create_approve_or_show_promotion(self):
        content = {**self.content, "target_type": "product", "product_id": "product-a"}
        first = self.create(content).json
        second = self.create(content).json
        self.assertEqual(self.moderate(first["uid"]).status_code, 200)
        self.store.col("shop_items").records["product-a"]["disabled_by_admin"] = True
        # is_available remains true: administrative suspension still wins.
        self.assertEqual(self.create(content).status_code, 409)
        self.assertEqual(self.moderate(second["uid"]).status_code, 409)
        self.assertEqual(self.client.get("/promotions").json, [])

    def test_query_and_moderation_validation(self):
        for query in ("limit=0", "limit=101", "limit=invalid", "city_id=..", "city_id=a/b"):
            self.assertEqual(self.client.get("/promotions?" + query).status_code, 422)
        self.assertEqual(self.client.get("/promotions/admin?status=active", headers=self.headers("admin-a")).status_code, 422)
        campaign = self.create().json
        for fields in ({"decision": []}, {"revision": True}, {"revision": 0}, {"revision": "1"}, {"extra": "unsafe"}):
            response = self.client.post(
                f"/promotions/{campaign['uid']}/moderation",
                json={"decision": "approved", "revision": 1, **fields}, headers=self.headers("admin-a"),
            )
            self.assertEqual(response.status_code, 422)
        self.assertEqual(self.moderate("missing").status_code, 404)


if __name__ == "__main__":
    unittest.main()
