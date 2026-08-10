from decimal import Decimal

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.models.consultation_entitlement import ConsultationEntitlement
from app.models.download_entitlement import DownloadEntitlement
from app.models.payment_provider_offer import PaymentProviderOffer
from app.models.product import Product
from app.models.product_release import ProductRelease
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.services.lava_top.client import LavaTopInvoice, LavaTopRequestError
from app.services.payment_service import (
    LAVA_TOP_PROVIDER,
    PaymentCheckoutError,
    PaymentReconciliationRequiredError,
    ProductReleaseUnavailableError,
    create_lava_top_checkout,
    prepare_product_payment,
)


def create_product(db_session, slug: str) -> Product:
    product = Product(
        family_slug="smartbudget",
        slug=slug,
        name="SmartBudget",
        edition="Standard",
        archive_path="archives/smartbudget.zip",
        status="in_sale",
    )
    db_session.add(product)
    db_session.flush()
    return product


def create_active_release(db_session, product: Product) -> ProductRelease:
    release = ProductRelease(
        product_id=product.id,
        version="1.0",
        storage_provider="cloudflare_r2",
        storage_key=f"product-releases/{product.slug}/1.0.zip",
        original_filename="SmartBudget_1.0.zip",
        is_active=True,
    )
    db_session.add(release)
    db_session.flush()
    return release


def create_pending_lava_sale(
    db_session,
    slug: str = "lava-checkout-test",
    *,
    amount: Decimal = Decimal("50.00"),
    currency: str = "RUB",
) -> Sale:
    product = create_product(db_session, slug)
    create_active_release(db_session, product)
    return prepare_product_payment(
        db_session,
        product=product,
        customer_email="buyer@example.com",
        amount=amount,
        currency=currency,
        payment_provider=LAVA_TOP_PROVIDER,
    )


def add_lava_offer(db_session, sale: Sale) -> PaymentProviderOffer:
    offer = PaymentProviderOffer(
        product_id=sale.product_id,
        provider=LAVA_TOP_PROVIDER,
        external_offer_id="database-offer-id",
    )
    db_session.add(offer)
    db_session.flush()
    return offer


def test_prepare_product_payment_stores_active_release(db_session):
    product = create_product(db_session, "payment-preparation-release-test")
    release = create_active_release(db_session, product)

    sale = prepare_product_payment(
        db_session,
        product=product,
        customer_email="customer@example.com",
        amount=Decimal("39.00"),
        currency="EUR",
        payment_provider="stripe",
    )

    item = db_session.query(SaleItem).filter_by(sale_id=sale.id).one()
    assert sale.payment_status == "pending"
    assert sale.external_payment_id is None
    assert item.product_release_id == release.id


def test_missing_active_release_blocks_sale_and_notifies_admin(
    db_session,
    monkeypatch,
):
    product = create_product(db_session, "payment-preparation-unavailable-test")
    sent_messages = []
    monkeypatch.setattr(settings, "ADMIN_NOTIFICATION_EMAIL", "admin@example.com")
    monkeypatch.setattr(
        "app.services.mail_service.send_email",
        lambda **kwargs: sent_messages.append(kwargs),
    )

    with pytest.raises(ProductReleaseUnavailableError) as exc_info:
        prepare_product_payment(
            db_session,
            product=product,
            customer_email="customer@example.com",
            amount=Decimal("39.00"),
            currency="EUR",
            payment_provider="stripe",
        )

    assert str(exc_info.value) == "The selected product is temporarily unavailable."
    assert db_session.query(Sale).count() == 0
    assert len(sent_messages) == 1
    assert sent_messages[0]["to_email"] == "admin@example.com"


def test_smtp_failure_is_logged_without_changing_unavailable_result(
    db_session,
    monkeypatch,
    caplog,
):
    product = create_product(db_session, "payment-preparation-smtp-failure-test")

    def fail_email(**kwargs):
        raise OSError("SMTP unavailable")

    monkeypatch.setattr("app.services.mail_service.send_email", fail_email)

    with caplog.at_level("ERROR"), pytest.raises(ProductReleaseUnavailableError):
        prepare_product_payment(
            db_session,
            product=product,
            customer_email="customer@example.com",
            amount=Decimal("39.00"),
            currency="EUR",
            payment_provider="stripe",
        )

    assert db_session.query(Sale).count() == 0
    assert "Failed to send missing active product release notification" in caplog.text


def test_create_lava_top_checkout_persists_invoice_and_returns_url(
    db_session,
    monkeypatch,
):
    sale = create_pending_lava_sale(db_session, "lava-checkout-success-test")
    add_lava_offer(db_session, sale)
    captured = {}

    def fake_create_invoice(**kwargs):
        captured.update(kwargs)
        return LavaTopInvoice(
            invoice_id="lava-invoice-123",
            payment_url="https://pay.example/hosted",
        )

    monkeypatch.setattr(
        "app.services.payment_service.create_invoice",
        fake_create_invoice,
    )

    payment_url = create_lava_top_checkout(db_session, sale=sale)

    db_session.refresh(sale)
    assert captured == {
        "email": "buyer@example.com",
        "offer_id": "database-offer-id",
        "currency": "RUB",
        "amount": Decimal("50.00"),
    }
    assert payment_url == "https://pay.example/hosted"
    assert sale.external_payment_id == "lava-invoice-123"
    assert sale.payment_status == "pending"
    assert db_session.query(DownloadEntitlement).count() == 0
    assert db_session.query(ConsultationEntitlement).count() == 0


