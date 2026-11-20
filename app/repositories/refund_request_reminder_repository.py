from datetime import date, datetime

from sqlalchemy import String, Time, and_, cast, func, or_, select
from sqlalchemy.orm import Session

from app.models.refund_request import RefundRequest
from app.models.refund_request_reminder import RefundRequestReminder


def list_reminder_candidates(
    db: Session,
    *,
    now: datetime,
    pending_before: datetime,
    review_before: datetime,
    limit: int,
) -> list[int]:
    cycle = RefundRequestReminder
    submitted_at = RefundRequest.submitted_at
    if db.get_bind().dialect.name == "postgresql":
        slot_due = cast(func.timezone("UTC", submitted_at), Time) <= now.time()
    else:
        # SQLite stores the UTC timestamps used by the test suite as text.
        slot_due = func.substr(cast(submitted_at, String), 12) <= now.time().isoformat(
            timespec="microseconds"
        )
    return list(
        db.scalars(
            select(RefundRequest.id)
            .outerjoin(
                cycle,
                and_(
                    cycle.request_id == RefundRequest.id,
                    cycle.cycle_date == now.date(),
                ),
            )
            .where(
                slot_due,
                or_(
                    and_(
                        RefundRequest.status == "pending", submitted_at < pending_before
                    ),
                    and_(
                        RefundRequest.status == "responded",
                        submitted_at < review_before,
                    ),
                ),
                or_(
                    cycle.id.is_(None),
                    and_(
                        cycle.status == "pending",
                        or_(cycle.telegram_due_at <= now, cycle.smtp_due_at <= now),
                    ),
                ),
            )
            .order_by(submitted_at, RefundRequest.id)
            .limit(limit)
        )
    )


def lock_reminder_cycle(
    db: Session, request_id: int, cycle_date: date
) -> RefundRequestReminder | None:
    cycle = RefundRequestReminder
    return db.scalar(
        select(cycle)
        .where(cycle.request_id == request_id, cycle.cycle_date == cycle_date)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def lock_expired_reminder_cycles(
    db: Session, *, now: datetime, limit: int
) -> list[RefundRequestReminder]:
    cycle = RefundRequestReminder
    return list(
        db.scalars(
            select(cycle)
            .join(RefundRequest, RefundRequest.id == cycle.request_id)
            .where(
                or_(
                    and_(cycle.status == "sending", cycle.lease_until <= now),
                    and_(
                        cycle.status == "pending",
                        or_(
                            cycle.cycle_date < now.date(),
                            RefundRequest.status == "closed",
                        ),
                    ),
                )
            )
            .order_by(cycle.cycle_date, cycle.id)
            .limit(limit)
            .with_for_update(of=cycle, skip_locked=True)
            .execution_options(populate_existing=True)
        )
    )
