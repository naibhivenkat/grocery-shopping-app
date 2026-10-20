"""Verified Play purchases and durable, authenticated notification recovery.

Provider calls run outside Firestore transactions. A fenced per-token journal
bridges those calls to the central idempotent entitlement transition.
"""
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import json
import secrets
import time

from flask import Blueprint, g, jsonify, request
from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from auth_utils import require_role
from db import col, db, doc, now_iso
from google_play_billing import (GooglePlayClient, PlayBillingError, PlayConfig,
    external_account, identifier, iso, parse_subscription, parse_time,
    purchase_token, verify_push_identity)


google_play_bp = Blueprint("google_play", __name__)
TOKENS = "google_play_purchase_tokens"
CONTEXTS = "google_play_checkout_contexts"
BINDINGS = "google_play_account_bindings"
OPERATIONS = "google_play_operations"
EVENTS = "google_play_events"
WORK = "google_play_work"
LEASE_SECONDS = 180


@google_play_bp.errorhandler(PlayBillingError)
def _error(exc):
    return jsonify({"detail": exc.detail, "code": exc.code}), exc.status


def _hash(value):
    return hashlib.sha256(value.encode()).hexdigest()


def _now():
    return datetime.now(timezone.utc)


def _read(ref, tx=None):
    snapshot = ref.get(transaction=tx) if tx is not None else ref.get()
    return snapshot.to_dict() if snapshot.exists else None


def _core_call(name, *args, **kwargs):
    try:
        import subscription_service
        callback = getattr(subscription_service, name)
    except (ImportError, AttributeError):
        raise PlayBillingError("Subscription verification is not yet configured", 503, "BILLING_NOT_CONFIGURED") from None
    try:
        return callback(*args, **kwargs)
    except Exception as exc:
        if hasattr(exc, "code") and hasattr(exc, "detail"):
            raise PlayBillingError(exc.detail, getattr(exc, "status", 409), exc.code) from None
        raise


def _json(limit=20000):
    if not request.is_json:
        raise PlayBillingError("JSON object required", 415, "BILLING_INVALID_REQUEST")
    raw = request.stream.read(limit + 1)
    if len(raw) > limit:
        raise PlayBillingError("Request is too large", 413, "BILLING_INVALID_REQUEST")
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        value = None
    if not isinstance(value, dict):
        raise PlayBillingError("JSON object required", 422, "BILLING_INVALID_REQUEST")
    return value


def _key():
    key = request.headers.get("Idempotency-Key")
    if (not isinstance(key, str) or not 8 <= len(key) <= 200
            or key != key.strip() or any(ord(c) < 33 or ord(c) > 126 for c in key)):
        raise PlayBillingError("An Idempotency-Key of 8 to 200 characters is required", 422, "BILLING_INVALID_REQUEST")
    return key


def _operation(vendor, name, key, body):
    ref = doc(OPERATIONS, _hash(f"{vendor}:{name}:{key}"))
    fingerprint = _hash(json.dumps(body, sort_keys=True, separators=(",", ":")))
    @firestore.transactional
    def start(tx):
        old = _read(ref, tx)
        if old:
            if old.get("fingerprint") != fingerprint:
                raise PlayBillingError("Idempotency-Key was used for different data", 409, "IDEMPOTENCY_CONFLICT")
            return old.get("response")
        tx.create(ref, {"vendor_id": vendor, "actor_id": vendor, "operation": name, "fingerprint": fingerprint,
                        "reason": body.get("reason"),
                        "status": "pending", "created_at": now_iso()})
        return None
    return ref, start(db().transaction())


def _finish_operation(ref, response):
    @firestore.transactional
    def finish(tx):
        old = _read(ref, tx)
        if old and old.get("response") is not None:
            return old["response"]
        tx.update(ref, {"status": "completed", "response": response, "completed_at": now_iso()})
        return response
    return finish(db().transaction())


def _mapping(version):
    mapping = version.get("google_play")
    if (not isinstance(mapping, dict) or type(version.get("price_paise")) is not int
            or version["price_paise"] <= 0 or version.get("renewal_rule") != "store"):
        raise PlayBillingError("This plan is not configured for Google Play checkout", 409, "BILLING_PLAN_UNAVAILABLE")
    return {"product_id": identifier(mapping.get("product_id"), "product"),
            "base_plan_id": identifier(mapping.get("base_plan_id"), "base plan")}


