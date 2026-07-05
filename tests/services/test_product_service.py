import pytest
from decimal import Decimal

from app.models.product import Product
from app.models.product_price import ProductPrice
from app.services.product_service import set_product_price
from fastapi import HTTPException


def test_set_product_price_creates_first_active_price(db_session):
    product = Product(
        family_slug="smartbudget",
        slug="smartbudget-ru-standard",
        name="SmartBudget RU Standard",
        edition="Standard",

        archive_path="products/smartbudget-ru-standard/v1/archive.zip",
        status="in_sale",
    )
    db_session.add(product)
    db_session.commit()
    db_session.refresh(product)

    result = set_product_price(
        db=db_session,
        product_id=product.id,
        currency_code="RUB",
        amount=Decimal("1490.00"),
    )

    prices = (
        db_session.query(ProductPrice)
        .filter(ProductPrice.product_id == product.id)
        .all()
    )

    assert result.id is not None
    assert result.product_id == product.id
    assert result.currency_code == "RUB"
    assert result.amount == Decimal("1490.00")
    assert result.is_active is True

    assert len(prices) == 1
    assert prices[0].is_active is True
    assert prices[0].amount == Decimal("1490.00")


def test_set_product_price_replaces_active_price(db_session):
    product = Product(
        family_slug="smartbudget",
        slug="smartbudget-ru-standard",
        name="SmartBudget RU Standard",
        edition="Standard",

        archive_path="products/smartbudget-ru-standard/v1/archive.zip",
        status="in_sale",
    )
    db_session.add(product)
    db_session.commit()
    db_session.refresh(product)

    # First price
    set_product_price(
        db=db_session,
        product_id=product.id,
        currency_code="RUB",
        amount=Decimal("1490.00"),
    )

    # Second price (new)
    result = set_product_price(
        db=db_session,
        product_id=product.id,
        currency_code="RUB",
        amount=Decimal("1990.00"),
    )

    prices = (
        db_session.query(ProductPrice)
        .filter(ProductPrice.product_id == product.id)
        .order_by(ProductPrice.id)
        .all()
    )

    assert len(prices) == 2

    old_price, new_price = prices

    assert old_price.is_active is False
    assert new_price.is_active is True
    assert new_price.amount == Decimal("1990.00")

    assert result.id == new_price.id


def test_set_product_price_rejects_unsupported_currency(db_session):
    product = Product(
        family_slug="smartbudget",
        slug="smartbudget-ru-standard",
        name="SmartBudget RU Standard",
        edition="Standard",

        archive_path="products/smartbudget-ru-standard/v1/archive.zip",
        status="in_sale",
    )
    db_session.add(product)
    db_session.commit()
    db_session.refresh(product)

    with pytest.raises(HTTPException) as exc_info:
        set_product_price(
            db=db_session,
            product_id=product.id,
            currency_code="USD",
            amount=Decimal("1490.00"),
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Unsupported currency: USD"
