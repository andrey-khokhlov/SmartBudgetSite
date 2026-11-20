from datetime import UTC, timedelta
from unittest.mock import Mock

import pytest

from app.models.enums import PaymentStatus
from app.models.refund_request import RefundRequest
from app.services import refund_request_notification_service as alerts
from app.services.refund_request_service import submit_refund_request
from tests.services.test_payment_reconciliation_service import create_pending_sale


@pytest.fixture
def queued(db_session):
    sale = create_pending_sale(db_session)
    sale.payment_status = PaymentStatus.PAID
    db_session.commit()
    email, reference = sale.customer_email, sale.sale_reference
    db_session.rollback()
    submit_refund_request(
        db_session,
        email=email,
        reference=reference,
        message="Private message",
        language="en",
        submission_token="a" * 64,
    )
    with db_session.begin():
        entry = db_session.query(RefundRequest).one()
        return entry.id, entry.submitted_at.replace(tzinfo=UTC)


def states(db):
    with db.begin():
        entry = db.query(RefundRequest).one()
        return {
            row.channel: (row.status, row.attempt_count, row.last_error)
            for row in entry.notifications
        }


@pytest.fixture
def providers(monkeypatch):
    telegram, smtp = Mock(return_value=None), Mock(return_value=None)
    monkeypatch.setattr(alerts, "send_telegram_alert", telegram)
    monkeypatch.setattr(alerts, "send_smtp_alert", smtp)
    return telegram, smtp


def test_disabled_and_dry_run_are_read_only(db_session, queued, providers, monkeypatch):
    monkeypatch.setattr(alerts.settings, "REFUND_REQUEST_ALERT_DELIVERY_ENABLED", False)
    _, now = queued
    assert alerts.dispatch_refund_request_alerts(db_session)["status"] == "disabled"
    result = alerts.dispatch_refund_request_alerts(
        db_session, dry_run=True, clock=lambda: now
    )
    assert result["selected_requests"] == 1 and result["attempted"] == 0
    assert states(db_session) == dict.fromkeys(
        ("telegram", "smtp"), ("pending", 0, None)
    )
    for provider in providers:
        provider.assert_not_called()


@pytest.mark.parametrize(
    "failure", ["permanent", "temporary", "ambiguous", "configuration"]
)
def test_fallback_and_privacy(db_session, queued, providers, failure, caplog):
    request_id, now = queued
    telegram, smtp = providers
    telegram.return_value = failure
    result = alerts._dispatch_pass(db_session, dry_run=False, clock=lambda: now)
    assert result["attempted"] == 2
    message = f"SmartBudget refund request #{request_id}. Review in Admin."
    telegram.assert_called_once_with(message)
    smtp.assert_called_once_with(message, subject="SmartBudget refund request")
    assert states(db_session)["smtp"] == ("delivered", 1, None)
    assert states(db_session)["telegram"][2] == failure
    with db_session.begin():
        request = db_session.get(RefundRequest, request_id)
        assert request.status == "pending"
        assert request.first_responded_at is None and request.closed_at is None
    assert (
        "buyer@example.com" not in caplog.text and "Private message" not in caplog.text
    )
    assert (
        alerts._dispatch_pass(
            db_session, dry_run=False, clock=lambda: now + timedelta(days=1)
        )["attempted"]
        == 0
    )


def test_independent_retries_and_attempt_limit(db_session, queued, providers):
    _, now = queued
    telegram, smtp = providers
    telegram.return_value = "permanent"
    smtp.return_value = "temporary"
    for attempt in range(alerts.MAX_ATTEMPTS):
        alerts._dispatch_pass(db_session, dry_run=False, clock=lambda: now)
        if attempt < alerts.MAX_ATTEMPTS - 1:
            assert (
                alerts._dispatch_pass(db_session, dry_run=False, clock=lambda: now)[
                    "attempted"
                ]
                == 0
            )
            now += timedelta(minutes=alerts.RETRY_MINUTES[attempt])
    assert states(db_session) == {
        "telegram": ("failed", 1, "permanent"),
        "smtp": ("failed", alerts.MAX_ATTEMPTS, "temporary"),
    }
    telegram.assert_called_once()
    assert smtp.call_count == alerts.MAX_ATTEMPTS


def test_telegram_retries_after_both_channels_fail(db_session, queued, providers):
    _, now = queued
    telegram, smtp = providers
    telegram.side_effect = ["temporary", None]
    smtp.return_value = "temporary"
    assert alerts._dispatch_pass(db_session, dry_run=False, clock=lambda: now)[
        "by_result"
    ] == {"pending": 2}
    now += timedelta(minutes=1)
    assert alerts._dispatch_pass(db_session, dry_run=False, clock=lambda: now)[
        "by_result"
    ] == {"delivered": 1}
    assert states(db_session) == {
        "telegram": ("delivered", 2, "temporary"),
        "smtp": ("skipped", 1, "temporary"),
    }
    smtp.assert_called_once()


def test_interrupted_telegram_claim_allows_fallback_after_lease(
    db_session, queued, providers
):
    request_id, now = queued
    assert alerts._claim(db_session, request_id, set(), now) == ("telegram", 1)
    assert (
        alerts._dispatch_pass(db_session, dry_run=False, clock=lambda: now)[
            "selected_requests"
        ]
        == 0
    )
    now += alerts.SEND_LEASE
    assert alerts._dispatch_pass(db_session, dry_run=False, clock=lambda: now)[
        "by_result"
    ] == {"delivered": 1}
    providers[0].assert_not_called()
    providers[1].assert_called_once()
    assert states(db_session) == {
        "telegram": ("skipped", 1, "ambiguous"),
        "smtp": ("delivered", 1, None),
    }