def _prepare(vendor, request_id):
    prepared = _core_call("prepare_google_play_checkout", vendor, request_id)
    version = prepared.get("plan_version") or {}
    version_id = version.get("uid") or version.get("id")
    identifier(version_id, "plan version")
    account = prepared.get("billing_account_id")
    if not isinstance(account, str) or not 16 <= len(account) <= 64 or any(ord(c) < 33 for c in account):
        raise PlayBillingError("Subscription account binding is unavailable", 503, "BILLING_NOT_CONFIGURED")
    return {"vendor_id": vendor, "request_id": request_id, "plan_version_id": version_id,
            "billing_account_id": account, **_mapping(version)}


def _replacement(context):
    account = _read(doc("vendor_subscription_accounts", context["vendor_id"])) or {}
    fingerprint = account.get("store_purchase_fingerprint")
    result = {"replacement_required": False, "replacement_allowed": True, "replacement_mode": None,
              "previous_product_id": None, "previous_base_plan_id": None, "previous_purchase_fingerprint": None}
    if not fingerprint:
        return result
    old = _read(doc(TOKENS, fingerprint)) or {}
    end = parse_time(old.get("ends_at"), required=False)
    # A locally elapsed date does not prove an auto-renewing store plan stopped.
    # Only the refreshed provider state permits an independent new purchase.
    if old.get("provider_state") in {"expired", "revoked"}:
        return result
    result.update(replacement_required=True, replacement_allowed=False,
                  previous_product_id=old.get("product_id"), previous_base_plan_id=old.get("base_plan_id"),
                  previous_purchase_fingerprint=fingerprint)
    if (old.get("vendor_id") != context["vendor_id"] or old.get("plan_type") != "auto_renewing"
            or old.get("provider_state") not in {"active", "grace", "canceled"}
            or old.get("acknowledgement_state") != "ACKNOWLEDGEMENT_STATE_ACKNOWLEDGED" or not end):
        result["replacement_message"] = "The existing Google subscription requires review before switching plans."
        return result
    same_product = old["product_id"] == context["product_id"]
    result.update(replacement_allowed=True, replacement_mode="WITHOUT_PRORATION" if same_product else "WITH_TIME_PRORATION",
                  replacement_message=("Features change immediately; the new price is charged at the next Google Play renewal."
                      if same_product else "Features change immediately; Google Play adjusts the billing date using remaining paid time."))
    return result


@google_play_bp.post("/subscriptions/google-play/checkout-context")
@require_role("vendor")
def checkout_context():
    config = PlayConfig.from_env()
    body = _json()
    if set(body) != {"request_id"}:
        raise PlayBillingError("Only request_id is accepted", 422, "BILLING_INVALID_REQUEST")
    identifier(body["request_id"], "request")
    op, response = _operation(g.user_id, "checkout", _key(), body)
    # A lost-response replay is not permission to launch an obsolete checkout.
    # Recheck current request authorization before returning historical terms.
    context = _prepare(g.user_id, body["request_id"])
    account = _read(doc("vendor_subscription_accounts", g.user_id)) or {}
    previous = account.get("store_purchase_fingerprint")
    if previous:
        stored = _read(doc(TOKENS, previous)) or {}
        if stored.get("vendor_id") == g.user_id and stored.get("purchase_token"):
            verify_purchase(stored["purchase_token"], vendor_hint=g.user_id, config=config)
    context = _prepare(g.user_id, body["request_id"])
    replacement = _replacement(context)
    if response is not None:
        expected = {**{k: context[k] for k in ("request_id", "plan_version_id", "billing_account_id", "product_id", "base_plan_id")},
                    "package_name": config.package_name, **replacement}
        saved = _read(doc(CONTEXTS, _hash(f"{g.user_id}:{body['request_id']}")))
        if response != expected or not saved or any(saved.get(k) != context[k] for k in context):
            raise PlayBillingError("Checkout eligibility changed; refresh before purchasing", 409, "BILLING_CHECKOUT_CHANGED")
        return jsonify(response)
    binding_ref = doc(BINDINGS, context["billing_account_id"])
    context_ref = doc(CONTEXTS, _hash(f"{g.user_id}:{body['request_id']}"))
    @firestore.transactional
    def persist(tx):
        binding, prior = _read(binding_ref, tx), _read(context_ref, tx)
        if binding and binding.get("vendor_id") != g.user_id:
            raise PlayBillingError("Billing account binding conflicts with another account", 409, "BILLING_ACCOUNT_MISMATCH")
        if prior and any(prior.get(k) != context[k] for k in context):
            raise PlayBillingError("Approved checkout terms changed", 409, "PLAN_CHANGED")
        tx.set(binding_ref, {"vendor_id": g.user_id, "current_request_id": body["request_id"], "updated_at": now_iso()})
        if not prior:
            tx.create(context_ref, {**context, "created_at": now_iso()})
    persist(db().transaction())
    response = {k: context[k] for k in ("request_id", "plan_version_id", "billing_account_id", "product_id", "base_plan_id")}
    response["package_name"] = config.package_name
    response.update(replacement)
    return jsonify(_finish_operation(op, response))


