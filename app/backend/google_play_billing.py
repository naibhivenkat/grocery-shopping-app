"""Google Play subscription verification. No client claim creates entitlement.

The public Google endpoint and server package are fixed here; purchase tokens
and provider response bodies must never be included in logs or public errors.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import os
import re
from urllib.parse import quote

import google.auth
from google.auth import impersonated_credentials
from google.auth.transport.requests import AuthorizedSession, Request
from google.oauth2 import id_token
import requests


PUBLISHER_SCOPE = "https://www.googleapis.com/auth/androidpublisher"
PUBLISHER_URL = "https://androidpublisher.googleapis.com/androidpublisher/v3/applications"
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_EMAIL = re.compile(r"^[A-Za-z0-9_.+-]+@[A-Za-z0-9.-]+\.gserviceaccount\.com$")
_STATES = {
    "SUBSCRIPTION_STATE_PENDING": "pending",
    "SUBSCRIPTION_STATE_ACTIVE": "active",
    "SUBSCRIPTION_STATE_IN_GRACE_PERIOD": "grace",
    "SUBSCRIPTION_STATE_CANCELED": "canceled",
    "SUBSCRIPTION_STATE_ON_HOLD": "hold",
    "SUBSCRIPTION_STATE_PAUSED": "paused",
    "SUBSCRIPTION_STATE_EXPIRED": "expired",
    "SUBSCRIPTION_STATE_PENDING_PURCHASE_CANCELED": "pending_canceled",
}


class PlayBillingError(Exception):
    def __init__(self, detail, status=503, code="BILLING_PROVIDER_UNAVAILABLE", *, retryable=False):
        super().__init__(detail)
        self.detail, self.status, self.code, self.retryable = detail, status, code, retryable


def _fail(detail, code="BILLING_PURCHASE_INVALID", status=422):
    raise PlayBillingError(detail, status, code)


def identifier(value, label="identifier"):
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        _fail(f"Invalid {label}")
    return value


def purchase_token(value):
    if (not isinstance(value, str) or not 8 <= len(value) <= 8192
            or value != value.strip() or any(ord(c) < 33 or ord(c) > 126 for c in value)):
        _fail("Invalid purchase token")
    return value


def parse_time(value, *, required=True):
    if value is None and not required:
        return None
    if not isinstance(value, str) or len(value) > 64:
        _fail("Provider returned an invalid subscription period", "BILLING_PROVIDER_RESPONSE", 502)
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None:
            raise ValueError()
        return result.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        _fail("Provider returned an invalid subscription period", "BILLING_PROVIDER_RESPONSE", 502)


def iso(value):
    return value.astimezone(timezone.utc).isoformat() if value else None


@dataclass(frozen=True)
class PlayConfig:
    package_name: str
    publisher_service_account: str | None = None
    rtdn_audience: str | None = None
    rtdn_push_email: str | None = None
    rtdn_subscription: str | None = None
    test_vendor_ids: frozenset = frozenset()

    @classmethod
    def from_env(cls, *, rtdn=False):
        enabled = os.getenv("GOOGLE_PLAY_BILLING_ENABLED", "false").lower()
        if enabled not in {"true", "1"}:
            raise PlayBillingError("Google Play billing is not configured", 503, "BILLING_NOT_CONFIGURED")
        package = os.getenv("GOOGLE_PLAY_PACKAGE_NAME", "")
        if (not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*){1,9}", package)
                or len(package) > 200):
            raise PlayBillingError("Google Play billing configuration is incomplete", 503, "BILLING_NOT_CONFIGURED")
        target = os.getenv("GOOGLE_PLAY_PUBLISHER_SERVICE_ACCOUNT") or None
        if target and not _EMAIL.fullmatch(target):
            raise PlayBillingError("Google Play billing configuration is incomplete", 503, "BILLING_NOT_CONFIGURED")
        audience = os.getenv("GOOGLE_PLAY_RTDN_AUDIENCE") or None
        email = os.getenv("GOOGLE_PLAY_RTDN_PUSH_EMAIL") or None
        subscription = os.getenv("GOOGLE_PLAY_RTDN_SUBSCRIPTION") or None
        if rtdn and (not audience or not audience.startswith("https://") or "?" in audience or "#" in audience
                     or not email or not _EMAIL.fullmatch(email)
                     or not subscription or not re.fullmatch(r"projects/[A-Za-z0-9_.:-]+/subscriptions/[A-Za-z0-9_.~-]+", subscription)):
            raise PlayBillingError("Google Play notification configuration is incomplete", 503, "BILLING_NOT_CONFIGURED")
        vendors = frozenset(x.strip() for x in os.getenv("GOOGLE_PLAY_TEST_VENDOR_IDS", "").split(",") if x.strip())
        if any(not _IDENTIFIER.fullmatch(x) for x in vendors):
            raise PlayBillingError("Google Play test configuration is invalid", 503, "BILLING_NOT_CONFIGURED")
        return cls(package, target, audience, email, subscription, vendors)


class BoundedSession(requests.Session):
    def request(self, method, url, **kwargs):
        # Also bounds certificate fetches and credential refresh requests.
        kwargs["timeout"] = (5, 20)
        return super().request(method, url, **kwargs)


class GooglePlayClient:
    def __init__(self, config, session=None):
        self.config = config
        if session is None:
            try:
                credentials, _ = google.auth.default(scopes=[PUBLISHER_SCOPE])
                if config.publisher_service_account:
                    credentials = impersonated_credentials.Credentials(
                        source_credentials=credentials,
                        target_principal=config.publisher_service_account,
                        target_scopes=[PUBLISHER_SCOPE], lifetime=300)
                session = AuthorizedSession(credentials, auth_request=Request(session=BoundedSession()), max_refresh_attempts=1)
            except Exception:
                raise PlayBillingError("Google Play verification credentials are unavailable", 503,
                                       "BILLING_NOT_CONFIGURED") from None
        self.session = session

    def _request(self, method, suffix, *, body=None):
        url = f"{PUBLISHER_URL}/{quote(self.config.package_name, safe='')}/{suffix}"
        try:
            response = self.session.request(method, url, json=body, timeout=(5, 20), allow_redirects=False)
        except Exception:
            raise PlayBillingError("Google Play verification is temporarily unavailable", 503,
                                   retryable=True) from None
        status = response.status_code
        if status in {401, 403}:
            raise PlayBillingError("Google Play verification access is unavailable", 503,
                                   "BILLING_NOT_CONFIGURED", retryable=True)
        if status in {404, 410}:
            raise PlayBillingError("Google Play could not verify this purchase", 422, "BILLING_PURCHASE_NOT_FOUND")
        if status == 429 or status >= 500:
            raise PlayBillingError("Google Play verification is temporarily unavailable", 503, retryable=True)
        if status < 200 or status >= 300:
            raise PlayBillingError("Google Play rejected subscription verification", 502, "BILLING_PROVIDER_RESPONSE")
        if method == "POST":
            return None
        try:
            # Prevent unbounded/malformed provider bodies from reaching persistence.
            if len(response.content) > 2_000_000:
                raise ValueError()
            result = response.json()
            if not isinstance(result, dict):
                raise ValueError()
            return result
        except Exception:
            raise PlayBillingError("Google Play returned an invalid verification response", 502,
                                   "BILLING_PROVIDER_RESPONSE", retryable=True) from None

    def get_subscription(self, token):
        return self._request("GET", "purchases/subscriptionsv2/tokens/" + quote(purchase_token(token), safe=""))

    def acknowledge(self, token, product_id, *, billing_account_id=None):
        body = {}
        if billing_account_id is not None:
            if (not isinstance(billing_account_id, str) or not 16 <= len(billing_account_id) <= 64
                    or any(ord(c) < 33 or ord(c) > 126 for c in billing_account_id)):
                _fail("Invalid billing account binding")
            # Out-of-app resubscribe context disappears on acknowledgement.
            # Persist the verified opaque binding on the provider purchase too.
            body["externalAccountIds"] = {"obfuscatedAccountId": billing_account_id}
        return self._request("POST", "purchases/subscriptions/" + quote(identifier(product_id, "product"), safe="")
                             + "/tokens/" + quote(purchase_token(token), safe="") + ":acknowledge", body=body)


def verify_push_identity(authorization, config):
    if not isinstance(authorization, str) or not authorization.startswith("Bearer "):
        raise PlayBillingError("Google Play notification authentication required", 401, "BILLING_PUSH_UNAUTHORIZED")
    token = authorization[7:].strip()
    if not token or len(token) > 16384:
        raise PlayBillingError("Invalid Google Play notification authentication", 401, "BILLING_PUSH_UNAUTHORIZED")
    try:
        claims = id_token.verify_oauth2_token(token, Request(session=BoundedSession()), audience=config.rtdn_audience)
    except Exception:
        raise PlayBillingError("Invalid Google Play notification authentication", 401, "BILLING_PUSH_UNAUTHORIZED") from None
    if (claims.get("iss") not in {"https://accounts.google.com", "accounts.google.com"}
            or claims.get("aud") != config.rtdn_audience
            or claims.get("email") != config.rtdn_push_email or claims.get("email_verified") is not True):
        raise PlayBillingError("Invalid Google Play notification identity", 403, "BILLING_PUSH_UNAUTHORIZED")
    return claims


def external_account(data):
    identifiers = data.get("externalAccountIdentifiers") or {}
    context = data.get("outOfAppPurchaseContext") or {}
    if not isinstance(identifiers, dict) or not isinstance(context, dict):
        _fail("Provider returned invalid account identifiers", "BILLING_PROVIDER_RESPONSE", 502)
    expired = context.get("expiredExternalAccountIdentifiers") or {}
    if not isinstance(expired, dict):
        _fail("Provider returned invalid account identifiers", "BILLING_PROVIDER_RESPONSE", 502)
    account = identifiers.get("obfuscatedExternalAccountId")
    if not account:
        account = expired.get("obfuscatedExternalAccountId")
    return account


def parse_subscription(data, *, product_id, base_plan_id, billing_account_id, now=None):
    """Validate one supported paid tier, preserving pending and canceled semantics."""
    if not isinstance(data, dict):
        _fail("Invalid Google Play subscription response", "BILLING_PROVIDER_RESPONSE", 502)
    identifier(product_id, "product")
    identifier(base_plan_id, "base plan")
    if external_account(data) != billing_account_id:
        _fail("This purchase is not bound to the signed-in vendor", "BILLING_ACCOUNT_MISMATCH", 403)
    state = _STATES.get(data.get("subscriptionState"))
    if state is None:
        _fail("Google Play returned an unsupported subscription state", "BILLING_PROVIDER_RESPONSE", 502)
    acknowledgement = data.get("acknowledgementState")
    if acknowledgement not in {"ACKNOWLEDGEMENT_STATE_PENDING", "ACKNOWLEDGEMENT_STATE_ACKNOWLEDGED"}:
        _fail("Google Play returned an invalid acknowledgement state", "BILLING_PROVIDER_RESPONSE", 502)
    items = data.get("lineItems")
    if not isinstance(items, list) or not 1 <= len(items) <= 20 or any(not isinstance(x, dict) for x in items):
        _fail("Google Play returned invalid subscription items", "BILLING_PROVIDER_RESPONSE", 502)
    matches = [x for x in items if x.get("productId") == product_id
               and isinstance(x.get("offerDetails"), dict) and x["offerDetails"].get("basePlanId") == base_plan_id]
    if len(matches) != 1:
        # Future/deferred tiers must never grant the requested tier early.
        deferred = any(isinstance(x.get("deferredItemReplacement"), dict)
                       and x["deferredItemReplacement"].get("productId") == product_id for x in items)
        _fail("Subscription replacement is awaiting its effective billing period" if deferred
              else "Purchased product does not match the approved plan",
              "BILLING_REPLACEMENT_PENDING" if deferred else "BILLING_PRODUCT_MISMATCH", 409)
    item = matches[0]
    current = now or datetime.now(timezone.utc)
    starts = parse_time(data.get("startTime"), required=state not in {"pending", "pending_canceled"})
    ends = parse_time(item.get("expiryTime"), required=state not in {"pending", "pending_canceled"})
    if starts and ends and starts >= ends:
        _fail("Provider returned an invalid subscription period", "BILLING_PROVIDER_RESPONSE", 502)
    if starts and starts > current:
        _fail("Subscription has not started", "BILLING_PURCHASE_PENDING", 409)
    if state in {"active", "grace", "canceled"} and ends and ends <= current:
        state = "expired"
    linked = data.get("linkedPurchaseToken")
    if linked is not None:
        purchase_token(linked)
    old = (data.get("outOfAppPurchaseContext") or {}).get("expiredPurchaseToken")
    if old is not None:
        purchase_token(old)
    # Acknowledge may set externalAccountIds only for a store resubscription.
    # Standard in-app purchases already bind through setObfuscatedAccountId.
    needs_rebinding = old is not None and not (data.get("externalAccountIdentifiers") or {}).get("obfuscatedExternalAccountId")
    auto = item.get("autoRenewingPlan")
    if auto is not None and (not isinstance(auto, dict) or type(auto.get("autoRenewEnabled")) is not bool):
        _fail("Provider returned invalid renewal information", "BILLING_PROVIDER_RESPONSE", 502)
    return {"provider_state": state, "starts_at": iso(starts), "ends_at": iso(ends),
            "grace_ends_at": iso(ends) if state == "grace" else None,
            "acknowledgement_state": acknowledgement, "product_id": product_id, "base_plan_id": base_plan_id,
            "auto_renew_enabled": auto.get("autoRenewEnabled") if auto else False,
            "plan_type": "installment" if auto and "installmentDetails" in auto else ("auto_renewing" if auto is not None else "prepaid"),
            "linked_purchase_token": linked, "expired_purchase_token": old,
            "needs_account_rebinding": needs_rebinding,
            "test_purchase": "testPurchase" in data}
