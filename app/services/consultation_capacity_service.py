import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.repositories.consultation_capacity_repository import (
    lock_capacity_state,
    read_capacity,
)

logger = logging.getLogger(__name__)


class ConsultationCapacityUnavailableError(Exception):
    """Consultation checkout is closed or its availability cannot be established."""


@dataclass(frozen=True)
class ConsultationCapacity:
    manually_suspended: bool
    outstanding: int
    warning_threshold: int
    limit: int

    @property
    def available(self) -> bool:
        return not self.manually_suspended and self.outstanding < self.limit


def get_consultation_capacity(
    db: Session, *, now: datetime | None = None
) -> ConsultationCapacity | None:
    """Read availability before checkout writes. An unknown result closes sales."""
    try:
        snapshot = read_capacity(db, now=now or datetime.now(UTC))
    except SQLAlchemyError:
        db.rollback()
        logger.error("Could not read consultation capacity")
        return None
    if snapshot is None:
        logger.error("Consultation capacity state is missing")
        return None
    suspended, outstanding = snapshot
    return ConsultationCapacity(
        suspended,
        outstanding,
        settings.CONSULTATION_CAPACITY_WARNING_THRESHOLD,
        settings.CONSULTATION_CAPACITY_LIMIT,
    )


def consultation_sales_available(db: Session) -> bool:
    capacity = get_consultation_capacity(db)
    return capacity is not None and capacity.available


def require_consultation_sales_available(db: Session) -> None:
    if not consultation_sales_available(db):
        raise ConsultationCapacityUnavailableError()


def set_consultation_sales_suspended(db: Session, *, suspended: bool) -> None:
    try:
        with db.begin():
            state = lock_capacity_state(db)
            if state is None:
                raise ConsultationCapacityUnavailableError()
            state.manually_suspended = suspended
    except SQLAlchemyError as exc:
        logger.error("Could not update consultation sales suspension")
        raise ConsultationCapacityUnavailableError() from exc