def _work_data(kind, reference, due=None):
    return {"kind": kind, "reference": reference, "due_at": iso(due or _now()), "attempts": 0}


def _claim(token, vendor_hint=None):
    fingerprint = _hash(token)
    ref, work = doc(TOKENS, fingerprint), doc(WORK, "token_" + fingerprint)
    lease = secrets.token_hex(16)
    now = _now()
    @firestore.transactional
    def claim(tx):
        old = _read(ref, tx) or {}
        old_work = _read(work, tx) or {}
        # Ownership is assigned only after Google account/product verification.
        if vendor_hint and old.get("vendor_id") and old["vendor_id"] != vendor_hint:
            raise PlayBillingError("This purchase belongs to another vendor", 403, "BILLING_ACCOUNT_MISMATCH")
        if old.get("lease_id") and parse_time(old["lease_expires_at"]) > now:
            raise PlayBillingError("Subscription verification is already in progress", 409, "BILLING_VERIFICATION_BUSY", retryable=True)
        expiry = now + timedelta(seconds=LEASE_SECONDS)
        update = {"purchase_token": token, "lease_id": lease, "lease_expires_at": iso(expiry),
                  "observation_sequence": int(old.get("observation_sequence", 0)) + 1, "updated_at": iso(now)}
        tx.set(ref, update, merge=True)
        # Recovery exists even when the client or process disappears mid-call.
        tx.set(work, {**_work_data("token", fingerprint, expiry), "attempts": old_work.get("attempts", 0)})
        return {**old, **update}
    return fingerprint, lease, claim(db().transaction())


def _leased(fingerprint, lease, tx):
    ref = doc(TOKENS, fingerprint)
    data = _read(ref, tx) or {}
    if data.get("lease_id") != lease or parse_time(data["lease_expires_at"]) <= _now():
        raise PlayBillingError("Subscription verification lease changed; retry safely", 409, "BILLING_VERIFICATION_BUSY", retryable=True)
    return ref, data


def _release(fingerprint, lease, error):
    @firestore.transactional
    def release(tx):
        ref, current = doc(TOKENS, fingerprint), _read(doc(TOKENS, fingerprint), tx) or {}
        work_ref = doc(WORK, "token_" + fingerprint)
        work = _read(work_ref, tx) or {}
        if current.get("lease_id") != lease:
            return
        attempts = int(work.get("attempts", 0)) + 1
        retryable = error.retryable or error.status >= 500 or error.code == "BILLING_REPLACEMENT_PENDING"
        tx.update(ref, {"lease_id": None, "lease_expires_at": None,
                       "status": "retry" if retryable else "requires_review",
                       "last_error_code": error.code, "updated_at": now_iso()})
        if retryable:
            delay = min(3600, 5 * 2 ** min(attempts, 9))
            tx.set(work_ref, {**_work_data("token", fingerprint, _now() + timedelta(seconds=delay)), "attempts": attempts})
        else:
            tx.delete(work_ref)
    release(db().transaction())


