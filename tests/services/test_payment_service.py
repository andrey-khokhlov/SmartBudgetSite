from decimal import Decimal

import pytest

from app.core.config import settings
from app.models.product import Product
from app.models.product_release import ProductRelease
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.services.payment_service import (
    ProductReleaseUnavailableError,
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
