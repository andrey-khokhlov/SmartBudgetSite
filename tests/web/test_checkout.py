from decimal import Decimal

from app.models.product import Product
from app.models.product_price import ProductPrice
from app.models.service_addon import ServiceAddon


def test_checkout_with_consultation_shows_product_addon_and_total(client, db_session):
    """
    Test case: checkout page with consultation add-on

    What we verify:
    - Product price is shown separately.
    - Consultation add-on price is shown separately.
    - Total amount includes both product and add-on.
    """

    product = Product(
        family_slug="smartbudget",
        slug="smartbudget-ru-standard-checkout-addon-test",
        name="SmartBudget",
        edition="Standard",

        archive_path="",
        status="in_sale",
    )
    db_session.add(product)
    db_session.commit()

    price = ProductPrice(
        product_id=product.id,
        currency_code="RUB",
        amount=Decimal("3900.00"),
        is_active=True,
    )
    db_session.add(price)

    addon = ServiceAddon(
        code="smartbudget_ru_consultation_1h_checkout_test",
        name="Личная консультация",
        service_type="consultation",
        usage_type="addon",
        family_slug="smartbudget",
        package_code="RU",
        currency_code="RUB",
        amount=Decimal("3500.00"),
        is_active=True,
    )
    db_session.add(addon)
    db_session.commit()

    response = client.get(
        "/checkout/smartbudget-ru-standard-checkout-addon-test?consultation=1"
    )

    assert response.status_code == 200
    assert "3,900.00 RUB" in response.text
    assert "3,500.00 RUB" in response.text
    assert "7,400.00 RUB" in response.text


def test_checkout_with_consultation_rejects_currency_mismatch(client, db_session):
    """
    Test case: checkout rejects product/add-on currency mismatch

    What we verify:
    - Checkout does not silently calculate totals across different currencies.
    - Currency mismatch returns server error until data is fixed.
    """

    product = Product(
        family_slug="smartbudget",
        slug="smartbudget-ru-standard-currency-mismatch-test",
        name="SmartBudget",
        edition="Standard",

        archive_path="",
        status="in_sale",
    )
    db_session.add(product)
    db_session.commit()

    price = ProductPrice(
        product_id=product.id,
        currency_code="RUB",
        amount=Decimal("3900.00"),
        is_active=True,
    )
    db_session.add(price)

    addon = ServiceAddon(
        code="smartbudget_ru_consultation_1h_currency_mismatch_test",
        name="Личная консультация",
        service_type="consultation",
        usage_type="addon",
        family_slug="smartbudget",
        package_code="RU",
        currency_code="EUR",
        amount=Decimal("35.00"),
        is_active=True,
    )
    db_session.add(addon)
    db_session.commit()

    response = client.get(
        "/checkout/smartbudget-ru-standard-currency-mismatch-test?consultation=1"
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "Currency mismatch between product and addon"


def test_checkout_with_consultation_uses_addon_usage_type_only(client, db_session):
    """
    Test case: checkout uses only consultation add-on usage type

    What we verify:
    - Checkout ignores standalone consultation records.
    - Checkout uses only usage_type='addon' for product checkout add-ons.
    - Standalone consultation price does not leak into product checkout.
    """

    product = Product(
        family_slug="smartbudget",
        slug="smartbudget-ru-standard-addon-usage-type-test",
        name="SmartBudget",
        edition="Standard",

        archive_path="",
        status="in_sale",
    )
    db_session.add(product)
    db_session.commit()

    price = ProductPrice(
        product_id=product.id,
        currency_code="RUB",
        amount=Decimal("3900.00"),
        is_active=True,
    )
    db_session.add(price)

    standalone_addon = ServiceAddon(
        code="smartbudget_ru_consultation_standalone_checkout_test",
        name="Standalone consultation",
        service_type="consultation",
        usage_type="standalone",
        family_slug="smartbudget",
        package_code="RU",
        currency_code="RUB",
        amount=Decimal("7900.00"),
        is_active=True,
    )
    db_session.add(standalone_addon)

    checkout_addon = ServiceAddon(
        code="smartbudget_ru_consultation_addon_checkout_test",
        name="Add-on consultation",
        service_type="consultation",
        usage_type="addon",
        family_slug="smartbudget",
        package_code="RU",
        currency_code="RUB",
        amount=Decimal("3500.00"),
        is_active=True,
    )
    db_session.add(checkout_addon)

    db_session.commit()

    response = client.get(
        "/checkout/smartbudget-ru-standard-addon-usage-type-test?consultation=1"
    )

    assert response.status_code == 200
    assert "3,500.00 RUB" in response.text
    assert "7,900.00 RUB" not in response.text
    assert "7,400.00 RUB" in response.text
