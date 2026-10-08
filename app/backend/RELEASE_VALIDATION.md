# Backend release validation — 9 October 2026

The release repairs the existing REST contract and adds free, moderated shop/product promotions. Wallet use is temporarily disabled. Razorpay orders, capture settlement, and refunds remain server-authoritative. The next Android build will call Cloud Run directly at `/razorpayApi`, avoiding an undeployed Firebase Functions URL.

## Deployment identity

- Cloud project: `grocery-backend-476417`
- Cloud Run service: `grocery-backend`, region `asia-south1`
- Client API: `https://grocery-backend-956424262985.asia-south1.run.app`
- Firebase data/auth/storage project: `groceryapp-fe2ec`
- Storage bucket: `groceryapp-fe2ec.firebasestorage.app`, `asia-south1`
- Deployment branch: `backend-branch`. The repository's `main` branch is unrelated to the active backend source.

The GitHub workflow validates Python before building an image tagged with the source commit. Cloud Run exposes that commit through `/features.release`. Existing environment configuration is preserved, secrets remain Secret Manager references, and previous images are retained for rollback.

## Changes and contracts

| Feature | Behavior |
| --- | --- |
| Authentication | Stored account roles and suspension govern access; missing accounts fail closed. Password reset invalidates older sessions. New password/Google accounts reserve email and username atomically. OTP consumption and account creation commit together. |
| Orders/inventory | Server prices and integer stock are authoritative. A batch reserves stock atomically; request replay is deduplicated. Cancellation restores stock once. Admin-disabled products remain unavailable through stock edits, cancellations, and refunds. |
| Khata | Vendors open ledgers and confirm transactions. Customers can view their own balances, but cannot claim repayments or settle debt. Service accounts retain their chat/referral features without wallet rewards. Money uses paise; ledger and transaction changes commit together. Khata orders and cancellation reversals update the same ledger atomically. |
| Razorpay | Amounts derive from owned order/booking references. Capture details and signatures are verified. Duplicate callbacks cannot double settle, and failure callbacks cannot undo captured payments. The owner-only intent reconciliation endpoint reads provider capture status without charging/refunding and supports recovery without the Firebase webhook bridge; SDK network calls are bounded. Historic wallet intents can reconcile without permitting new wallet use. |
| Refunds | `POST /vendors/orders/{id}/refund` returns accurate completed/submitted/processing/retryable/requires_review states. Refund requests use stable provider idempotency and fenced leases. Real provider capture is verified; stock restoration happens once. |
| Wallet | `/wallet*` and `/service-wallet*` return HTTP 410 `WALLET_DISABLED`. New order wallet payments are disabled. Historic balances are retained. |
| Promotions | Vendors submit owned shop/product promotions for moderation. Content edits require reapproval, and moderation requires the reviewed revision. Public feeds show approved active campaigns and suppress unavailable targets. Promotions are free; no digital advertising payment is collected. |
| Services | Active provider/service checks, consistent server quotes, private addresses/current-city settings, read-only public calendars, protected booked slots, and atomic booking earnings. Confirmation requires a verified paid intent. |
| Media | `POST /media/images`: vendor/service JWT, multipart field `file`, JPEG/PNG/WebP only, maximum 5 MiB and 16 MP. Actual decoding, metadata removal, re-encoding, and UUID paths prevent client-selected ownership/path writes. Storage SDK client access remains denied; catalog images use download-token URLs. |
| Admin/referrals | Ordinary admins cannot grant roles or manage privileged accounts. User mutations and audits commit together. Missing records are never fabricated. Referral issuance/application are atomic; disabled wallets receive no rewards. |
| Support | Durable Gmail replies preserve threading and reconcile ambiguous sends instead of repeating them. Pub/Sub payloads and cursors are validated; Support-label ingestion is paginated and deduplicated. Initial recovery is explicitly limited to the latest 100 support messages. |

New digital subscription Razorpay checkout returns `BILLING_REQUIRED`. Android must hide external digital subscription purchasing until Play Billing is implemented. Physical goods/services can use Razorpay under Google's payments policy: https://support.google.com/googleplay/android-developer/answer/9858738

## Evidence

- Python suite: 256 tests passed before deployment, including strict transaction mocks and real image decoding.
- Native Flask HTTP + actual loopback Firestore emulator: 99 checks passed, including signup, stock reservation/cancellation, khata, moderation, reviews, chat, referrals, and booking validation. No production data or payment/email providers were contacted.
- Firestore rules emulator: 26 assertions passed. The deployed rules preserve the previous access model and replace only three publicly writable configuration collections with admin writes.
- Firebase Storage was created with private default rules; the same policy was deployed from `storage.rules`.
- Firebase Node 22 bridge: all six function exports load, nine unit tests pass, production npm audit reports zero vulnerabilities. Bridge deployment remains unavailable to the current Editor account because HTTPS function IAM permission is missing. The new Android release uses Cloud Run directly.

Local/mocked/emulator evidence does not prove live captures, refunds, Google sign-in on a Play-installed build, OTP delivery, Gmail delivery, or successful Android rollout. Each requires separate recorded evidence.

## Reproduce

From `app/backend`:

```sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m compileall -q main.py auth_utils.py routes tests scripts
.venv/bin/python scripts/verify_deployed.py --phase release --output deployed-proof.json
```

The deployed probe uses public GETs and unauthenticated boundary checks. It never registers users, creates orders, charges money, or invokes the old mutating smoke endpoint. It first verifies backend contract version 2 before any smoke-disabled check.

The emulator journey harness refuses any non-demo project or non-loopback Firestore host. Run it with Firebase `emulators:exec`, the `demo-localshop-validation` project, and a loopback emulator configuration. The harness starts and terminates its own native Flask process.

## Runtime requirements and release gate

Existing Cloud Run configuration includes names for Firebase credentials, Brevo OTP delivery, Gmail OAuth, JWT, Razorpay, and webhook secrets. Presence of names alone does not prove credentials/provider behavior. Gmail automation additionally needs a Support label, watch/PubSub configuration, and a sync trigger; manual admin sync is implemented.

Verify the ready Cloud Run revision and traffic, the immutable source image tag, `/features.release`, public/boundary probes from the Mac, and isolated authenticated QA journeys after deployment. Only then integrate Android promotions, provider setup, media uploads, wallet removal, refunds, and the direct payment URL, build the signed AAB, and validate Play Console before rollout.

## Rollback

The previously verified revision was `grocery-backend-00297-hz8`. If a new revision fails startup or the live contract checks, use Cloud Run traffic rollback while diagnosing:

```sh
gcloud run services update-traffic grocery-backend --project=grocery-backend-476417 --region=asia-south1 --to-revisions=grocery-backend-00297-hz8=100
```

Rollback restores the old implementation and its limitations. It is not completion of this release.
