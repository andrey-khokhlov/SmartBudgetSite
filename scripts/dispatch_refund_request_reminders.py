"""Run one bounded refund request deadline reminder pass."""

import argparse
import json
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        from app.core.db import SessionLocal
        from app.services.refund_request_reminder_service import (
            dispatch_refund_request_reminders,
        )

        with SessionLocal() as db:
            result = dispatch_refund_request_reminders(db, dry_run=args.dry_run)
    except Exception:
        print(
            json.dumps({"error": "refund_request_reminder_dispatch_failed"}),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
