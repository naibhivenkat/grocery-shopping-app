"""Razorpay configuration and signature verification.

Secrets are supplied by the deployment environment and are never committed
to the repository.
"""

import hashlib
import hmac
import os
from functools import lru_cache

import razorpay


def _required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


@lru_cache(maxsize=1)
def get_razorpay_client():
    return razorpay.Client(auth=(_required("RAZORPAY_KEY_ID"), _required("RAZORPAY_KEY_SECRET")))


def get_razorpay_key_id() -> str:
    return _required("RAZORPAY_KEY_ID")


def verify_webhook_signature(raw_body: bytes, signature: str) -> bool:
    expected = hmac.new(
        _required("RAZORPAY_WEBHOOK_SECRET").encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature or "")
