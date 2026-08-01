"""
Gmail OAuth authentication helper.

Responsibilities:
- Read Gmail credentials from environment variables.
- Refresh expired access tokens.
- Return an authenticated Gmail API service.

This module intentionally contains NO Flask routes,
NO Firestore logic, and NO Support Center business logic.
"""

from __future__ import annotations

import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from google.auth.exceptions import RefreshError

GMAIL_SCOPES = [
    "https://mail.google.com/",
]


class GmailAuthError(Exception):
    """Raised when Gmail authentication cannot be completed."""


def _required_env(name: str) -> str:
    value = os.getenv(name)

    if value is None or value.strip() == "":
        raise GmailAuthError(
            f"Missing required environment variable: {name}"
        )

    return value.strip()


def get_credentials() -> Credentials:
    """
    Returns a valid OAuth credential.

    Automatically refreshes the access token
    using the stored refresh token.
    """

    creds = Credentials(
        token=None,
        refresh_token=_required_env("GOOGLE_REFRESH_TOKEN"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=_required_env("GOOGLE_CLIENT_ID"),
        client_secret=_required_env("GOOGLE_CLIENT_SECRET"),
        scopes=GMAIL_SCOPES,
    )

    try:
        creds.refresh(Request())
    except RefreshError as e:
        raise GmailAuthError(
            "Google refresh token is invalid or expired. "
            "Generate a new GOOGLE_REFRESH_TOKEN and update Cloud Run."
        ) from e

    return creds

def get_gmail_service():
    """
    Returns an authenticated Gmail API client.
    """

    creds = get_credentials()

    return build(
        "gmail",
        "v1",
        credentials=creds,
        cache_discovery=False,
    )


def validate_connection() -> dict:
    """
    Validates the Gmail connection by requesting
    the authenticated user's profile.
    """

    try:
        service = get_gmail_service()

        profile = (
            service.users()
            .getProfile(userId="me")
            .execute()
        )

        return {
            "success": True,
            "connected": True,
            "email": profile.get("emailAddress"),
            "messages_total": profile.get("messagesTotal", 0),
            "threads_total": profile.get("threadsTotal", 0),
            "history_id": profile.get("historyId"),
        }

    except Exception as exc:
        return {
            "success": False,
            "connected": False,
            "error": str(exc),
        }