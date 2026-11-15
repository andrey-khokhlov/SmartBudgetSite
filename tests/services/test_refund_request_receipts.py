from datetime import UTC, timedelta
from smtplib import SMTPAuthenticationError, SMTPDataError, SMTPRecipientsRefused
from unittest.mock import Mock

import pytest

from app.models.enums import PaymentStatus
from app.models.refund_request import RefundRequest
from app.models.refund_request_receipt import RefundRequestReceipt
from app.services import mail_service, refund_request_receipt_service as receipts
from app.services.refund_request_service import submit_refund_request
from tests.services.test_payment_reconciliation_service import create_pending_sale


send_email = mail_service.send_email


def test_bounded_smtp_timeout_and_close_after_acceptance(monkeypatch):
    smtp = Mock()
    smtp.return_value.close.side_effect = OSError("disconnected after acceptance")
    monkeypatch.setattr(mail_service.smtplib, "SMTP", smtp)
    monkeypatch.setattr(mail_service.settings, "MAIL_SMTP_TLS", True)
    send_email("buyer@example.com", "Subject", "Receipt", timeout=5)
    assert smtp.call_args.kwargs["timeout"] == 5
    assert smtp.return_value.starttls.call_args.kwargs["context"].check_hostname
    smtp.return_value.send_message.assert_called_once()


@pytest.fixture
def submission(db_session, monkeypatch):
    sale = create_pending_sale(db_session)
    sale.payment_status = PaymentStatus.PAID
    db_session.commit()
    reference = sale.sale_reference
    db_session.rollback()
    sender = Mock()
    monkeypatch.setattr(mail_service, "send_email", sender)
    return sender, dict(
        email="buyer@example.com",
        reference=reference,
        message="Private request",
        language="ru",
        submission_token="a" * 64,
    )


def state(db):
    with db.begin():
        row = db.query(RefundRequestReceipt).one()
        due = row.next_attempt_at
        if due is not None and due.tzinfo is None:
            due = due.replace(tzinfo=UTC)
        return (
            row.request_id,
            row.status,
            row.attempt_count,
            due,
            row.failure_classification,
        )


def test_initial_acceptance_and_replay(db_session, submission):
    sender, payload = submission

    def verify_committed(**mail):
        assert not db_session.in_transaction()
        with db_session.begin():
            request = db_session.query(RefundRequest).one()
            assert request.receipt.status == "sending"
            assert len(request.notifications) == 2
        assert mail["to_email"] == payload["email"]
        assert mail["subject"] == "SmartBudget — запрос на возврат получен"
        assert payload["message"] not in mail["body"]
        assert payload["reference"] not in mail["body"]
        assert mail["timeout"] == 5

    sender.side_effect = verify_committed
    submit_refund_request(db_session, **payload)
    submit_refund_request(db_session, **payload)
    request_id, status, attempts, due, failure = state(db_session)
    assert (status, attempts, due, failure) == ("accepted", 1, None, None)
    assert (
        receipts.deliver_refund_request_receipt(db_session, request_id) == "not_claimed"
    )
    sender.assert_called_once()


@pytest.mark.parametrize(
    ("error", "classification", "expected"),
    [
        (SMTPAuthenticationError(535, b"private"), "configuration", "failed"),
        (
            SMTPRecipientsRefused({"buyer@example.com": (550, b"private")}),
            "permanent",
            "failed",
        ),
        (SMTPDataError(451, b"private"), "temporary", "pending"),
        (ConnectionError("private"), "ambiguous", "pending"),
    ],
)
def test_failure_classification_and_retry(
    db_session, submission, caplog, error, classification, expected
):
    sender, payload = submission
    sender.side_effect = error
    submit_refund_request(db_session, **payload)
    request_id, status, attempts, due, failure = state(db_session)
    assert (status, attempts, failure) == (expected, 1, classification)
    assert "private" not in caplog.text.lower() and payload["email"] not in caplog.text
    if expected == "pending":
        assert (
            receipts.recover_refund_request_receipts(
                db_session, dry_run=True, clock=lambda: due
            )["selected"]
            == 1
        )
        assert state(db_session)[1:3] == ("pending", 1)
        sender.side_effect = None
        assert (
            receipts.deliver_refund_request_receipt(
                db_session, request_id, clock=lambda: due
            )
            == "accepted"
        )
        assert state(db_session)[1:3] == ("accepted", 2)
    else:
        assert due is None


def test_retry_delays_and_exhaustion(db_session, submission):
    sender, payload = submission
    sender.side_effect = SMTPDataError(451, b"retry")
    submit_refund_request(db_session, **payload)
    request_id, _, _, now, _ = state(db_session)
    for attempt in range(2, 8):
        result = receipts.deliver_refund_request_receipt(
            db_session, request_id, clock=lambda: now
        )
        _, status, count, due, _ = state(db_session)
        assert result == status and count == attempt
        if attempt < 7:
            assert due - now == timedelta(minutes=receipts.RETRY_MINUTES[attempt - 1])
            now = due
        else:
            assert status == "failed" and due is None
    assert sender.call_count == 7


def test_interruption_leaves_lease_and_recovers(db_session, submission):
    sender, payload = submission
    sender.side_effect = RuntimeError("private unexpected failure")
    submit_refund_request(db_session, **payload)
    request_id, status, attempts, lease_end, _ = state(db_session)
    assert (status, attempts) == ("sending", 1)
    before_lease = lease_end - timedelta(seconds=1)
    assert (
        receipts.deliver_refund_request_receipt(
            db_session, request_id, clock=lambda: before_lease
        )
        == "not_claimed"
    )
    receipts.deliver_refund_request_receipt(
        db_session, request_id, clock=lambda: lease_end
    )
    _, status, attempts, due, failure = state(db_session)
    assert (status, attempts, due, failure) == (
        "pending",
        1,
        lease_end + timedelta(minutes=1),
        "ambiguous",
    )
    sender.side_effect = None
    assert (
        receipts.deliver_refund_request_receipt(
            db_session, request_id, clock=lambda: due
        )
        == "accepted"
    )
    assert sender.call_count == 2
