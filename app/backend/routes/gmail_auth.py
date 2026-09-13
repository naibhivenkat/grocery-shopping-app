"""Lazy Gmail OAuth credential loading for the Support Center."""

from __future__ import annotations

import os

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials


GMAIL_SCOPES = ("https://mail.google.com/",)


class GmailAuthError(RuntimeError):
    """Raised when the configured Gmail OAuth session cannot be used."""


def _required(name: str) -> str:
    value = (os.getenv(name) or "").strip()
    if not value:
        raise GmailAuthError(f"Missing Gmail configuration: {name}")
    return value


def get_credentials() -> Credentials:
    credentials = Credentials(
        token=None,
        refresh_token=_required("GOOGLE_REFRESH_TOKEN"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=_required("GOOGLE_CLIENT_ID"),
        client_secret=_required("GOOGLE_CLIENT_SECRET"),
        scopes=list(GMAIL_SCOPES),
    )
    try:
        credentials.refresh(Request())
    except RefreshError as exc:
        raise GmailAuthError(
            "Gmail OAuth refresh failed; rotate GOOGLE_REFRESH_TOKEN"
        ) from exc
    return credentials


def get_gmail_service():
    """Build the Gmail API client only when an admin endpoint uses it."""
    try:
        from googleapiclient.discovery import build
    except ImportError as exc:  # pragma: no cover - deployment dependency guard
        raise GmailAuthError("Gmail API dependency is not installed") from exc
    return build(
        "gmail",
        "v1",
        credentials=get_credentials(),
        cache_discovery=False,
    )
