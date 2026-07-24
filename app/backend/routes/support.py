"""Routes for the Enterprise Support Center."""

from flask import Blueprint, jsonify, request, g
from google.cloud.firestore_v1.base_query import FieldFilter

from auth_utils import require_role, log_admin_action, require_webhook_secret
from db import (
    col,
    doc,
    now_iso,
    to_dict,
    SUPPORT_TICKETS,
    SUPPORT_MESSAGES,
    SUPPORT_INTERNAL_NOTES,
    SUPPORT_SYNC,
)

support_bp = Blueprint("support", __name__)


@support_bp.post("/admin/support/webhook")
@require_webhook_secret
def support_webhook():
    """
    Google Cloud Pub/Sub webhook endpoint.
    Triggered by the Gmail API when a new email arrives or state changes.
    """
    data = request.get_json(force=True, silent=True) or {}
    message = data.get("message", {})

    history_id = message.get("messageId") or "unknown"

    # Store the trigger state. The background Sync Service will process this.
    doc(SUPPORT_SYNC, "state").set({
        "last_webhook_received": now_iso(),
        "latest_history_id": history_id,
        "status": "pending_sync"
    }, merge=True)

    return jsonify({"success": True}), 200


@support_bp.get("/admin/support")
@require_role("admin", "super_admin")
def list_support_tickets():
    """Fetch paginated, filterable omnichannel support tickets."""
    status_filter = request.args.get("status")
    query = col(SUPPORT_TICKETS)

    if status_filter:
        query = query.where(filter=FieldFilter("status", "==", status_filter))

    # Relies on composite index (status ASC, updated_at DESC)
    docs = query.order_by("updated_at", direction="DESCENDING").stream()

    tickets = [to_dict(d) for d in docs]
    return jsonify(tickets)


@support_bp.get("/admin/support/<ticket_id>")
@require_role("admin", "super_admin")
def get_support_ticket(ticket_id):
    """Retrieve full ticket metadata along with child messages and notes."""
    snap = doc(SUPPORT_TICKETS, ticket_id).get()
    if not snap.exists:
        return jsonify({"detail": "Ticket not found"}), 404

    ticket = to_dict(snap)

    messages = [
        to_dict(m)
        for m in col(SUPPORT_MESSAGES)
        .where(filter=FieldFilter("ticket_id", "==", ticket_id))
        .order_by("internal_date", direction="ASCENDING")
        .stream()
    ]

    notes = [
        to_dict(n)
        for n in col(SUPPORT_INTERNAL_NOTES)
        .where(filter=FieldFilter("ticket_id", "==", ticket_id))
        .order_by("timestamp", direction="ASCENDING")
        .stream()
    ]

    ticket["messages"] = messages
    ticket["internal_notes"] = notes

    return jsonify(ticket)


@support_bp.post("/admin/support/<ticket_id>/reply")
@require_role("admin", "super_admin")
def reply_support_ticket(ticket_id):
    """
    Saves an outbound reply to Firestore.
    The background Gmail Service uses this event to transmit the email.
    """
    data = request.get_json(force=True)
    reply_body = data.get("reply", "")

    if not reply_body:
        return jsonify({"error": "Reply body is required"}), 400

    ticket_ref = doc(SUPPORT_TICKETS, ticket_id)
    if not ticket_ref.get().exists:
        return jsonify({"error": "Ticket not found"}), 404

    msg_ref = col(SUPPORT_MESSAGES).document()
    msg_ref.set({
        "uid": msg_ref.id,
        "ticket_id": ticket_id,
        "direction": "outbound",
        "from": "support@alllocal.in",
        "bodyText": reply_body,
        "internal_date": now_iso(),
        "admin_id": g.user_id,
        "status": "pending_send"
    })

    ticket_ref.set({
        "status": "resolved",
        "updated_at": now_iso(),
        "resolved_at": now_iso()
    }, merge=True)

    log_admin_action(
        admin_id=g.user_id,
        admin_email=getattr(g, "user_email", ""),
        action="Reply to Ticket",
        target_id=ticket_id,
        target_type="support_ticket"
    )

    return jsonify({"success": True, "message_id": msg_ref.id})


@support_bp.post("/admin/support/<ticket_id>/notes")
@require_role("admin", "super_admin")
def add_internal_note(ticket_id):
    """Appends a private administrative note to the ticket timeline."""
    data = request.get_json(force=True)
    note_text = data.get("note", "").strip()

    if not note_text:
        return jsonify({"error": "Note text is required"}), 400

    note_ref = col(SUPPORT_INTERNAL_NOTES).document()
    note_ref.set({
        "uid": note_ref.id,
        "ticket_id": ticket_id,
        "admin_id": g.user_id,
        "admin_name": getattr(g, "user_name", "Admin"),
        "note": note_text,
        "timestamp": now_iso()
    })

    return jsonify({"success": True, "note_id": note_ref.id})