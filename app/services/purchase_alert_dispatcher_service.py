from collections import Counter
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.config import settings
from app.repositories.lava_top_payment_recovery_repository import lock_recovery_pass
from app.repositories.purchase_delivery_notification_repository import (
    lock_dispatch_incident,
    read_dispatch_candidates,
)
from app.services.purchase_alert_transport import send_smtp_alert, send_telegram_alert
from app.services.purchase_delivery_notification_service import (
    materialize_purchase_delivery_notifications,
)

MAX_INCIDENTS = 20
SEND_LEASE = timedelta(minutes=2)
DISPATCH_LOCK_ID = 812194340104
RETRY_MINUTES = (1, 2, 5, 15, 30, 60)


@dataclass(frozen=True)
class Claim:
    channel: str
    attempt: int
    message: str


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _skip(entries, reason: str) -> None:
    for entry in entries:
        if entry.status not in {"delivered", "skipped"}:
            entry.status = "skipped"
            entry.skip_reason = reason


def _claim(
    db: Session, incident_id: int, *, clock, attempted: set[str]
) -> Claim | None:
    with db.begin():
        incident, entries = lock_dispatch_incident(db, incident_id)
        if incident is None:
            return None
        now = clock()
        if any(
            row.status == "sending" and _utc(row.next_attempt_at) > now
            for row in entries
        ):
            return None
        if any(row.status == "delivered" for row in entries):
            _skip(entries, "other_channel_succeeded")
            return None
        if incident.resolved_at is not None:
            _skip(entries, "incident_resolved")
            return None
        for row in sorted(entries, key=lambda entry: entry.channel != "telegram"):
            if row.channel in attempted or row.status not in {"pending", "sending"}:
                continue
            if _utc(row.next_attempt_at) > now:
                continue
            row.status = "sending"
            row.attempt_count += 1
            row.last_attempt_at = now
            row.next_attempt_at = now + SEND_LEASE
            # Keep the alert independent of free-text fields and commerce records.
            message = (
                f"SmartBudget incident #{incident.id} · {incident.kind} · "
                f"{incident.severity}\n"
                f"First detected {_utc(incident.first_detected_at).isoformat()}"
            )
            return Claim(row.channel, row.attempt_count, message)
    return None


def _finish(
    db: Session, incident_id: int, claim: Claim, outcome: str | None, *, clock
) -> str:
    with db.begin():
        _, entries = lock_dispatch_incident(db, incident_id)
        row = next(entry for entry in entries if entry.channel == claim.channel)
        if row.status != "sending" or row.attempt_count != claim.attempt:
            return "stale_claim"
        now = clock()
        if outcome is None:
            row.status = "delivered"
            row.delivered_at = now
            _skip(entries, "other_channel_succeeded")
        else:
            row.last_error = outcome
            if outcome in {"configuration", "permanent"}:
                row.status = "failed"
            else:
                row.status = "pending"
                delay = RETRY_MINUTES[min(row.attempt_count, len(RETRY_MINUTES)) - 1]
                row.next_attempt_at = now + timedelta(minutes=delay)
        return row.status


def dispatch_purchase_alerts(
    db: Session,
    *,
    dry_run: bool = False,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict:
    if not dry_run and not settings.PURCHASE_ALERT_DELIVERY_ENABLED:
        return {"status": "disabled", "attempted": 0}
    engine = db.get_bind()
    lock = (
        lock_recovery_pass(engine, lock_id=DISPATCH_LOCK_ID)
        if not dry_run and engine.dialect.name == "postgresql"
        else nullcontext(True)
    )
    with lock as acquired:
        if not acquired:
            return {"status": "already_running", "attempted": 0}
        return _dispatch_pass(db, dry_run=dry_run, clock=clock)


def _dispatch_pass(db: Session, *, dry_run: bool, clock) -> dict:
    created = 0 if dry_run else materialize_purchase_delivery_notifications(db)
    with db.begin():
        candidates = read_dispatch_candidates(db, now=clock(), limit=MAX_INCIDENTS)
    results: Counter[str] = Counter()
    if not dry_run:
        senders = {"telegram": send_telegram_alert, "smtp": send_smtp_alert}
        for incident_id in candidates:
            attempted: set[str] = set()
            for _ in range(2):
                claim = _claim(db, incident_id, clock=clock, attempted=attempted)
                if claim is None:
                    break
                attempted.add(claim.channel)
                outcome = senders[claim.channel](claim.message)
                if outcome not in {
                    None,
                    "configuration",
                    "permanent",
                    "temporary",
                    "ambiguous",
                }:
                    outcome = "ambiguous"
                result = _finish(db, incident_id, claim, outcome, clock=clock)
                results[result] += 1
                if result in {"delivered", "stale_claim"}:
                    break
    return {
        "status": "dry_run" if dry_run else "completed",
        "materialized": created,
        "selected_incidents": len(candidates),
        "attempted": sum(results.values()),
        "by_result": dict(results),
    }
