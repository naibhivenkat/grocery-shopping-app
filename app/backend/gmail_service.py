"""Service for interacting with the Gmail API."""

import base64
import json
import os
from email.message import EmailMessage
from typing import Dict, Any, List, Optional

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


class GmailService:
    def __init__(self):
        self.scopes = ["https://mail.google.com/"]
        self.service = self._build_service()

    def _build_service(self):
        """Constructs the Gmail API client using stored credentials."""
        creds_json = os.getenv("GMAIL_OAUTH_CREDENTIALS_JSON")
        if not creds_json:
            # Fallback for local development or when credentials are not yet injected
            return None

        try:
            creds_data = json.loads(creds_json)
            creds = Credentials.from_authorized_user_info(creds_data, self.scopes)
            return build("gmail", "v1", credentials=creds, cache_discovery=False)
        except Exception as e:
            print(f"Failed to initialize Gmail API: {e}")
            return None

    def get_message_raw(self, message_id: str) -> Optional[Dict[str, Any]]:
        """Fetches the raw email payload by ID."""
        if not self.service:
            return None

        try:
            message = self.service.users().messages().get(
                userId="me",
                id=message_id,
                format="full"
            ).execute()
            return message
        except HttpError as e:
            print(f"Gmail API HTTP Error getting message {message_id}: {e}")
            return None

    def parse_message(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Parses the raw Gmail payload into a structured dictionary."""
        payload = message.get("payload", {})
        headers = payload.get("headers", [])

        parsed_data = {
            "id": message.get("id"),
            "threadId": message.get("threadId"),
            "snippet": message.get("snippet"),
            "subject": "",
            "from": "",
            "to": "",
            "date": "",
            "message_id_header": "",
            "in_reply_to": "",
            "references": "",
            "body_text": "",
            "body_html": ""
        }

        for header in headers:
            name = header.get("name", "").lower()
            value = header.get("value", "")

            if name == "subject":
                parsed_data["subject"] = value
            elif name == "from":
                parsed_data["from"] = value
            elif name == "to":
                parsed_data["to"] = value
            elif name == "date":
                parsed_data["date"] = value
            elif name == "message-id":
                parsed_data["message_id_header"] = value
            elif name == "in-reply-to":
                parsed_data["in_reply_to"] = value
            elif name == "references":
                parsed_data["references"] = value

        # Extract body
        parts = payload.get("parts")
        if parts:
            for part in parts:
                mime_type = part.get("mimeType")
                data = part.get("body", {}).get("data")
                if not data:
                    continue

                decoded_bytes = base64.urlsafe_b64decode(data)
                text_content = decoded_bytes.decode("utf-8", errors="replace")

                if mime_type == "text/plain":
                    parsed_data["body_text"] = text_content
                elif mime_type == "text/html":
                    parsed_data["body_html"] = text_content
        else:
            # Single part message
            data = payload.get("body", {}).get("data")
            if data:
                decoded_bytes = base64.urlsafe_b64decode(data)
                text_content = decoded_bytes.decode("utf-8", errors="replace")
                if payload.get("mimeType") == "text/html":
                    parsed_data["body_html"] = text_content
                else:
                    parsed_data["body_text"] = text_content

        return parsed_data

    def send_reply(self, to_email: str, subject: str, body: str, thread_id: str, message_id_header: str) -> Optional[
        str]:
        """Dispatches an outbound reply in the same thread."""
        if not self.service:
            return None

        try:
            message = EmailMessage()
            message.set_content(body)
            message["To"] = to_email
            message["From"] = os.getenv("SUPPORT_EMAIL_ADDRESS", "support@yourdomain.com")
            message["Subject"] = subject

            # Critical headers for threading
            message["In-Reply-To"] = message_id_header
            message["References"] = message_id_header

            encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()

            create_message = {
                "raw": encoded_message,
                "threadId": thread_id
            }

            sent_message = self.service.users().messages().send(
                userId="me",
                body=create_message
            ).execute()

            return sent_message.get("id")

        except HttpError as e:
            print(f"Gmail API HTTP Error sending reply: {e}")
            return None

    def list_history(self, start_history_id: str) -> List[Dict[str, Any]]:
        """Retrieves history records since the last sync."""
        if not self.service:
            return []

        try:
            response = self.service.users().history().list(
                userId="me",
                startHistoryId=start_history_id
            ).execute()

            return response.get("history", [])
        except HttpError as e:
            print(f"Gmail API HTTP Error listing history: {e}")
            return []


gmail_service = GmailService()