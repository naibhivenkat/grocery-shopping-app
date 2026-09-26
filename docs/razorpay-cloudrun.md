# Razorpay on the existing Cloud Run backend

The installed app's payment service has a fixed Firebase URL, so requests to
`/razorpayApi/orders` and `/razorpayApi/verify` must keep that URL alive until
the app can be updated. Payment creation, signature verification, settlement,
and webhook validation now belong to the existing Cloud Run service. The two
Firebase HTTP functions are temporary transport bridges without Razorpay or
JWT secrets attached.

## Request and data flow

1. The app sends its existing bearer session token to the Firebase compatibility
   URL.
2. `razorpayApi` forwards `/orders` and `/verify` to Cloud Run, preserving the
   bearer token and response status/body.
3. Cloud Run authenticates with the existing `require_auth` decorator. It uses
   the existing Razorpay secrets, creates records in
   `localshop/v1/payment_orders`, and verifies signatures server-side.
4. Wallet settlement updates `wallets` and writes one
   `wallet_transactions/razorpay_<intent-id>` entry atomically. Service payments
   settle the intent before the app calls its existing booking-confirm endpoint.
5. The existing Razorpay webhook URL is preserved. Its Firebase bridge relays
   the raw request body and signature to Cloud Run, where signature validation
   and idempotent settlement run.

The Cloud Run deploy workflow syncs `JWT_SECRET`, `RAZORPAY_KEY_ID`,
`RAZORPAY_KEY_SECRET`, and `RAZORPAY_WEBHOOK_SECRET` from GitHub Actions secrets
to Secret Manager. `RAZORPAY_BACKEND_URL` on the Firebase bridge is optional;
the code defaults to the current production Cloud Run URL.

## Deployment order

1. Push the backend repository branch. Its existing GitHub Actions workflow
   deploys the changed Flask API to Cloud Run. Confirm the workflow succeeds.
2. From the parent app repository, deploy only the bridge functions:

   ```sh
   firebase deploy --only functions:razorpayApi,functions:razorpayWebhook --project groceryapp-fe2ec --non-interactive
   ```

   These bridge exports do not bind Secret Manager secrets, avoiding the
   `secretmanager.secrets.setIamPolicy` failure from the previous deployment.
3. Keep the existing Razorpay webhook URL in the Razorpay dashboard. It does
   not change.

## Smoke checks and rollback

- Confirm the Cloud Run health endpoint returns HTTP 200.
- `GET https://asia-south1-groceryapp-fe2ec.cloudfunctions.net/razorpayApi`
  should return HTTP 404 for the unknown route; this alone is not proof of
  checkout readiness.
- An unauthenticated `POST .../razorpayApi/orders` should return JSON HTTP 401,
  not the previous HTML HTTP 404.
- Complete one low-value authorized payment and confirm the payment intent,
  wallet balance/ledger or booking confirmation, then check for duplicate
  credits after webhook delivery.
- If the backend deploy fails, the prior Cloud Run revision remains available.
  If the bridge deploy fails, the prior Firebase function revision remains
  available. Do not disable the Razorpay webhook while either deploy is being
  rolled back.

Live payment settlement is not considered verified until a real authorized
payment and its webhook have both been observed. Never log or commit provider
secrets.
