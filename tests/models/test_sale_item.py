from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.product import Product
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.models.service_addon import ServiceAddon
from app.models.enums import PaymentStatus


def test_sale_item_product_can_be_created(db_session):
    product = Product(
        family_slug="smartbudget",
        slug="smartbudget-int-standard-sale-item-test",
        name="SmartBudget",
        edition="Standard",

        archive_path="archives/smartbudget.zip",
        status="in_sale",
    )
    db_session.add(product)
    db_session.flush()

    sale = Sale(
        product_id=product.id,
        customer_email="customer@example.com",
        amount=Decimal("39.00"),
        currency="EUR",
        payment_status=PaymentStatus.PAID,
    )
    db_session.add(sale)
    db_session.flush()

    item = SaleItem(
        sale_id=sale.id,
        item_type="product",
        product_id=product.id,
        item_name="SmartBudget INT Standard",
        currency_code="EUR",
        amount=Decimal("39.00"),
        quantity=1,
    )
    db_session.add(item)
    db_session.commit()

    assert item.id is not None
    assert item.sale_id == sale.id
    assert item.product_id == product.id
    assert item.product_release_id is None
    assert item.service_addon_id is None

    db_session.expire_all()
    legacy_item = db_session.get(SaleItem, item.id)
    assert legacy_item is not None
    assert legacy_item.product_release_id is None


def test_sale_item_service_can_be_created(db_session):
    product = Product(
        family_slug="smartbudget",
        slug="smartbudget-int-standard-sale-item-service-test",
        name="SmartBudget",
        edition="Standard",

        archive_path="archives/smartbudget.zip",
        status="in_sale",
    )
    db_session.add(product)
    db_session.flush()

    service_addon = ServiceAddon(
        code="consultation_1h_int_sale_item_test",
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

    sale = Sale(
        product_id=product.id,
        customer_email="customer@example.com",
        amount=Decimal("74.00"),
        currency="EUR",
        payment_status=PaymentStatus.PAID,
    )
    db_session.add(sale)
    db_session.flush()

    item = SaleItem(
        sale_id=sale.id,
        item_type="service",
        service_addon_id=service_addon.id,
        item_name="1:1 consultation",
        currency_code="EUR",
        amount=Decimal("35.00"),
        quantity=1,
    )
    db_session.add(item)
    db_session.commit()

    assert item.id is not None
    assert item.sale_id == sale.id
    assert item.product_id is None
    assert item.service_addon_id == service_addon.id


def test_sale_item_requires_exactly_one_reference(db_session):
    product = Product(
        family_slug="smartbudget",
        slug="smartbudget-int-standard-sale-item-invalid-test",
        name="SmartBudget",
        edition="Standard",

        archive_path="archives/smartbudget.zip",
        status="in_sale",
    )
    db_session.add(product)
    db_session.flush()

    sale = Sale(
        product_id=product.id,
        customer_email="customer@example.com",
        amount=Decimal("39.00"),
        currency="EUR",
        payment_status=PaymentStatus.PAID,
    )
    db_session.add(sale)
    db_session.flush()

    item = SaleItem(
        sale_id=sale.id,
        item_type="product",
        product_id=None,
        service_addon_id=None,
        item_name="Invalid item",
        currency_code="EUR",
        amount=Decimal("39.00"),
        quantity=1,
    )
    db_session.add(item)

    with pytest.raises(IntegrityError):
        db_session.commit()
