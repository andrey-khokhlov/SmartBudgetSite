from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.refund_request import RefundRequest
from app.models.refund_request_reminder import RefundRequestReminder
from app.repositories.lava_top_payment_recovery_repository import lock_recovery_pass
from app.repositories.refund_request_reminder_repository import (
    list_reminder_candidates,
    lock_expired_reminder_cycles,
    lock_reminder_cycle,
)
from app.repositories.refund_request_repository import lock_refund_request
from app.services.purchase_alert_transport import send_smtp_alert, send_telegram_alert

FIRST_REMINDER_DAYS = 1
FIRST_RESPONSE_DAYS = 3
REVIEW_DAYS = 5
MAX_REQUESTS = 20
SEND_LEASE = timedelta(minutes=2)
DISPATCH_LOCK_ID = 812194340109
RETRY_MINUTES = (1, 2, 5, 15, 30, 60)
CONFIRMED_FAILURES = {"configuration", "permanent", "temporary"}
Channel = Literal["telegram", "smtp"]


@dataclass(frozen=True)
class Claim:
    channel: Channel
    attempt: int
    message: str


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def add_business_days(start: datetime, days: int) -> datetime:
    stamp = _utc(start)
    step = timedelta(days=1 if days >= 0 else -1)
    remaining = abs(days)
    while remaining:
        stamp += step
        if stamp.weekday() < 5:
            remaining -= 1
    return stamp


def _submission_cutoff(now: datetime, days: int) -> datetime:
    # A weekend submission starts counting on Monday, just like Friday.
    last_date = add_business_days(now, -days).date()
    return datetime.combine(
        last_date + timedelta(days=3 if last_date.weekday() == 4 else 1),
        time.min,
        UTC,
    )


def _message(request: RefundRequest, now: datetime) -> str | None:
    submitted = _utc(request.submitted_at)
    if (
        request.status == "closed"
        or now.weekday() >= 5
        or now.time() < submitted.time()
    ):
        return None
    concerns = []
    if request.status == "pending" and now >= add_business_days(
        submitted, FIRST_REMINDER_DAYS
    ):
        response_due = add_business_days(submitted, FIRST_RESPONSE_DAYS)
        concerns.append(
            "First response overdue."
            if now >= response_due
            else "First response outstanding."
        )
    if now >= add_business_days(submitted, REVIEW_DAYS):
        concerns.append("Review overdue.")
    if concerns:
        return f"SmartBudget refund request #{request.id}. {' '.join(concerns)} Review in Admin."
    return None


def _stop(cycle: RefundRequestReminder, status: str) -> None:
    cycle.status = status
    cycle.telegram_due_at = cycle.smtp_due_at = cycle.lease_until = None


def _retire_expired(db: Session, now: datetime) -> int:
    with db.begin():
        cycles = lock_expired_reminder_cycles(db, now=now, limit=MAX_REQUESTS)
        for cycle in cycles:
            if cycle.status == "sending":
                cycle.last_error = "ambiguous"
                _stop(cycle, "ambiguous")
            else:
                _stop(cycle, "skipped")
        return len(cycles)


def _claim(
    db: Session,
    request_id: int,
    cycle_date: date,
    attempted: set[Channel],
    now: datetime,
) -> Claim | None:
    if now.date() != cycle_date:
        return None
    with db.begin():
        request = lock_refund_request(db, request_id)
        if request is None:
            return None
        cycle = lock_reminder_cycle(db, request_id, cycle_date)
        if cycle is not None and cycle.status != "pending":
            return None
        message = _message(request, now)
        if message is None:
            if cycle is not None:
                _stop(cycle, "skipped")
            return None
        if cycle is None:
            cycle = RefundRequestReminder(
                request_id=request_id,
                cycle_date=cycle_date,
                telegram_due_at=now,
                smtp_due_at=now,
                telegram_attempts=0,
                smtp_attempts=0,
            )
            db.add(cycle)
        for channel in ("telegram", "smtp"):
            due = cycle.telegram_due_at if channel == "telegram" else cycle.smtp_due_at
            if channel in attempted or due is None or _utc(due) > now:
                continue
            if channel == "telegram":
                cycle.telegram_attempts += 1
                attempt = cycle.telegram_attempts
            else:
                cycle.smtp_attempts += 1
                attempt = cycle.smtp_attempts
            cycle.status = "sending"
            cycle.claim_channel = channel
            cycle.lease_until = now + SEND_LEASE
            return Claim(channel, attempt, message)
    return None


