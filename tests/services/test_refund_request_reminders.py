from contextlib import nullcontext
from datetime import UTC, datetime, timedelta, timezone
from secrets import token_hex
from unittest.mock import Mock

import pytest
from sqlalchemy import select

from app.models.refund_request import RefundRequest
from app.models.refund_request_reminder import RefundRequestReminder
from app.services import refund_request_reminder_service as reminders
from app.services.refund_request_service import record_refund_request_action
from tests.services.test_payment_reconciliation_service import create_pending_sale

MONDAY = datetime(2026, 11, 16, 12, 34, 56, 123456, tzinfo=UTC)
FRIDAY = MONDAY - timedelta(days=3)
WEDNESDAY = MONDAY + timedelta(days=2)


@pytest.mark.parametrize(
    ("submitted", "days", "expected"),
    [
        (FRIDAY, 1, MONDAY),
        (FRIDAY + timedelta(days=1), 3, WEDNESDAY),
        (FRIDAY + timedelta(days=2), 5, FRIDAY + timedelta(days=7)),
        (MONDAY, 5, MONDAY + timedelta(days=7)),
        (FRIDAY.astimezone(timezone(timedelta(hours=13))), 1, MONDAY),
    ],
)
def test_deadlines_preserve_utc_submission_time(submitted, days, expected):
    result = reminders.add_business_days(submitted, days)
    assert result == expected
    assert result.tzinfo is UTC


@pytest.fixture
def seed(db_session):
    sale = create_pending_sale(db_session)
    sale_id = sale.id
    reference = sale.sale_reference
    db_session.rollback()

    def add(submitted, status="pending"):
        with db_session.begin():
            request = RefundRequest(
                sale_id=sale_id,
                purchase_reference=reference,
                customer_email="private-buyer@example.test",
                submission_token=token_hex(32),
                submitted_at=submitted,
                language="en",
                message="Private customer message",
                composition="product",
                status=status,
                first_responded_at=submitted if status != "pending" else None,
                closed_at=submitted if status == "closed" else None,
            )
            db_session.add(request)
            db_session.flush()
            return request.id

    return add


@pytest.fixture
def providers(monkeypatch):
    telegram, smtp = Mock(return_value=None), Mock(return_value=None)
    monkeypatch.setattr(reminders, "send_telegram_alert", telegram)
    monkeypatch.setattr(reminders, "send_smtp_alert", smtp)
    monkeypatch.setattr(
        reminders, "lock_recovery_pass", lambda *a, **k: nullcontext(True)
    )
    monkeypatch.setattr(
        reminders.settings, "REFUND_REQUEST_REMINDER_DELIVERY_ENABLED", True
    )
    return telegram, smtp


def dispatch(db, now, *, dry_run=False):
    return reminders.dispatch_refund_request_reminders(
        db, dry_run=dry_run, clock=lambda: now
    )


def cycles(db):
    with db.begin():
        return db.execute(
            select(
                RefundRequestReminder.request_id,
                RefundRequestReminder.cycle_date,
                RefundRequestReminder.status,
                RefundRequestReminder.telegram_attempts,
                RefundRequestReminder.smtp_attempts,
                RefundRequestReminder.last_error,
            ).order_by(RefundRequestReminder.id)
        ).all()


@pytest.mark.parametrize("submitted", [FRIDAY, FRIDAY + timedelta(days=2)])
def test_pending_reminder_timing_escalation_and_combination(
    db_session, seed, providers, submitted
):
    request_id = seed(submitted)
    telegram, smtp = providers
    assert dispatch(db_session, FRIDAY + timedelta(days=2))["attempted"] == 0
    assert dispatch(db_session, MONDAY - timedelta(microseconds=1))["attempted"] == 0
    for day in (
        MONDAY,
        MONDAY + timedelta(days=1),
        WEDNESDAY,
        FRIDAY + timedelta(days=7),
    ):
        assert dispatch(db_session, day)["attempted"] == 1
        assert dispatch(db_session, day + timedelta(minutes=1))["attempted"] == 0
    messages = [call.args[0] for call in telegram.call_args_list]
    assert len(messages) == 4
    assert "First response outstanding." in messages[0]
    assert "First response outstanding." in messages[1]
    assert "First response overdue." in messages[2]
    assert "Review overdue." not in messages[2]
    assert messages[3] == (
        f"SmartBudget refund request #{request_id}. First response overdue. "
        "Review overdue. Review in Admin."
    )
    assert all(
        call.kwargs == {"require_confirmed_rejection": True}
        for call in telegram.call_args_list
    )
    assert all(
        "private" not in message.lower() and "PAY-" not in message
        for message in messages
    )
    smtp.assert_not_called()
    assert {row[2:] for row in cycles(db_session)} == {("delivered", 1, 0, None)}


def test_responded_review_cutoff_and_closed_suppression(db_session, seed, providers):
    responded = seed(FRIDAY + timedelta(days=1), "responded")
    seed(FRIDAY, "closed")
    telegram, smtp = providers
    review = FRIDAY + timedelta(days=7)
    assert dispatch(db_session, review - timedelta(microseconds=1))["attempted"] == 0
    assert dispatch(db_session, review)["attempted"] == 1
    telegram.assert_called_once_with(
        f"SmartBudget refund request #{responded}. Review overdue. Review in Admin.",
        require_confirmed_rejection=True,
    )
    record_refund_request_action(db_session, request_id=responded, action="close")
    assert dispatch(db_session, review + timedelta(days=3))["attempted"] == 0
    assert len(cycles(db_session)) == 1
    smtp.assert_not_called()


