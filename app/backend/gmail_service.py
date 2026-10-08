"""Small, authenticated Gmail service used by the Support Center."""

from __future__ import annotations

import base64
import mimetypes
from email import encoders
from email.header import decode_header, make_header
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any
from email.utils import parseaddr
import re

from routes.gmail_auth import get_gmail_service


def _decode(value: str | None) -> bytes:
    if not value:
        return b""
    padded = value + "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


class GmailService:
    def __init__(self):
        self._service = None

    @property
    def service(self):
        if self._service is None:
            self._service = get_gmail_service()
            transport = getattr(self._service, "_http", None)
            raw_http = getattr(transport, "http", transport)
            if raw_http is not None:
                raw_http.timeout = 20
        return self._service

    @staticmethod
    def _execute(api_request, *, retries=2):
        return api_request.execute(num_retries=retries)

    @staticmethod
    def header(headers: list[dict], name: str) -> str:
        for header in headers or []:
            if str(header.get("name", "")).lower() == name.lower():
                return str(header.get("value", ""))
        return ""

    @staticmethod
    def decode_header(value: str) -> str:
        try:
            return str(make_header(decode_header(value)))
        except Exception:
            return value

    def test_connection(self) -> dict[str, Any]:
        profile = self._execute(self.service.users().getProfile(userId="me"))
        return {
            "success": True,
            "connected": True,
            "gmail_email": profile.get("emailAddress"),
            "messages_total": profile.get("messagesTotal", 0),
            "threads_total": profile.get("threadsTotal", 0),
            "history_id": profile.get("historyId"),
        }

    def get_profile(self) -> dict[str, Any]:
        return self._execute(self.service.users().getProfile(userId="me"))

    def get_labels(self) -> list[dict]:
        return self._execute(self.service.users().labels().list(userId="me")).get(
            "labels", []
        )

    def list_messages(self, query: str = "", max_results: int = 20) -> list[dict]:
        gmail_query = "label:Support in:inbox -label:sent"
        if query.strip():
            gmail_query = f"{gmail_query} {query.strip()}"
        maximum = max(1, min(int(max_results), 500))
        result, token = [], None
        for _ in range(5):
            response = self._execute(self.service.users().messages().list(
                userId="me", q=gmail_query, maxResults=min(100, maximum-len(result)),
                **({"pageToken":token} if token else {})))
            result.extend(response.get("messages", []))
            token = response.get("nextPageToken")
            if not token or len(result) >= maximum:
                break
        return result[:maximum]

    def get_message(self, message_id: str, fmt: str = "full") -> dict:
        return self._execute(self.service.users().messages().get(
            userId="me", id=message_id, format=fmt
        ))

    def get_thread(self, thread_id: str) -> list[dict]:
        return self._execute(self.service.users().threads().get(
            userId="me", id=thread_id, format="full"
        )).get("messages", [])

    def list_history(self, history_id: str, label_id: str | None = None):
        token = None
        for _ in range(20):
            response = self._execute(self.service.users().history().list(
                userId="me", startHistoryId=history_id, historyTypes=["messageAdded"], maxResults=100,
                **({"labelId":label_id} if label_id else {}),
                **({"pageToken":token} if token else {})))
            yield from response.get("history", [])
            token = response.get("nextPageToken")
            if not token:
                return
        # Synchronizer persists the cursor after each completed record, so
        # remaining pages resume on the next bounded run without skipping mail.
        raise ValueError("History page limit reached; run synchronization again")

    def find_sent_message(self, message_id_header: str):
        if not message_id_header or any(c in message_id_header for c in ('\r','\n')):
            return None
        response = self._execute(self.service.users().messages().list(
            userId="me", q=f"in:sent rfc822msgid:{message_id_header.strip('<>')}", maxResults=10))
        for item in response.get("messages", []):
            raw = self.get_message(item["id"], "metadata")
            headers = (raw.get("payload") or {}).get("headers") or []
            if self.header(headers, "Message-ID").strip() == message_id_header:
                return {"id":item["id"]}
        return None

    def get_attachment(self, message_id: str, attachment_id: str) -> bytes:
        data = self._execute(self.service.users().messages().attachments().get(
            userId="me", messageId=message_id, id=attachment_id
        )).get("data")
        return _decode(data)

    def _body(self, payload: dict) -> tuple[str, str]:
        mime_type = payload.get("mimeType")
        if mime_type in {"text/plain", "text/html"}:
            body = _decode((payload.get("body") or {}).get("data")).decode(
                "utf-8", errors="replace"
            )
            if mime_type == "text/plain":
                return body, ""
            return "", body
        plain, html = "", ""
        for part in payload.get("parts", []) or []:
            part_plain, part_html = self._body(part)
            plain = plain or part_plain
            html = html or part_html
        return plain, html

    def parse_message(self, message: dict) -> dict[str, Any]:
        payload = message.get("payload") or {}
        headers = payload.get("headers") or []
        plain, html = self._body(payload)
        return {
            "id": message.get("id"),
            "threadId": message.get("threadId"),
            "from": self.decode_header(self.header(headers, "From")),
            "to": self.decode_header(self.header(headers, "To")),
            "reply_to": self.decode_header(self.header(headers, "Reply-To")),
            "subject": self.decode_header(self.header(headers, "Subject")),
            "body_text": plain,
            "body_html": html,
            "internal_date": message.get("internalDate"),
            "message_id_header": self.header(headers, "Message-ID"),
            "references": self.header(headers, "References"),
            "label_ids": message.get("labelIds") or [],
        }

    def get_message_summary(self, message_id: str) -> dict[str, Any]:
        return self.parse_message(self.get_message(message_id, "full"))

    def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        *,
        thread_id: str | None = None,
        in_reply_to: str | None = None,
        attachments: list[dict] | None = None,
        message_id_header: str | None = None,
    ) -> dict[str, Any]:
        if not to.strip() or not subject.strip() or not body.strip():
            raise ValueError("to, subject, and body are required")
        _, address = parseaddr(to)
        if (not re.fullmatch(r"[^\s@,<>]+@[^\s@,<>]+\.[^\s@,<>]+",address)
            or any(c in to+subject+(in_reply_to or '')+(message_id_header or '') for c in ('\r','\n'))):
            raise ValueError("Invalid email recipient or headers")
        message = MIMEMultipart()
        if message_id_header:
            message["Message-ID"] = message_id_header
        message["To"] = to.strip()
        message["Subject"] = subject.strip()
        if in_reply_to:
            message["In-Reply-To"] = in_reply_to
            message["References"] = in_reply_to
        message.attach(MIMEText(body, "plain", "utf-8"))
        for attachment in attachments or []:
            name = str(attachment.get("name") or "attachment")
            raw = attachment.get("bytes") or b""
            if isinstance(raw, str):
                raw = _decode(raw)
            mime = str(attachment.get("mime_type") or mimetypes.guess_type(name)[0] or "application/octet-stream")
            maintype, subtype = mime.split("/", 1) if "/" in mime else ("application", "octet-stream")
            part = MIMEBase(maintype, subtype)
            part.set_payload(raw)
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", "attachment", filename=name)
            message.attach(part)
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
        request = self.service.users().messages().send(
            userId="me", body={"raw": raw, **({"threadId": thread_id} if thread_id else {})}
        )
        # Gmail send has no idempotency API; automatic retries could duplicate
        # customer mail after a lost response. Callers persist/reconcile identity.
        return self._execute(request, retries=0)


gmail_service = GmailService()