def test_shared_lava_offer_uses_each_sale_currency_and_amount(
    db_session,
    monkeypatch,
):
    rub_sale = create_pending_lava_sale(
        db_session,
        "lava-shared-offer-rub-test",
        amount=Decimal("50.00"),
        currency="RUB",
    )
    eur_sale = create_pending_lava_sale(
        db_session,
        "lava-shared-offer-eur-test",
        amount=Decimal("39.00"),
        currency="EUR",
    )
    add_lava_offer(db_session, rub_sale)
    add_lava_offer(db_session, eur_sale)
    captured_requests = []

    def fake_create_invoice(**kwargs):
        captured_requests.append(kwargs)
        return LavaTopInvoice(
            invoice_id=f"lava-shared-invoice-{len(captured_requests)}",
            payment_url=f"https://pay.example/shared/{len(captured_requests)}",
        )

    monkeypatch.setattr(
        "app.services.payment_service.create_invoice",
        fake_create_invoice,
    )

    create_lava_top_checkout(db_session, sale=rub_sale)
    create_lava_top_checkout(db_session, sale=eur_sale)

    assert captured_requests == [
        {
            "email": "buyer@example.com",
            "offer_id": "database-offer-id",
            "currency": "RUB",
            "amount": Decimal("50.00"),
        },
        {
            "email": "buyer@example.com",
            "offer_id": "database-offer-id",
            "currency": "EUR",
            "amount": Decimal("39.00"),
        },
    ]


def test_create_lava_top_checkout_missing_mapping_marks_sale_failed(db_session):
    sale = create_pending_lava_sale(db_session, "lava-checkout-no-mapping-test")

    with pytest.raises(PaymentCheckoutError):
        create_lava_top_checkout(db_session, sale=sale)

    db_session.refresh(sale)
    assert sale.payment_status == "failed"
    assert sale.external_payment_id is None


def test_create_lava_top_checkout_missing_api_key_marks_sale_failed(
    db_session,
    monkeypatch,
):
    sale = create_pending_lava_sale(db_session, "lava-checkout-no-key-test")
    add_lava_offer(db_session, sale)
    monkeypatch.setattr(settings, "LAVA_TOP_API_KEY", "")

    with pytest.raises(PaymentCheckoutError):
        create_lava_top_checkout(db_session, sale=sale)

    db_session.refresh(sale)
    assert sale.payment_status == "failed"
    assert sale.external_payment_id is None


def test_create_lava_top_checkout_provider_failure_marks_sale_failed(
    db_session,
    monkeypatch,
):
    sale = create_pending_lava_sale(db_session, "lava-checkout-provider-failure-test")
    add_lava_offer(db_session, sale)

    def fail_create_invoice(**kwargs):
        raise LavaTopRequestError("provider unavailable")

    monkeypatch.setattr(
        "app.services.payment_service.create_invoice",
        fail_create_invoice,
    )

    with pytest.raises(PaymentCheckoutError):
        create_lava_top_checkout(db_session, sale=sale)

    db_session.refresh(sale)
    assert sale.payment_status == "failed"
    assert sale.external_payment_id is None
    assert db_session.query(DownloadEntitlement).count() == 0
    assert db_session.query(ConsultationEntitlement).count() == 0


def test_invoice_persistence_failure_requires_reconciliation(
    db_session,
    monkeypatch,
):
    sale = create_pending_lava_sale(
        db_session,
        "lava-checkout-persistence-failure-test",
    )
    add_lava_offer(db_session, sale)
    provider_calls = 0
    rollback_calls = 0
    provider_invoice_id = "lava-invoice-reconcile-123"
    payment_url = "https://pay.example/hosted?token=payment-url-secret"
    api_key = "api-key-must-not-be-exposed"

    def fake_create_invoice(**kwargs):
        nonlocal provider_calls
        provider_calls += 1
        return LavaTopInvoice(
            invoice_id=provider_invoice_id,
            payment_url=payment_url,
        )

    def fail_commit():
        raise SQLAlchemyError("simulated identity persistence failure")

    real_rollback = db_session.rollback

    def tracked_rollback():
        nonlocal rollback_calls
        rollback_calls += 1
        real_rollback()

    monkeypatch.setattr(settings, "LAVA_TOP_API_KEY", api_key)
    monkeypatch.setattr(
        "app.services.payment_service.create_invoice",
        fake_create_invoice,
    )
    monkeypatch.setattr(db_session, "commit", fail_commit)
    monkeypatch.setattr(db_session, "rollback", tracked_rollback)

    with pytest.raises(PaymentReconciliationRequiredError) as exc_info:
        create_lava_top_checkout(db_session, sale=sale)

    error = exc_info.value
    exposed_error = f"{error!s} {error!r} {vars(error)!r}"
    assert error.provider_invoice_id == provider_invoice_id
    assert vars(error) == {"provider_invoice_id": provider_invoice_id}
    assert error.args == ("Payment reconciliation is required.",)
    assert payment_url not in exposed_error
    assert api_key not in exposed_error
    assert provider_calls == 1
    assert rollback_calls == 1
    assert db_session.query(Sale).filter_by(payment_status="paid").count() == 0
    assert db_session.query(DownloadEntitlement).count() == 0
    assert db_session.query(ConsultationEntitlement).count() == 0
