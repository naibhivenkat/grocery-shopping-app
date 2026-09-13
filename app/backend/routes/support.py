"""Admin Support Center ticket and webhook endpoints.

Gmail ingestion and outbound delivery are deliberately separate workers. The
HTTP API stores ticket state and queues outbound messages; it never trusts a
client-provided admin identity or exposes Gmail credentials.
"""

from flask import Blueprint, g, jsonify, request
from google.cloud.firestore_v1.base_query import FieldFilter

from auth_utils import log_admin_action, require_role, require_webhook_secret
from db import (
    SUPPORT_INTERNAL_NOTES,
    SUPPORT_MESSAGES,
    SUPPORT_SYNC,
    SUPPORT_TICKETS,
    col,
    doc,
    now_iso,
    to_dict,
)


support_bp = Blueprint("support", __name__)


@support_bp.post("/admin/support/webhook")
@require_webhook_secret
def support_webhook():
    payload = request.get_json(silent=True) or {}
    message = payload.get("message") or {}
    history_id = message.get("historyId") or message.get("messageId") or "unknown"
    doc(SUPPORT_SYNC, "state").set({
        "last_webhook_received": now_iso(),
        "latest_history_id": history_id,
        "status": "pending_sync",
    }, merge=True)
    return jsonify({"success": True}), 200


@support_bp.get("/admin/support")
@require_role("admin", "super_admin")
def list_support_tickets():
    status_filter = (request.args.get("status") or "").strip()
    query = col(SUPPORT_TICKETS)
    if status_filter:
        query = query.where(filter=FieldFilter("status", "==", status_filter))
    tickets = [to_dict(item) for item in query.order_by(
        "updated_at", direction="DESCENDING"
    ).stream()]
    return jsonify(tickets), 200


@support_bp.get("/admin/support/<ticket_id>")
@require_role("admin", "super_admin")
def get_support_ticket(ticket_id):
    ticket_snap = doc(SUPPORT_TICKETS, ticket_id).get()
    if not ticket_snap.exists:
        return jsonify({"detail": "Ticket not found"}), 404

    ticket = to_dict(ticket_snap)
    ticket["messages"] = [to_dict(item) for item in col(SUPPORT_MESSAGES).where(
        filter=FieldFilter("ticket_id", "==", ticket_id)
    ).stream()]
    ticket["notes"] = [to_dict(item) for item in col(SUPPORT_INTERNAL_NOTES).where(
        filter=FieldFilter("ticket_id", "==", ticket_id)
    ).stream()]
    ticket["messages"].sort(key=lambda item: item.get("internal_date") or "")
    ticket["notes"].sort(key=lambda item: item.get("timestamp") or "")
    return jsonify(ticket), 200


@support_bp.post("/admin/support/<ticket_id>/reply")
@require_role("admin", "super_admin")
def reply_support_ticket(ticket_id):
    payload = request.get_json(silent=True) or {}
    reply_body = str(payload.get("reply") or "").strip()
    if not reply_body:
        return jsonify({"detail": "Reply body is required"}), 422

    ticket_ref = doc(SUPPORT_TICKETS, ticket_id)
    if not ticket_ref.get().exists:
        return jsonify({"detail": "Ticket not found"}), 404

    message_ref = col(SUPPORT_MESSAGES).document()
    message_ref.set({
        "uid": message_ref.id,
        "ticket_id": ticket_id,
        "direction": "outbound",
        "from": "support@alllocal.in",
        "bodyText": reply_body,
        "internal_date": now_iso(),
        "admin_id": g.user_id,
        "status": "pending_send",
    })
    now = now_iso()
    ticket_ref.set({
        "status": "resolved",
        "updated_at": now,
        "resolved_at": now,
    }, merge=True)
    log_admin_action(
        admin_id=g.user_id,
        admin_email=getattr(g, "user_email", ""),
        action="Reply to Ticket",
        target_id=ticket_id,
        target_type="support_ticket",
    )
    return jsonify({"success": True, "message_id": message_ref.id}), 200


@support_bp.post("/admin/support/<ticket_id>/notes")
@require_role("admin", "super_admin")
def add_internal_note(ticket_id):
    payload = request.get_json(silent=True) or {}
    note_text = str(payload.get("note") or "").strip()
    if not note_text:
        return jsonify({"detail": "Note text is required"}), 422
    if not doc(SUPPORT_TICKETS, ticket_id).get().exists:
        return jsonify({"detail": "Ticket not found"}), 404

    note_ref = col(SUPPORT_INTERNAL_NOTES).document()
    note_ref.set({
        "uid": note_ref.id,
        "ticket_id": ticket_id,
        "admin_id": g.user_id,
        "admin_name": getattr(g, "user_name", "Admin"),
        "note": note_text,
        "timestamp": now_iso(),
    })
    return jsonify({"success": True, "note_id": note_ref.id}), 200
