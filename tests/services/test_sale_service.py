from decimal import Decimal

import pytest

from app.models.enums import PaymentStatus
from app.models.product import Product
from app.models.product_release import ProductRelease
from app.models.sale_item import SaleItem
from app.models.service_addon import ServiceAddon
from app.services.sale_service import create_service_sale_item
from app.services.sale_service import create_product_sale
from app.services.sale_service import create_standalone_service_sale


def create_product_release(db_session, product: Product) -> ProductRelease:
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


def test_create_product_sale_creates_sale_and_sale_item(db_session):
    product = Product(
        family_slug="smartbudget",
        slug="smartbudget-int-standard-sale-service-test",
        name="SmartBudget",
        edition="Standard",

        archive_path="archives/smartbudget.zip",
        status="in_sale",
    )
    db_session.add(product)
    db_session.commit()
    release = create_product_release(db_session, product)

    sale = create_product_sale(
        db_session,
        product=product,
        product_release=release,
        customer_email="customer@example.com",
        amount=Decimal("39.00"),
        currency="EUR",
        payment_status=PaymentStatus.PAID,
    )

    db_session.commit()

    items = (
        db_session.query(SaleItem)
        .filter(SaleItem.sale_id == sale.id)
        .all()
    )

    assert sale.id is not None
    assert len(items) == 1

    item = items[0]

    assert item.item_type == "product"
    assert item.product_id == product.id
    assert item.product_release_id == release.id
    assert item.service_addon_id is None
    assert item.amount == Decimal("39.00")
    assert item.currency_code == "EUR"


def test_create_service_sale_item_builds_service_item(db_session):
    product = Product(
        family_slug="smartbudget",
        slug="smartbudget-int-standard-service-item-helper-test",
        name="SmartBudget",
        edition="Standard",

        archive_path="archives/smartbudget.zip",
        status="in_sale",
    )
    db_session.add(product)
    db_session.flush()
    release = create_product_release(db_session, product)

    service_addon = ServiceAddon(
        code="consultation_1h_int_service_item_helper_test",
        name="1:1 consultation",
        service_type="consultation",
        usage_type="addon",
        family_slug="smartbudget",
        package_code="INT",
        currency_code="EUR",
        amount=Decimal("35.00"),
        is_active=True,
    )
    db_session.add(service_addon)
    db_session.flush()

    sale = create_product_sale(
        db_session,
        product=product,
        product_release=release,
        customer_email="customer@example.com",
        amount=Decimal("74.00"),
        currency="EUR",
        payment_status=PaymentStatus.PAID,
    )

    service_item = create_service_sale_item(
        sale=sale,
        service_addon_id=service_addon.id,
        item_name="1:1 consultation",
        currency_code="EUR",
        amount=Decimal("35.00"),
    )
    db_session.add(service_item)
    db_session.commit()

    assert service_item.id is not None
    assert service_item.sale_id == sale.id
    assert service_item.item_type == "service"
    assert service_item.product_id is None
    assert service_item.service_addon_id == service_addon.id
    assert service_item.amount == Decimal("35.00")


def test_create_product_sale_rejects_missing_release(db_session):
    product = Product(
        family_slug="smartbudget",
        slug="smartbudget-missing-release-sale-test",
        name="SmartBudget",
        edition="Standard",
        archive_path="archives/smartbudget.zip",
        status="in_sale",
    )
    db_session.add(product)
    db_session.flush()

    with pytest.raises(ValueError, match="require a product release"):
        create_product_sale(
            db_session,
            product=product,
            product_release=None,
            customer_email="customer@example.com",
            amount=Decimal("39.00"),
            currency="EUR",
        )


def test_create_standalone_service_sale_creates_service_only_sale(db_session):
    service_addon = ServiceAddon(
        code="consultation_1h_int_standalone_sale_test",
        name="Standalone consultation",
        service_type="consultation",
        usage_type="standalone",
        family_slug="smartbudget",
        package_code="INT",
        currency_code="EUR",
        amount=Decimal("79.00"),
        is_active=True,
    )
    db_session.add(service_addon)
    db_session.commit()

    sale = create_standalone_service_sale(
        db=db_session,
        service_addon_id=service_addon.id,
        service_name="Standalone consultation",
        customer_email="customer@example.com",
        amount=Decimal("79.00"),
        currency="EUR",
        payment_status=PaymentStatus.PAID,
    )

    db_session.commit()

    db_session.refresh(sale)

    assert sale.id is not None
    assert sale.product_id is None

    items = (
        db_session.query(SaleItem)
        .filter(SaleItem.sale_id == sale.id)
        .all()
    )

    assert len(items) == 1

    item = items[0]

    assert item.item_type == "service"
    assert item.product_id is None
    assert item.service_addon_id == service_addon.id
    assert item.amount == Decimal("79.00")
