"""Run one automatic Lava.top payment recovery pass."""

import json
import sys


def main() -> int:
    try:
        from app.core.db import SessionLocal
        from app.services.lava_top_payment_recovery_service import (
            run_lava_top_payment_recovery,
        )

        with SessionLocal() as db:
            summary = run_lava_top_payment_recovery(db)
    except Exception:
        print(
            json.dumps({"error": "lava_top_payment_recovery_failed"}), file=sys.stderr
        )
        return 1

    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
