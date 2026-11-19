from collections import Counter
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.consultation_capacity import ConsultationCapacityNotification
from app.repositories.consultation_capacity_repository import (
    count_outstanding,
    list_due_episodes,
    lock_capacity_state,
    lock_episode_notifications,
)
from app.repositories.lava_top_payment_recovery_repository import lock_recovery_pass
from app.services.consultation_capacity_service import (
    ConsultationCapacityUnavailableError,
)
from app.services.purchase_alert_transport import send_smtp_alert, send_telegram_alert

MAX_EPISODES = 5
SEND_LEASE = timedelta(minutes=2)
DISPATCH_LOCK_ID = 812194340108
RETRY_MINUTES = (1, 2, 5, 15, 30, 60)
MAX_ATTEMPTS = 1 + len(RETRY_MINUTES)


@dataclass(frozen=True)
class Claim:
    channel: str
    attempt: int
    message: str


def _observe_workload(db: Session, now: datetime) -> bool:
    with db.begin():
        state = lock_capacity_state(db)
        if state is None:
            raise ConsultationCapacityUnavailableError()
        outstanding = count_outstanding(db, now=now)
        if outstanding >= settings.CONSULTATION_CAPACITY_LIMIT:
            level = "exhausted"
        elif outstanding >= settings.CONSULTATION_CAPACITY_WARNING_THRESHOLD:
            level = "warning"
        else:
            level = "normal"

        previous = state.observed_level
        state.observed_level = level
        crossed_warning = level == "warning" and previous == "normal"
        crossed_limit = level == "exhausted" and previous != "exhausted"
        if not (crossed_warning or crossed_limit):
            return False

        episode_id = uuid4()
        db.add_all(
            [
                ConsultationCapacityNotification(
                    episode_id=episode_id,
                    kind=level,
                    observed_at=now,
                    channel=channel,
                    next_attempt_at=now,
                )
                for channel in ("telegram", "smtp")
            ]
        )
        return True


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _record_failure(
    row: ConsultationCapacityNotification, outcome: str, now: datetime
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
    db: Session, episode_id: UUID, attempted: set[str], now: datetime
) -> Claim | None:
    with db.begin():
        rows = lock_episode_notifications(db, episode_id)
        if any(
            row.status == "sending" and _utc(row.next_attempt_at) > now for row in rows
        ):
            return None
        for row in rows:
            if row.status == "sending":
                _record_failure(row, "ambiguous", now)
        for row in sorted(rows, key=lambda row: row.channel != "telegram"):
            if (
                row.status == "pending"
                and row.channel not in attempted
                and _utc(row.next_attempt_at) <= now
            ):
                row.status = "sending"
                row.attempt_count += 1
                row.last_attempt_at = now
                row.next_attempt_at = now + SEND_LEASE
                message = (
                    f"SmartBudget consultation capacity {row.kind}\n"
                    f"Observed {_utc(row.observed_at).isoformat()}. "
                    "Review Admin → Consultation offers."
                )
                return Claim(row.channel, row.attempt_count, message)
    return None


def _finish(
    db: Session, episode_id: UUID, claim: Claim, outcome: str | None, now: datetime
) -> str:
    with db.begin():
        rows = lock_episode_notifications(db, episode_id)
        row = next(entry for entry in rows if entry.channel == claim.channel)
        if row.status != "sending" or row.attempt_count != claim.attempt:
            return "stale_claim"
        if outcome is None:
            row.status = "delivered"
            row.delivered_at = now
            for other in rows:
                if other.status == "pending":
                    other.status = "skipped"
        else:
            _record_failure(row, outcome, now)
        return row.status


def dispatch_consultation_capacity_alerts(
    db: Session, *, dry_run: bool = False, clock=lambda: datetime.now(UTC)
) -> dict:
    if not dry_run and not settings.CONSULTATION_CAPACITY_ALERT_DELIVERY_ENABLED:
        return {"status": "disabled", "attempted": 0}
    engine = db.get_bind().engine
    lock = (
        lock_recovery_pass(engine, lock_id=DISPATCH_LOCK_ID)
        if not dry_run and engine.dialect.name == "postgresql"
        else nullcontext(True)
    )
    with lock as acquired:
        if not acquired:
            return {"status": "already_running", "attempted": 0}
        created = False if dry_run else _observe_workload(db, clock())
        with db.begin():
            candidates = list_due_episodes(db, now=clock(), limit=MAX_EPISODES)
        results: Counter[str] = Counter()
        if not dry_run:
            for episode_id in candidates:
                attempted: set[str] = set()
                for _ in range(2):
                    claim = _claim(db, episode_id, attempted, clock())
                    if claim is None:
                        break
                    attempted.add(claim.channel)
                    outcome = (
                        send_telegram_alert(claim.message)
                        if claim.channel == "telegram"
                        else send_smtp_alert(
                            claim.message, subject="SmartBudget consultation capacity"
                        )
                    )
                    if outcome not in {
                        None,
                        "configuration",
                        "permanent",
                        "temporary",
                        "ambiguous",
                    }:
                        outcome = "ambiguous"
                    result = _finish(db, episode_id, claim, outcome, clock())
                    results[result] += 1
                    if result in {"delivered", "stale_claim"}:
                        break
        return {
            "status": "dry_run" if dry_run else "completed",
            "materialized": int(created),
            "selected_episodes": len(candidates),
            "attempted": sum(results.values()),
            "by_result": dict(results),
        }
