# Requested workflow integration and release proof — 9 October 2026

The release adds customer Cash/UPI Khata payment requests with owner approval,
atomic daily customer chat limits, modern FCM device ownership, explicit cash
receipt confirmation, order bills, printable PDFs, vendor cash-order discounts,
and atomic Excel/CSV product imports. The mobile app uses Venkat's latest login,
hub and service discovery alongside these authenticated backend contracts.

## Local evidence

- Native Python unittest discovery: **299 tests passed**.
- Native Flask HTTP against the actual isolated loopback Firestore emulator:
  **204 assertions passed**. This exercises customer/owner permissions, pending
  Cash/UPI approval/rejection, idempotency, global chat limits, cash collection,
  fulfillment and durable inbox events, both-party invoices and actual PDF text,
  discounts and actual multipart CSV/XLSX preview/import/retry.
- Syntax compilation and `git diff --check` passed.
- Real Razorpay capture/refund, physical FCM delivery, and actual printing were
  not performed. Emulator transport uses no production credentials/providers.

Commands (from `app/backend`; emulator must already listen on loopback):

```sh
.venv/bin/python -m unittest discover -s tests
.venv/bin/python -m compileall -q main.py auth_utils.py notification_delivery.py routes scripts tests
FIRESTORE_EMULATOR_HOST=127.0.0.1:18080 GCLOUD_PROJECT=demo-localshop-verification \
  .venv/bin/python scripts/verify_emulator_journeys.py --output /tmp/localshop-local.json
```

`pdftotext` is required for the native PDF integration check. Production PDF
generation uses ReportLab for ASCII and WeasyPrint/Pango/Noto for Indian scripts.

## Deployment and data contract

Deploy backend before mobile build 8. Existing workflow validates tests, builds
an immutable commit-tagged image and deploys the Cloud Run service. Verify Ready,
100% serving traffic, matching image commit and `/features.release`, then run:

```sh
python scripts/verify_deployed.py --base-url "$SERVICE_URL" --phase release \
  --expected-release "$BACKEND_COMMIT" --output /tmp/localshop-deployed.json
```

These public/unauthenticated route checks are separate from authenticated
business journeys. Use only newly created scoped QA fixtures for live mutation
checks; remove precisely those fixtures and verify absence before handoff.

The new `device_tokens`, `chat_daily_usage`, and `product_imports` collections
are created lazily by authenticated backend transactions. No destructive
migration is required. Customer debit requests use `status=pending` and reserve
outstanding balance until owner approval/rejection. Financial balances change
only on approval; UPI marking is not proof of gateway capture. Discounts apply
only to uncollected cash orders; product import creates products and does not
overwrite existing SKUs. See `app/backend/README.md` for endpoint contracts.

Keep the prior immutable serving image/revision for recovery. The previous
revision was `grocery-backend-00299-sfv`. Prefer a forward repair if pending
payment requests already exist: rollback removes the approval endpoints and
must not be represented as restoring a complete customer payment workflow.
Retain ledgers/payment/inbox records; do not reset balances or payment states.
Investigate Cloud Run startup/errors and durable inbox behavior after release;
FCM is best effort after commit, with no background retry worker. Existing
released clients retain their request contracts. New UI requires the new build.

Deployment identity and live test results are recorded in the parent project's
dated feature verification report after actual deployment, rather than inferred
from a successful image build.