def _context(data, current, vendor_hint, request_id):
    if current.get("vendor_id"):
        if vendor_hint and current["vendor_id"] != vendor_hint:
            raise PlayBillingError("This purchase belongs to another vendor", 403, "BILLING_ACCOUNT_MISMATCH")
        pending = current.get("pending_context") or {}
        if request_id and current.get("request_id") != request_id and pending.get("request_id") != request_id:
            raise PlayBillingError("Purchase does not match this request", 409, "BILLING_REQUEST_MISMATCH")
        if pending and _matches(data, pending):
            return _prepare(current["vendor_id"], pending["request_id"])
        result = {k: current[k] for k in ("vendor_id", "request_id", "plan_version_id", "billing_account_id", "product_id", "base_plan_id")}
        if pending:
            result["pending_context"] = pending
        return result
    if vendor_hint and request_id:
        context = _prepare(vendor_hint, request_id)
        saved = _read(doc(CONTEXTS, _hash(f"{vendor_hint}:{request_id}")))
        if not saved or any(saved.get(k) != context[k] for k in context):
            raise PlayBillingError("Prepare approved checkout before purchasing", 409, "BILLING_CHECKOUT_REQUIRED")
        return context
    account = external_account(data)
    if not isinstance(account, str) or not 16 <= len(account) <= 64 or "/" in account:
        raise PlayBillingError("Purchase has no registered vendor binding", 409, "BILLING_ACCOUNT_MISMATCH")
    binding = _read(doc(BINDINGS, account)) or {}
    vendor = binding.get("vendor_id")
    if not vendor:
        raise PlayBillingError("Purchase has no registered vendor binding", 409, "BILLING_ACCOUNT_MISMATCH")
    if vendor_hint and vendor != vendor_hint:
        raise PlayBillingError("This purchase belongs to another vendor", 403, "BILLING_ACCOUNT_MISMATCH")
    old_token = data.get("linkedPurchaseToken") or (data.get("outOfAppPurchaseContext") or {}).get("expiredPurchaseToken")
    old = _read(doc(TOKENS, _hash(purchase_token(old_token)))) if old_token else None
    if vendor_hint and not request_id and (not old or old.get("vendor_id") != vendor_hint):
        raise PlayBillingError("An approved request is required for the first purchase", 409, "BILLING_REQUEST_REQUIRED")
    req = binding.get("current_request_id")
    if req:
        try:
            prepared = _prepare(vendor, req)
            if _matches(data, prepared, deferred=True):
                return prepared
        except PlayBillingError as exc:
            if exc.status >= 500:
                raise
    # An out-of-app resubscribe retains the expired account/token context.
    if old_token:
        old = old or {}
        if old.get("vendor_id") and old["vendor_id"] != vendor:
            raise PlayBillingError("Replacement belongs to another vendor", 403, "BILLING_ACCOUNT_MISMATCH")
        if old.get("vendor_id") == vendor and _matches(data, old):
            return {**{k: old[k] for k in ("vendor_id", "plan_version_id", "billing_account_id", "product_id", "base_plan_id")}, "request_id": None}
    if not req:
        raise PlayBillingError("An approved request is required for this purchase", 409, "BILLING_REQUEST_REQUIRED")
    return _prepare(vendor, req)


def _matches(data, context, *, deferred=False):
    items = data.get("lineItems")
    if not isinstance(items, list):
        return False
    for item in items:
        if not isinstance(item, dict):
            continue
        details = item.get("offerDetails")
        replacement = item.get("deferredItemReplacement")
        if (item.get("productId") == context.get("product_id") and isinstance(details, dict)
                and details.get("basePlanId") == context.get("base_plan_id")):
            return True
        if deferred and isinstance(replacement, dict) and replacement.get("productId") == context.get("product_id"):
            return True
    return False


def _parse(data, context):
    try:
        parsed = parse_subscription(data, product_id=context["product_id"], base_plan_id=context["base_plan_id"],
                                    billing_account_id=context["billing_account_id"])
        if context.get("pending_context"):
            parsed["replacement_pending"] = True
        return context, parsed
    except PlayBillingError as exc:
        if exc.code != "BILLING_REPLACEMENT_PENDING":
            raise
    # A server-observed deferred replacement can arrive even though the app
    # never requests that mode. Keep the verified old tier and acknowledge the
    # real purchase; the new request is fulfilled only after the real switch.
    linked = data.get("linkedPurchaseToken")
    previous = _read(doc(TOKENS, _hash(purchase_token(linked)))) if linked else None
    if not previous or previous.get("vendor_id") != context["vendor_id"]:
        raise PlayBillingError("Deferred replacement has no verified previous purchase", 409, "BILLING_REPLACEMENT_PENDING", retryable=True)
    old = {k: previous[k] for k in ("vendor_id", "plan_version_id", "billing_account_id", "product_id", "base_plan_id")}
    old.update(request_id=None, pending_context=context)
    parsed = parse_subscription(data, product_id=old["product_id"], base_plan_id=old["base_plan_id"],
                                billing_account_id=old["billing_account_id"])
    parsed["replacement_pending"] = True
    return old, parsed


