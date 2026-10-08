"""Real Pillow decode/re-encode proof, mocked Firebase Storage upload calls."""

import io
import unittest
from unittest.mock import MagicMock, patch

from flask import Flask
from PIL import Image

from auth_utils import create_token
from routes import media
from test_promotions_api import Store


def picture(format="PNG", mode="RGB", size=(40, 20), **options):
    stream = io.BytesIO()
    Image.new(mode, size, "red").save(stream, format=format, **options)
    return stream.getvalue()


class MediaImageTests(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        for identity, role in (("vendor-a", "vendor"), ("service-a", "service"), ("customer-a", "customer"), ("admin-a", "admin")):
            self.store.col("users").document(identity).set({"role": role})
        self.bucket = MagicMock()
        self.blob = self.bucket.blob.return_value
        self.storage = MagicMock(return_value=self.bucket)
        patches = [patch("db.col", self.store.col), patch.object(media.storage, "bucket", self.storage),
                   patch.dict("os.environ", {"FIREBASE_STORAGE_BUCKET": "example.firebasestorage.app"})]
        for current in patches:
            current.start()
            self.addCleanup(current.stop)
        app = Flask(__name__)
        app.config["TESTING"] = True
        app.register_blueprint(media.media_bp)
        self.client = app.test_client()

    def headers(self, identity="vendor-a", role=None):
        account = self.store.col("users").records.get(identity, {})
        return {"Authorization": "Bearer " + create_token(identity, role or account.get("role", "vendor"))}

    def upload(self, raw=None, mime="image/png", identity="vendor-a", filename="../../foreign-owner.png", extra=None):
        data = {"file": (io.BytesIO(picture() if raw is None else raw), filename, mime), **(extra or {})}
        return self.client.post("/media/images", data=data, headers=self.headers(identity))

    def test_success_is_scoped_to_verified_owner_not_filename_and_preserves_token_metadata(self):
        response = self.upload()
        self.assertEqual(response.status_code, 201)
        path = response.json["path"]
        self.assertTrue(path.startswith("vendor_images/vendor-a/"))
        self.assertNotIn("..", path)
        self.assertNotIn("foreign-owner", path)
        self.assertTrue(path.endswith(".jpg"))
        self.assertEqual(response.json["content_type"], "image/jpeg")
        self.assertIn("vendor_images%2Fvendor-a%2F", response.json["image_url"])
        self.assertIn("?alt=media&token=", response.json["image_url"])
        self.assertEqual(self.blob.metadata["owner_id"], "vendor-a")
        self.assertTrue(self.blob.metadata["firebaseStorageDownloadTokens"])
        self.assertEqual(self.blob.upload_from_string.call_args.kwargs["if_generation_match"], 0)

    def test_exif_is_removed_and_orientation_applied(self):
        exif = Image.Exif()
        exif[0x010E] = "private-metadata-marker"
        exif[0x0112] = 6
        original = picture("JPEG", exif=exif)
        response = self.upload(original, "image/jpeg")
        self.assertEqual(response.status_code, 201)
        stored = self.blob.upload_from_string.call_args.args[0]
        self.assertNotIn(b"private-metadata-marker", stored)
        with Image.open(io.BytesIO(stored)) as decoded:
            self.assertEqual(decoded.size, (20, 40))
            self.assertFalse(decoded.getexif())

    def test_transparency_preserved_and_large_valid_images_downscaled(self):
        response = self.upload(picture("PNG", "RGBA", size=(2200, 1000)))
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json["content_type"], "image/png")
        self.assertEqual(response.json["width"], media.MAX_OUTPUT_SIDE)
        with Image.open(io.BytesIO(self.blob.upload_from_string.call_args.args[0])) as decoded:
            self.assertEqual(decoded.mode, "RGBA")

    def test_webp_is_decoded_and_reencoded(self):
        response = self.upload(picture("WEBP"), "image/webp")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json["content_type"], "image/jpeg")

    def test_customer_admin_deleted_and_suspended_accounts_cannot_upload(self):
        for identity in ("customer-a", "admin-a"):
            self.assertEqual(self.upload(identity=identity).status_code, 403)
        self.store.col("users").records["vendor-a"]["is_suspended"] = True
        self.assertEqual(self.upload().status_code, 403)
        del self.store.col("users").records["vendor-a"]
        self.assertEqual(self.upload().status_code, 401)
        self.storage.assert_not_called()

    def test_service_role_uses_its_own_prefix(self):
        response = self.upload(identity="service-a")
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json["path"].startswith("vendor_images/service-a/"))

    def test_unsafe_account_id_and_duplicate_files_cannot_choose_object_paths(self):
        self.store.col("users").document("..").set({"role": "vendor"})
        self.assertEqual(self.upload(identity="..").status_code, 403)
        response = self.client.post("/media/images", data={"file": [
            (io.BytesIO(picture()), "first.png", "image/png"),
            (io.BytesIO(picture()), "second.png", "image/png"),
        ]}, headers=self.headers())
        self.assertEqual(response.status_code, 422)
        self.storage.assert_not_called()

    def test_invalid_decode_mime_mismatch_svg_and_animation_are_rejected(self):
        for raw, mime, status in ((b"", "image/png", 422), (b"not-an-image", "image/png", 422),
                                  (picture("PNG"), "image/jpeg", 415),
                                  (b"<svg><script>alert(1)</script></svg>", "image/svg+xml", 415),
                                  (picture("PNG"), "application/octet-stream", 415)):
            self.assertEqual(self.upload(raw, mime).status_code, status)
        stream = io.BytesIO()
        Image.new("RGB", (10, 10), "red").save(stream, format="PNG", save_all=True,
            append_images=[Image.new("RGB", (10, 10), "blue")])
        self.assertEqual(self.upload(stream.getvalue(), "image/png").status_code, 415)
        self.storage.assert_not_called()

    def test_bytes_side_and_pixel_limits_are_checked_before_storage(self):
        self.assertEqual(self.upload(b"x" * (media.MAX_IMAGE_BYTES + 1)).status_code, 413)
        self.assertEqual(self.upload(picture(size=(media.MAX_SOURCE_SIDE + 1, 1))).status_code, 413)
        with patch.object(media, "MAX_PIXELS", 10):
            self.assertEqual(self.upload(picture(size=(4, 4))).status_code, 413)
        self.storage.assert_not_called()

    def test_owner_form_fields_extra_files_and_wrong_content_type_rejected(self):
        self.assertEqual(self.upload(extra={"owner_id": "customer-a"}).status_code, 422)
        self.assertEqual(self.upload(extra={"other": (io.BytesIO(picture()), "other.png", "image/png")}).status_code, 422)
        self.assertEqual(self.client.post("/media/images", json={"file": "bad"}, headers=self.headers()).status_code, 415)
        self.storage.assert_not_called()

    def test_storage_configuration_or_provider_failure_returns_safe_503(self):
        with patch.dict("os.environ", {"FIREBASE_STORAGE_BUCKET": ""}):
            response = self.upload()
            self.assertEqual(response.status_code, 503)
            self.storage.assert_not_called()
        self.blob.upload_from_string.side_effect = RuntimeError("private-credential-error-marker")
        response = self.upload()
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("private-credential", response.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
