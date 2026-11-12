from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta

from sqlalchemy import extract, func, or_, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.models.enums import PaymentStatus
from app.models.lava_top_payment_recovery import (
    LavaTopPaymentRecovery,
    LavaTopRecoveryCooldown,
)
from app.models.sale import Sale

RECOVERY_LOCK_ID = 812194340102
COOLDOWN_ID = 1


@contextmanager
def lock_recovery_pass(engine: Engine) -> Iterator[bool]:
    if engine.dialect.name != "postgresql":
        raise RuntimeError("Automatic payment recovery requires PostgreSQL.")

    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        try:
            acquired = conn.scalar(
                text("SELECT pg_try_advisory_lock(:key)"), {"key": RECOVERY_LOCK_ID}
            )
            conn.commit()
            try:
                yield bool(acquired)
            finally:
                if acquired:
                    conn.execute(
                        text("SELECT pg_advisory_unlock(:key)"),
                        {"key": RECOVERY_LOCK_ID},
                    )
                    conn.commit()
        except BaseException:
            # Never return a potentially locked connection to the pool.
            conn.invalidate()
            raise


def read_due_sales(
    db: Session, *, now: datetime, initial_delay: timedelta, aged: bool, limit: int
):
    aged_before = now - timedelta(days=1)
    joined = (
        select(Sale.id, Sale.external_payment_id, Sale.created_at)
        .outerjoin(LavaTopPaymentRecovery, LavaTopPaymentRecovery.sale_id == Sale.id)
        .where(
            Sale.payment_provider == "lava_top",
            Sale.payment_status == PaymentStatus.PENDING,
            func.trim(Sale.external_payment_id) != "",
            Sale.created_at <= now - initial_delay,
            Sale.created_at <= aged_before if aged else Sale.created_at > aged_before,
            or_(
                LavaTopPaymentRecovery.sale_id.is_(None),
                LavaTopPaymentRecovery.next_check_at <= now,
            ),
        )
    )
    due_at = func.coalesce(
        extract("epoch", LavaTopPaymentRecovery.next_check_at),
        extract("epoch", Sale.created_at) + int(initial_delay.total_seconds()),
    )
    candidates = db.execute(
        joined.add_columns(
            due_at.label("due_at"), func.count().over().label("due_count")
        )
        .order_by(due_at, Sale.id)
        .limit(limit)
    ).all()
    return candidates[0].due_count if candidates else 0, candidates


def record_lookup(
    db: Session,
    *,
    sale_id: int,
    checked_at: datetime,
    next_check_at: datetime | None,
    outcome: str,
) -> None:
    state = db.get(LavaTopPaymentRecovery, sale_id)
    if state is None:
        state = LavaTopPaymentRecovery(sale_id=sale_id)
        db.add(state)
    state.last_checked_at = checked_at
    state.next_check_at = next_check_at
    state.last_outcome = outcome


def get_cooldown(db: Session) -> LavaTopRecoveryCooldown | None:
    return db.get(LavaTopRecoveryCooldown, COOLDOWN_ID)


def set_cooldown(
    db: Session, *, until: datetime, consecutive_provider_failures: int
) -> None:
    cooldown = get_cooldown(db)
    if cooldown is None:
        cooldown = LavaTopRecoveryCooldown(id=COOLDOWN_ID)
        db.add(cooldown)
    cooldown.until = until
    cooldown.consecutive_provider_failures = consecutive_provider_failures


def clear_cooldown(db: Session) -> None:
    cooldown = get_cooldown(db)
    if cooldown is not None:
        db.delete(cooldown)
