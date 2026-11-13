from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum


class VoluntaryRefundWindowStatus(StrEnum):
    WITHIN_WINDOW = "within_window"
    EXPIRED = "expired"
    MANUAL_REVIEW = "manual_review"


@dataclass(frozen=True)
class VoluntaryRefundWindowAssessment:
    status: VoluntaryRefundWindowStatus
    deadline: datetime | None


def assess_voluntary_refund_window(
    paid_at: datetime | None, *, now: datetime | None = None
) -> VoluntaryRefundWindowAssessment:
    """Assess the SmartBudget voluntary refund window from payment confirmation."""
    if now is None:
        now = datetime.now(UTC)
    elif not isinstance(now, datetime) or now.utcoffset() is None:
        raise ValueError("Assessment time must be a timezone-aware datetime.")
    assessment_time = now.astimezone(UTC)

    manual_review = VoluntaryRefundWindowAssessment(
        VoluntaryRefundWindowStatus.MANUAL_REVIEW, None
    )
    if not isinstance(paid_at, datetime):
        return manual_review

    try:
        if paid_at.utcoffset() is None:
            return manual_review
        payment_time = paid_at.astimezone(UTC)
        deadline = payment_time + timedelta(days=14)
    except (OverflowError, ValueError):
        return manual_review

    if payment_time > assessment_time:
        return manual_review
    status = (
        VoluntaryRefundWindowStatus.WITHIN_WINDOW
        if assessment_time <= deadline
        else VoluntaryRefundWindowStatus.EXPIRED
    )
    return VoluntaryRefundWindowAssessment(status, deadline)
