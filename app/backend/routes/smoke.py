"""`/debug/smoke-test` — exercises every endpoint and reports pass/fail.

Call via `GET /debug/smoke-test`. The handler uses Flask's in-process test
client to hit every route the Flutter datasources call, with freshly
registered customer / vendor / admin users, and returns a single JSON
report: `{ok, passed, total, results: [...] }`.

Intended as an operational smoke test. Set `SMOKE_TEST_KEY` env var and
pass `?key=<value>` to gate access in production.
"""

from __future__ import annotations

import os
import secrets
import time
from typing import Any

from flask import Blueprint, current_app, jsonify, request


smoke_bp = Blueprint("smoke", __name__)


def _hit(client, method: str, path: str, *, token: str | None = None, body: Any = None) -> dict:
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    kwargs: dict[str, Any] = {"headers": headers}
    if body is not None:
        kwargs["json"] = body
    start = time.perf_counter()
    resp = client.open(path, method=method, **kwargs)
    elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
    data = resp.get_json(silent=True)
    if data is None:
        preview = resp.data[:300].decode("utf-8", "replace") if resp.data else None
    else:
        preview = data
    return {
        "method": method,
        "path": path,
        "status": resp.status_code,
        "ok": 200 <= resp.status_code < 400,
        "ms": elapsed_ms,
        "body": preview,
    }


def _register(client, email: str, password: str, role: str, full_name: str) -> tuple[str | None, str | None]:
    r = _hit(client, "POST", "/auth/register", body={
        "email": email,
        "password": password,
        "role": role,
        "full_name": full_name,
    })
    if not r["ok"] or not isinstance(r["body"], dict):
        return None, None
    token = r["body"].get("access_token")
    uid = (r["body"].get("user") or {}).get("uid")
    return token, uid


