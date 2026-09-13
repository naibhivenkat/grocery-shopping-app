"""Admin-only Gmail operations for the Support Center."""

from __future__ import annotations

import base64
import binascii
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
        limit = 20
    query = request.args.get("q", "")
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


def _json_attachments(items):
    if items is None:
        items = []
    if not isinstance(items, list):
        raise ValueError("attachments must be a list")
    if len(items) > 10:
        raise ValueError("At most 10 attachments are allowed")
    result = []
    for item in items or []:
        if not isinstance(item, dict) or not item.get("name"):
            raise ValueError("Each attachment needs a name")
        encoded = item.get("data") or item.get("bytes") or ""
        if not isinstance(encoded, str):
            raise ValueError("Attachment data must be base64 text")
        try:
            decoded = base64.urlsafe_b64decode(
                encoded + "=" * (-len(encoded) % 4)
            )
        except (ValueError, binascii.Error) as exc:
            raise ValueError("Attachment data must be valid base64") from exc
        if len(decoded) > 10 * 1024 * 1024:
            raise ValueError("Each attachment must be 10 MB or smaller")
        result.append({
            "name": item["name"],
            "mime_type": item.get("mime_type"),
            "bytes": decoded,
        })
    return result


@gmail_admin_bp.post("/admin/support/gmail/send")
@require_role("admin", "super_admin")
def gmail_send():
    payload = request.get_json(silent=True) or {}
    try:
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
    payload = request.get_json(silent=True) or {}
    try:
        result = gmail_service.send_email(
            str(payload.get("to") or ""),
            str(payload.get("subject") or "Re: Support request"),
            str(payload.get("body") or ""),
            thread_id=str(payload.get("thread_id") or "") or None,
            in_reply_to=str(payload.get("message_id") or "") or None,
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
    except Exception:
        return jsonify({"detail": "Support synchronization failed"}), 502
