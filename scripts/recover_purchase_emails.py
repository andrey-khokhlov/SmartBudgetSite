"""Run one bounded purchase-email recovery pass."""

import argparse
import json
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        from app.core.db import SessionLocal
        from app.services.purchase_email_recovery_service import (
            run_purchase_email_recovery,
        )

        with SessionLocal() as db:
            summary = run_purchase_email_recovery(db, dry_run=args.dry_run)
    except Exception:
        print(json.dumps({"error": "purchase_email_recovery_failed"}), file=sys.stderr)
        return 1
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