@smoke_bp.get("/debug/smoke-test")
def smoke_test():
    expected_key = os.getenv("SMOKE_TEST_KEY")
    if expected_key and request.args.get("key") != expected_key:
        return jsonify({"detail": "Forbidden"}), 403

    client = current_app.test_client()
    results: list[dict] = []

    def record(label: str, r: dict) -> dict:
        r["label"] = label
        results.append(r)
        return r

    # ── Public / anonymous ────────────────────────────────────────────────
    record("health", _hit(client, "GET", "/health"))
    record("root", _hit(client, "GET", "/"))
    record("list cities", _hit(client, "GET", "/cities"))
    record("list shops", _hit(client, "GET", "/shops"))
    record("list categories", _hit(client, "GET", "/shops/categories"))
    record("list subscription plans", _hit(client, "GET", "/subscriptions/plans"))
    record("ai summary", _hit(client, "GET", "/ai/summary"))

    # ── Register customer, vendor, admin ──────────────────────────────────
    suffix = secrets.token_hex(3)
    password = "SmokeTest123!"
    cust_email = f"smoke-cust-{suffix}@test.local"
    vend_email = f"smoke-vend-{suffix}@test.local"
    admin_email = f"smoke-admin-{suffix}@test.local"

    record("register customer",
           _hit(client, "POST", "/auth/register", body={
               "email": cust_email, "password": password,
               "role": "customer", "full_name": "Smoke Customer",
           }))
    cust_token, cust_uid = _register(client, cust_email + ".dup", password, "customer", "Smoke Customer Dup")
    # Use the first registration's token
    first_cust = results[-1]
    cust_token = (first_cust["body"] or {}).get("access_token") if first_cust["ok"] else None
    cust_uid = ((first_cust["body"] or {}).get("user") or {}).get("uid") if first_cust["ok"] else None

    vend_token, vend_uid = _register(client, vend_email, password, "vendor", "Smoke Vendor")
    admin_token, admin_uid = _register(client, admin_email, password, "admin", "Smoke Admin")

    results.append({"label": "register vendor", "method": "POST", "path": "/auth/register",
                    "status": 201 if vend_token else 500,
                    "ok": bool(vend_token), "ms": 0,
                    "body": {"uid": vend_uid} if vend_uid else "registration failed"})
    results.append({"label": "register admin", "method": "POST", "path": "/auth/register",
                    "status": 201 if admin_token else 500,
                    "ok": bool(admin_token), "ms": 0,
                    "body": {"uid": admin_uid} if admin_uid else "registration failed"})

    # ── Login round-trip ──────────────────────────────────────────────────
    record("login customer",
           _hit(client, "POST", "/auth/login",
                body={"email": cust_email, "password": password}))

    # ── Customer-scoped endpoints ────────────────────────────────────────
    if cust_token:
        record("auth me", _hit(client, "GET", "/auth/me", token=cust_token))
        record("auth role", _hit(client, "GET", "/auth/role", token=cust_token))
        record("get profile", _hit(client, "GET", "/profile", token=cust_token))
        record("update profile", _hit(client, "PUT", "/profile",
                                      token=cust_token, body={"phone": "9999999999"}))
        record("list notifications",
               _hit(client, "GET", "/notifications", token=cust_token))
        record("mark all read",
               _hit(client, "POST", "/notifications/read-all", token=cust_token))
        record("get wallet", _hit(client, "GET", "/wallet", token=cust_token))
        record("wallet credit",
               _hit(client, "POST", "/wallet/credit",
                    token=cust_token, body={"amount": 100, "description": "smoke"}))
        record("wallet deduct",
               _hit(client, "POST", "/wallet/deduct",
                    token=cust_token, body={"amount": 10, "description": "smoke-deduct"}))
        record("wallet transactions",
               _hit(client, "GET", "/wallet/transactions?limit=5", token=cust_token))
        record("generate referral",
               _hit(client, "POST", "/referrals/generate", token=cust_token))
        record("list referrals",
               _hit(client, "GET", "/referrals", token=cust_token))
        record("list favorites",
               _hit(client, "GET", "/shops/favorites", token=cust_token))
        record("list customer orders",
               _hit(client, "GET", "/orders", token=cust_token))
        record("list chat rooms",
               _hit(client, "GET", "/chat/rooms", token=cust_token))
        record("set current city",
               _hit(client, "PUT", "/cities/current",
                    token=cust_token, body={"city_id": "smoke-city"}))
        if cust_uid:
            record("get current city",
                   _hit(client, "GET", f"/cities/current/{cust_uid}"))
        record("ai budget plan",
               _hit(client, "POST", "/ai/budget-plan",
                    token=cust_token, body={"budget": 500, "city_id": ""}))

    # ── Vendor-scoped endpoints ──────────────────────────────────────────
    item_uid: str | None = None
    if vend_token:
        r = record("create vendor item",
                   _hit(client, "POST", "/vendors/items", token=vend_token, body={
                       "name": f"Smoke item {suffix}",
                       "description": "Created by /debug/smoke-test",
                       "price": 49.5,
                       "category": "test",
                       "stock_quantity": 20,
                       "image_urls": [],
                       "is_available": True,
                   }))
        if r["ok"] and isinstance(r["body"], dict):
            item_uid = r["body"].get("uid")
        record("list vendor items",
               _hit(client, "GET", "/vendors/items", token=vend_token))
        record("list vendor orders",
               _hit(client, "GET", "/vendors/orders", token=vend_token))
        record("list inventory",
               _hit(client, "GET", "/inventory", token=vend_token))
        record("list low-stock",
               _hit(client, "GET", "/inventory/low-stock", token=vend_token))
        # Expect 404 when no subscription exists — still a "known" response.
        sub_me = _hit(client, "GET", "/subscriptions/me", token=vend_token)
        sub_me["ok"] = sub_me["status"] in (200, 404)
        record("vendor subscription (me)", sub_me)
        record("list khata ledgers",
               _hit(client, "GET", "/khata/ledgers", token=vend_token))

        if cust_uid:
            r = record("create khata ledger",
                       _hit(client, "POST", "/khata/ledgers",
                            token=vend_token, body={
                                "customer_id": cust_uid,
                                "customer_name": "Smoke Customer",
                            }))
            ledger_uid = r["body"].get("uid") if r["ok"] and isinstance(r["body"], dict) else None
            if ledger_uid:
                record("record khata transaction",
                       _hit(client, "POST", "/khata/transactions",
                            token=vend_token, body={
                                "ledger_id": ledger_uid,
                                "type": "credit",
                                "amount": 200,
                                "description": "Smoke credit",
                            }))
                record("list ledger transactions",
                       _hit(client, "GET", f"/khata/ledgers/{ledger_uid}/transactions",
                            token=vend_token))
                record("settle ledger",
                       _hit(client, "POST", f"/khata/ledgers/{ledger_uid}/settle",
                            token=vend_token))

        if item_uid:
            record("update vendor item",
                   _hit(client, "PUT", f"/vendors/items/{item_uid}",
                        token=vend_token, body={"price": 55.0}))
            record("update stock",
                   _hit(client, "PUT", f"/inventory/{item_uid}/stock",
                        token=vend_token, body={"quantity": 15}))
            record("bulk update stock",
                   _hit(client, "POST", "/inventory/bulk-update",
                        token=vend_token, body={
                            "items": [{"item_id": item_uid, "quantity": 10}],
                        }))
            record("get shop by id",
                   _hit(client, "GET", f"/shops/{item_uid}"))

            if cust_token:
                record("add favorite",
                       _hit(client, "POST", "/shops/favorites",
                            token=cust_token, body={"shop_item_id": item_uid}))
                record("check favorite",
                       _hit(client, "GET", f"/shops/favorites/{item_uid}/check",
                            token=cust_token))
                record("remove favorite",
                       _hit(client, "DELETE", f"/shops/favorites/{item_uid}",
                            token=cust_token))
                r = record("create order",
                           _hit(client, "POST", "/orders",
                                token=cust_token, body={
                                    "item_id": item_uid,
                                    "quantity": 1,
                                    "total_price": 55.0,
                                }))
                order_id = r["body"].get("order_id") if r["ok"] and isinstance(r["body"], dict) else None
                if order_id:
                    record("cancel order",
                           _hit(client, "POST", f"/orders/{order_id}/cancel",
                                token=cust_token))
                record("add review",
                       _hit(client, "POST", "/reviews",
                            token=cust_token, body={
                                "item_id": item_uid,
                                "vendor_id": vend_uid,
                                "rating": 4.5,
                                "comment": "Smoke review",
                            }))
                record("list item reviews",
                       _hit(client, "GET", f"/reviews/item/{item_uid}"))
                record("list vendor reviews",
                       _hit(client, "GET", f"/reviews/vendor/{vend_uid}"))

    # ── Admin-scoped endpoints ───────────────────────────────────────────
    if admin_token:
        record("admin stats",
               _hit(client, "GET", "/admin/stats", token=admin_token))
        record("admin vendors",
               _hit(client, "GET", "/admin/vendors", token=admin_token))
        record("admin customers",
               _hit(client, "GET", "/admin/customers", token=admin_token))
        r = record("admin create category",
                   _hit(client, "POST", "/shops/categories",
                        token=admin_token, body={"name": f"smoke-cat-{suffix}"}))
        if r["ok"] and isinstance(r["body"], dict):
            cat_uid = r["body"].get("uid")
            if cat_uid:
                record("admin delete category",
                       _hit(client, "DELETE", f"/shops/categories/{cat_uid}",
                            token=admin_token))
        r = record("admin create city",
                   _hit(client, "POST", "/cities", token=admin_token, body={
                       "name": f"Smoke City {suffix}",
                       "state": "ST",
                       "country": "IN",
                       "latitude": 12.97,
                       "longitude": 77.59,
                   }))
        if r["ok"] and isinstance(r["body"], dict):
            city_uid = r["body"].get("id") or r["body"].get("uid")
            if city_uid:
                record("admin update city",
                       _hit(client, "PUT", f"/cities/{city_uid}",
                            token=admin_token, body={"is_active": True}))
                record("get city by id",
                       _hit(client, "GET", f"/cities/{city_uid}"))
        if vend_uid:
            record("admin suspend vendor",
                   _hit(client, "POST", f"/admin/users/{vend_uid}/suspend",
                        token=admin_token))
            record("admin unsuspend vendor",
                   _hit(client, "POST", f"/admin/users/{vend_uid}/unsuspend",
                        token=admin_token))
        record("list all payments (admin)",
               _hit(client, "GET", "/payments/all", token=admin_token))

        # Cleanup: delete the smoke item now that all dependent tests ran.
        if item_uid and vend_token:
            record("delete vendor item",
                   _hit(client, "DELETE", f"/vendors/items/{item_uid}",
                        token=vend_token))

    # ── Logout ────────────────────────────────────────────────────────────
    if cust_token:
        record("logout customer",
               _hit(client, "POST", "/auth/logout", token=cust_token))

    passed = sum(1 for r in results if r.get("ok"))
    failures = [r for r in results if not r.get("ok")]
    return jsonify({
        "ok": passed == len(results),
        "passed": passed,
        "total": len(results),
        "failures": failures,
        "results": results,
    })
