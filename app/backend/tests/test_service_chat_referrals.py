"""Service-role compatibility without weakening chat or referral ownership."""
import copy
import unittest
from unittest.mock import patch
from flask import Flask
import auth_utils
import db as storage
from routes import chat, referrals, khata
from test_core_routes import CoreStore


class ServiceChatReferralTests(unittest.TestCase):
    def setUp(self):
        self.store = CoreStore()
        self.store.data = {
            (storage.USERS, "customer"): {"role": "customer", "full_name": "Customer"},
            (storage.USERS, "other_customer"): {"role": "customer"},
            (storage.USERS, "vendor"): {"role": "vendor", "shop_name": "Shop"},
            (storage.USERS, "provider"): {"role": "service", "full_name": "Provider", "password_hash": "private"},
            (storage.USERS, "other_provider"): {"role": "service"},
            (storage.USERS, "admin"): {"role": "admin"},
        }
        self.app = Flask(__name__)
        self.app.config["TESTING"] = True
        self.app.register_blueprint(chat.chat_bp)
        self.app.register_blueprint(referrals.referrals_bp)
        patches = [patch.object(storage, "doc", self.store.doc), patch.object(auth_utils, "decode_token", lambda token: {"sub": token})]
        for module in (chat, referrals, khata):
            patches += [patch.object(module, "col", self.store.col), patch.object(module, "doc", self.store.doc),
                        patch.object(module, "db", lambda: self.store), patch.object(module.firestore, "transactional", self.store.transactional)]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        self.client = self.app.test_client()

    def call(self, path, body=None, user="customer", method="POST"):
        return self.client.open(path, json=body, method=method, headers={"Authorization": f"Bearer {user}"})

    def test_customer_provider_chat_is_private_and_provider_can_reply(self):
        room = self.call("/chat/rooms", {"vendor_id": "provider"})
        self.assertEqual(room.status_code, 200)
        identifier = room.json["uid"]
        self.assertNotIn("password_hash", room.json)
        self.assertEqual(self.call("/chat/rooms", user="provider", method="GET").json[0]["uid"], identifier)
        path = f"/chat/rooms/{identifier}/messages"
        self.assertEqual(self.call(path, {"text": "Can you help?"}).status_code, 201)
        self.assertEqual(self.call(path, {"text": "Yes"}, user="provider").status_code, 201)
        self.assertEqual(len(self.call(path, user="provider", method="GET").json), 2)
        self.assertEqual(self.call(path, {"text": "Intrusion"}, user="other_provider").status_code, 403)
        self.assertEqual(self.call(path, user="other_customer", method="GET").status_code, 403)

    def test_service_requester_legacy_chats_and_provider_chats_both_listed(self):
        first = self.call("/chat/rooms", {"vendor_id": "vendor"}, user="provider")
        second = self.call("/chat/rooms", {"vendor_id": "provider"}, user="customer")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        rooms = self.call("/chat/rooms", user="provider", method="GET").json
        self.assertEqual({room["uid"] for room in rooms}, {first.json["uid"], second.json["uid"]})
        self.assertEqual(self.call("/chat/rooms", {"vendor_id": "provider"}, user="provider").status_code, 422)
        self.assertEqual(self.call("/chat/rooms", {"vendor_id": "admin"}).status_code, 403)

    def test_suspended_or_deleted_service_participant_cannot_be_contacted(self):
        room = self.call("/chat/rooms", {"vendor_id": "provider"}).json["uid"]
        self.store.data[(storage.USERS, "provider")]["is_suspended"] = True
        self.assertEqual(self.call(f"/chat/rooms/{room}/messages", {"text": "Hello"}).status_code, 403)
        self.assertEqual(self.call("/chat/rooms", {"vendor_id": "provider"}).status_code, 403)
        self.assertEqual(self.call("/chat/rooms", method="GET").json, [])
        del self.store.data[(storage.USERS, "provider")]
        self.assertEqual(self.call(f"/chat/rooms/{room}/messages", {"text": "Hello"}).status_code, 403)

    def test_service_referral_generation_and_application_remain_once_only_no_wallet_rewards(self):
        generated = self.call("/referrals/generate", user="provider")
        self.assertEqual(generated.status_code, 200)
        code = generated.json["code"]
        self.assertEqual(self.call("/referrals/generate", user="provider").json["code"], code)
        applied = self.call("/referrals/apply", {"code": code}, user="other_provider")
        self.assertEqual(applied.status_code, 200)
        self.assertFalse(applied.json["reward_credited"])
        history = self.call("/referrals", user="provider", method="GET").json
        self.assertEqual(history[0]["referee_id"], "other_provider")
        self.assertEqual(self.call("/referrals", user="other_provider", method="GET").json[0]["code"], code)
        self.assertEqual(self.call("/referrals/apply", {"code": code}, user="other_provider").status_code, 200)
        self.assertEqual(self.call("/referrals/apply", {"code": code}, user="provider").status_code, 422)
        before = copy.deepcopy(self.store.data)
        self.assertEqual(self.call("/referrals/apply", {"code": code}).status_code, 409)
        self.assertEqual(self.store.data, before)
        self.assertFalse(any(name in {storage.WALLETS, storage.WALLET_TRANSACTIONS} for name, _ in self.store.data))


if __name__ == "__main__":
    unittest.main()
