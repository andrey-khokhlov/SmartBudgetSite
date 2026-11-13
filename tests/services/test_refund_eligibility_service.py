from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.services.refund_eligibility_service import (
    VoluntaryRefundWindowAssessment,
    VoluntaryRefundWindowStatus,
    assess_voluntary_refund_window,
)

PAID_AT = datetime(2024, 12, 24, 12, tzinfo=UTC)
DEADLINE = datetime(2025, 1, 7, 12, tzinfo=UTC)


@pytest.mark.parametrize(
    ("now", "status"),
    [
        (PAID_AT, VoluntaryRefundWindowStatus.WITHIN_WINDOW),
        (DEADLINE - timedelta(seconds=1), VoluntaryRefundWindowStatus.WITHIN_WINDOW),
        (DEADLINE, VoluntaryRefundWindowStatus.WITHIN_WINDOW),
        (DEADLINE + timedelta(microseconds=1), VoluntaryRefundWindowStatus.EXPIRED),
        (datetime(2026, 11, 13, tzinfo=UTC), VoluntaryRefundWindowStatus.EXPIRED),
    ],
)
def test_assesses_the_inclusive_window(now, status):
    assert assess_voluntary_refund_window(PAID_AT, now=now) == (
        VoluntaryRefundWindowAssessment(status, DEADLINE)
    )


@pytest.mark.parametrize(
    "paid_at",
    [None, PAID_AT.replace(tzinfo=None), PAID_AT + timedelta(microseconds=1)],
    ids=["missing", "naive", "future"],
)
def test_unreliable_payment_timestamp_requires_manual_review(paid_at):
    assert assess_voluntary_refund_window(paid_at, now=PAID_AT) == (
        VoluntaryRefundWindowAssessment(VoluntaryRefundWindowStatus.MANUAL_REVIEW, None)
    )


def test_normalizes_payment_and_assessment_offsets():
    paid_at = PAID_AT.astimezone(timezone(timedelta(hours=5, minutes=30)))
    now = DEADLINE.astimezone(timezone(timedelta(hours=-8)))

    result = assess_voluntary_refund_window(paid_at, now=now)

    assert result.status == VoluntaryRefundWindowStatus.WITHIN_WINDOW
    assert result.deadline == DEADLINE
    assert result.deadline.tzinfo is UTC


def test_invalid_assessment_time_raises_even_when_payment_timestamp_is_missing():
    with pytest.raises(ValueError, match="timezone-aware"):
        assess_voluntary_refund_window(None, now=PAID_AT.replace(tzinfo=None))


def test_unrepresentable_deadline_requires_manual_review():
    paid_at = datetime.max.replace(tzinfo=UTC)
    assert assess_voluntary_refund_window(paid_at, now=paid_at) == (
        VoluntaryRefundWindowAssessment(VoluntaryRefundWindowStatus.MANUAL_REVIEW, None)
    )


def test_identical_inputs_produce_equal_immutable_results():
    first = assess_voluntary_refund_window(PAID_AT, now=DEADLINE)
    second = assess_voluntary_refund_window(PAID_AT, now=DEADLINE)

    assert first == second
    with pytest.raises(FrozenInstanceError):
        first.deadline = None
