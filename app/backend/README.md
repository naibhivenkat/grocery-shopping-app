# LocalShop Finder Backend

Flask REST API that backs the authenticated LocalShop Finder clients. All
data lives in Firestore
under `localshop/v1/<collection>` (same path the Flutter `FirebaseConstants`
reads from).

## Endpoints

Every path called by the Flutter client is implemented. See `routes/` for
the source of each blueprint:

| Area        | Blueprint                | Paths                                                                  |
|-------------|--------------------------|------------------------------------------------------------------------|
| Auth        | `routes/auth.py`         | `POST /auth/send_otp` `POST /auth/verify_otp` `POST /auth/register_after_otp` `POST /auth/login` `POST /auth/forgot_password` `POST /auth/reset_password` `POST /auth/register` `POST /auth/logout` `GET /auth/me` `GET /auth/role` |
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
| Services    | `routes/services.py` `routes/provider_profiles.py` | `GET/PUT /provider/profile` `POST/PUT/DELETE /provider/services/<id>` `GET /provider/services` `GET /providers/<id>/services` `GET /services/available` |
| Bookings    | `routes/availability.py` `routes/bookings.py` | `GET /provider/availability` `PUT /provider/availability` `GET /providers/<id>/availability` `POST /bookings/create-pending` `POST /bookings/<id>/confirm|accept|reject|start|complete|cancel` `GET /bookings` `GET /provider/bookings` |
| Service wallet | `routes/service_wallet.py` | `GET /service-wallet` `GET /service-wallet/transactions` `POST /service-wallet/withdraw` |
| Support Center | `routes/support.py`, `routes/gmail_admin.py` | `GET /admin/support` `GET /admin/support/<id>` `POST /admin/support/<id>/reply` `POST /admin/support/<id>/notes` `POST /admin/support/webhook` `POST /admin/support/sync` plus admin-only Gmail read/send/attachment endpoints |

All authenticated endpoints expect `Authorization: Bearer <jwt>` — the token
returned by `/auth/login` or `/auth/register`.

## Environment

Required:
- `FIREBASE_CREDENTIALS_JSON` — full Firebase service-account JSON for Cloud
  Run/Secret Manager deployments. This must be from the Firebase project used
  by the Flutter app (`groceryapp-fe2ec`), otherwise Firestore calls will use
  the Cloud Run project instead.
- `GOOGLE_APPLICATION_CREDENTIALS` — path to a Firebase service-account JSON
  file for local/dev environments. Omit only when intentionally using
  application-default credentials.
- `JWT_SECRET` — secret for signing session tokens. Must be set in
  production.

Optional:
- `PORT` (default `8000`).
- `JWT_EXPIRE_DAYS` (default `30`).
- `FIREBASE_PROJECT_ID` — explicit project ID when using application-default
  credentials.
- `FIREBASE_STORAGE_BUCKET` — optional default bucket for legacy storage
  helpers.
- `SENDINBLUE_API_KEY` and `FROM_EMAIL` — enables registration OTP emails via
  Brevo/Sendinblue. If omitted, OTP codes are logged only.
- `SMTP_HOST`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_SENDER`, `SMTP_PORT` —
  SMTP fallback for registration OTP emails.
- `AUTH_OTP_TTL_MINUTES` (default `10`).
- `AUTH_OTP_DEBUG_RESPONSE=1` — includes OTP in the JSON response for local
  debugging only. Do not enable in production.
- `FLASK_DEBUG=1` to enable Flask's debug reloader.
- `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, and `RAZORPAY_WEBHOOK_SECRET` —
  required for payment creation, signature verification, refunds, and the
  `POST /webhooks/razorpay` endpoint. Store these in Secret Manager or the
  Cloud Run environment; never commit them or return the secret to clients.
- `ENABLE_LEGACY_ROUTES=1` only for a controlled migration of older
  client-supplied-ID service routes; leave unset in production.
- `WEBHOOK_SECRET` — required by the authenticated Support Center webhook;
  store it in Secret Manager and send it as `X-Webhook-Secret`.
