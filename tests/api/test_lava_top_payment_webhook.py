from decimal import Decimal

from app.core.config import settings
from app.models.download_entitlement import DownloadEntitlement
from app.models.enums import PaymentStatus
from app.models.product import Product
from app.models.product_release import ProductRelease
from app.services.sale_service import create_product_sale

WEBHOOK_URL = "/v1/webhooks/lava-top/payment-result"


def create_sale(db_session):
    product = Product(
        family_slug="smartbudget",
        slug="lava-webhook-product",
        name="SmartBudget",
        edition="Standard",
        archive_path="archives/smartbudget.zip",
        status="in_sale",
    )
    db_session.add(product)
    db_session.flush()
    release = ProductRelease(
        product_id=product.id,
        version="1.0",
        storage_provider="cloudflare_r2",
        storage_key="product-releases/lava-webhook-product/1.0.zip",
        original_filename="SmartBudget.zip",
        is_active=True,
    )
    db_session.add(release)
    db_session.flush()
    sale = create_product_sale(
        db_session,
        product=product,
        product_release=release,
        customer_email="private-buyer@example.com",
        amount=Decimal("50.00"),
        currency="RUB",
        payment_provider="lava_top",
        external_payment_id="invoice-webhook-1",
    )
    db_session.commit()
    return sale


def payload(event_type="payment.success", invoice_id="invoice-webhook-1"):
    return {
        "eventType": event_type,
        "contractId": invoice_id,
        "amount": 50,
        "currency": "RUB",
        "buyer": {"email": "must-not-be-logged@example.com"},
    }


def test_authenticated_success_commits_then_replay_is_safe(
    client, db_session, monkeypatch
):
    sale = create_sale(db_session)
    monkeypatch.setattr(settings, "LAVA_TOP_WEBHOOK_SECRET", "inbound-secret")
    headers = {"X-Api-Key": "inbound-secret"}

    first = client.post(WEBHOOK_URL, headers=headers, json=payload())
    second = client.post(WEBHOOK_URL, headers=headers, json=payload())

    db_session.expire_all()
    assert first.status_code == 204
    assert second.status_code == 204
    assert db_session.get(type(sale), sale.id).payment_status == PaymentStatus.PAID
    assert db_session.query(DownloadEntitlement).count() == 1


def test_wrong_or_missing_key_is_rejected_before_domain_processing(
    client, db_session, monkeypatch
):
    sale = create_sale(db_session)
    monkeypatch.setattr(settings, "LAVA_TOP_WEBHOOK_SECRET", "inbound-secret")

    missing = client.post(WEBHOOK_URL, json=payload())
    wrong = client.post(
        WEBHOOK_URL,
        headers={"X-Api-Key": "outbound-or-wrong-key"},
        json=payload(),
    )

    db_session.expire_all()
    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert db_session.get(type(sale), sale.id).payment_status == PaymentStatus.PENDING
    assert db_session.query(DownloadEntitlement).count() == 0


def test_malformed_json_and_unknown_invoice_are_controlled(
    client, db_session, monkeypatch
):
    create_sale(db_session)
    monkeypatch.setattr(settings, "LAVA_TOP_WEBHOOK_SECRET", "inbound-secret")
    headers = {"X-Api-Key": "inbound-secret"}

    malformed = client.post(
        WEBHOOK_URL,
        headers={**headers, "Content-Type": "application/json"},
        content=b"{",
    )
    unknown = client.post(
        WEBHOOK_URL,
        headers=headers,
        json=payload(invoice_id="unknown-private-invoice"),
    )

    assert malformed.status_code == 400
    assert unknown.status_code == 409
    assert "unknown-private-invoice" not in unknown.text
    assert "private-buyer@example.com" not in unknown.text


def test_failed_event_commits_no_fulfillment(client, db_session, monkeypatch):
    sale = create_sale(db_session)
    monkeypatch.setattr(settings, "LAVA_TOP_WEBHOOK_SECRET", "inbound-secret")

    response = client.post(
        WEBHOOK_URL,
        headers={"X-Api-Key": "inbound-secret"},
        json=payload(event_type="payment.failed"),
    )

    db_session.expire_all()
    assert response.status_code == 204
    assert db_session.get(type(sale), sale.id).payment_status == PaymentStatus.FAILED
    assert db_session.query(DownloadEntitlement).count() == 0