def _journal(fingerprint, lease, context, parsed):
    linked_token = parsed.get("linked_purchase_token") or parsed.get("expired_purchase_token")
    linked = _hash(linked_token) if linked_token else None
    if linked == fingerprint:
        raise PlayBillingError("Invalid subscription replacement reference", 409, "BILLING_PURCHASE_INVALID")
    @firestore.transactional
    def journal(tx):
        ref, current = _leased(fingerprint, lease, tx)
        previous = _read(doc(TOKENS, linked), tx) if linked else None
        binding = _read(doc(BINDINGS, context["billing_account_id"]), tx)
        account = _read(doc("vendor_subscription_accounts", context["vendor_id"]), tx) or {}
        old_fingerprint = account.get("store_purchase_fingerprint")
        active_previous = (_read(doc(TOKENS, old_fingerprint), tx) or {}) if old_fingerprint and old_fingerprint != fingerprint else None
        if not binding or binding.get("vendor_id") != context["vendor_id"]:
            raise PlayBillingError("Billing account binding is unavailable", 409, "BILLING_ACCOUNT_MISMATCH")
        if current.get("vendor_id") and current["vendor_id"] != context["vendor_id"]:
            raise PlayBillingError("Purchase belongs to another vendor", 403, "BILLING_ACCOUNT_MISMATCH")
        if previous and previous.get("vendor_id") and previous["vendor_id"] != context["vendor_id"]:
            raise PlayBillingError("Replacement belongs to another vendor", 403, "BILLING_ACCOUNT_MISMATCH")
        if (active_previous is not None and linked != old_fingerprint
                and active_previous.get("provider_state") not in {"expired", "revoked"}
                and parsed["provider_state"] not in {"pending", "pending_canceled", "expired", "revoked"}):
            raise PlayBillingError("Replace the existing Google subscription instead of purchasing another one", 409,
                                   "BILLING_REPLACEMENT_REQUIRED")
        sequence = current["observation_sequence"]
        safe = {k: v for k, v in parsed.items() if k not in {"linked_purchase_token", "expired_purchase_token"}}
        transition = {**safe, **context, "linked_purchase_fingerprint": linked,
                      "event_id": f"play:{fingerprint}:{sequence}", "source_revision": sequence}
        tx.update(ref, {**context, "pending_context": context.get("pending_context"),
                        "linked_purchase_fingerprint": linked, "pending_transition": transition,
                        "status": "verified_pending_transition", "updated_at": now_iso()})
        return transition
    return journal(db().transaction())


