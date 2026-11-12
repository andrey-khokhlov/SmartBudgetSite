from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from time import monotonic

from sqlalchemy.engine import Engine, Row
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.enums import PaymentStatus
from app.repositories.lava_top_payment_recovery_repository import (
    clear_cooldown,
    get_cooldown,
    lock_recovery_pass,
    read_due_sales,
    record_lookup,
    set_cooldown,
)
from app.repositories.sales_repository import get_sale_for_payment_reconciliation
from app.services.lava_top.client import (
    LavaTopInvoiceDetails,
    LavaTopInvoiceStatus,
    LavaTopRateLimitError,
    LavaTopRequestError,
    LavaTopResponseError,
    get_invoice,
)
from app.services.payment_delivery_orchestration_service import (
    reconcile_payment_and_deliver,
)
from app.services.payment_reconciliation_service import PaymentReconciliationError
from app.services.webhooks.payload_normalizers.lava_top_payment_normalizer import (
    normalize_lava_top_invoice,
)

INITIAL_DELAY = timedelta(minutes=5)
AGED_RESERVED_LOOKUPS = 4


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _poll_interval(age: timedelta) -> timedelta:
    if age < timedelta(hours=1):
        return INITIAL_DELAY
    if age < timedelta(days=1):
        return timedelta(minutes=15)
    if age < timedelta(days=7):
        return timedelta(hours=1)
    return timedelta(days=1)


def _rate_limit_until(retry_after: str | None, now: datetime) -> datetime:
    if retry_after is not None:
        try:
            value = retry_after.strip()
            if value.isascii() and value.isdecimal():
                return now + timedelta(seconds=int(value))
            return max(now, _utc(parsedate_to_datetime(value)))
        except (ValueError, TypeError, OverflowError):
            pass
    return now + timedelta(minutes=15)


def _select_batch(recent: list[Row], aged: list[Row], limit: int) -> list[Row]:
    if limit == 1:
        return sorted(recent + aged, key=lambda row: (row.due_at, row.id))[:1]
    reserved = min(len(aged), AGED_RESERVED_LOOKUPS, limit - 1)
    recent = recent[: limit - reserved]
    # Leave time for the reserved aged lookups even when the pass hits its deadline.
    return (
        recent[:1] + aged[:reserved] + recent[1:] + aged[reserved : limit - len(recent)]
    )


def _get_candidate_sale(db: Session, candidate: Row):
    sale = get_sale_for_payment_reconciliation(
        db,
        payment_provider="lava_top",
        external_payment_id=candidate.external_payment_id,
    )
    if sale is not None and sale.id == candidate.id:
        return sale
    return None


def _record_provider_pause(
    db: Session,
    candidate: Row,
    *,
    now: datetime,
    error: LavaTopRequestError,
) -> str:
    with db.begin():
        if isinstance(error, LavaTopRateLimitError):
            outcome = "rate_limited"
            until = _rate_limit_until(error.retry_after, now)
            failures = 0
        else:
            outcome = "provider_unavailable"
            cooldown = get_cooldown(db)
            previous_failures = (
                cooldown.consecutive_provider_failures if cooldown else 0
            )
            failures = min(previous_failures + 1, 4)
            until = now + timedelta(minutes=min(5 * 2 ** (failures - 1), 30))
        set_cooldown(db, until=until, consecutive_provider_failures=failures)
        sale = _get_candidate_sale(db, candidate)
        if sale is not None:
            record_lookup(
                db,
                sale_id=sale.id,
                checked_at=now,
                next_check_at=until,
                outcome=outcome,
            )
    return outcome


def _invoice_outcome(invoice: LavaTopInvoiceDetails, sale) -> str:
    if invoice.invoice_id != sale.external_payment_id:
        return "review_invoice_evidence"
    if invoice.amount is not None and invoice.amount != sale.amount:
        return "review_invoice_evidence"
    if invoice.currency is not None and invoice.currency != sale.currency.upper():
        return "review_invoice_evidence"
    if invoice.status == LavaTopInvoiceStatus.COMPLETED:
        if invoice.amount is not None and invoice.currency is not None:
            return "recovered"
        return "review_invoice_evidence"
    if invoice.status in {LavaTopInvoiceStatus.NEW, LavaTopInvoiceStatus.IN_PROGRESS}:
        return "non_terminal"
    if invoice.status == LavaTopInvoiceStatus.FAILED:
        return "review_provider_failed"
    return "review_invoice_evidence"


