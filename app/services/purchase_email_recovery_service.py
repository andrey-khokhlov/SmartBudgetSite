from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.core.config import settings
from app.repositories.lava_top_payment_recovery_repository import lock_recovery_pass
from app.repositories.purchase_email_delivery_repository import read_due_email_recovery
from app.services.email_transport import EmailTransport
from app.services.purchase_email_delivery_service import (
    attempt_purchase_email_delivery,
    purchase_email_recovery_cutoffs,
)
from app.services.resend_email_transport import ResendEmailTransport

MAX_DELIVERIES_PER_PASS = 20
EMAIL_RECOVERY_LOCK_ID = 812194340103


def run_purchase_email_recovery(
    db: Session,
    *,
    dry_run: bool = False,
    transport: EmailTransport | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict:
    """Run a single bounded pass on a fresh PostgreSQL session."""
    engine = db.get_bind()
    if not isinstance(engine, Engine) or db.in_transaction():
        raise RuntimeError("Recovery requires a fresh engine-bound session.")

    allow_sends = transport is not None or settings.PURCHASE_EMAIL_DELIVERY_ENABLED
    with lock_recovery_pass(engine, lock_id=EMAIL_RECOVERY_LOCK_ID) as acquired:
        if not acquired:
            return {"status": "already_running", "processed": 0}
        with db.begin():
            due, candidates = read_due_email_recovery(
                db,
                purchase_email_recovery_cutoffs(
                    clock(), allow_sends=dry_run or allow_sends
                ),
                limit=MAX_DELIVERIES_PER_PASS,
            )
        results: Counter[str] = Counter()
        if not dry_run:
            sender = transport or ResendEmailTransport()
            for candidate in candidates:
                try:
                    result = attempt_purchase_email_delivery(
                        db,
                        sale_id=candidate.sale_id,
                        transport=sender,
                        clock=clock,
                        recovery_allow_sends=allow_sends,
                    )
                except Exception:
                    db.rollback()
                    raise
                results[result.value] += 1
    return {
        "status": "dry_run" if dry_run else "completed",
        "sending_enabled": allow_sends,
        "due": due,
        "selected": len(candidates),
        "selected_for_reconciliation": sum(row.expired for row in candidates),
        "processed": sum(results.values()),
        "deferred": due - len(candidates),
        "by_result": dict(results),
    }
