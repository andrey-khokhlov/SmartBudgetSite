from collections import Counter
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.refund_request_notification import RefundRequestNotification
from app.repositories.lava_top_payment_recovery_repository import lock_recovery_pass
from app.repositories.refund_request_repository import (
    lock_request_notifications,
    read_notification_candidates,
)
from app.services.purchase_alert_transport import send_smtp_alert, send_telegram_alert

MAX_REQUESTS = 20
SEND_LEASE = timedelta(minutes=2)
DISPATCH_LOCK_ID = 812194340105
RETRY_MINUTES = (1, 2, 5, 15, 30, 60)
MAX_ATTEMPTS = 1 + len(RETRY_MINUTES)


def _due(row: RefundRequestNotification, now: datetime) -> bool:
    scheduled = row.next_attempt_at
    if scheduled.tzinfo is None:
        scheduled = scheduled.replace(tzinfo=UTC)
    return scheduled <= now


def _record_failure(
    row: RefundRequestNotification, outcome: str, now: datetime
) -> None:
    row.last_error = outcome
    if outcome in {"configuration", "permanent"} or row.attempt_count >= MAX_ATTEMPTS:
        row.status = "failed"
    else:
        row.status = "pending"
        row.next_attempt_at = now + timedelta(
            minutes=RETRY_MINUTES[row.attempt_count - 1]
        )


def _claim(
    db: Session, request_id: int, attempted: set[str], now: datetime
) -> tuple[str, int] | None:
    with db.begin():
        rows = lock_request_notifications(db, request_id)
        if any(row.status == "sending" and not _due(row, now) for row in rows):
            return None
        for row in rows:
            if row.status == "sending":
                _record_failure(row, "ambiguous", now)
        for row in rows:
            if (
                row.status == "pending"
                and _due(row, now)
                and row.channel not in attempted
            ):
                row.status = "sending"
                row.attempt_count += 1
                row.last_attempt_at = now
                row.next_attempt_at = now + SEND_LEASE
                return row.channel, row.attempt_count
    return None


def _finish(
    db: Session,
    request_id: int,
    channel: str,
    attempt: int,
    outcome: str | None,
    now: datetime,
) -> str:
    with db.begin():
        rows = lock_request_notifications(db, request_id)
        row = next(entry for entry in rows if entry.channel == channel)
        if row.status != "sending" or row.attempt_count != attempt:
            return "stale_claim"
        if outcome is not None:
            _record_failure(row, outcome, now)
        else:
            row.status = "delivered"
            row.delivered_at = now
            for other in rows:
                if other.status == "pending":
                    other.status = "skipped"
        return row.status


def _dispatch_pass(db: Session, *, dry_run: bool, clock) -> dict:
    with db.begin():
        candidates = read_notification_candidates(db, now=clock(), limit=MAX_REQUESTS)
    results: Counter[str] = Counter()
    if not dry_run:
        for request_id in candidates:
            attempted: set[str] = set()
            message = f"SmartBudget refund request #{request_id}. Review in Admin."
            for _ in range(2):
                claim = _claim(db, request_id, attempted, clock())
                if claim is None:
                    break
                channel, attempt = claim
                attempted.add(channel)
                outcome = (
                    send_telegram_alert(message)
                    if channel == "telegram"
                    else send_smtp_alert(message, subject="SmartBudget refund request")
                )
                if outcome not in {
                    None,
                    "configuration",
                    "permanent",
                    "temporary",
                    "ambiguous",
                }:
                    outcome = "ambiguous"
                result = _finish(db, request_id, channel, attempt, outcome, clock())
                results[result] += 1
                if result in {"delivered", "stale_claim"}:
                    break
    return {
        "status": "dry_run" if dry_run else "completed",
        "selected_requests": len(candidates),
        "attempted": sum(results.values()),
        "by_result": dict(results),
    }


def dispatch_refund_request_alerts(
    db: Session, *, dry_run: bool = False, clock=lambda: datetime.now(UTC)
) -> dict:
    if dry_run:
        return _dispatch_pass(db, dry_run=True, clock=clock)
    if not settings.REFUND_REQUEST_ALERT_DELIVERY_ENABLED:
        return {"status": "disabled", "attempted": 0}
    with lock_recovery_pass(db.get_bind(), lock_id=DISPATCH_LOCK_ID) as acquired:
        if not acquired:
            return {"status": "already_running", "attempted": 0}
        return _dispatch_pass(db, dry_run=False, clock=clock)
