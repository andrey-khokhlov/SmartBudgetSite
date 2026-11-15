"""Run one bounded refund request receipt recovery pass."""

import argparse
import json
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        from app.core.db import SessionLocal
        from app.services.refund_request_receipt_service import (
            recover_refund_request_receipts,
        )

        with SessionLocal() as db:
            result = recover_refund_request_receipts(db, dry_run=args.dry_run)
    except Exception:
        print(
            json.dumps({"error": "refund_request_receipt_recovery_failed"}),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
