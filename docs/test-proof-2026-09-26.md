# Test proof — 2026-09-26

Environment: local macOS workspace; backend repository submodule at the
current `backend-branch` checkout. Razorpay live credentials and production
payment fixtures were not used.

| Scope | Command | Result |
| --- | --- | --- |
| Python syntax | `python3 -m compileall -q app/backend` | Passed. |
| Firebase bridge syntax | `node --check ../../functions/index.js` | Passed. |
| Existing Razorpay signature utilities | `node --test ../../functions/test/razorpay_utils.test.js` | 3 passed, 0 failed. |
| New backend amount tests | `PYTHONPATH=app/backend python3 -m unittest discover -s app/backend/tests -v` | Could not run: local Python lacks Flask (`ModuleNotFoundError`). |

## Not executed

- Backend Python unit tests require the backend's declared dependencies.
- Cloud Run deployment, authenticated order creation, Razorpay signature
  verification, Firestore settlement, and webhook delivery were not run in
  production during this local validation.
- Firebase bridge deployment and its live HTTP smoke checks were not run.

The rollout is verified only after the Cloud Run workflow and Firebase bridge
deployment both succeed and a low-value real payment settles once in the
wallet/booking flow.
