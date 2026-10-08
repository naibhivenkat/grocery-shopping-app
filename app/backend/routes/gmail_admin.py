"""Admin-only Gmail operations for the Support Center."""

from __future__ import annotations

import base64
import binascii
import re
from io import BytesIO

from flask import Blueprint, jsonify, request, send_file
from auth_utils import require_role
from attachment_service import attachment_service
from gmail_service import gmail_service
from sync_service import sync_service
from routes.gmail_auth import GmailAuthError


gmail_admin_bp = Blueprint("gmail_admin", __name__)


def _call(fn):
    try:
        return jsonify(fn()), 200
    except GmailAuthError as exc:
        return jsonify({"detail": str(exc)}), 503
    except ValueError as exc:
        return jsonify({"detail": str(exc)}), 422
    except Exception:
        return jsonify({"detail": "Gmail service temporarily unavailable"}), 502


@gmail_admin_bp.get("/admin/support/gmail/test")
@require_role("admin", "super_admin")
def gmail_test():
    return _call(gmail_service.test_connection)


@gmail_admin_bp.get("/admin/support/gmail/profile")
@require_role("admin", "super_admin")
def gmail_profile():
    return _call(gmail_service.get_profile)


@gmail_admin_bp.get("/admin/support/gmail/labels")
@require_role("admin", "super_admin")
def gmail_labels():
    return _call(gmail_service.get_labels)


@gmail_admin_bp.get("/admin/support/gmail/messages")
@require_role("admin", "super_admin")
def gmail_messages():
    try:
        limit = max(1, min(int(request.args.get("limit", "20")), 100))
    except ValueError:
        return jsonify({"detail": "Invalid message limit"}), 422
    query = request.args.get("q", "")
    if len(query) > 4096:
        return jsonify({"detail": "Search query is too long"}), 422
    return _call(lambda: [
        gmail_service.get_message_summary(item["id"])
        for item in gmail_service.list_messages(query, limit)
        if item.get("id")
    ])


@gmail_admin_bp.get("/admin/support/gmail/messages/<message_id>")
@require_role("admin", "super_admin")
def gmail_message(message_id: str):
    return _call(lambda: gmail_service.parse_message(
        gmail_service.get_message(message_id, "full")
    ))


@gmail_admin_bp.get("/admin/support/gmail/thread/<thread_id>")
@require_role("admin", "super_admin")
def gmail_thread(thread_id: str):
    return _call(lambda: [
        gmail_service.parse_message(message)
        for message in gmail_service.get_thread(thread_id)
    ])


def _send_payload():
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        raise ValueError("JSON object required")
    for field, limit in (("to", 320), ("subject", 998), ("body", 200000), ("thread_id", 128), ("message_id", 128)):
        value = payload.get(field)
        if value is not None and (not isinstance(value, str) or len(value) > limit):
            raise ValueError(f"Invalid {field}")
    required = ("to", "body", "subject") if request.path.endswith("/send") else ("to", "body")
    if any(not isinstance(payload.get(k),str) or not payload[k].strip() for k in required):
        raise ValueError("Recipient, body and subject are required")
    return payload


def _json_attachments(items):
    if items is None:
        items = []
    if not isinstance(items, list):
        raise ValueError("attachments must be a list")
    if len(items) > 10:
        raise ValueError("At most 10 attachments are allowed")
    result = []
    total = 0
    for item in items or []:
        if (not isinstance(item, dict) or not isinstance(item.get("name"), str)
            or not 1 <= len(item["name"]) <= 255 or any(c in item["name"] for c in ("\r", "\n", "/", "\\"))):
            raise ValueError("Each attachment needs a name")
        encoded = item.get("data") or item.get("bytes") or ""
        if not isinstance(encoded, str) or len(encoded) > 14 * 1024 * 1024:
            raise ValueError("Attachment data must be base64 text")
        try:
            decoded = base64.b64decode(
                encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True
            )
        except (ValueError, binascii.Error) as exc:
            raise ValueError("Attachment data must be valid base64") from exc
        if len(decoded) > 10 * 1024 * 1024:
            raise ValueError("Each attachment must be 10 MB or smaller")
        total += len(decoded)
        if total > 20 * 1024 * 1024:
            raise ValueError("Attachments must total 20 MB or smaller")
        mime = item.get("mime_type")
        if mime is not None and (not isinstance(mime, str) or not re.fullmatch(r"[A-Za-z0-9.+_-]+/[A-Za-z0-9.+_-]+", mime)):
            raise ValueError("Invalid attachment MIME type")
        result.append({
            "name": item["name"],
            "mime_type": item.get("mime_type"),
            "bytes": decoded,
        })
    return result


