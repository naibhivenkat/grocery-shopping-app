#!/usr/bin/env python3
"""One bounded Play RTDN/acknowledgement recovery pass. No charges/refunds.

Run as a trusted Cloud Run Job or scheduled service identity. The process uses
ADC; no user credentials or purchase tokens are printed or accepted on the CLI.
"""
import argparse
import json
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--budget-seconds", type=int, default=90)
    args = parser.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from google_play_billing import PlayBillingError, PlayConfig
    try:
        config = PlayConfig.from_env()
        import firebase_admin
        if not firebase_admin._apps:
            firebase_admin.initialize_app()
        from routes.google_play import reconcile_google_play
        result = reconcile_google_play(limit=args.limit, budget_seconds=args.budget_seconds, config=config)
        print(json.dumps(result, sort_keys=True))
        return 0
    except PlayBillingError as exc:
        print(json.dumps({"code": exc.code, "detail": exc.detail, "status": exc.status}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
