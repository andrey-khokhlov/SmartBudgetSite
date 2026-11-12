"""Resolve one operator-required purchase delivery incident."""

import argparse
import json
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--incident-id", required=True, type=int)
    parser.add_argument("--operator", required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args(argv)
    try:
        from app.core.db import SessionLocal
        from app.services.purchase_delivery_monitoring_service import (
            resolve_operator_incident,
        )

        with SessionLocal() as db:
            resolved = resolve_operator_incident(
                db,
                incident_id=args.incident_id,
                operator=args.operator,
                reason=args.reason,
                confirmed=args.confirm,
            )
    except ValueError:
        print(json.dumps({"error": "invalid_resolution"}), file=sys.stderr)
        return 1
    except Exception:
        print(json.dumps({"error": "incident_resolution_failed"}), file=sys.stderr)
        return 1
    if not resolved:
        print(json.dumps({"error": "incident_not_open_for_operator"}), file=sys.stderr)
        return 1
    print(json.dumps({"status": "resolved"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
