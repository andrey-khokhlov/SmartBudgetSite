"""Run one local purchase delivery monitoring pass."""

import json
import sys


def main() -> int:
    try:
        from app.core.db import SessionLocal
        from app.services.purchase_delivery_monitoring_service import (
            scan_purchase_delivery,
        )

        with SessionLocal() as db:
            summary = scan_purchase_delivery(db)
    except Exception:
        # Configuration and database exceptions can contain sensitive values.
        print(
            json.dumps({"error": "purchase_delivery_monitoring_failed"}),
            file=sys.stderr,
        )
        return 1

    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
