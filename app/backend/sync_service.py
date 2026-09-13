"""Idempotent Gmail-history synchronizer for Support Center tickets."""

from google.cloud.firestore_v1.base_query import FieldFilter

from db import SUPPORT_MESSAGES, SUPPORT_SYNC, SUPPORT_TICKETS, col, doc, now_iso
from gmail_service import gmail_service


class SyncService:
    def process_webhook_queue(self) -> dict:
        """Consume Gmail history newer than the stored webhook cursor."""
        state_ref = doc(SUPPORT_SYNC, "state")
        state = state_ref.get().to_dict() or {}
        latest = state.get("latest_history_id")

        if not latest:
            latest = gmail_service.get_profile().get("historyId")
            if latest:
                state_ref.set({
                    "latest_history_id": latest,
                    "last_processed_history_id": latest,
                    "status": "idle",
                    "last_sync_time": now_iso(),
                }, merge=True)
            return {"ingested": 0, "status": "initialized"}

        last = state.get("last_processed_history_id")
        if not last or last == latest:
            return {"ingested": 0, "status": "idle"}

        ingested = 0
        for record in gmail_service.list_history(str(last)):
            for wrapper in record.get("messagesAdded", []) or []:
                message_id = (wrapper.get("message") or {}).get("id")
                if message_id and self._ingest_message(message_id):
                    ingested += 1

        state_ref.set({
            "last_processed_history_id": latest,
            "status": "idle",
            "last_sync_time": now_iso(),
        }, merge=True)
        return {"ingested": ingested, "status": "idle"}

    def _ingest_message(self, message_id: str) -> bool:
        parsed = gmail_service.parse_message(
            gmail_service.get_message(message_id, "full")
        )
        thread_id = parsed.get("threadId")
        existing = list(col(SUPPORT_TICKETS).where(
            filter=FieldFilter("gmail_thread_id", "==", thread_id)
        ).limit(1).stream())
        ticket_id = existing[0].id if existing else col(SUPPORT_TICKETS).document().id

        if not existing:
            doc(SUPPORT_TICKETS, ticket_id).set({
                "uid": ticket_id,
                "gmail_thread_id": thread_id,
                "subject": parsed.get("subject") or "No Subject",
                "customer_email": parsed.get("from") or "Unknown",
                "status": "open",
                "created_at": now_iso(),
                "updated_at": now_iso(),
            })

        message_ref = doc(SUPPORT_MESSAGES, message_id)
        if message_ref.get().exists:
            return False
        message_ref.set({
            "uid": message_id,
            "ticket_id": ticket_id,
            "direction": "inbound",
            "from": parsed.get("from"),
            "to": parsed.get("to"),
            "subject": parsed.get("subject"),
            "bodyText": parsed.get("body_text"),
            "bodyHtml": parsed.get("body_html"),
            "internal_date": now_iso(),
            "status": "delivered",
        })
        doc(SUPPORT_TICKETS, ticket_id).set({
            "status": "open",
            "updated_at": now_iso(),
        }, merge=True)
        return True


sync_service = SyncService()
