# AllLocal backend release readiness

This release implements the defined customer/vendor/admin backlog: measured pricing, shop applications, grouped checkout/recovery, one eligible promotion, customer-approved order amendments, original-payment refund jobs, selected invoices, advertisements, and non-order notifications. Service Module requirements remain explicitly deferred by the user.

## Pre-release evidence

- Full native backend suite: 390 passing tests; 23 amendment regressions.
- Native Flask HTTP plus an actual loopback Firestore emulator: 259/259 checks passed against an isolated demo project, including measured units, selected discounts/invoices, partial availability, consent, substitutions, administrator deletion protection, manual repayment and legacy review guards. Harness safety checks: 4 passed. Emulator stopped and closed port verified. No production credentials, provider requests or production data were used.
- Independent release review reproduced and corrected two gaps: administrator product deletion could remove a reserved new product; legacy unbatched orders could lose the payment-review guard after proposal withdrawal.
- Administrator and vendor deletion now respect active proposals and retained stock reservations. Legacy raw order IDs and invoice ownership remain intact while the synthetic batch reference is persisted atomically.
- Git patch check passes. The deployment pipeline installs pinned requirements and reruns the complete suite before building the immutable image. The deployed verifier now requires its exact source revision, not just HTTP health.

## Deployment and rollback

Deploy this backend before distributing the updated client. Preserve all existing Secret Manager references, provider secrets, service identity, disabled-wallet policy and Firebase project. New collections/fields are additive; no destructive migration or provider-secret rotation is required.

Before deployment the live service is grocery-backend in grocery-backend-476417 / asia-south1, serving revision grocery-backend-00300-lfb and release2276d12f38ca0061355bd152feea3046d6f66321. Retain that immutable image/revision for traffic rollback. Deployment itself does not alter customer records. Firestore is in groceryapp-fe2ec / asia-south2; PITR is currently disabled and no database export is claimed by this change. An application rollback cannot undo any subsequently accepted financial amendments or actual provider refunds; retain all audits/capture quotas and reconcile them before restoring older financial behavior.

Post-deploy run scripts/verify_deployed.py with --phase release --expected-release matching this commit. These probes are read-only public/auth-boundary checks, not authenticated business or provider proof. Keep live production business validation read-only; do not create customers/orders, send real mail/push, charge or refund as a smoke test.

Refund first attempts are dispatched after durable jobs commit. Pending/submitted/retryable refunds require explicit reconciliation/retry; there is no automatic scheduler. Expiry cleanup is lazy on proposal/history reads. Genuine capture/inventory ambiguity preserves payment_review_required. No blind duplicate charge/refund is allowed.

Gmail may still need authorized mailbox reauthentication. Live provider callbacks/refunds, FCM delivery, physical printing, real Firestore contention and device journeys require separate evidence.
