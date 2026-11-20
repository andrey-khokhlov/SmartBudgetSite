from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest

from app.core.config import settings
from app.core.refund_request_csrf import create_csrf_cookie_value
from app.dependencies import ADMIN_COOKIE_NAME
from app.models.enums import PaymentStatus
from app.models.refund_operation import RefundOperation
from app.models.refund_request import RefundRequest
from app.models.refund_request_notification import RefundRequestNotification
from app.models.refund_request_receipt import RefundRequestReceipt
from app.services import refund_request_service
from tests.services.test_payment_reconciliation_service import create_pending_sale

PATH = "/admin/refund-requests"
SUBMITTED = datetime(2026, 11, 16, 10, tzinfo=UTC)
RESPONDED = SUBMITTED + timedelta(days=1)
CLOSED = SUBMITTED + timedelta(days=2)


@pytest.fixture
def request_id(db_session, monkeypatch):
    monkeypatch.setattr(settings, "SECRET_KEY", "test-admin-refund-request-csrf")
    sale = create_pending_sale(db_session)
    sale.payment_status = PaymentStatus.PAID
    entry = RefundRequest(
        submission_token="a" * 64,
        sale_id=sale.id,
        purchase_reference=sale.sale_reference,
        customer_email=sale.customer_email,
        submitted_at=SUBMITTED,
        language="en",
        composition="product",
        status="pending",
        receipt=RefundRequestReceipt(next_attempt_at=SUBMITTED),
        notifications=[
            RefundRequestNotification(channel="telegram", next_attempt_at=SUBMITTED)
        ],
    )
    db_session.add(entry)
    db_session.flush()
    identifier = entry.id
    db_session.commit()
    return identifier


def csrf_fields(page):
    assert page.status_code == 200
    return {key: page.context[key] for key in ("csrf_cookie_id", "csrf_token")}


def test_admin_records_write_once_response_and_closure(
    auth_client, db_session, monkeypatch, request_id
):
    clock = Mock(side_effect=[RESPONDED, CLOSED])
    monkeypatch.setattr(refund_request_service, "datetime", Mock(now=clock))
    base = f"{PATH}/{request_id}"
    pending = auth_client.get(PATH)
    response_form = csrf_fields(pending)
    assert f'action="{base}/respond?page=1"' in pending.text
    assert "Mark first response sent" in pending.text
    assert "Close request" not in pending.text

    response = auth_client.post(
        f"{base}/respond", data=response_form, follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"] == f"{PATH}?page=1#refund-request-{request_id}"
    responded = auth_client.get(response.headers["location"])
    close_form = csrf_fields(responded)
    assert "Mark first response sent" not in responded.text
    assert "Close request" in responded.text
    assert f'action="{base}/close?page=1"' in responded.text
    assert RESPONDED.isoformat(sep=" ") in responded.text
    entry = db_session.get(RefundRequest, request_id)
    assert entry.status == "responded"
    assert entry.first_responded_at.replace(tzinfo=UTC) == RESPONDED
    assert entry.closed_at is None

    for action, fields in (
        ("respond", response_form),
        ("close", close_form),
        ("close", close_form),
        ("respond", response_form),
    ):
        assert (
            auth_client.post(
                f"{base}/{action}", data=fields, follow_redirects=False
            ).status_code
            == 303
        )

    db_session.refresh(entry)
    assert entry.status == "closed"
    assert entry.submitted_at.replace(tzinfo=UTC) == SUBMITTED
    assert entry.first_responded_at.replace(tzinfo=UTC) == RESPONDED
    assert entry.closed_at.replace(tzinfo=UTC) == CLOSED
    assert clock.call_args_list == [((UTC,), {}), ((UTC,), {})]
    assert entry.receipt.status == "pending" and entry.receipt.attempt_count == 0
    assert entry.notifications[0].status == "pending"
    assert entry.notifications[0].attempt_count == 0
    assert entry.sale.payment_status == PaymentStatus.PAID
    assert db_session.query(RefundOperation).count() == 0
    closed = auth_client.get(PATH)
    assert CLOSED.isoformat(sep=" ") in closed.text
    assert (
        "Close request" not in closed.text
        and "Mark first response sent" not in closed.text
    )


def test_admin_rejects_close_before_response_and_unknown_actions(
    auth_client, db_session, request_id
):
    fields = csrf_fields(auth_client.get(PATH))
    base = f"{PATH}/{request_id}"
    assert auth_client.get(f"{base}/respond").status_code == 405
    assert auth_client.post(f"{base}/close", data=fields).status_code == 409
    assert auth_client.post(f"{base}/reopen", data=fields).status_code == 422
    assert (
        auth_client.post(f"{PATH}/{request_id + 1}/respond", data=fields).status_code
        == 404
    )
    entry = db_session.get(RefundRequest, request_id)
    assert entry.status == "pending"
    assert entry.first_responded_at is None and entry.closed_at is None


@pytest.mark.parametrize("action", ["respond", "close"])
@pytest.mark.parametrize(
    "failure", ["no_admin", "no_csrf", "wrong_token", "public_csrf"]
)
def test_admin_actions_require_authentication_and_admin_csrf(
    auth_client, db_session, request_id, action, failure
):
    fields = csrf_fields(auth_client.get(PATH))
    if failure == "no_admin":
        auth_client.cookies.delete(ADMIN_COOKIE_NAME)
    elif failure == "no_csrf":
        fields = {}
    elif failure == "wrong_token":
        fields["csrf_token"] = "0" * 64
    else:
        cookie_id = fields["csrf_cookie_id"]
        auth_client.cookies.delete(f"refund_request_admin_csrf_{cookie_id}")
        auth_client.cookies.set(
            f"refund_request_admin_csrf_{cookie_id}",
            create_csrf_cookie_value(cookie_id, fields["csrf_token"]),
        )
    response = auth_client.post(f"{PATH}/{request_id}/{action}", data=fields)
    assert response.status_code == 403
    entry = db_session.get(RefundRequest, request_id)
    assert entry.status == "pending"
    assert entry.first_responded_at is None and entry.closed_at is None
