# LocalShop Finder Backend

Flask REST API that backs the `lib/features/**/data/datasources/*.dart`
clients of the LocalShop Finder Flutter app. All data lives in Firestore
under `localshop/v1/<collection>` (same path the Flutter `FirebaseConstants`
reads from).

## Endpoints

Every path called by the Flutter client is implemented. See `routes/` for
the source of each blueprint:

| Area        | Blueprint                | Paths                                                                  |
|-------------|--------------------------|------------------------------------------------------------------------|
| Auth        | `routes/auth.py`         | `POST /auth/login` `POST /auth/register` `POST /auth/logout` `GET /auth/me` `GET /auth/role` |
| Shops       | `routes/shops.py`        | `GET /shops` `GET /shops/<id>` `GET/POST /shops/categories` `DELETE /shops/categories/<id>` `POST/GET /shops/favorites` `DELETE /shops/favorites/<id>` `GET /shops/favorites/<id>/check` `POST/GET /orders` `POST /orders/<id>/cancel` |
| Vendors     | `routes/vendors.py`      | `GET/POST /vendors/items` `PUT/DELETE /vendors/items/<id>` `GET /vendors/orders` `PUT /vendors/orders/<id>/status` |
| Cities      | `routes/cities.py`       | `GET /cities` `GET /cities/<id>` `GET /cities/current/<user_id>` `PUT /cities/current` `POST /cities` `PUT /cities/<id>` |
| Admin       | `routes/admin.py`        | `GET /admin/stats` `GET /admin/vendors` `GET /admin/customers` `POST /admin/users/<id>/suspend` `POST /admin/users/<id>/unsuspend` |
| Profile     | `routes/profile.py`      | `GET /profile` `PUT /profile` |
| Chat        | `routes/chat.py`         | `GET/POST /chat/rooms` `GET/POST /chat/rooms/<id>/messages` |
| Notifications | `routes/notifications.py` | `GET /notifications` `POST /notifications/<id>/read` `POST /notifications/read-all` |
| Subscriptions | `routes/subscriptions.py` | `GET /subscriptions/plans` `GET /subscriptions/me` `POST /subscriptions/subscribe` |
| AI          | `routes/ai.py`           | `GET /ai/summary` `POST /ai/budget-plan` |
| Referrals   | `routes/referrals.py`    | `POST /referrals/generate` `POST /referrals/apply` `GET /referrals` |
| Inventory   | `routes/inventory.py`    | `GET /inventory` `PUT /inventory/<id>/stock` `POST /inventory/bulk-update` `GET /inventory/low-stock` |
| Reviews     | `routes/reviews.py`      | `POST /reviews` `GET /reviews/item/<id>` `GET /reviews/vendor/<id>` |
| Payments    | `routes/payments.py`     | `POST /payments` `GET /payments` `GET /payments/all` `POST /payments/<id>/verify` `POST /payments/<id>/reject` |
| Wallet      | `routes/wallet.py`       | `GET /wallet` `GET /wallet/transactions` `POST /wallet/credit` `POST /wallet/deduct` |
| Khata       | `routes/khata.py`        | `GET/POST /khata/ledgers` `GET /khata/ledgers/<id>/transactions` `POST /khata/transactions` `POST /khata/ledgers/<id>/settle` |

All authenticated endpoints expect `Authorization: Bearer <jwt>` — the token
returned by `/auth/login` or `/auth/register`.

## Environment

Required:
- `GOOGLE_APPLICATION_CREDENTIALS` — path to a Firebase service-account JSON
  file (omit to use gcloud application-default credentials, e.g. on Cloud
  Run).
- `JWT_SECRET` — secret for signing session tokens. Must be set in
  production.

Optional:
- `PORT` (default `8000`).
- `JWT_EXPIRE_DAYS` (default `30`).
- `FLASK_DEBUG=1` to enable Flask's debug reloader.

## Local development

```bash
cd backend/grocery-shopping-app/app/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export GOOGLE_APPLICATION_CREDENTIALS=/absolute/path/to/serviceAccount.json
export JWT_SECRET=local-dev-only
python main.py        # http://localhost:8000
```

The Flutter app is preconfigured to call `http://10.0.2.2:8000` (the Android
emulator alias for localhost) — see `env.json`.

## Running with gunicorn

```bash
gunicorn --bind :8000 --workers 2 --threads 8 main:app
```

## Docker

```bash
docker build -t localshop-backend .
docker run --rm -p 8000:8000 \
  -e JWT_SECRET=change-me \
  -v /absolute/path/to/serviceAccount.json:/secret.json \
  -e GOOGLE_APPLICATION_CREDENTIALS=/secret.json \
  localshop-backend
```

## Firestore layout

The backend reads and writes under a single root path, matching the Flutter
`FirebaseConstants`:

```
localshop/
  v1/
    users/             # with fields: email, password_hash, role, full_name, ...
    cities/
    shop_items/
    categories/
    customer_orders/
    user_favorites/
    vendor_subscriptions/
    subscription_plans/
    subscription_payments/
    reviews/
    chat_rooms/
    messages/
    referrals/
    ai_summaries/
    wallets/
    wallet_transactions/
    notifications/
    khata_ledgers/
    khata_transactions/
```

## Notes

- Password hashing uses PBKDF2-HMAC-SHA256 (`auth_utils.hash_password`). The
  backend owns its own credentials in the `users` collection — it does not
  rely on Firebase Auth for password verification.
- Orphaned legacy modules from the prior grocery-shopping-app (e.g.
  `firebase_db.py`, `khata.py`, `service_*.py`, `wallet_routes.py`) remain
  in the directory but are no longer imported by `main.py`. They can be
  deleted when convenient.
