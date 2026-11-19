"""Run bounded purchase delivery and consultation capacity alert passes."""

import argparse
import json
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        from app.core.db import SessionLocal
        from app.services.consultation_capacity_alert_service import (
            dispatch_consultation_capacity_alerts,
        )
        from app.services.purchase_alert_dispatcher_service import (
            dispatch_purchase_alerts,
        )
    except Exception:
        print(json.dumps({"error": "purchase_alert_dispatch_failed"}), file=sys.stderr)
        return 1

    results = {}
    failed = False
    for name, dispatch in (
        ("purchase_alert", dispatch_purchase_alerts),
        ("consultation_capacity", dispatch_consultation_capacity_alerts),
    ):
        try:
            with SessionLocal() as db:
                results[name] = dispatch(db, dry_run=args.dry_run)
        except Exception:
            failed = True
            results[name] = {"status": "error"}
            print(json.dumps({"error": f"{name}_dispatch_failed"}), file=sys.stderr)
    print(
        json.dumps(
            {
                **results["purchase_alert"],
                "consultation_capacity": results["consultation_capacity"],
            },
            sort_keys=True,
        )
    )
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
