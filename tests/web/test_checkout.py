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
        "/checkout/smartbudget-ru-standard-checkout-addon-test"
        "?currency=RUB&consultation=1"
    )

    assert response.status_code == 200
    assert "3,900.00 RUB" in response.text
    assert "3,500.00 RUB" in response.text
    assert "7,400.00 RUB" in response.text
    assert 'method="post"' in response.text
    assert (
        'action="/checkout/smartbudget-ru-standard-checkout-addon-test"'
        in response.text
    )
    assert 'name="customer_email"' in response.text
    assert 'name="currency" value="RUB"' in response.text
    assert 'name="consultation" value="1"' in response.text


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
        "/checkout/smartbudget-ru-standard-currency-mismatch-test"
        "?currency=RUB&consultation=1"
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
        "/checkout/smartbudget-ru-standard-addon-usage-type-test"
        "?currency=RUB&consultation=1"
    )

    assert response.status_code == 200
    assert "3,500.00 RUB" in response.text
    assert "7,900.00 RUB" not in response.text
    assert "7,400.00 RUB" in response.text


def test_checkout_selects_active_price_by_normalized_currency(client, db_session):
    product = Product(
        family_slug="smartbudget",
        slug="smartbudget-int-standard-currency-selection-test",
        name="SmartBudget",
        edition="Standard",
        archive_path="",
        status="in_sale",
    )
    db_session.add(product)
    db_session.flush()
    db_session.add_all(
        [
            ProductPrice(
                product_id=product.id,
                currency_code="EUR",
                amount=Decimal("39.00"),
                is_active=True,
            ),
            ProductPrice(
                product_id=product.id,
                currency_code="RUB",
                amount=Decimal("3900.00"),
                is_active=True,
            ),
        ]
    )
    db_session.commit()

    eur_response = client.get(
        f"/checkout/{product.slug}",
        params={"currency": " eur "},
    )
    rub_response = client.get(
        f"/checkout/{product.slug}",
        params={"currency": "RUB"},
    )

    assert eur_response.status_code == 200
    assert "39.00 EUR" in eur_response.text
    assert "3,900.00 RUB" not in eur_response.text
    assert rub_response.status_code == 200
    assert "3,900.00 RUB" in rub_response.text
    assert "39.00 EUR" not in rub_response.text


def test_checkout_requires_nonempty_currency(client, db_session):
    product = Product(
        family_slug="smartbudget",
        slug="smartbudget-int-standard-required-currency-test",
        name="SmartBudget",
        edition="Standard",
        archive_path="",
        status="in_sale",
    )
    db_session.add(product)
    db_session.commit()

    missing_response = client.get(f"/checkout/{product.slug}")
    empty_response = client.get(
        f"/checkout/{product.slug}",
        params={"currency": "  "},
    )

    assert missing_response.status_code == 400
    assert missing_response.json()["detail"] == "Currency is required"
    assert empty_response.status_code == 400
    assert empty_response.json()["detail"] == "Currency is required"


def test_checkout_unavailable_currency_fails_without_fallback(client, db_session):
    product = Product(
        family_slug="smartbudget",
        slug="smartbudget-int-standard-unavailable-currency-test",
        name="SmartBudget",
        edition="Standard",
        archive_path="",
        status="in_sale",
    )
    db_session.add(product)
    db_session.flush()
    db_session.add(
        ProductPrice(
            product_id=product.id,
            currency_code="EUR",
            amount=Decimal("39.00"),
            is_active=True,
        )
    )
    db_session.commit()

    response = client.get(
        f"/checkout/{product.slug}",
        params={"currency": "RUB"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == (
        "Active price not found for requested currency"
    )
    assert "39.00 EUR" not in response.text


def test_checkout_missing_product_returns_controlled_not_found(client):
    response = client.get(
        "/checkout/missing-product-exact-slug",
        params={"currency": "EUR"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Product not found"


def test_product_buy_links_include_displayed_price_currency(client, db_session):
    product = Product(
        family_slug="smartbudget-currency-link-test",
        slug="smartbudget-int-standard-currency-link-test",
        name="SmartBudget",
        edition="Standard",
        archive_path="",
        status="in_sale",
    )
    db_session.add(product)
    db_session.flush()
    db_session.add_all(
        [
            ProductPrice(
                product_id=product.id,
                currency_code="EUR",
                amount=Decimal("39.00"),
                is_active=True,
            ),
            ProductPrice(
                product_id=product.id,
                currency_code="RUB",
                amount=Decimal("3900.00"),
                is_active=True,
            ),
        ]
    )
    db_session.commit()

    response = client.get("/products/smartbudget-currency-link-test/buy")

    assert response.status_code == 200
    assert f'/checkout/{product.slug}?currency=EUR' in response.text
    assert f'/checkout/{product.slug}?currency=RUB' in response.text


def test_product_buy_without_active_price_has_no_checkout_action(
    client,
    db_session,
):
    product = Product(
        family_slug="smartbudget-unpriced-link-test",
        slug="smartbudget-int-standard-unpriced-link-test",
        name="SmartBudget",
        edition="Standard",
        archive_path="",
        status="in_sale",
    )
    db_session.add(product)
    db_session.flush()
    db_session.add(
        ServiceAddon(
            code="smartbudget_int_consultation_unpriced_link_test",
            name="Consultation",
            service_type="consultation",
            usage_type="addon",
            family_slug=product.family_slug,
            package_code="INT",
            currency_code="EUR",
            amount=Decimal("35.00"),
            is_active=True,
        )
    )
    db_session.commit()

    response = client.get("/products/smartbudget-unpriced-link-test/buy")

    assert response.status_code == 200
    assert "Price is not configured" in response.text
    assert f"/checkout/{product.slug}" not in response.text
    assert 'class="btn checkout-link"' not in response.text
    assert "data-base-url=" not in response.text
    assert "disabled" in response.text