- `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and `GOOGLE_REFRESH_TOKEN` —
  optional Gmail OAuth credentials for Support Center sync and mail actions.
  Missing or invalid credentials fail closed with `503`.

## Cloud Run deployment and Secret Manager

The deployment workflow passes these Secret Manager references to Cloud Run:

```text
FIREBASE_CREDENTIALS_JSON
SENDINBLUE_API_KEY
FROM_EMAIL
JWT_SECRET
RAZORPAY_KEY_ID
RAZORPAY_KEY_SECRET
RAZORPAY_WEBHOOK_SECRET
WEBHOOK_SECRET
```

Every referenced secret must already exist in the same GCP project used by the
deployment. If Cloud Run reports `secret ... was not found`, create the missing
secret and add at least one version before retrying. For the failure reported
by the latest deployment, the missing names were:

```text
JWT_SECRET
RAZORPAY_KEY_ID
RAZORPAY_KEY_SECRET
RAZORPAY_WEBHOOK_SECRET
WEBHOOK_SECRET
```

The GitHub Actions deployment now handles these five secrets automatically.
Before pushing backend changes, add the following repository-level GitHub
Actions Secrets under **Settings → Secrets and variables → Actions**:

```text
JWT_SECRET
RAZORPAY_KEY_ID
RAZORPAY_KEY_SECRET
RAZORPAY_WEBHOOK_SECRET
WEBHOOK_SECRET
```

The workflow validates that each value exists, creates the corresponding
Secret Manager secret when necessary, and adds a new version before deploying
Cloud Run. The GitHub Actions service account therefore needs permission to
create and version secrets (`roles/secretmanager.admin`, or an equivalent
custom role); the Cloud Run runtime service account still needs
`roles/secretmanager.secretAccessor`.

Create empty Secret Manager containers first, if needed:

```bash
PROJECT_ID="your-gcp-project-id"

for NAME in \
  JWT_SECRET \
  RAZORPAY_KEY_ID \
  RAZORPAY_KEY_SECRET \
  RAZORPAY_WEBHOOK_SECRET \
  WEBHOOK_SECRET; do
  gcloud secrets describe "$NAME" --project="$PROJECT_ID" >/dev/null 2>&1 || \
    gcloud secrets create "$NAME" \
      --replication-policy=automatic \
      --project="$PROJECT_ID"
done
```

Add versions without putting values in source control or in the deploy command.
Replace the example values only in your local shell:

```bash
printf '%s' 'replace-with-a-long-random-jwt-secret' |
  gcloud secrets versions add JWT_SECRET --data-file=- --project="$PROJECT_ID"

printf '%s' 'replace-with-razorpay-key-id' |
  gcloud secrets versions add RAZORPAY_KEY_ID --data-file=- --project="$PROJECT_ID"

printf '%s' 'replace-with-razorpay-key-secret' |
  gcloud secrets versions add RAZORPAY_KEY_SECRET --data-file=- --project="$PROJECT_ID"

printf '%s' 'replace-with-razorpay-webhook-secret' |
  gcloud secrets versions add RAZORPAY_WEBHOOK_SECRET --data-file=- --project="$PROJECT_ID"

printf '%s' 'replace-with-support-webhook-secret' |
  gcloud secrets versions add WEBHOOK_SECRET --data-file=- --project="$PROJECT_ID"
```

Use a JWT secret of at least 32 characters in production. Razorpay values must
come from the same Razorpay account configured for the mobile checkout, and
`WEBHOOK_SECRET` must match the value sent in the `X-Webhook-Secret` header.
Do not commit these values or print them in CI logs.

The Cloud Run runtime service account also needs Secret Manager access. Grant
`roles/secretmanager.secretAccessor` to that service account for the project,
then verify the references before retrying:

```bash
for NAME in JWT_SECRET RAZORPAY_KEY_ID RAZORPAY_KEY_SECRET \
  RAZORPAY_WEBHOOK_SECRET WEBHOOK_SECRET; do
  gcloud secrets describe "$NAME" --project="$PROJECT_ID" \
    --format='value(name)'
done
```

Razorpay webhooks are idempotent for captured/paid/failed events. A captured
service payment also transitions its pending booking to `confirmed` when the
payment order contains `booking_id`.

Customer wallet recharge is intentionally not implemented by the Flask
`/wallet/recharge/*` aliases: they return `410 Gone`. The production mobile
checkout creates and verifies Razorpay orders through the Firebase
`razorpayApi` Function, and its webhook performs the wallet settlement. This
keeps a client from converting an unverified local intent into wallet credit.

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
