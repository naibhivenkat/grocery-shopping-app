# """
# Gmail Service
#
# Business layer over Gmail API.
#
# Responsibilities
# ----------------
# - Test Gmail connectivity
# - Read Gmail profile
# - Read labels
# - List messages
# - Read message
# - Read thread
#
# No Flask routes.
# No Firestore writes.
# No Support Ticket logic.
# """
#
# from __future__ import annotations
#
# import re
# from email.header import decode_header, make_header
# from typing import Any
#
# from email.mime.text import MIMEText
# from email.mime.multipart import MIMEMultipart
# from email.mime.base import MIMEBase
# from email import encoders
# import mimetypes
# import os
# import base64
#
# from routes.gmail_auth import get_gmail_service
#
#
# class GmailService:
#
#     def __init__(self):
#         self.service = get_gmail_service()
#
#     # ------------------------------------------------------------------
#     # Connection
#     # ------------------------------------------------------------------
#
#     def test_connection(self) -> dict[str, Any]:
#         profile = (
#             self.service.users()
#             .getProfile(userId="me")
#             .execute()
#         )
#
#         return {
#             "success": True,
#             "connected": True,
#             "gmail_email": profile.get("emailAddress"),
#             "messages_total": profile.get("messagesTotal", 0),
#             "threads_total": profile.get("threadsTotal", 0),
#             "history_id": profile.get("historyId"),
#         }
#
#     # ------------------------------------------------------------------
#     # Profile
#     # ------------------------------------------------------------------
#
#     def get_profile(self) -> dict[str, Any]:
#         return (
#             self.service.users()
#             .getProfile(userId="me")
#             .execute()
#         )
#
#     # ------------------------------------------------------------------
#     # Labels
#     # ------------------------------------------------------------------
#
#     def get_labels(self) -> list[dict]:
#         response = (
#             self.service.users()
#             .labels()
#             .list(userId="me")
#             .execute()
#         )
#
#         return response.get("labels", [])
#
#     # ------------------------------------------------------------------
#     # Messages
#     # ------------------------------------------------------------------
#
#     def list_messages(
#             self,
#             query: str = "",
#             max_results: int = 20,
#     ) -> list[dict]:
#         """
#         Returns only support emails.
#
#         Default:
#             - Must have Support label
#             - Must be in Inbox
#             - Excludes Sent mail
#
#         Additional search text from the UI is appended.
#         """
#
#         gmail_query = "label:Support"
#
#         if query:
#             gmail_query += f" {query}"
#
#         response = (
#             self.service.users()
#             .messages()
#             .list(
#                 userId="me",
#                 q=gmail_query,
#                 maxResults=max_results,
#             )
#             .execute()
#         )
#
#         return response.get("messages", [])
#
#     def get_reply_to(self, payload: dict) -> str:
#         return self.get_header(
#             payload.get("headers", []),
#             "Reply-To",
#         )
#
#     def get_message(
#             self,
#             message_id: str,
#             fmt: str = "full",
#     ) -> dict:
#
#         return (
#             self.service.users()
#             .messages()
#             .get(
#                 userId="me",
#                 id=message_id,
#                 format=fmt,
#             )
#             .execute()
#         )
#
#     # ------------------------------------------------------------------
#     # Helpers
#     # ------------------------------------------------------------------
#
#     @staticmethod
#     def get_header(
#             headers: list[dict],
#             name: str,
#     ) -> str:
#
#         for h in headers:
#             if h.get("name", "").lower() == name.lower():
#                 return h.get("value", "")
#
#         return ""
#
#     @staticmethod
#     def decode_header(value: str) -> str:
#         try:
#             return str(make_header(decode_header(value)))
#         except Exception:
#             return value
#
#     def get_subject(self, payload: dict) -> str:
#
#         subject = self.get_header(
#             payload.get("headers", []),
#             "Subject",
#         )
#
#         return self.decode_header(subject)
#
#     def get_from(self, payload: dict) -> str:
#         return self.get_header(
#             payload.get("headers", []),
#             "From",
#         )
#
#     def get_to(self, payload: dict) -> str:
#         return self.get_header(
#             payload.get("headers", []),
#             "To",
#         )
#
#     def get_date(self, payload: dict) -> str:
#         return self.get_header(
#             payload.get("headers", []),
#             "Date",
#         )
#
#     def extract_plain_text(
#             self,
#             payload: dict,
#     ) -> str:
#
#         mime = payload.get("mimeType")
#
#         if mime == "text/plain":
#             data = payload.get("body", {}).get("data")
#
#             if data:
#                 text = base64.urlsafe_b64decode(
#                     data.encode()
#                 ).decode(
#                     "utf-8",
#                     errors="ignore",
#                 )
#
#                 return self.clean_email_body(text)
#
#         for part in payload.get("parts", []):
#             text = self.extract_plain_text(part)
#
#             if text:
#                 return text
#
#         return ""
#
#     import re
#
#     def clean_email_body(
#             self,
#             body: str,
#     ) -> str:
#         if not body:
#             return ""
#
#         body = body.replace("\r\n", "\n")
#
#         # Remove quoted conversation
#         split_patterns = [
#             r"\nOn .+? wrote:",
#             r"\nFrom:.*",
#             r"\nSent:.*",
#             r"\nTo:.*",
#             r"\nSubject:.*",
#             r"\n-----Original Message-----",
#             r"\n_{10,}",
#         ]
#
#         for pattern in split_patterns:
#             match = re.search(
#                 pattern,
#                 body,
#                 flags=re.IGNORECASE | re.DOTALL,
#             )
#             if match:
#                 body = body[:match.start()]
#                 break
#
#         # Remove excessive blank lines
#         body = re.sub(r"\n{3,}", "\n\n", body)
#
#         return body.strip()
#
#     def extract_attachments(self, payload: dict) -> list[dict]:
#         """
#         Recursively extract attachment metadata from a Gmail message payload.
#         """
#
#         attachments = []
#
#         def walk(part: dict):
#             filename = part.get("filename", "")
#
#             body = part.get("body", {})
#
#             attachment_id = body.get("attachmentId")
#
#             if filename and attachment_id:
#                 attachments.append(
#                     {
#                         "filename": filename,
#                         "mime_type": part.get(
#                             "mimeType",
#                             "application/octet-stream",
#                         ),
#                         "attachment_id": attachment_id,
#                         "size": body.get("size", 0),
#                     }
#                 )
#
#             for child in part.get("parts", []):
#                 walk(child)
#
#         walk(payload)
#
#         return attachments
#
#     def get_message_summary(
#             self,
#             message_id: str,
#     ) -> dict:
#
#         message = self.get_message(message_id)
#
#         payload = message.get("payload", {})
#         reply_to = self.get_reply_to(payload)
#
#         return {
#             "id": message.get("id"),
#             "thread_id": message.get("threadId"),
#             "snippet": message.get("snippet", ""),
#             "subject": self.get_subject(payload),
#             "from": self.get_from(payload),
#             "reply_to": reply_to,
#             "to": self.get_to(payload),
#             "date": self.get_date(payload),
#             "body": self.extract_plain_text(payload),
#             "label_ids": message.get("labelIds", []),
#             "internal_date": message.get("internalDate"),
#
#             "attachments": self.extract_attachments(payload),
#         }
#
#     def get_thread(
#             self,
#             thread_id: str,
#     ) -> list[dict]:
#         """
#         Returns all messages in a Gmail conversation.
#         """
#
#         thread = (
#             self.service.users()
#             .threads()
#             .get(
#                 userId="me",
#                 id=thread_id,
#                 format="full",
#             )
#             .execute()
#         )
#
#         results = []
#
#         for message in thread.get("messages", []):
#             payload = message.get("payload", {})
#
#             results.append(
#                 {
#                     "id": message.get("id"),
#                     "thread_id": message.get("threadId"),
#                     "snippet": message.get("snippet", ""),
#                     "subject": self.get_subject(payload),
#                     "from": self.get_from(payload),
#                     "reply_to": self.get_reply_to(payload),
#                     "to": self.get_to(payload),
#                     "date": self.get_date(payload),
#                     "body": self.extract_plain_text(payload),
#                     "label_ids": message.get("labelIds", []),
#                     "internal_date": message.get("internalDate"),
#
#                     "attachments": self.extract_attachments(payload),
#                 }
#             )
#
#         return results
#
#     def reply_to_thread(
#             self,
#             thread_id: str,
#             to: str,
#             subject: str,
#             body: str,
#             attachments=None,
#     ) -> dict:
#         """
#         Send a reply in an existing Gmail thread.
#         """
#
#         message = MIMEMultipart()
#
#         message["To"] = to
#         message["Subject"] = subject
#         message["MIME-Version"] = "1.0"
#
#         message.attach(
#             MIMEText(body, "plain", "utf-8")
#         )
#
#         for uploaded in attachments or []:
#             uploaded.seek(0)
#
#             mime_type = uploaded.mimetype or "application/octet-stream"
#
#             if "/" in mime_type:
#                 main, sub = mime_type.split("/", 1)
#             else:
#                 main = "application"
#                 sub = "octet-stream"
#
#             part = MIMEBase(main, sub)
#             part.set_payload(uploaded.read())
#
#             encoders.encode_base64(part)
#
#             part.add_header(
#                 "Content-Disposition",
#                 f'attachment; filename="{uploaded.filename}"',
#             )
#
#             message.attach(part)
#
#         raw = base64.urlsafe_b64encode(
#             message.as_bytes()
#         ).decode()
#
#         response = (
#             self.service.users()
#             .messages()
#             .send(
#                 userId="me",
#                 body={
#                     "raw": raw,
#                     "threadId": thread_id,
#                 },
#             )
#             .execute()
#         )
#
#         return response
#
#     def send_email(
#             self,
#             to: str,
#             subject: str,
#             body: str,
#             cc: str = "",
#             bcc: str = "",
#             attachments: list[str] | None = None,
#     ) -> dict:
#         """
#         Send a brand-new Gmail message with optional attachments.
#         """
#
#         message = MIMEMultipart()
#
#         message["To"] = to
#         message["Subject"] = subject
#
#         if cc:
#             message["Cc"] = cc
#
#         if bcc:
#             message["Bcc"] = bcc
#
#         message.attach(
#             MIMEText(body, "plain", "utf-8")
#         )
#
#         for attachment in attachments or []:
#             filename = attachment.get("name")
#             encoded = attachment.get("bytes")
#
#             if not filename or not encoded:
#                 continue
#
#             file_bytes = base64.b64decode(encoded)
#
#             content_type = (
#                     mimetypes.guess_type(filename)[0]
#                     or "application/octet-stream"
#             )
#
#             maintype, subtype = content_type.split("/", 1)
#
#             part = MIMEBase(maintype, subtype)
#             part.set_payload(file_bytes)
#
#             encoders.encode_base64(part)
#
#             part.add_header(
#                 "Content-Disposition",
#                 f'attachment; filename="{filename}"',
#             )
#
#             message.attach(part)
#
#         raw = base64.urlsafe_b64encode(
#             message.as_bytes()
#         ).decode()
#
#         return (
#             self.service.users()
#             .messages()
#             .send(
#                 userId="me",
#                 body={
#                     "raw": raw,
#                 },
#             )
#             .execute()
#         )
#
#     def download_attachment(
#             self,
#             message_id: str,
#             attachment_id: str,
#     ) -> tuple[bytes, str]:
#         """
#         Download a Gmail attachment.
#         """
#
#         message = self.get_message(message_id)
#
#         payload = message.get("payload", {})
#
#         filename = "attachment"
#
#         mime_type = "application/octet-stream"
#
#         def find_attachment(part: dict):
#             nonlocal filename, mime_type
#
#             body = part.get("body", {})
#
#             if body.get("attachmentId") == attachment_id:
#                 filename = part.get("filename") or filename
#                 mime_type = part.get("mimeType") or mime_type
#                 return True
#
#             for child in part.get("parts", []):
#                 if find_attachment(child):
#                     return True
#
#             return False
#
#         find_attachment(payload)
#
#         response = (
#             self.service.users()
#             .messages()
#             .attachments()
#             .get(
#                 userId="me",
#                 messageId=message_id,
#                 id=attachment_id,
#             )
#             .execute()
#         )
#
#         data = base64.urlsafe_b64decode(
#             response["data"].encode()
#         )
#
#         return data, filename, mime_type
#
#
# gmail_service = GmailService()


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

