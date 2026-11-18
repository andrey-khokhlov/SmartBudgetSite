"""Run one bounded pass to revoke expired Calendly Shares."""

import argparse
import json
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        from app.core.db import SessionLocal
        from app.services.calendly.share_revocation_service import revoke_expired_shares

        with SessionLocal() as db:
            summary = revoke_expired_shares(db, dry_run=args.dry_run)
    except Exception:
        print(json.dumps({"error": "calendly_share_revocation_failed"}), file=sys.stderr)
        return 1
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
