from decimal import Decimal

import pytest

from app.models.download_entitlement import DownloadEntitlement
from app.models.enums import PaymentStatus
from app.models.product import Product
from app.models.product_release import ProductRelease
from app.models.purchase_email_delivery import (
    PurchaseEmailDelivery,
    PurchaseEmailDeliveryStatus,
)
from app.core.config import settings
from app.services.email_transport import EmailTransportResult
from app.services.lava_top.client import LavaTopInvoiceDetails, LavaTopInvoiceStatus
from app.services.payment_reconciliation_service import (
    PaymentReconciliationMismatchError,
)
from app.services.sale_service import create_product_sale
from scripts.reconcile_lava_top_invoice import (
    InvoiceNotTerminalError,
    reconcile_lava_top_invoice,
)


def create_sale(
    db_session,
    *,
    suffix: str = "",
    external_payment_id: str = "manual-invoice",
):
    product = Product(
        family_slug="smartbudget",
        slug=f"manual-lava-reconciliation{suffix}",
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
        storage_key=f"product-releases/manual-lava-reconciliation{suffix}/1.0.zip",
        original_filename="SmartBudget.zip",
        is_active=True,
    )
    db_session.add(release)
    db_session.flush()
    sale = create_product_sale(
        db_session,
        product=product,
        product_release=release,
        customer_email="buyer@example.com",
        amount=Decimal("50.00"),
        currency="RUB",
        payment_provider="lava_top",
        external_payment_id=external_payment_id,
    )
    db_session.commit()
    return sale


def invoice(status=LavaTopInvoiceStatus.COMPLETED):
    return LavaTopInvoiceDetails(
        invoice_id="manual-invoice",
        status=status,
        amount=Decimal("50.00"),
        currency="RUB",
    )


def test_manual_path_reuses_domain_reconciliation_and_commits(db_session):
    sale = create_sale(db_session)

    result = reconcile_lava_top_invoice(
        db_session,
        sale_id=sale.id,
        external_payment_id="manual-invoice",
        invoice_lookup=lambda invoice_id: invoice(),
    )

    db_session.expire_all()
    assert result.sale_id == sale.id
    assert db_session.get(type(sale), sale.id).payment_status == PaymentStatus.PAID
    assert db_session.query(DownloadEntitlement).count() == 1
    assert db_session.query(PurchaseEmailDelivery).count() == 1


def test_manual_path_attempts_purchase_email_after_commit(
    db_session, monkeypatch
):
    sale = create_sale(db_session)
    monkeypatch.setattr(settings, "PURCHASE_EMAIL_DELIVERY_ENABLED", True)
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "https://app.example.test")
    monkeypatch.setattr(settings, "MAIL_FROM_EMAIL", "support@example.test")
    monkeypatch.setattr(settings, "MAIL_FROM_NAME", "SmartBudget")
    sent_messages = []

    def fake_send(_transport, message):
        sent_messages.append(message)
        return EmailTransportResult(provider_message_id="manual-resend-id")

    monkeypatch.setattr(
        "app.services.resend_email_transport.ResendEmailTransport.send",
        fake_send,
    )

    reconcile_lava_top_invoice(
        db_session,
        sale_id=sale.id,
        external_payment_id="manual-invoice",
        invoice_lookup=lambda invoice_id: invoice(),
    )

    delivery = db_session.query(PurchaseEmailDelivery).one()
    assert delivery.status == PurchaseEmailDeliveryStatus.SENT.value
    assert len(sent_messages) == 1


def test_manual_failed_reconciliation_does_not_attempt_purchase_email(
    db_session, monkeypatch
):
    sale = create_sale(db_session)
    monkeypatch.setattr(settings, "PURCHASE_EMAIL_DELIVERY_ENABLED", True)
    sent_messages = []

    def fake_send(_transport, message):
        sent_messages.append(message)
        return EmailTransportResult(provider_message_id="must-not-be-used")

    monkeypatch.setattr(
        "app.services.resend_email_transport.ResendEmailTransport.send",
        fake_send,
    )

    result = reconcile_lava_top_invoice(
        db_session,
        sale_id=sale.id,
        external_payment_id="manual-invoice",
        invoice_lookup=lambda invoice_id: invoice(LavaTopInvoiceStatus.FAILED),
    )

    db_session.expire_all()
    assert result.sale_id == sale.id
    assert db_session.get(type(sale), sale.id).payment_status == PaymentStatus.FAILED
    assert db_session.query(DownloadEntitlement).count() == 0
    assert db_session.query(PurchaseEmailDelivery).count() == 0
    assert sent_messages == []


def test_manual_path_rejects_nonterminal_and_wrong_sale_identity(db_session):
    sale = create_sale(db_session)

    with pytest.raises(InvoiceNotTerminalError):
        reconcile_lava_top_invoice(
            db_session,
            sale_id=sale.id,
            external_payment_id="manual-invoice",
            invoice_lookup=lambda invoice_id: invoice(LavaTopInvoiceStatus.IN_PROGRESS),
        )

    with pytest.raises(PaymentReconciliationMismatchError):
        reconcile_lava_top_invoice(
            db_session,
            sale_id=sale.id + 1,
            external_payment_id="manual-invoice",
            invoice_lookup=lambda invoice_id: invoice(),
        )


def test_manual_path_rejects_cross_sale_invoice_mismatch_without_mutation(
    db_session,
):
    sale_a = create_sale(
        db_session,
        suffix="-a",
        external_payment_id="manual-invoice-a",
    )
    sale_b = create_sale(
        db_session,
        suffix="-b",
        external_payment_id="manual-invoice-b",
    )

    with pytest.raises(PaymentReconciliationMismatchError):
        reconcile_lava_top_invoice(
            db_session,
            sale_id=sale_a.id,
            external_payment_id="manual-invoice-b",
            invoice_lookup=lambda invoice_id: LavaTopInvoiceDetails(
                invoice_id=invoice_id,
                status=LavaTopInvoiceStatus.COMPLETED,
                amount=Decimal("50.00"),
                currency="RUB",
            ),
        )

    db_session.expire_all()
    assert (
        db_session.get(type(sale_a), sale_a.id).payment_status == PaymentStatus.PENDING
    )
    assert (
        db_session.get(type(sale_b), sale_b.id).payment_status == PaymentStatus.PENDING
    )
    assert db_session.query(DownloadEntitlement).count() == 0
