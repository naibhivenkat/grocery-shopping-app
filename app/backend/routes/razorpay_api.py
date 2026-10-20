"""Server priced Razorpay checkout and idempotent captured-payment settlement."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import uuid
from flask import Blueprint, g, jsonify, request
from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter
from auth_utils import require_auth
from db import (CUSTOMER_ORDERS, SUBSCRIPTION_PLANS, VENDOR_SUBSCRIPTIONS, NOTIFICATIONS,
                WALLET_TRANSACTIONS, WALLETS, col, db, doc, now_iso)
from razorpay_config import get_razorpay_client, get_razorpay_key_id
from notification_delivery import notification_data, deliver_push
from routes.order_amendments import guard_order_mutation, validate_amendment_payment, settle_captured_amendment, _expired

razorpay_api_bp = Blueprint("razorpay_api", __name__)
PAYMENT_ORDERS = "payment_orders"
ALLOWED_PURPOSES = {"order", "subscription", "service", "order_amendment"}


def _amount_paise(value, *, allow_zero=False):
    try:
        amount = Decimal(str(value))
        paise = (amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not amount.is_finite() or amount < 0 or (paise < 0 if allow_zero else paise <= 0) or paise > 10_000_000_00:
        return None
    return int(paise)


def _target_spec(purpose):
    return {"order": (CUSTOMER_ORDERS, "customer_id", "total_price"),
            "order_amendment": ("order_amendments", "customer_id", "amount_due"),
            "service": ("service_bookings", "requester_id", "final_total"),
            "subscription": (VENDOR_SUBSCRIPTIONS, "vendor_id", "amount")}[purpose]


def _trusted_checkout(purpose, reference_id, user_id):
    collection, owner_field, amount_field = _target_spec(purpose)
    first = doc(collection, reference_id).get()
    if not first.exists:
        raise ValueError("Payment reference not found")
    initial = first.to_dict() or {}
    if initial.get(owner_field) != user_id:
        raise PermissionError("Payment reference belongs to another account")
    targets = [first]
    if purpose == "order" and initial.get("batch_id"):
        targets = list(col(collection).where(filter=FieldFilter(
            "batch_id", "==", initial["batch_id"])).stream())
    if not targets or len(targets) > 100:
        raise ValueError("Invalid checkout batch")
    total = 0
    for snap in targets:
        data = snap.to_dict() or {}
        if data.get(owner_field) != user_id:
            raise PermissionError("Payment reference belongs to another account")
        if data.get("status") in {"cancelled", "rejected", "completed", "active"} or data.get("payment_status") == "paid":
            raise ValueError("Payment reference is no longer payable")
        if purpose == "order" and data.get("payment_method") not in {"upi", "razorpay"}:
            raise ValueError("Order is not a Razorpay checkout")
        if purpose == "order_amendment" and (data.get("status") != "awaiting_payment" or _expired(data)):
            raise ValueError("Order amendment is no longer payable")
        if purpose == "service" and data.get("status") != "pending_payment":
            raise ValueError("Booking is no longer payable")
        amount = data.get(amount_field)
        if purpose == "subscription":
            plan = doc(SUBSCRIPTION_PLANS, str(data.get("plan_id") or "")).get()
            if not plan.exists:
                raise ValueError("Subscription plan not found")
            amount = (plan.to_dict() or {}).get("price")
        paise = _amount_paise(amount, allow_zero=purpose == "order")
        if paise is None or (purpose == "order" and paise == 0 and data.get("payment_exempt") is not True):
            raise ValueError("Payment reference has an invalid server price")
        total += paise
    if total <= 0:
        raise ValueError("No payment is required for this order")
    if total > 10_000_000_00:
        raise ValueError("Checkout amount exceeds limit")
    return targets, total


def captured_payment_matches(intent, payment):
    """Signature alone proves identity, not that funds were captured."""
    return (isinstance(payment, dict)
            and bool(payment.get("id"))
            and payment.get("order_id") == intent.get("razorpay_order_id")
            and payment.get("status") == "captured"
            and payment.get("captured") is True
            and payment.get("currency") == intent.get("currency", "INR")
            and type(payment.get("amount")) is int
            and payment.get("amount") == intent.get("amount_paise"))


def settle_payment_order(intent_id, payment_id, event_id=None):
    """Caller must first verify provider capture, amount, currency and order."""
    intent_ref = doc(PAYMENT_ORDERS, intent_id)

    @firestore.transactional
    def _settle(transaction):
        snap = intent_ref.get(transaction=transaction)
        if not snap.exists:
            return {"status": "missing"}
        intent = snap.to_dict() or {}
        if intent.get("status") == "paid":
            return {"status": "already_paid", "settlement_status": intent.get("settlement_status", "settled")}
        purpose = intent.get("purpose")
        writes = []
        events = []
        settlement_status = "settled"
        if purpose == "wallet":
            # Preserve money captured for historical wallet intents even while
            # new wallet checkouts and wallet spending are disabled.
            wallet_ref = doc(WALLETS, intent["user_id"])
            wallet_snap = wallet_ref.get(transaction=transaction)
            wallet_tx_ref = doc(WALLET_TRANSACTIONS, f"razorpay_{intent_id}")
            wallet_tx = wallet_tx_ref.get(transaction=transaction)
            wallet = wallet_snap.to_dict() or {}
            if not wallet_tx.exists:
                amount = intent["amount_paise"] / 100
                writes.append(("set", wallet_ref, {"user_id": intent["user_id"],
                    "balance": float(wallet.get("balance") or 0) + amount,
                    "total_credit": float(wallet.get("total_credit") or 0) + amount,
                    "last_updated": now_iso()}))
                writes.append(("create", wallet_tx_ref, {"wallet_id": intent["user_id"],
                    "user_id": intent["user_id"], "type": "credit", "amount": amount,
                    "description": "Razorpay wallet recharge", "payment_intent_id": intent_id,
                    "payment_id": payment_id, "created_at": now_iso()}))
        elif purpose == "order_amendment":
            outcome = settle_captured_amendment(transaction, intent, payment_id, intent_id)
            settlement_status = outcome["settlement_status"]
            events.extend(outcome.get("events", []))
        elif purpose in ALLOWED_PURPOSES:
            collection, owner_field, _ = _target_spec(purpose)
            target_ids = intent.get("target_ids") or [intent.get("reference_id")]
            targets = []
            for target_id in target_ids:
                if not target_id:
                    settlement_status = "requires_review"
                    continue
                ref = doc(collection, target_id)
                target = ref.get(transaction=transaction)
                data = target.to_dict() or {}
                if (not target.exists or data.get(owner_field) != intent.get("user_id")
                    or data.get("status") in {"cancelled", "rejected"}
                    or (data.get("payment_status") == "paid" and data.get("payment_intent_id") != intent_id)):
                    settlement_status = "requires_review"
                targets.append((ref, data))
            if purpose == "order":
                amounts = [_amount_paise(data.get("total_price"), allow_zero=True) for _, data in targets]
                if (any(value is None for value in amounts)
                        or any(amount == 0 and data.get("payment_exempt") is not True for (_, data), amount in zip(targets, amounts))
                        or sum(value or 0 for value in amounts) != intent.get("amount_paise")):
                    settlement_status = "requires_review"
            # All target documents are read before any writes. A captured
            # cancelled/duplicate payment is retained for refund review.
            if settlement_status == "settled":
                for ref, data in targets:
                    updates = {"payment_status": "paid", "payment_method": "razorpay",
                        "payment_intent_id": intent_id, "razorpay_payment_id": payment_id,
                        "payment_id": payment_id, "paid_at": now_iso(), "updated_at": now_iso()}
                    if purpose == "order":
                        updates.update({"partial_amount_paid": data.get("total_price"), "due_amount": 0,
                                        "payment_exempt": _amount_paise(data.get("total_price"), allow_zero=True) == 0})
                        for recipient in (data.get("customer_id"), data.get("vendor_id")):
                            if recipient:
                                event = notification_data(recipient, "order_payment", "Payment confirmed",
                                    "Online payment was confirmed.", ref.id)
                                events.append(event)
                                writes.append(("set", doc(NOTIFICATIONS, f"payment_{intent_id}_{ref.id}_{recipient}"), event))
                    elif purpose == "subscription":
                        now = datetime.now(timezone.utc)
                        updates.update({"status": "active", "activated_at": now.isoformat(),
                            "start_date": now.isoformat(), "end_date": (now + timedelta(
                                days=int(intent.get("duration_days") or 30))).isoformat()})
                    writes.append(("update", ref, updates))
        else:
            settlement_status = "requires_review"
        for method, ref, data in writes:
            if method == "set":
                transaction.set(ref, data, merge=True)
            else:
                getattr(transaction, method)(ref, data)
        transaction.update(intent_ref, {"status": "paid", "payment_id": payment_id,
            "settlement_status": settlement_status, "settled_at": now_iso(),
            **({"last_webhook_event_id": event_id} if event_id else {})})
        return {"status": "paid", "purpose": purpose, "settlement_status": settlement_status, "_events": events}
    result = _settle(db().transaction())
    for event in result.pop("_events", []):
        deliver_push(event, lookup=doc)
    return result


def fail_payment_order(intent_id, payment_id=None, event_id=None, reason=None):
    ref = doc(PAYMENT_ORDERS, intent_id)
    @firestore.transactional
    def _fail(transaction):
        snap = ref.get(transaction=transaction)
        if not snap.exists:
            return {"status": "missing"}
        data = snap.to_dict() or {}
        if data.get("status") == "paid":
            return {"status": "paid"}
        transaction.update(ref, {"status": "failed", "failed_payment_id": payment_id,
            "failure_reason": reason or "Payment failed", "failed_at": now_iso(),
            **({"last_webhook_event_id": event_id} if event_id else {})})
        return {"status": "failed"}
    return _fail(db().transaction())


@razorpay_api_bp.post("/razorpayApi/orders")
@require_auth
def create_razorpay_order():
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify({"detail": "JSON object required"}), 422
    purpose = str(payload.get("purpose") or "order")
    reference_id = str(payload.get("reference_id") or "").strip()
    if purpose == "subscription":
        return jsonify({"detail": "Digital vendor subscriptions require Google Play Billing", "code": "BILLING_REQUIRED"}), 403
    if purpose == "wallet":
        return jsonify({"detail": "Wallet is temporarily disabled", "code": "WALLET_DISABLED"}), 403
    if purpose not in ALLOWED_PURPOSES or not reference_id or len(reference_id) > 128 or "/" in reference_id:
        return jsonify({"detail": "Valid purpose and reference_id are required"}), 422
    try:
        targets, amount_paise = _trusted_checkout(purpose, reference_id, g.user_id)
        # Amount is always taken from the server-owned reference. Reject stale
        # UI totals instead of silently charging a different displayed amount.
        if payload.get("amount") is not None and _amount_paise(payload["amount"]) != amount_paise:
            return jsonify({"detail": "Checkout total changed; refresh and retry"}), 409
        client = get_razorpay_client()
        existing_ids = {(snap.to_dict() or {}).get("payment_intent_id") for snap in targets}
        if len(existing_ids) == 1 and next(iter(existing_ids)):
            existing_id = next(iter(existing_ids))
            existing_snap = doc(PAYMENT_ORDERS, existing_id).get()
            existing = existing_snap.to_dict() or {}
            if (existing_snap.exists and existing.get("user_id") == g.user_id
                and existing.get("amount_paise") == amount_paise
                and existing.get("status") in {"created", "failed"}
                and existing.get("razorpay_order_id")):
                return jsonify({"backend_order_id": existing_id,
                    "razorpay_order_id": existing["razorpay_order_id"],
                    "key_id": get_razorpay_key_id(), "amount": amount_paise,
                    "currency": "INR"}), 200
        duration_days = 30
        if purpose == "subscription":
            plan_id = (targets[0].to_dict() or {}).get("plan_id")
            plan = doc(SUBSCRIPTION_PLANS, plan_id).get().to_dict() or {}
            duration_days = int(plan.get("duration_days") or 30)
        intent_ref = col(PAYMENT_ORDERS).document()
        @firestore.transactional
        def _reserve(tx):
            refs = []
            reserved_total = 0
            for target in targets:
                snap = target.reference.get(transaction=tx)
                data = snap.to_dict() or {}
                if not snap.exists or data.get("payment_status") == "paid" or data.get("status") in {"cancelled", "rejected"}:
                    raise ValueError("Payment reference is no longer payable")
                collection, owner_field, price_field = _target_spec(purpose)
                if data.get(owner_field) != g.user_id:
                    raise PermissionError("Payment reference belongs to another account")
                if purpose == "order":
                    guard_order_mutation(tx, data, lookup=doc)
                elif purpose == "order_amendment":
                    validate_amendment_payment(tx, data, snap.id, g.user_id)
                price = data.get(price_field)
                if purpose == "subscription":
                    current_plan = doc(SUBSCRIPTION_PLANS, data.get("plan_id")).get(transaction=tx)
                    price = (current_plan.to_dict() or {}).get("price")
                current_paise = _amount_paise(price, allow_zero=purpose == "order")
                if current_paise is None or (purpose == "order" and current_paise == 0 and data.get("payment_exempt") is not True):
                    raise ValueError("Payment reference has an invalid server price")
                reserved_total += current_paise
                prior_id = data.get("payment_intent_id")
                if prior_id:
                    prior = doc(PAYMENT_ORDERS, prior_id).get(transaction=tx)
                    prior_data = prior.to_dict() or {}
                    # A failed attempt can later be captured. Keep one provider
                    # order per checkout rather than permitting double charging.
                    if prior.exists:
                        raise ValueError("Checkout already has a payment attempt; retry that checkout")
                refs.append(target.reference)
            if reserved_total != amount_paise:
                raise ValueError("Checkout total changed; refresh and retry")
            tx.create(intent_ref, {"user_id": g.user_id, "amount": amount_paise / 100,
                "amount_paise": amount_paise, "currency": "INR", "purpose": purpose,
                "reference_id": reference_id, "target_ids": [s.id for s in targets],
                "status": "initializing", "duration_days": duration_days, "created_at": now_iso()})
            for ref in refs:
                tx.update(ref, {"payment_intent_id": intent_ref.id})
        _reserve(db().transaction())
        try:
            order = client.order.create({"amount": amount_paise, "currency": "INR",
                "receipt": f"ls_{uuid.uuid4().hex[:24]}", "notes": {
                    "user_id": g.user_id, "purpose": purpose, "reference_id": reference_id,
                    "backend_order_id": intent_ref.id}})
        except Exception:
            # No provider order was returned: release the checkout reservation
            # atomically. An unknown provider outcome is never exposed to client.
            @firestore.transactional
            def _release(tx):
                snaps = [s.reference.get(transaction=tx) for s in targets]
                for snap in snaps:
                    if (snap.to_dict() or {}).get("payment_intent_id") == intent_ref.id:
                        tx.update(snap.reference, {"payment_intent_id": None})
                tx.update(intent_ref, {"status": "creation_failed"})
            _release(db().transaction())
            raise
        intent_ref.update({"razorpay_order_id": order["id"], "status": "created"})
        return jsonify({"backend_order_id": intent_ref.id, "razorpay_order_id": order["id"],
            "key_id": get_razorpay_key_id(), "amount": amount_paise, "currency": "INR"}), 201
    except PermissionError as exc:
        return jsonify({"detail": str(exc)}), 403
    except ValueError as exc:
        return jsonify({"detail": str(exc)}), 409
    except Exception as exc:
        print(f"Razorpay order creation failed: {type(exc).__name__}")
        return jsonify({"detail": "Payment service temporarily unavailable"}), 503


@razorpay_api_bp.post("/razorpayApi/verify")
@require_auth
def verify_razorpay_payment():
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify({"detail": "JSON object required"}), 422
    fields = [str(payload.get(k) or "") for k in ("backend_order_id", "order_id", "payment_id", "signature")]
    intent_id, order_id, payment_id, signature = fields
    if not all(fields) or any("/" in v or len(v) > 256 for v in fields):
        return jsonify({"detail": "Valid payment verification fields are required"}), 422
    snap = doc(PAYMENT_ORDERS, intent_id).get()
    intent = snap.to_dict() or {} if snap.exists else {}
    if not snap.exists or intent.get("user_id") != g.user_id:
        return jsonify({"detail": "Payment intent not found"}), 404
    if intent.get("razorpay_order_id") != order_id:
        return jsonify({"detail": "Razorpay order mismatch"}), 422
    client = get_razorpay_client()
    try:
        client.utility.verify_payment_signature({"razorpay_order_id": order_id,
            "razorpay_payment_id": payment_id, "razorpay_signature": signature})
    except Exception:
        return jsonify({"detail": "Invalid Razorpay payment signature"}), 400
    try:
        payment = client.payment.fetch(payment_id)
    except Exception:
        return jsonify({"detail": "Provider payment verification temporarily unavailable"}), 503
    if not captured_payment_matches(intent, payment) or payment.get("id") != payment_id:
        return jsonify({"detail": "Payment is not captured for this order and amount"}), 409
    result = settle_payment_order(intent_id, payment_id)
    if result["status"] not in {"paid", "already_paid"} or result.get("settlement_status") != "settled":
        return jsonify({"detail": "Captured payment requires settlement review", **result}), 409
    return jsonify({"success": True, **result, "backend_order_id": intent_id})


@razorpay_api_bp.post('/razorpayApi/intents/<intent_id>/reconcile')
@require_auth
def reconcile_razorpay_intent(intent_id):
    """Recover server-observed capture after checkout interruption, without charging.

    This reads only the authenticated owner's original provider order. Client
    payment IDs, signatures, amounts and status claims are never accepted here.
    """
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or payload:
        return jsonify({'detail': 'Send an empty JSON object; payment details are read from the provider'}), 422
    if not intent_id or '/' in intent_id or len(intent_id) > 128:
        return jsonify({'detail': 'Invalid payment intent ID'}), 422
    try:
        snap = doc(PAYMENT_ORDERS, intent_id).get()
    except Exception:
        return jsonify({'detail': 'Payment status temporarily unavailable', 'retryable': True}), 503
    intent = snap.to_dict() or {} if snap.exists else {}
    if not snap.exists or intent.get('user_id') != g.user_id:
        return jsonify({'detail': 'Payment intent not found'}), 404

    def response(status, *, payment_id=None, settlement_status=None, http=200):
        return jsonify({'success': status == 'paid', 'status': status,
            'backend_order_id': intent_id, 'payment_id': payment_id,
            **({'settlement_status': settlement_status} if settlement_status else {}),
            'retryable': status in {'pending', 'failed'}}), http

    if intent.get('status') == 'paid':
        settled = intent.get('settlement_status', 'settled')
        return response('paid' if settled == 'settled' else 'requires_review',
            payment_id=intent.get('payment_id'), settlement_status=settled,
            http=200 if settled == 'settled' else 409)
    order_id = intent.get('razorpay_order_id')
    if not order_id:
        if intent.get('status') == 'creation_failed':
            return response('failed')
        return response('pending')
    if (not isinstance(order_id, str) or not order_id.startswith('order_')
        or '/' in order_id or len(order_id) > 128
        or intent.get('currency') != 'INR' or type(intent.get('amount_paise')) is not int
        or intent['amount_paise'] <= 0):
        return response('requires_review', http=409)
    try:
        result = get_razorpay_client().order.payments(order_id, timeout=20)
        items = result.get('items') if isinstance(result, dict) else None
        if not isinstance(items, list) or len(items) > 2000 or any(not isinstance(item, dict) for item in items):
            raise ValueError('Invalid provider payment collection')
    except Exception:
        return jsonify({'detail': 'Provider payment status temporarily unavailable', 'retryable': True,
            'backend_order_id': intent_id}), 503
    captures = {}
    for payment in items:
        if payment.get('order_id') != order_id:
            return response('requires_review', http=409)
        if payment.get('status') == 'captured' or payment.get('captured') is True:
            payment_id = payment.get('id')
            if (not captured_payment_matches(intent, payment) or not isinstance(payment_id, str)
                or not payment_id.startswith('pay_') or '/' in payment_id or len(payment_id) > 128):
                return response('requires_review', http=409)
            captures[payment_id] = payment
    if len(captures) > 1:
        return response('requires_review', http=409)
    if captures:
        payment_id = next(iter(captures))
        try:
            settled = settle_payment_order(intent_id, payment_id)
        except Exception:
            return jsonify({'detail': 'Captured payment settlement temporarily unavailable', 'retryable': True,
                'backend_order_id': intent_id}), 503
        if settled.get('status') not in {'paid', 'already_paid'} or settled.get('settlement_status') != 'settled':
            return response('requires_review', payment_id=payment_id,
                settlement_status=settled.get('settlement_status'), http=409)
        return response('paid', payment_id=payment_id, settlement_status='settled')
    if items and all(payment.get('status') == 'failed' for payment in items):
        return response('failed')
    if not items and intent.get('status') == 'failed':
        return response('failed')
    return response('pending')
