"""
Gmail Service

Business layer over Gmail API.

Responsibilities
----------------
- Test Gmail connectivity
- Read Gmail profile
- Read labels
- List messages
- Read message
- Read thread

No Flask routes.
No Firestore writes.
No Support Ticket logic.
"""

from __future__ import annotations


from email.header import decode_header, make_header
from typing import Any

from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
import mimetypes
import os
import base64

from routes.gmail_auth import get_gmail_service


class GmailService:

    def __init__(self):
        self.service = get_gmail_service()

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def test_connection(self) -> dict[str, Any]:
        profile = (
            self.service.users()
            .getProfile(userId="me")
            .execute()
        )

        return {
            "success": True,
            "connected": True,
            "gmail_email": profile.get("emailAddress"),
            "messages_total": profile.get("messagesTotal", 0),
            "threads_total": profile.get("threadsTotal", 0),
            "history_id": profile.get("historyId"),
        }

    # ------------------------------------------------------------------
    # Profile
    # ------------------------------------------------------------------

    def get_profile(self) -> dict[str, Any]:
        return (
            self.service.users()
            .getProfile(userId="me")
            .execute()
        )

    # ------------------------------------------------------------------
    # Labels
    # ------------------------------------------------------------------

    def get_labels(self) -> list[dict]:
        response = (
            self.service.users()
            .labels()
            .list(userId="me")
            .execute()
        )

        return response.get("labels", [])

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------


    def list_messages(
            self,
            query: str = "",
            max_results: int = 20,
    ) -> list[dict]:
        """
        Returns only support emails.

        Default:
            - Must have Support label
            - Must be in Inbox
            - Excludes Sent mail

        Additional search text from the UI is appended.
        """

        gmail_query = "label:Support"

        if query:
            gmail_query += f" {query}"

        response = (
            self.service.users()
            .messages()
            .list(
                userId="me",
                q=gmail_query,
                maxResults=max_results,
            )
            .execute()
        )

        return response.get("messages", [])

    def get_reply_to(self, payload: dict) -> str:
        return self.get_header(
            payload.get("headers", []),
            "Reply-To",
        )



    def get_message(
        self,
        message_id: str,
        fmt: str = "full",
    ) -> dict:

        return (
            self.service.users()
            .messages()
            .get(
                userId="me",
                id=message_id,
                format=fmt,
            )
            .execute()
        )


    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def get_header(
        headers: list[dict],
        name: str,
    ) -> str:

        for h in headers:
            if h.get("name", "").lower() == name.lower():
                return h.get("value", "")

        return ""

    @staticmethod
    def decode_header(value: str) -> str:
        try:
            return str(make_header(decode_header(value)))
        except Exception:
            return value

    def get_subject(self, payload: dict) -> str:

        subject = self.get_header(
            payload.get("headers", []),
            "Subject",
        )

        return self.decode_header(subject)

    def get_from(self, payload: dict) -> str:
        return self.get_header(
            payload.get("headers", []),
            "From",
        )

    def get_to(self, payload: dict) -> str:
        return self.get_header(
            payload.get("headers", []),
            "To",
        )

    def get_date(self, payload: dict) -> str:
        return self.get_header(
            payload.get("headers", []),
            "Date",
        )

    def extract_plain_text(
        self,
        payload: dict,
    ) -> str:

        mime = payload.get("mimeType")

        if mime == "text/plain":
            data = payload.get("body", {}).get("data")

            if data:
                return base64.urlsafe_b64decode(
                    data.encode()
                ).decode(
                    "utf-8",
                    errors="ignore",
                )

        for part in payload.get("parts", []):

            if part.get("mimeType") == "text/plain":

                data = (
                    part.get("body", {})
                    .get("data")
                )

                if data:
                    return base64.urlsafe_b64decode(
                        data.encode()
                    ).decode(
                        "utf-8",
                        errors="ignore",
                    )

        return ""

    def get_message_summary(
        self,
        message_id: str,
    ) -> dict:

        message = self.get_message(message_id)

        payload = message.get("payload", {})
        reply_to = self.get_reply_to(payload)

        return {
            "id": message.get("id"),
            "thread_id": message.get("threadId"),
            "snippet": message.get("snippet", ""),
            "subject": self.get_subject(payload),
            "from": self.get_from(payload),
            "reply_to": reply_to,
            "to": self.get_to(payload),
            "date": self.get_date(payload),
            "body": self.extract_plain_text(payload),
            "label_ids": message.get("labelIds", []),
            "internal_date": message.get("internalDate"),
        }

    def get_thread(
            self,
            thread_id: str,
    ) -> list[dict]:
        """
        Returns all messages in a Gmail conversation.
        """

        thread = (
            self.service.users()
            .threads()
            .get(
                userId="me",
                id=thread_id,
                format="full",
            )
            .execute()
        )

        results = []

        for message in thread.get("messages", []):
            payload = message.get("payload", {})

            results.append(
                {
                    "id": message.get("id"),
                    "thread_id": message.get("threadId"),
                    "snippet": message.get("snippet", ""),
                    "subject": self.get_subject(payload),
                    "from": self.get_from(payload),
                    "reply_to": self.get_reply_to(payload),
                    "to": self.get_to(payload),
                    "date": self.get_date(payload),
                    "body": self.extract_plain_text(payload),
                    "label_ids": message.get("labelIds", []),
                    "internal_date": message.get("internalDate"),
                }

            )

        return results

    def reply_to_thread(
            self,
            thread_id: str,
            to: str,
            subject: str,
            body: str,
    ) -> dict:
        """
        Send a reply in an existing Gmail thread.
        """

        message = MIMEText(body, "plain", "utf-8")

        message["To"] = to
        message["Subject"] = subject

        raw = base64.urlsafe_b64encode(
            message.as_bytes()
        ).decode()

        response = (
            self.service.users()
            .messages()
            .send(
                userId="me",
                body={
                    "raw": raw,
                    "threadId": thread_id,
                },
            )
            .execute()
        )

        return response

    def send_email(
            self,
            to: str,
            subject: str,
            body: str,
            cc: str = "",
            bcc: str = "",
            attachments: list[str] | None = None,
    ) -> dict:
        """
        Send a brand-new Gmail message with optional attachments.
        """

        message = MIMEMultipart()

        message["To"] = to
        message["Subject"] = subject

        if cc:
            message["Cc"] = cc

        if bcc:
            message["Bcc"] = bcc

        message.attach(
            MIMEText(body, "plain", "utf-8")
        )

        for attachment in attachments or []:
            filename = attachment.get("name")
            encoded = attachment.get("bytes")

            if not filename or not encoded:
                continue

            file_bytes = base64.b64decode(encoded)

            content_type = (
                    mimetypes.guess_type(filename)[0]
                    or "application/octet-stream"
            )

            maintype, subtype = content_type.split("/", 1)

            part = MIMEBase(maintype, subtype)
            part.set_payload(file_bytes)

            encoders.encode_base64(part)

            part.add_header(
                "Content-Disposition",
                f'attachment; filename="{filename}"',
            )

            message.attach(part)

        raw = base64.urlsafe_b64encode(
            message.as_bytes()
        ).decode()

        return (
            self.service.users()
            .messages()
            .send(
                userId="me",
                body={
                    "raw": raw,
                },
            )
            .execute()
        )


gmail_service = GmailService()
