"""Authenticated public catalog-image uploads using server Storage credentials.

Only decoded, re-encoded images are stored. Original filenames/paths and EXIF
metadata are never uploaded. Firebase download-token URLs are suitable for public
shop, product and service images; this endpoint does not handle private documents.
"""

import io
import os
import re
import struct
import uuid
import warnings
from urllib.parse import quote

from firebase_admin import storage
from flask import Blueprint, g, jsonify, request, current_app
from PIL import Image, ImageOps, UnidentifiedImageError

from auth_utils import require_role


media_bp = Blueprint("media", __name__)
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_REQUEST_BYTES = MAX_IMAGE_BYTES + 64 * 1024
MAX_PIXELS = 16_000_000
MAX_SOURCE_SIDE = 8192
MAX_OUTPUT_SIDE = 2048
FORMATS = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}


class ImageUploadError(Exception):
    def __init__(self, detail, status=422):
        self.detail, self.status = detail, status


@media_bp.errorhandler(ImageUploadError)
def _error(error):
    return jsonify({"detail": error.detail}), error.status


def _normalize_image(raw, declared_mime):
    if declared_mime not in FORMATS.values():
        raise ImageUploadError("file must be a JPEG, PNG or WebP image", 415)
    if not raw:
        raise ImageUploadError("Image file is empty")
    if len(raw) > MAX_IMAGE_BYTES:
        raise ImageUploadError("Image file exceeds 5 MiB", 413)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as probe:
                actual_format = probe.format
                if actual_format not in FORMATS or FORMATS[actual_format] != declared_mime:
                    raise ImageUploadError("File content does not match its declared image MIME type", 415)
                width, height = probe.size
                if (width < 1 or height < 1 or max(width, height) > MAX_SOURCE_SIDE
                    or width * height > MAX_PIXELS):
                    raise ImageUploadError("Image exceeds dimension or 16-megapixel limits", 413)
                if getattr(probe, "n_frames", 1) != 1:
                    raise ImageUploadError("Animated images are not supported", 415)
                probe.verify()
            with Image.open(io.BytesIO(raw)) as image:
                image.load()
                oriented = ImageOps.exif_transpose(image)
                oriented.thumbnail((MAX_OUTPUT_SIDE, MAX_OUTPUT_SIDE), Image.Resampling.LANCZOS)
                has_alpha = "A" in oriented.getbands() or "transparency" in oriented.info
                # New image objects have no source EXIF, ICC, comments or text.
                clean = Image.new("RGBA" if has_alpha else "RGB", oriented.size)
                clean.paste(oriented.convert(clean.mode))
                output = io.BytesIO()
                if has_alpha:
                    clean.save(output, format="PNG", optimize=True)
                    extension, mime = "png", "image/png"
                else:
                    clean.save(output, format="JPEG", quality=85, optimize=True)
                    extension, mime = "jpg", "image/jpeg"
                normalized = output.getvalue()
                if len(normalized) > MAX_IMAGE_BYTES:
                    raise ImageUploadError("Re-encoded image exceeds 5 MiB", 413)
                return normalized, extension, mime, clean.width, clean.height
    except ImageUploadError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, struct.error, KeyError, TypeError,
            Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ImageUploadError("Image file is invalid or could not be safely decoded")


@media_bp.post("/media/images")
@require_role("vendor", "service")
def upload_image():
    if (not isinstance(g.user_id, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", g.user_id)
        or g.user_id in (".", "..")):
        raise ImageUploadError("Account cannot upload images", 403)
    if request.mimetype != "multipart/form-data":
        raise ImageUploadError("Use multipart/form-data with one file field named file", 415)
    # Dio multipart forms provide Content-Length. Require it to bound parsing,
    # including malformed multipart bodies, before Werkzeug reads their contents.
    if request.content_length is None:
        raise ImageUploadError("Content-Length is required for image uploads", 411)
    if request.content_length > MAX_REQUEST_BYTES:
        raise ImageUploadError("Image upload request exceeds the size limit", 413)
    if request.form or set(request.files) != {"file"} or len(request.files.getlist("file")) != 1:
        raise ImageUploadError("Provide exactly one file field named file, with no additional form fields")
    upload = request.files["file"]
    try:
        raw = upload.stream.read(MAX_IMAGE_BYTES + 1)
    finally:
        upload.close()
    normalized, extension, mime, width, height = _normalize_image(raw, upload.mimetype)
    bucket_name = os.getenv("FIREBASE_STORAGE_BUCKET", "").strip()
    if not bucket_name or "/" in bucket_name or ":" in bucket_name:
        raise ImageUploadError("Image storage is not configured", 503)
    # User identity is verified from the current database account by require_role.
    # Client-supplied filename, folder, owner and metadata are never used.
    object_id = uuid.uuid4().hex
    path = f"vendor_images/{g.user_id}/{object_id}.{extension}"
    download_token = str(uuid.uuid4())
    try:
        bucket = storage.bucket(name=bucket_name)
        blob = bucket.blob(path)
        blob.metadata = {"firebaseStorageDownloadTokens": download_token, "owner_id": g.user_id}
        blob.cache_control = "public, max-age=31536000, immutable"
        blob.upload_from_string(normalized, content_type=mime, if_generation_match=0, timeout=30)
    except Exception:
        current_app.logger.warning("Catalog image upload failed", exc_info=False)
        raise ImageUploadError("Image storage is temporarily unavailable", 503)
    url = (
        f"https://firebasestorage.googleapis.com/v0/b/{quote(bucket_name, safe='')}/o/"
        f"{quote(path, safe='')}?alt=media&token={download_token}"
    )
    return jsonify({"image_url": url, "path": path, "content_type": mime,
                    "size_bytes": len(normalized), "width": width, "height": height}), 201