def _apply(fingerprint, lease, transition, token, client):
    state = transition["provider_state"]
    entitlement = None
    if state not in {"pending", "pending_canceled", "pending_replacement"}:
        args = {k: transition.get(k) for k in ("event_id", "provider_state", "plan_version_id", "starts_at", "ends_at",
            "source_revision", "grace_ends_at", "request_id", "linked_purchase_fingerprint", "acknowledgement_state", "test_purchase")}
        args["purchase_fingerprint"] = fingerprint
        entitlement = _core_call("apply_verified_store_state", transition["vendor_id"], **args)
    ack = transition["acknowledgement_state"]
    if state in {"active", "grace", "canceled", "pending_replacement"} and ack == "ACKNOWLEDGEMENT_STATE_PENDING":
        try:
            client.acknowledge(token, transition["product_id"],
                               billing_account_id=transition["billing_account_id"] if transition.get("needs_account_rebinding") else None)
            ack = "ACKNOWLEDGEMENT_STATE_ACKNOWLEDGED"
        except PlayBillingError:
            # A network timeout can follow a successful ack. Re-read rather than
            # assuming failure or telling a paid user to buy again.
            try:
                check = client.get_subscription(token)
            except PlayBillingError:
                error = PlayBillingError("Purchase verified; acknowledgement is awaiting confirmation", 503,
                                         "BILLING_ACKNOWLEDGEMENT_PENDING", retryable=True)
                error.entitlements = entitlement
                raise error from None
            if (external_account(check) != transition["billing_account_id"]
                    or check.get("acknowledgementState") != "ACKNOWLEDGEMENT_STATE_ACKNOWLEDGED"):
                error = PlayBillingError("Purchase verified; acknowledgement is awaiting confirmation", 503,
                                         "BILLING_ACKNOWLEDGEMENT_PENDING", retryable=True)
                error.entitlements = entitlement
                raise error from None
            ack = "ACKNOWLEDGEMENT_STATE_ACKNOWLEDGED"
    now = _now()
    end = parse_time(transition.get("ends_at"), required=False)
    due = now + timedelta(hours=6)
    if state in {"pending", "pending_canceled", "pending_replacement"} or transition.get("replacement_pending"):
        due = now + timedelta(minutes=10)
    elif end and end > now:
        due = min(due, end + timedelta(seconds=30))
    terminal = state in {"expired", "revoked"}
    @firestore.transactional
    def finish(tx):
        ref, current = _leased(fingerprint, lease, tx)
        if current.get("pending_transition", {}).get("event_id") != transition["event_id"]:
            raise PlayBillingError("Subscription verification changed; retry safely", 409, "BILLING_VERIFICATION_BUSY", retryable=True)
        tx.update(ref, {"provider_state": state, "acknowledgement_state": ack, "starts_at": transition.get("starts_at"),
            "ends_at": transition.get("ends_at"), "test_purchase": transition["test_purchase"],
            "auto_renew_enabled": transition["auto_renew_enabled"], "plan_type": transition["plan_type"],
            "last_applied_revision": transition["source_revision"], "pending_transition": None,
            "lease_id": None, "lease_expires_at": None, "status": "verified", "last_verified_at": iso(now), "last_error_code": None})
        if terminal:
            tx.delete(doc(WORK, "token_" + fingerprint))
        else:
            tx.set(doc(WORK, "token_" + fingerprint), _work_data("token", fingerprint, due))
    finish(db().transaction())
    waiting = transition.get("replacement_pending")
    status = "pending" if state in {"pending", "pending_canceled", "pending_replacement"} or waiting else "verified"
    return {"status": status, "provider_state": "pending_replacement" if waiting else state, "acknowledgement_state": ack,
            "entitlements": entitlement, "test_purchase": transition["test_purchase"]}


def verify_purchase(token, *, vendor_hint=None, request_id=None, config=None, client=None):
    token = purchase_token(token)
    config = config or PlayConfig.from_env()
    client = client or GooglePlayClient(config)
    fingerprint, lease, current = _claim(token, vendor_hint)
    try:
        # Resume the exact journal if a process died between the central commit
        # and provider acknowledgement/finalization. The hook event is stable.
        if current.get("pending_transition"):
            _apply(fingerprint, lease, current["pending_transition"], token, client)
            fingerprint, lease, current = _claim(token, vendor_hint)
        data = client.get_subscription(token)
        context = _context(data, current, vendor_hint, request_id)
        context, parsed = _parse(data, context)
        if parsed["plan_type"] != "auto_renewing" and parsed["provider_state"] not in {"pending", "pending_canceled"}:
            raise PlayBillingError("Prepaid and installment subscriptions require review", 409, "BILLING_PLAN_UNSUPPORTED")
        if parsed["test_purchase"] and context["vendor_id"] not in config.test_vendor_ids:
            raise PlayBillingError("Test purchases are not enabled for this vendor", 403, "BILLING_TEST_PURCHASE_DISABLED")
        transition = _journal(fingerprint, lease, context, parsed)
        return _apply(fingerprint, lease, transition, token, client)
    except PlayBillingError as exc:
        _release(fingerprint, lease, exc)
        raise
    except Exception:
        _release(fingerprint, lease, PlayBillingError("Verification interrupted", retryable=True))
        raise


