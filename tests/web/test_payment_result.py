from contextlib import contextmanager
from decimal import Decimal
from unittest.mock import Mock

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.core.config import PAYMENT_RESULT_PATH, settings
from app.models.consultation_entitlement import ConsultationEntitlement
from app.models.download_entitlement import DownloadEntitlement
from app.models.purchase_email_delivery import PurchaseEmailDelivery
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from tests.api.test_lava_top_payment_webhook import WEBHOOK_URL, create_sale, payload

INVOICE_ID = "3fa85f64-5717-4562-b3fc-2c963f66afa6"


@contextmanager
def observe_result_reads(monkeypatch):
    statements = []

    def record(execution):
        statements.append(str(execution.statement))

    with monkeypatch.context() as patches:
        for target in (
            "httpx.post",
            "httpx.get",
            "app.services.payment_reconciliation_service.reconcile_payment_event",
            "app.services.purchase_email_delivery_service.deliver_purchase_email_after_payment_commit",
            "app.services.mail_service.send_email",
        ):
            patches.setattr(target, Mock(side_effect=AssertionError(target)))
        for method in ("flush", "commit"):
            patches.setattr(Session, method, Mock(side_effect=AssertionError(method)))

        event.listen(Session, "do_orm_execute", record)
        try:
            yield statements
        finally:
            event.remove(Session, "do_orm_execute", record)


def add_sale(db, *, status="pending", provider="lava_top"):
    db.add(
        Sale(
            customer_email="private-buyer@example.test",
            amount=Decimal("917.31"),
            currency="EUR",
            payment_provider=provider,
            payment_status=status,
            external_payment_id=INVOICE_ID,
        )
    )
    db.commit()


def assert_private_result(response, *, status=200):
    assert response.status_code == status
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert INVOICE_ID not in response.text
    assert "invoiceId" not in response.text
    assert "private-buyer@" not in response.text
    assert "917.31" not in response.text


@pytest.mark.parametrize(
    ("status", "browser_hint", "en", "ru"),
    [
        ("paid", "cancelled", "Payment confirmed", "Оплата подтверждена"),
        ("pending", "cancelled", "Payment is being verified", "Платёж проверяется"),
        ("failed", "success", "Payment unsuccessful", "Оплата не завершена"),
        ("refunded", "success", "Payment refunded", "Оплата возвращена"),
    ],
)
@pytest.mark.parametrize("lang", ["en", "ru"])
def test_result_displays_only_authoritative_state(
    client, db_session, monkeypatch, status, browser_hint, en, ru, lang
):
    add_sale(db_session, status=status)

    with observe_result_reads(monkeypatch) as statements:
        response = client.get(
            PAYMENT_RESULT_PATH,
            params={"invoiceId": INVOICE_ID, "status": browser_hint, "lang": lang},
        )

    assert_private_result(response)
    title = en if lang == "en" else ru
    other_lang = "en" if lang == "ru" else "ru"
    assert f'<h1 class="checkout-title">{title}</h1>' in response.text
    assert f'<html lang="{lang}">' in response.text
    assert f'href="?lang={other_lang}"' in response.text
    assert f"status={browser_hint}" not in response.text
    if status == "paid":
        message = (
            "Purchase access instructions are sent to the email address"
            if lang == "en"
            else "Инструкции по получению покупки отправляются на электронную почту"
        )
        assert message in response.text
    (statement,) = statements
    assert statement.splitlines()[0].strip() == "SELECT sales.payment_status"
    assert "sales.payment_provider =" in statement
    assert "sales.external_payment_id =" in statement
    assert "FOR UPDATE" not in statement.upper()
    assert db_session.query(Sale).one().payment_status == status


@pytest.mark.parametrize(
    "ids",
    [
        [],
        [""],
        ["../invalid"],
        ["a" * 512],
        [f" {INVOICE_ID}"],
        [INVOICE_ID, INVOICE_ID],
    ],
)
def test_missing_invalid_or_ambiguous_id_skips_lookup(
    client, db_session, monkeypatch, ids
):
    add_sale(db_session, status="paid")
    params = [("invoiceId", value) for value in ids]
    params.append(("status", "browser-status-secret"))

    with observe_result_reads(monkeypatch) as statements:
        response = client.get(PAYMENT_RESULT_PATH, params=params)

    assert_private_result(response)
    assert "Unable to confirm payment status" in response.text
    assert "browser-status-secret" not in response.text
    assert "contact support before making another payment" in response.text
    assert not statements


def test_result_requires_an_exact_lava_top_identity(client, db_session):
    add_sale(db_session, status="paid", provider="manual")
    params = {"invoiceId": INVOICE_ID, "lang": "ru"}
    response = client.get(PAYMENT_RESULT_PATH, params=params)
    assert_private_result(response)
    assert "Не удалось подтвердить статус оплаты" in response.text

    add_sale(db_session, status="pending")
    response = client.get(PAYMENT_RESULT_PATH, params=params)
    assert_private_result(response)
    assert "Платёж проверяется" in response.text

    params["invoiceId"] = INVOICE_ID.upper()
    response = client.get(PAYMENT_RESULT_PATH, params=params)
    assert_private_result(response)
    assert "Не удалось подтвердить статус оплаты" in response.text


def test_return_and_refresh_leave_fulfillment_to_authenticated_webhook(
    client, db_session, monkeypatch
):
    sale = create_sale(db_session)
    sale.external_payment_id = INVOICE_ID
    db_session.commit()
    monkeypatch.setattr(settings, "LAVA_TOP_WEBHOOK_SECRET", "browser-return-test-key")
    monkeypatch.setattr(settings, "PURCHASE_EMAIL_DELIVERY_ENABLED", False)
    params = {"invoiceId": INVOICE_ID, "status": "success"}

    with observe_result_reads(monkeypatch) as statements:
        before = client.get(PAYMENT_RESULT_PATH, params=params)
    assert_private_result(before)
    assert "Payment is being verified" in before.text
    assert len(statements) == 1
    assert db_session.query(Sale).one().payment_status == "pending"
    assert db_session.query(SaleItem).count() == 1
    assert db_session.query(DownloadEntitlement).count() == 0
    assert db_session.query(ConsultationEntitlement).count() == 0
    assert db_session.query(PurchaseEmailDelivery).count() == 0

    webhook = client.post(
        WEBHOOK_URL,
        headers={"X-Api-Key": "browser-return-test-key"},
        json=payload(invoice_id=INVOICE_ID),
    )
    assert webhook.status_code == 204
    token = db_session.query(DownloadEntitlement).one().download_token

    with observe_result_reads(monkeypatch) as statements:
        for _ in range(2):
            after = client.get(PAYMENT_RESULT_PATH, params=params)
            assert_private_result(after)
            assert "Payment confirmed" in after.text
            assert token not in after.text
            assert "SmartBudget.zip" not in after.text

    assert len(statements) == 2
    db_session.expire_all()
    assert db_session.query(Sale).one().payment_status == "paid"
    assert db_session.query(SaleItem).count() == 1
    assert db_session.query(DownloadEntitlement).one().download_token == token
    assert db_session.query(ConsultationEntitlement).count() == 0
    assert db_session.query(PurchaseEmailDelivery).count() == 1


def test_result_method_error_keeps_privacy_headers(client):
    assert_private_result(client.post(PAYMENT_RESULT_PATH), status=405)
