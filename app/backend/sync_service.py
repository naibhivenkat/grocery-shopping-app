"""Service for synchronizing Gmail inbox state with Firestore Support Tickets."""

from google.cloud.firestore_v1.base_query import FieldFilter
from db import (
    col,
    doc,
    now_iso,
    SUPPORT_TICKETS,
    SUPPORT_MESSAGES,
    SUPPORT_SYNC,
)
from gmail_service import gmail_service


class SyncService:
    def process_webhook_queue(self):
        """
        Triggered asynchronously or via cron.
        Checks for new history IDs and ingests missing emails into Firestore.
        """
        sync_state_ref = doc(SUPPORT_SYNC, "state")
        sync_state = sync_state_ref.get().to_dict() or {}

        last_history_id = sync_state.get("last_processed_history_id")
        latest_history_id = sync_state.get("latest_history_id")

        if not last_history_id:
            # First time setup or missing state
            return

        if last_history_id == latest_history_id:
            # Already up to date
            return

        history_records = gmail_service.list_history(last_history_id)

        for record in history_records:
            messages_added = record.get("messagesAdded", [])
            for msg_wrapper in messages_added:
                msg_info = msg_wrapper.get("message", {})
                message_id = msg_info.get("id")

                if message_id:
                    self._ingest_message(message_id)

        # Update state lock
        sync_state_ref.set({
            "last_processed_history_id": latest_history_id,
            "status": "idle",
            "last_sync_time": now_iso()
        }, merge=True)

    def _ingest_message(self, message_id: str):
        """Fetches a single raw message, parses it, and maps it to a Ticket."""
        raw_msg = gmail_service.get_message_raw(message_id)
        if not raw_msg:
            return

        parsed = gmail_service.parse_message(raw_msg)
        gmail_thread_id = parsed.get("threadId")

        # Check if we already have this thread
        tickets_query = col(SUPPORT_TICKETS).where(
            filter=FieldFilter("gmail_thread_id", "==", gmail_thread_id)
        ).stream()

        existing_tickets = list(tickets_query)

        if existing_tickets:
            ticket_doc = existing_tickets[0]
            ticket_id = ticket_doc.id
            self._append_message_to_ticket(ticket_id, parsed)
        else:
            self._create_new_ticket_from_message(parsed)

    def _create_new_ticket_from_message(self, parsed: dict):
        """Creates a new top-level Support Ticket from an inbound email."""
        ticket_ref = col(SUPPORT_TICKETS).document()
        ticket_id = ticket_ref.id

        # Build initial ticket metadata
        ticket_ref.set({
            "uid": ticket_id,
            "gmail_thread_id": parsed.get("threadId"),
            "subject": parsed.get("subject", "No Subject"),
            "customer_email": parsed.get("from", "Unknown"),
            "status": "open",
            "created_at": now_iso(),
            "updated_at": now_iso()
        })

        self._append_message_to_ticket(ticket_id, parsed)

    def _append_message_to_ticket(self, ticket_id: str, parsed: dict):
        """Attaches a parsed Gmail payload as a child document to a Ticket."""
        # Ensure idempotent insertions using Gmail's immutable ID
        msg_id = parsed.get("id")
        msg_ref = doc(SUPPORT_MESSAGES, msg_id)

        if msg_ref.get().exists:
            return  # Avoid duplicates

        msg_ref.set({
            "uid": msg_id,
            "ticket_id": ticket_id,
            "direction": "inbound",
            "from": parsed.get("from"),
            "to": parsed.get("to"),
            "subject": parsed.get("subject"),
            "bodyText": parsed.get("body_text"),
            "bodyHtml": parsed.get("body_html"),
            "internal_date": now_iso(),
            "status": "delivered"
        })

        # Bump the ticket's updated_at marker for sorting
        doc(SUPPORT_TICKETS, ticket_id).set({
            "status": "open",
            "updated_at": now_iso()
        }, merge=True)


sync_service = SyncService()