@google_play_bp.post("/subscriptions/google-play/verify")
@require_role("vendor")
def verify_checkout():
    config = PlayConfig.from_env()
    body = _json()
    if set(body) - {"request_id", "purchase_token"} or "purchase_token" not in body:
        raise PlayBillingError("Only purchase_token and optional request_id are accepted", 422, "BILLING_INVALID_REQUEST")
    token = purchase_token(body["purchase_token"])
    req = body.get("request_id")
    if req is not None:
        identifier(req, "request")
    op, response = _operation(g.user_id, "verify", _key(), {"request_id": req, "purchase_fingerprint": _hash(token)})
    if response is not None:
        return jsonify({**response, "entitlements": _core_call("entitlements", g.user_id)})
    try:
        response = verify_purchase(token, vendor_hint=g.user_id, request_id=req, config=config)
    except PlayBillingError as exc:
        if exc.code == "BILLING_ACKNOWLEDGEMENT_PENDING":
            return jsonify({"status": "verification_pending", "detail": exc.detail, "code": exc.code,
                            "entitlements": getattr(exc, "entitlements", None),
                            "retry_after_seconds": 10}), 202
        raise
    if response["status"] == "pending":
        return jsonify({**response, "retry_after_seconds": 10}), 202
    return jsonify(_finish_operation(op, response))


def _notification(body, config):
    message = body.get("message")
    if body.get("subscription") != config.rtdn_subscription or not isinstance(message, dict):
        raise PlayBillingError("Unexpected notification subscription", 403, "BILLING_PUSH_UNAUTHORIZED")
    mid, encoded = message.get("messageId"), message.get("data")
    if not isinstance(mid, str) or not 1 <= len(mid) <= 200 or not isinstance(encoded, str) or len(encoded) > 40000:
        raise PlayBillingError("Invalid notification envelope", 422, "BILLING_INVALID_NOTIFICATION")
    try:
        decoded = json.loads(base64.b64decode(encoded, validate=True))
    except (ValueError, UnicodeDecodeError):
        raise PlayBillingError("Invalid notification data", 422, "BILLING_INVALID_NOTIFICATION") from None
    if not isinstance(decoded, dict) or decoded.get("packageName") != config.package_name:
        raise PlayBillingError("Unexpected notification package", 403, "BILLING_PUSH_UNAUTHORIZED")
    names = [x for x in ("subscriptionNotification", "voidedPurchaseNotification", "pendingRefundReviewNotification",
                        "oneTimeProductNotification", "testNotification") if x in decoded]
    if len(names) != 1 or not isinstance(decoded[names[0]], dict):
        raise PlayBillingError("Invalid notification kind", 422, "BILLING_INVALID_NOTIFICATION")
    kind, detail = names[0], decoded[names[0]]
    token = detail.get("purchaseToken")
    if kind in {"subscriptionNotification", "voidedPurchaseNotification"}:
        purchase_token(token)
    # Physical goods never use Play Billing. Retain unhandled kinds for review,
    # but never interpret their payload as a subscription grant.
    return mid, {"kind": kind, "purchase_token": token, "package_name": config.package_name,
                 "notification_type": detail.get("notificationType"), "event_time_millis": decoded.get("eventTimeMillis"),
                 "refund_type": detail.get("refundType"), "product_type": detail.get("productType")}


@google_play_bp.post("/webhooks/google-play/rtdn")
def receive_notification():
    config = PlayConfig.from_env(rtdn=True)
    verify_push_identity(request.headers.get("Authorization"), config)
    mid, notification = _notification(_json(60000), config)
    event_id = _hash(mid)
    ref = doc(EVENTS, event_id)
    fingerprint = _hash(json.dumps(notification, sort_keys=True, separators=(",", ":")))
    @firestore.transactional
    def accept(tx):
        old = _read(ref, tx)
        if old:
            if old.get("fingerprint") != fingerprint:
                raise PlayBillingError("Notification identity was reused", 409, "BILLING_INVALID_NOTIFICATION")
            return
        process = notification["kind"] in {"subscriptionNotification", "voidedPurchaseNotification"}
        status = "pending" if process else ("completed" if notification["kind"] == "testNotification" else "requires_review")
        tx.create(ref, {**notification, "message_id": mid, "fingerprint": fingerprint,
                        "status": status, "received_at": now_iso()})
        if process:
            tx.set(doc(WORK, "event_" + event_id), _work_data("event", event_id))
    accept(db().transaction())
    # No acknowledgement before durable acceptance. Worker retries survive
    # client logout, Pub/Sub redelivery, or a Google API outage.
    return "", 204


