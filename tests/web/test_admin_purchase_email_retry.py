from decimal import Decimal

from app.core.config import settings
from app.models.enums import PaymentStatus
from app.models.purchase_email_delivery import (
    PurchaseEmailDelivery,
    PurchaseEmailDeliveryStatus,
)
from app.models.sale import Sale
from app.services.email_transport import (
    EmailTransportDefinitiveError,
    EmailTransportResult,
)
from app.services.payment_delivery_orchestration_service import (
    reconcile_payment_and_deliver,
)
from app.services.purchase_email_delivery_service import PurchaseEmailAttemptResult
from tests.services.test_purchase_email_delivery_service import (
    RecordingTransport,
    configure_email,
    create_pending_sale,
    payment_event,
)


def create_sale_with_delivery(db_session, *, status: str) -> Sale:
    sale = Sale(
        customer_email="buyer@example.test",
        amount=Decimal("39.00"),
        currency="EUR",
        payment_status=PaymentStatus.PAID,
    )
    sale.purchase_email_delivery = PurchaseEmailDelivery(status=status)
    db_session.add(sale)
    db_session.commit()
    return sale


def test_admin_sales_shows_normal_retry_but_not_reconciliation_resend(
    auth_client, db_session
):
    create_sale_with_delivery(
        db_session,
        status=PurchaseEmailDeliveryStatus.FAILED.value,
    )
    create_sale_with_delivery(
        db_session,
        status=PurchaseEmailDeliveryStatus.RECONCILIATION_REQUIRED.value,
    )

    response = auth_client.get("/admin/sales")

    assert response.status_code == 200
    assert response.text.count("Retry email") == 1
    assert response.text.count("Authorize resend") == 1
    assert PurchaseEmailDeliveryStatus.RECONCILIATION_REQUIRED.value in response.text


def test_admin_retry_delegates_to_delivery_service(
    auth_client, db_session, monkeypatch
):
    sale = create_sale_with_delivery(
        db_session,
        status=PurchaseEmailDeliveryStatus.FAILED.value,
    )
    called_sale_ids = []

    def fake_delivery(db, *, sale_id):
        called_sale_ids.append(sale_id)
        return PurchaseEmailAttemptResult.SENT

    monkeypatch.setattr(
        "app.web.routes.deliver_purchase_email_after_payment_commit",
        fake_delivery,
    )
    response = auth_client.post(
        f"/admin/sales/{sale.id}/purchase-email/retry",
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/admin/sales?email_result=sent"
    assert called_sale_ids == [sale.id]


def test_admin_retry_uses_saved_language_and_original_key(
    auth_client, db_session, monkeypatch
):
    configure_email(monkeypatch)
    monkeypatch.setattr(settings, "PURCHASE_EMAIL_DELIVERY_ENABLED", True)
    sale = create_pending_sale(db_session, kind="bundle", language="ru")
    first = RecordingTransport(failure=EmailTransportDefinitiveError("rejected"))
    reconcile_payment_and_deliver(db_session, payment_event(sale), transport=first)
    retried = []

    def fake_send(_transport, message):
        retried.append(message)
        return EmailTransportResult(provider_message_id="retried")

    monkeypatch.setattr(
        "app.services.resend_email_transport.ResendEmailTransport.send", fake_send
    )
    response = auth_client.post(
        f"/admin/sales/{sale.id}/purchase-email/retry?lang=en", follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/sales?email_result=sent"
    assert retried == first.messages
    assert retried[0].subject == "SmartBudget — ваша покупка и запись на консультацию"
    db_session.refresh(sale)
    assert sale.purchase_language == "ru"
    assert sale.payment_status == PaymentStatus.PAID


def test_admin_reconciliation_resend_requires_separate_confirmation(
    auth_client, db_session, monkeypatch
):
    sale = create_sale_with_delivery(
        db_session,
        status=PurchaseEmailDeliveryStatus.RECONCILIATION_REQUIRED.value,
    )
    calls = []

    def fake_authorize(db, *, sale_id, provider_confirmed_not_sent):
        calls.append((sale_id, provider_confirmed_not_sent))
        return PurchaseEmailAttemptResult.SENT

    monkeypatch.setattr(
        "app.web.routes.authorize_reconciliation_resend",
        fake_authorize,
    )
    rejected = auth_client.post(
        f"/admin/sales/{sale.id}/purchase-email/authorize-resend",
        data={"authorization": "unconfirmed"},
        follow_redirects=False,
    )
    accepted = auth_client.post(
        f"/admin/sales/{sale.id}/purchase-email/authorize-resend",
        data={"authorization": "provider_confirmed_not_sent"},
        follow_redirects=False,
    )

    assert rejected.status_code == 400
    assert accepted.status_code == 303
    assert calls == [(sale.id, True)]