def test_dry_run_disabled_and_historical_restart_coalescing(
    db_session, seed, providers, monkeypatch
):
    request_id = seed(FRIDAY - timedelta(days=90))
    telegram, smtp = providers
    monkeypatch.setattr(
        reminders.settings, "REFUND_REQUEST_REMINDER_DELIVERY_ENABLED", False
    )
    assert dispatch(db_session, MONDAY)["status"] == "disabled"
    assert dispatch(db_session, MONDAY, dry_run=True)["selected_requests"] == 1
    assert cycles(db_session) == []
    telegram.assert_not_called()
    smtp.assert_not_called()
    monkeypatch.setattr(
        reminders.settings, "REFUND_REQUEST_REMINDER_DELIVERY_ENABLED", True
    )
    assert dispatch(db_session, MONDAY)["attempted"] == 1
    assert cycles(db_session) == [(request_id, MONDAY.date(), "delivered", 1, 0, None)]


def test_definitive_failure_falls_back_and_temporary_outcome_retries(
    db_session, seed, providers
):
    request_id = seed(FRIDAY)
    telegram, smtp = providers
    telegram.return_value = "permanent"
    smtp.side_effect = ["temporary", None]
    assert dispatch(db_session, MONDAY)["by_result"] == {"pending": 2}
    assert dispatch(db_session, MONDAY + timedelta(seconds=59))["attempted"] == 0
    assert dispatch(db_session, MONDAY + timedelta(minutes=1))["by_result"] == {
        "delivered": 1
    }
    assert telegram.call_count == 1 and smtp.call_count == 2
    assert cycles(db_session) == [(request_id, MONDAY.date(), "delivered", 1, 2, None)]


@pytest.mark.parametrize("interrupted", [False, True])
def test_uncertain_acceptance_fences_the_cycle_then_next_cycle_resumes(
    db_session, seed, providers, interrupted
):
    request_id = seed(FRIDAY)
    telegram, smtp = providers
    if interrupted:
        telegram.side_effect = RuntimeError("interrupted after claim")
        with pytest.raises(RuntimeError, match="interrupted"):
            dispatch(db_session, MONDAY)
        assert cycles(db_session)[0][2] == "sending"
        assert (
            dispatch(db_session, MONDAY + timedelta(minutes=1))["retired_cycles"] == 0
        )
    else:
        telegram.return_value = "ambiguous"
        assert dispatch(db_session, MONDAY)["by_result"] == {"ambiguous": 1}
    outcome = dispatch(db_session, MONDAY + reminders.SEND_LEASE)
    assert outcome["attempted"] == 0
    assert outcome["retired_cycles"] == int(interrupted)
    assert cycles(db_session) == [
        (request_id, MONDAY.date(), "ambiguous", 1, 0, "ambiguous")
    ]
    smtp.assert_not_called()
    telegram.side_effect = None
    telegram.return_value = None
    assert dispatch(db_session, MONDAY + timedelta(days=1))["attempted"] == 1
    assert cycles(db_session)[-1][2] == "delivered"


def test_rechecks_response_between_telegram_and_smtp_claims(
    db_session, seed, providers
):
    request_id = seed(FRIDAY)
    telegram, smtp = providers

    def record_response(*args, **kwargs):
        assert not db_session.in_transaction()
        record_refund_request_action(
            db_session, request_id=request_id, action="respond"
        )
        return "permanent"

    telegram.side_effect = record_response
    assert dispatch(db_session, MONDAY)["attempted"] == 1
    assert cycles(db_session) == [
        (request_id, MONDAY.date(), "skipped", 1, 0, "permanent")
    ]
    smtp.assert_not_called()


def test_definitive_failures_are_terminal_for_only_the_current_day(
    db_session, seed, providers
):
    request_id = seed(FRIDAY)
    telegram, smtp = providers
    telegram.return_value = "configuration"
    smtp.return_value = "permanent"
    assert dispatch(db_session, MONDAY)["by_result"] == {"pending": 1, "failed": 1}
    assert dispatch(db_session, MONDAY + timedelta(hours=1))["attempted"] == 0
    assert cycles(db_session) == [
        (request_id, MONDAY.date(), "failed", 1, 1, "permanent")
    ]


def test_old_retry_is_retired_and_pass_is_bounded(
    db_session, seed, providers, monkeypatch
):
    first = seed(FRIDAY)
    telegram, smtp = providers
    telegram.return_value = smtp.return_value = "temporary"
    assert dispatch(db_session, MONDAY)["attempted"] == 2
    second = seed(FRIDAY)
    telegram.return_value = None
    next_day = MONDAY + timedelta(days=2)
    monkeypatch.setattr(reminders, "MAX_REQUESTS", 1)
    assert dispatch(db_session, next_day)["retired_cycles"] == 1
    assert cycles(db_session) == [
        (first, MONDAY.date(), "skipped", 1, 1, "temporary"),
        (first, next_day.date(), "delivered", 1, 0, None),
    ]
    assert dispatch(db_session, next_day)["attempted"] == 1
    assert cycles(db_session)[-1] == (second, next_day.date(), "delivered", 1, 0, None)