def _record_observation(
    db: Session,
    candidate: Row,
    *,
    now: datetime,
    invoice: LavaTopInvoiceDetails | None,
    fallback_outcome: str = "review_invoice_evidence",
) -> str:
    # Payment orchestration owns the commit for a recovered Sale. Stage the
    # recovery result in the same transaction before invoking it.
    try:
        clear_cooldown(db)
        sale = _get_candidate_sale(db, candidate)
        if sale is None:
            db.commit()
            return "no_longer_pending"
        outcome = "no_longer_pending"
        if sale.payment_status == PaymentStatus.PENDING:
            outcome = _invoice_outcome(invoice, sale) if invoice else fallback_outcome
        next_check_at = None
        if outcome == "non_terminal":
            next_check_at = now + _poll_interval(now - _utc(sale.created_at))
        record_lookup(
            db,
            sale_id=sale.id,
            checked_at=now,
            next_check_at=next_check_at,
            outcome=outcome,
        )
        if outcome == "recovered" and invoice is not None:
            event = normalize_lava_top_invoice(invoice)
            assert event is not None
            reconcile_payment_and_deliver(db, event, expected_sale_id=sale.id)
        else:
            db.commit()
    except PaymentReconciliationError:
        db.rollback()
        return _record_observation(
            db,
            candidate,
            now=now,
            invoice=None,
            fallback_outcome="review_reconciliation",
        )
    finally:
        if db.in_transaction():
            db.rollback()
    return outcome


def run_lava_top_payment_recovery(
    db: Session,
    *,
    invoice_lookup: Callable[[str], LavaTopInvoiceDetails] = get_invoice,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    elapsed_clock: Callable[[], float] = monotonic,
) -> dict:
    """Run one bounded pass using a fresh PostgreSQL session."""
    engine = db.get_bind()
    if not isinstance(engine, Engine) or db.in_transaction():
        raise RuntimeError("Recovery requires a fresh engine-bound session.")

    with lock_recovery_pass(engine) as acquired:
        if not acquired:
            return {"status": "already_running", "processed": 0}
        limit = settings.LAVA_TOP_RECOVERY_MAX_LOOKUPS
        deadline = elapsed_clock() + settings.LAVA_TOP_RECOVERY_REQUEST_WINDOW_SECONDS
        now = clock()
        with db.begin():
            cooldown = get_cooldown(db)
            paused = cooldown is not None and _utc(cooldown.until) > now
            recent_count, recent = read_due_sales(
                db, now=now, initial_delay=INITIAL_DELAY, aged=False, limit=limit
            )
            aged_count, aged = read_due_sales(
                db, now=now, initial_delay=INITIAL_DELAY, aged=True, limit=limit
            )
        due = recent_count + aged_count
        processed = 0
        aged_processed = 0
        outcomes: Counter[str] = Counter()
        status = "cooldown" if paused else "completed"
        for candidate in [] if paused else _select_batch(recent, aged, limit):
            if elapsed_clock() >= deadline:
                status = "request_window_elapsed"
                break
            processed += 1
            if _utc(candidate.created_at) <= now - timedelta(days=1):
                aged_processed += 1
            try:
                invoice = invoice_lookup(candidate.external_payment_id)
            except LavaTopResponseError:
                invoice = None
            except LavaTopRequestError as exc:
                if (
                    exc.status_code is None
                    or exc.status_code in {401, 403, 408, 429}
                    or exc.status_code >= 500
                ):
                    status = _record_provider_pause(
                        db, candidate, now=clock(), error=exc
                    )
                    outcomes[status] += 1
                    break
                invoice = None
            outcomes[
                _record_observation(db, candidate, now=clock(), invoice=invoice)
            ] += 1
    return {
        "status": status,
        "due": due,
        "processed": processed,
        "deferred": due - processed,
        "by_age": {
            "recent": {
                "due": recent_count,
                "processed": processed - aged_processed,
                "deferred": recent_count - (processed - aged_processed),
            },
            "aged": {
                "due": aged_count,
                "processed": aged_processed,
                "deferred": aged_count - aged_processed,
            },
        },
        "by_outcome": dict(outcomes),
    }
