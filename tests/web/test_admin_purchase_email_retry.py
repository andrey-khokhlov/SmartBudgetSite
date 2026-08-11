from decimal import Decimal

from app.models.enums import PaymentStatus
from app.models.purchase_email_delivery import (
    PurchaseEmailDelivery,
    PurchaseEmailDeliveryStatus,
)
from app.models.sale import Sale
from app.services.purchase_email_delivery_service import PurchaseEmailAttemptResult


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