def _finish(
    db: Session,
    request_id: int,
    cycle_date: date,
    claim: Claim,
    outcome: str | None,
    now: datetime,
) -> str:
    with db.begin():
        cycle = lock_reminder_cycle(db, request_id, cycle_date)
        if (
            cycle is None
            or cycle.status != "sending"
            or cycle.claim_channel != claim.channel
        ):
            return "stale_claim"
        attempts = (
            cycle.telegram_attempts
            if claim.channel == "telegram"
            else cycle.smtp_attempts
        )
        if attempts != claim.attempt:
            return "stale_claim"
        if outcome is None:
            cycle.delivered_at = now
            cycle.last_error = None
            _stop(cycle, "delivered")
        elif outcome not in CONFIRMED_FAILURES:
            cycle.last_error = "ambiguous"
            _stop(cycle, "ambiguous")
        else:
            cycle.last_error = outcome
            next_attempt = (
                now + timedelta(minutes=RETRY_MINUTES[attempts - 1])
                if outcome == "temporary" and attempts <= len(RETRY_MINUTES)
                else None
            )
            if claim.channel == "telegram":
                cycle.telegram_due_at = next_attempt
            else:
                cycle.smtp_due_at = next_attempt
            cycle.lease_until = None
            cycle.status = (
                "pending" if cycle.telegram_due_at or cycle.smtp_due_at else "failed"
            )
        return cycle.status


def _dispatch_pass(
    db: Session, *, dry_run: bool, clock: Callable[[], datetime]
) -> dict:
    now = _utc(clock())
    retired = 0 if dry_run else _retire_expired(db, now)
    candidates = []
    if now.weekday() < 5:
        with db.begin():
            candidates = list_reminder_candidates(
                db,
                now=now,
                pending_before=_submission_cutoff(now, FIRST_REMINDER_DAYS),
                review_before=_submission_cutoff(now, REVIEW_DAYS),
                limit=MAX_REQUESTS,
            )
    results: Counter[str] = Counter()
    if not dry_run:
        for request_id in candidates:
            attempted: set[Channel] = set()
            for _ in range(2):
                claim = _claim(db, request_id, now.date(), attempted, _utc(clock()))
                if claim is None:
                    break
                attempted.add(claim.channel)
                outcome = (
                    send_telegram_alert(claim.message, require_confirmed_rejection=True)
                    if claim.channel == "telegram"
                    else send_smtp_alert(
                        claim.message, subject="SmartBudget refund request reminder"
                    )
                )
                result = _finish(
                    db, request_id, now.date(), claim, outcome, _utc(clock())
                )
                results[result] += 1
                if result != "pending":
                    break
    return {
        "status": "dry_run" if dry_run else "completed",
        "selected_requests": len(candidates),
        "retired_cycles": retired,
        "attempted": sum(results.values()),
        "by_result": dict(results),
    }


def dispatch_refund_request_reminders(
    db: Session, *, dry_run: bool = False, clock=lambda: datetime.now(UTC)
) -> dict:
    if dry_run:
        return _dispatch_pass(db, dry_run=True, clock=clock)
    if not settings.REFUND_REQUEST_REMINDER_DELIVERY_ENABLED:
        return {"status": "disabled", "attempted": 0}
    with lock_recovery_pass(db.get_bind(), lock_id=DISPATCH_LOCK_ID) as acquired:
        if not acquired:
            return {"status": "already_running", "attempted": 0}
        return _dispatch_pass(db, dry_run=False, clock=clock)