@gmail_admin_bp.post("/admin/support/gmail/send")
@require_role("admin", "super_admin")
def gmail_send():
    try:
        payload = _send_payload()
        result = gmail_service.send_email(
            str(payload.get("to") or ""),
            str(payload.get("subject") or ""),
            str(payload.get("body") or ""),
            attachments=_json_attachments(payload.get("attachments")),
        )
        return jsonify({"success": True, "message_id": result.get("id")}), 200
    except GmailAuthError as exc:
        return jsonify({"detail": str(exc)}), 503
    except ValueError as exc:
        return jsonify({"detail": str(exc)}), 422
    except Exception:
        return jsonify({"detail": "Gmail send failed"}), 502


@gmail_admin_bp.post("/admin/support/gmail/reply")
@require_role("admin", "super_admin")
def gmail_reply():
    try:
        payload = _send_payload()
        parent = payload.get("message_id")
        if not parent or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", parent):
            raise ValueError("A valid Gmail parent message_id is required")
        raw = gmail_service.get_message(parent, "metadata")
        parsed = gmail_service.parse_message(raw)
        if payload.get("thread_id") and payload["thread_id"] != parsed.get("threadId"):
            raise ValueError("Gmail thread mismatch")
        result = gmail_service.send_email(
            str(payload.get("to") or ""),
            str(parsed.get("subject") or "Support request"),
            str(payload.get("body") or ""),
            thread_id=parsed.get("threadId"),
            in_reply_to=parsed.get("message_id_header"),
            attachments=_json_attachments(payload.get("attachments")),
        )
        return jsonify({"success": True, "message_id": result.get("id")}), 200
    except GmailAuthError as exc:
        return jsonify({"detail": str(exc)}), 503
    except ValueError as exc:
        return jsonify({"detail": str(exc)}), 422
    except Exception:
        return jsonify({"detail": "Gmail reply failed"}), 502


@gmail_admin_bp.get("/admin/support/gmail/attachment/<message_id>/<attachment_id>")
@require_role("admin", "super_admin")
def gmail_attachment(message_id: str, attachment_id: str):
    try:
        data = attachment_service.extract(message_id, attachment_id)
        if not data:
            return jsonify({"detail": "Attachment not found"}), 404
        return send_file(
            BytesIO(data),
            mimetype="application/octet-stream",
            as_attachment=True,
            download_name="support-attachment",
        )
    except GmailAuthError as exc:
        return jsonify({"detail": str(exc)}), 503
    except ValueError as exc:
        return jsonify({"detail": str(exc)}), 422
    except Exception:
        return jsonify({"detail": "Gmail attachment unavailable"}), 502


@gmail_admin_bp.post("/admin/support/sync")
@require_role("admin", "super_admin")
def support_sync():
    """Ingest new Gmail messages into Firestore support tickets idempotently."""
    try:
        return jsonify({"success": True, **sync_service.process_webhook_queue()}), 200
    except GmailAuthError as exc:
        return jsonify({"detail": str(exc)}), 503
    except ValueError as exc:
        return jsonify({"detail": str(exc)}), 422
    except Exception:
        return jsonify({"detail": "Support synchronization failed"}), 502