import re
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
                text = base64.urlsafe_b64decode(
                    data.encode()
                ).decode(
                    "utf-8",
                    errors="ignore",
                )

                return self.clean_email_body(text)

        for part in payload.get("parts", []):
            text = self.extract_plain_text(part)

            if text:
                return text

        return ""

    import re

    def clean_email_body(
            self,
            body: str,
    ) -> str:
        if not body:
            return ""

        body = body.replace("\r\n", "\n")

        # Remove quoted conversation
        split_patterns = [
            r"\nOn .+? wrote:",
            r"\nFrom:.*",
            r"\nSent:.*",
            r"\nTo:.*",
            r"\nSubject:.*",
            r"\n-----Original Message-----",
            r"\n_{10,}",
        ]

        for pattern in split_patterns:
            match = re.search(
                pattern,
                body,
                flags=re.IGNORECASE | re.DOTALL,
            )
            if match:
                body = body[:match.start()]
                break

        # Remove excessive blank lines
        body = re.sub(r"\n{3,}", "\n\n", body)

        return body.strip()

    def extract_attachments(self, payload: dict) -> list[dict]:
        """
        Recursively extract attachment metadata from a Gmail message payload.
        """

        attachments = []

        def walk(part: dict):
            filename = part.get("filename", "")

            body = part.get("body", {})

            attachment_id = body.get("attachmentId")

            if filename and attachment_id:
                attachments.append(
                    {
                        "filename": filename,
                        "mime_type": part.get(
                            "mimeType",
                            "application/octet-stream",
                        ),
                        "attachment_id": attachment_id,
                        "size": body.get("size", 0),
                    }
                )

            for child in part.get("parts", []):
                walk(child)

        walk(payload)

        return attachments

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

            "attachments": self.extract_attachments(payload),
        }

    def get_thread(
            self,
            thread_id: str,
    ) -> list[dict]:
        """
        Returns all messages in a Gmail conversation.
        """

        # Mark the thread as read by permanently removing the UNREAD label in Gmail
        try:
            self.service.users().threads().modify(
                userId="me",
                id=thread_id,
                body={
                    "removeLabelIds": ["UNREAD"]
                }
            ).execute()
        except Exception:
            pass

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

                    "attachments": self.extract_attachments(payload),
                }
            )

        return results

    def reply_to_thread(
            self,
            thread_id: str,
            to: str,
            subject: str,
            body: str,
            attachments=None,
    ) -> dict:
        """
        Send a reply in an existing Gmail thread.
        """

        message = MIMEMultipart()

        message["To"] = to
        message["Subject"] = subject
        message["MIME-Version"] = "1.0"

        message.attach(
            MIMEText(body, "plain", "utf-8")
        )

        for uploaded in attachments or []:
            uploaded.seek(0)

            mime_type = uploaded.mimetype or "application/octet-stream"

            if "/" in mime_type:
                main, sub = mime_type.split("/", 1)
            else:
                main = "application"
                sub = "octet-stream"

            part = MIMEBase(main, sub)
            part.set_payload(uploaded.read())

            encoders.encode_base64(part)

            part.add_header(
                "Content-Disposition",
                f'attachment; filename="{uploaded.filename}"',
            )

            message.attach(part)

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

    def download_attachment(
            self,
            message_id: str,
            attachment_id: str,
    ) -> tuple[bytes, str]:
        """
        Download a Gmail attachment.
        """

        message = self.get_message(message_id)

        payload = message.get("payload", {})

        filename = "attachment"

        mime_type = "application/octet-stream"

        def find_attachment(part: dict):
            nonlocal filename, mime_type

            body = part.get("body", {})

            if body.get("attachmentId") == attachment_id:
                filename = part.get("filename") or filename
                mime_type = part.get("mimeType") or mime_type
                return True

            for child in part.get("parts", []):
                if find_attachment(child):
                    return True

            return False

        find_attachment(payload)

        response = (
            self.service.users()
            .messages()
            .attachments()
            .get(
                userId="me",
                messageId=message_id,
                id=attachment_id,
            )
            .execute()
        )

        data = base64.urlsafe_b64decode(
            response["data"].encode()
        )

        return data, filename, mime_type


gmail_service = GmailService()