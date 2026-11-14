from datetime import UTC, datetime, timedelta
from decimal import Decimal
from secrets import token_hex
from smtplib import SMTPAuthenticationError, SMTPRecipientsRefused
from unittest.mock import Mock

import pytest
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

from app.dependencies import ADMIN_COOKIE_NAME
from app.models.enums import PaymentStatus
from app.models.refund_operation import RefundOperation
from app.models.refund_request import RefundRequest
from app.services import refund_request_service
from app.services.sale_service import create_standalone_service_sale
from tests.services.test_payment_reconciliation_service import create_pending_sale
from tests.services.test_standalone_consultation_payment import add_offer


def form_fields(response):
    context = getattr(response, "context")
    return {
        "submission_token": context["submission_token"],
        "csrf_cookie_id": context["csrf_cookie_id"],
        "csrf_token": context["csrf_token"],
    }


@pytest.mark.parametrize(
    "tamper",
    ["missing_cookie", "csrf_token", "cookie_id", "cookie_signature"],
)
def test_public_refund_request_rejects_invalid_csrf(
    auth_client, db_session, tamper
):
    client = auth_client
    form = client.get("/refund-request?lang=en")
    assert form.status_code == 200

    fields = form_fields(form)
    cookie_name = f"refund_csrf_{fields['csrf_cookie_id']}"
    cookie_value = client.cookies.get(cookie_name)
    assert cookie_value is not None

    if tamper == "missing_cookie":
        headers = {"Cookie": ""}

    elif tamper == "csrf_token":
        token = fields["csrf_token"]
        fields["csrf_token"] = (
            ("0" if token[0] != "0" else "1") + token[1:]
        )
        headers = {"Cookie": f"{cookie_name}={cookie_value}"}

    elif tamper == "cookie_id":
        cookie_id = fields["csrf_cookie_id"]
        fields["csrf_cookie_id"] = (
            ("0" if cookie_id[0] != "0" else "1") + cookie_id[1:]
        )
        headers = {"Cookie": f"{cookie_name}={cookie_value}"}

    else:
        cookie_token, signature = cookie_value.split(".", 1)
        tampered_signature = (
            ("0" if signature[0] != "0" else "1") + signature[1:]
        )
        headers = {
            "Cookie": f"{cookie_name}={cookie_token}.{tampered_signature}"
        }

    response = client.post(
        "/refund-request?lang=en",
        data={
            **fields,
            "email": "buyer@example.com",
            "purchase_reference": "PAY-AAAAAAAAAAAAAA",
            "message": "",
        },
        headers=headers,
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert 'role="alert"' in response.text
    assert db_session.query(RefundRequest).count() == 0


@pytest.mark.parametrize(
    ("kind", "days_ago", "expected"),
    [
        ("product", 1, "within_window"),
        ("product", 15, "expired"),
        ("product", None, "manual_review"),
        ("mixed", 1, "manual_review"),
        ("consultation", 1, None),
    ],
)
def test_persists_request_and_assessment(
    db_session, monkeypatch, kind, days_ago, expected
):
    now = datetime.now(UTC)
    if kind == "consultation":
        sale = create_standalone_service_sale(
            db=db_session,
            service_addon_id=add_offer(db_session),
            service_name="Consultation",
            customer_email="buyer@example.com",
            amount=Decimal("50"),
            currency="RUB",
            payment_status=PaymentStatus.PAID,
        )
    else:
        sale = create_pending_sale(db_session, bundle=kind == "mixed")
    sale.payment_status = PaymentStatus.PAID
    sale.paid_at = now - timedelta(days=days_ago) if days_ago is not None else None
    db_session.commit()
    reference = sale.sale_reference
    db_session.rollback()
    # SQLite drops offsets. Restore the database driver's PostgreSQL behavior
    # for aware-time cases while leaving the missing timestamp case intact.
    find_paid = refund_request_service.find_paid_sale_for_request

    def find_with_aware_timestamp(*args):
        found = find_paid(*args)
        if found.paid_at is not None:
            set_committed_value(found, "paid_at", found.paid_at.replace(tzinfo=UTC))
        return found

    monkeypatch.setattr(
        refund_request_service,
        find_paid.__name__,
        find_with_aware_timestamp,
    )
    refund_request_service.submit_refund_request(
        db_session,
        email=" BUYER@EXAMPLE.COM ",
        reference=reference,
        message=" ",
        language="ru",
        submission_token=token_hex(32),
    )
    saved = db_session.query(RefundRequest).one()
    assert (saved.composition, saved.window_status, saved.status) == (
        kind,
        expected,
        "pending",
    )
    assert (saved.window_deadline is not None) == (
        expected in {"within_window", "expired"}
    )
    assert saved.message is None and saved.language == "ru"
    assert saved.customer_email == "buyer@example.com"
    assert saved.purchase_reference == reference
    assert saved.sale.payment_status == PaymentStatus.PAID
    assert db_session.query(RefundOperation).count() == 0


@pytest.mark.parametrize("case", ["email", "reference", "pending", "refunded"])
def test_verification_failures_share_response(client, db_session, case):
    sale = create_pending_sale(db_session)
    sale.payment_status = {
        "pending": PaymentStatus.PENDING,
        "refunded": PaymentStatus.REFUNDED,
    }.get(case, PaymentStatus.PAID)
    db_session.commit()

    form = client.get("/refund-request?lang=en")

    result = client.post(
        "/refund-request?lang=en",
        data={
            **form_fields(form),
            "email": "wrong@example.com" if case == "email" else sale.customer_email,
            "purchase_reference": "PAY-AAAAAAAAAAAAAA"
            if case == "reference"
            else sale.sale_reference,
        },
    )
    assert result.status_code == 400
    assert "Check the purchase email and purchase reference" in result.text
    assert sale.sale_reference not in result.text
    assert db_session.query(RefundRequest).count() == 0


@pytest.mark.parametrize("lang", ["ru", "en"])
@pytest.mark.parametrize(
    "failure",
    [
        SMTPAuthenticationError(535, b"denied"),
        SMTPRecipientsRefused({"private@example.com": (550, b"denied")}),
        ConnectionError("connection failed"),
    ],
)
def test_public_form_admin_and_receipt_failure(
    auth_client, db_session, monkeypatch, lang, failure, caplog
):
    client = auth_client
    admin_token = client.cookies.pop(ADMIN_COOKIE_NAME)
    sale = create_pending_sale(db_session)
    sale.payment_status = PaymentStatus.PAID
    db_session.commit()
    email, reference = sale.customer_email, sale.sale_reference
    path = f"/refund-request?lang={lang}"
    form = client.get(path)
    assert form.status_code == 200
    assert f'<html lang="{lang}">' in form.text
    assert f'action="{path}"' in form.text
    assert "<textarea" in form.text and 'type="file"' not in form.text
    assert client.get("/refund-request?submitted=true").text.count('role="status"') == 0

    form_data = form_fields(form)
    token = form_data["submission_token"]

    another_form = client.get(path)
    assert token != form_fields(another_form)["submission_token"]
    sender = Mock(side_effect=failure)
    monkeypatch.setattr(refund_request_service.mail_service, "send_email", sender)
    assert client.get("/admin/refund-requests").status_code == 403
    payload = {
        **form_data,
        "email": email,
        "purchase_reference": reference,
        "message": "<script>test</script>",
    }
    replay_payload = {
        **form_fields(another_form),
        "submission_token": token,
        "email": email,
        "purchase_reference": reference,
        "message": payload["message"],
    }

    for attempt_payload in (payload, replay_payload):
        response = client.post(
            path,
            data=attempt_payload,
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"] == f"/refund-request/received?lang={lang}"
        receipt = client.get(response.headers["location"])
        assert 'role="status"' in receipt.text
        assert f'<html lang="{lang}">' in receipt.text
    assert "Refund request receipt could not be sent" in caplog.text
    assert not any(
        value in caplog.text for value in (email, reference, payload["message"])
    )
    sender.assert_called_once()
    assert sender.call_args.kwargs["to_email"] == email
    assert db_session.query(RefundRequest).count() == 1
    client.cookies.set(ADMIN_COOKIE_NAME, admin_token)
    admin = client.get("/admin/refund-requests")
    assert admin.status_code == 200
    assert admin.headers["cache-control"] == "private, no-store"
    assert reference in admin.text and email in admin.text
    assert "manual_review" in admin.text and "50.00 RUB" in admin.text
    assert "&lt;script&gt;test&lt;/script&gt;" in admin.text


def test_persistence_failure_rolls_back(db_session, monkeypatch):
    sale = create_pending_sale(db_session)
    sale.payment_status = PaymentStatus.PAID
    db_session.commit()
    email, reference = sale.customer_email, sale.sale_reference
    db_session.rollback()
    original_flush = Session.flush

    def fail_request_flush(session, *args, **kwargs):
        if any(isinstance(row, RefundRequest) for row in session.new):
            raise SQLAlchemyError("write failed")
        return original_flush(session, *args, **kwargs)

    monkeypatch.setattr(Session, "flush", fail_request_flush)
    sender = Mock()
    monkeypatch.setattr(refund_request_service.mail_service, "send_email", sender)
    with pytest.raises(refund_request_service.RefundRequestPersistenceError):
        refund_request_service.submit_refund_request(
            db_session,
            email=email,
            reference=reference,
            message="",
            language="en",
            submission_token=token_hex(32),
        )
    assert db_session.query(RefundRequest).count() == 0
    sender.assert_not_called()


def test_rate_limit_applies_before_validation(client):
    for _ in range(5):
        assert client.post("/refund-request").status_code == 400
    assert client.post("/refund-request?lang=ru").status_code == 429


def test_overlong_message_is_rejected_before_persistence(client, db_session):
    form = client.get("/refund-request?lang=en")
    response = client.post(
        "/refund-request?lang=en",
        data={
            **form_fields(form),
            "email": "buyer@example.com",
            "purchase_reference": "PAY-AAAAAAAAAAAAAA",
            "message": "x" * 2001,
        },
    )
    assert response.status_code == 400
    assert "2,000 characters" in response.text
    assert db_session.query(RefundRequest).count() == 0


@pytest.mark.parametrize("status", ["pending", "reconciliation_required"])
def test_existing_operation_remains_visible_and_allows_request(
    auth_client, db_session, status
):
    sale = create_pending_sale(db_session)
    sale.payment_status = PaymentStatus.PAID
    operation = RefundOperation(
        sale_id=sale.id,
        status=status,
        amount=sale.amount,
        currency=sale.currency,
        payment_provider=sale.payment_provider,
        external_payment_id=sale.external_payment_id,
    )
    db_session.add(operation)
    db_session.commit()

    form = auth_client.get("/refund-request")

    response = auth_client.post(
        "/refund-request",
        data={
            **form_fields(form),
            "email": sale.customer_email,
            "purchase_reference": sale.sale_reference,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert db_session.query(RefundRequest).count() == 1
    page = auth_client.get("/admin/refund-requests")
    detail_path = f"/admin/sales/{sale.id}"
    assert f'href="{detail_path}"' in page.text
    assert f"<dd>{status}</dd>" in auth_client.get(detail_path).text
    db_session.refresh(operation)
    assert operation.status == status


@pytest.mark.parametrize(
    ("email_override", "reference_override"),
    [
        ("other@example.com", None),
        (None, "PAY-BBBBBBBBBBBBBB"),
    ],
)
def test_submission_token_cannot_be_reused_for_another_purchase(
    db_session, monkeypatch, email_override, reference_override
):
    sale = create_pending_sale(db_session)

    email = sale.customer_email
    reference = sale.sale_reference

    sale.payment_status = PaymentStatus.PAID
    db_session.commit()

    token = token_hex(32)
    sender = Mock()

    monkeypatch.setattr(
        refund_request_service.mail_service,
        "send_email",
        sender,
    )

    refund_request_service.submit_refund_request(
        db_session,
        email=email,
        reference=reference,
        message="Original request",
        language="en",
        submission_token=token,
    )

    with pytest.raises(
        refund_request_service.RefundRequestValidationError,
        match="refund_request_invalid_purchase",
    ):
        refund_request_service.submit_refund_request(
            db_session,
            email=email_override or email,
            reference=reference_override or reference,
            message="Modified request",
            language="en",
            submission_token=token,
        )

    assert db_session.query(RefundRequest).count() == 1
    sender.assert_called_once()