def _claim_work(work_id):
    ref = doc(WORK, work_id)
    lease = secrets.token_hex(16)
    @firestore.transactional
    def claim(tx):
        current = _read(ref, tx)
        if not current or not current.get("due_at") or parse_time(current["due_at"]) > _now():
            return None
        update = {"work_lease_id": lease, "due_at": iso(_now() + timedelta(seconds=LEASE_SECONDS))}
        tx.update(ref, update)
        return {**current, **update}
    return claim(db().transaction())


def reconcile_google_play(*, limit=20, config=None, client=None, budget_seconds=90):
    """Bounded durable worker, callable by an authenticated admin or job."""
    if type(limit) is not int or not 1 <= limit <= 50:
        raise PlayBillingError("Reconciliation limit must be 1 to 50", 422, "BILLING_INVALID_REQUEST")
    if type(budget_seconds) is not int or not 10 <= budget_seconds <= 300:
        raise PlayBillingError("Invalid reconciliation time budget", 422, "BILLING_INVALID_REQUEST")
    config = config or PlayConfig.from_env()
    client = client or GooglePlayClient(config)
    jobs = list(col(WORK).where(filter=FieldFilter("due_at", "<=", iso(_now()))).limit(limit).stream())
    result = {"processed": 0, "completed": 0, "retry": 0, "requires_review": 0}
    started = time.monotonic()
    for snapshot in jobs:
        if time.monotonic() - started >= budget_seconds:
            break
        job = _claim_work(snapshot.id)
        if job is None:
            continue
        event = None
        if job.get("kind") == "event":
            event = _read(doc(EVENTS, job.get("reference")))
            token = (event or {}).get("purchase_token")
        else:
            stored = _read(doc(TOKENS, job.get("reference")))
            token = (stored or {}).get("purchase_token")
        if not token:
            # Persist a visible review state rather than silently dropping work.
            @firestore.transactional
            def invalid(tx):
                current = _read(doc(WORK, snapshot.id), tx)
                if not current or current.get("work_lease_id") != job["work_lease_id"]:
                    return
                tx.set(doc("google_play_work_failures", snapshot.id), {"kind": job.get("kind"), "reference": job.get("reference"),
                    "last_error_code": "BILLING_WORK_INVALID", "status": "requires_review", "detected_at": now_iso()})
                tx.delete(doc(WORK, snapshot.id))
            invalid(db().transaction())
            result["requires_review"] += 1
            continue
        result["processed"] += 1
        try:
            verify_purchase(token, config=config, client=client)
            if event:
                @firestore.transactional
                def complete(tx):
                    current = _read(doc(WORK, snapshot.id), tx)
                    if not current or current.get("work_lease_id") != job["work_lease_id"]:
                        return
                    tx.update(doc(EVENTS, job["reference"]), {"status": "completed", "processed_at": now_iso()})
                    tx.delete(doc(WORK, snapshot.id))
                complete(db().transaction())
            result["completed"] += 1
        except PlayBillingError as exc:
            retry = exc.retryable or exc.status >= 500 or exc.code == "BILLING_REPLACEMENT_PENDING"
            result["retry" if retry else "requires_review"] += 1
            if event:
                attempts = int(job.get("attempts", 0)) + 1
                @firestore.transactional
                def failure(tx):
                    current = _read(doc(WORK, snapshot.id), tx)
                    if not current or current.get("work_lease_id") != job["work_lease_id"]:
                        return
                    tx.update(doc(EVENTS, job["reference"]), {"status": "retry" if retry else "requires_review", "last_error_code": exc.code})
                    if retry:
                        tx.set(doc(WORK, snapshot.id), {**job, "attempts": attempts,
                            "due_at": iso(_now() + timedelta(seconds=min(3600, 5 * 2 ** min(attempts, 9))))})
                    else:
                        tx.delete(doc(WORK, snapshot.id))
                failure(db().transaction())
    return result


@google_play_bp.post("/admin/subscriptions/google-play/reconcile")
@require_role("admin", "super_admin")
def reconcile_route():
    body = _json()
    reason = body.get("reason")
    if set(body) - {"limit", "reason"} or not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 1000:
        raise PlayBillingError("Supply a reason and optional limit", 422, "BILLING_INVALID_REQUEST")
    op, response = _operation(g.user_id, "reconcile", _key(), body)
    if response is not None:
        return jsonify(response)
    return jsonify(_finish_operation(op, reconcile_google_play(limit=body.get("limit", 20))))
