from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import MultipleResultsFound

from app.core.config import settings
from app.models.consultation_entitlement import ConsultationEntitlement
from app.models.download_entitlement import DownloadEntitlement
from app.models.product import Product
from app.models.product_price import ProductPrice
from app.models.product_release import ProductRelease
from app.models.sale import Sale
from app.repositories.products_repository import ProductsRepository
from app.services.payment_service import (
    PaymentCheckoutError,
    PaymentReconciliationRequiredError,
)
from scripts.smoke_lava_top_checkout import (
    SmokeCheckoutPriceNotFoundError,
    SmokeCheckoutProductNotFoundError,
    build_parser,
    main,
    smoke_lava_top_checkout,
)


def create_product_with_prices(
    db_session,
    *,
    slug: str,
    prices: tuple[tuple[str, Decimal], ...],
) -> Product:
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
    for currency_code, amount in prices:
        db_session.add(
            ProductPrice(
                product_id=product.id,
                currency_code=currency_code,
                amount=amount,
                is_active=True,
            )
        )
    db_session.commit()
    return product


@pytest.mark.parametrize(
    ("requested_currency", "expected_amount"),
    (("EUR", Decimal("39.00")), ("RUB", Decimal("3900.00"))),
)
def test_requested_currency_selects_matching_active_catalog_price(
    db_session,
    monkeypatch,
    requested_currency,
    expected_amount,
):
    product = create_product_with_prices(
        db_session,
        slug="smoke-price-selection-test",
        prices=(("EUR", Decimal("39.00")), ("RUB", Decimal("3900.00"))),
    )
    captured = {}
    output = []

    def fake_prepare_product_payment(db, **kwargs):
        captured["prepare"] = kwargs
        return SimpleNamespace(
            id=101,
            payment_status="pending",
            external_payment_id=None,
            amount=kwargs["amount"],
            currency=kwargs["currency"],
        )

    def fake_create_lava_top_checkout(db, *, sale):
        captured["checkout_sale"] = sale
        sale.external_payment_id = "invoice-101"
        return "https://pay.example/hosted?token=must-not-print"

    monkeypatch.setattr(
        "scripts.smoke_lava_top_checkout.prepare_product_payment",
        fake_prepare_product_payment,
    )
    monkeypatch.setattr(
        "scripts.smoke_lava_top_checkout.create_lava_top_checkout",
        fake_create_lava_top_checkout,
    )

    smoke_lava_top_checkout(
        db_session,
        product_slug=product.slug,
        customer_email="buyer@example.com",
        currency=requested_currency.lower(),
        output=output.append,
    )

    assert captured["prepare"]["product"].id == product.id
    assert captured["prepare"]["amount"] == expected_amount
    assert captured["prepare"]["currency"] == requested_currency
    assert captured["prepare"]["payment_provider"] == "lava_top"
    assert captured["checkout_sale"].id == 101
    assert output == [
        "result=success",
        "sale_id=101",
        "payment_status=pending",
        "external_payment_id=invoice-101",
        f"amount={expected_amount}",
        f"currency={requested_currency}",
    ]


def test_requested_unavailable_currency_fails_without_payment_preparation(
    db_session,
    monkeypatch,
):
    product = create_product_with_prices(
        db_session,
        slug="smoke-unavailable-currency-test",
        prices=(("EUR", Decimal("39.00")),),
    )
    prepare_calls = 0

    def unexpected_prepare(*args, **kwargs):
        nonlocal prepare_calls
        prepare_calls += 1

    monkeypatch.setattr(
        "scripts.smoke_lava_top_checkout.prepare_product_payment",
        unexpected_prepare,
    )

    with pytest.raises(
        SmokeCheckoutPriceNotFoundError,
        match="No active catalog price for requested currency: RUB",
    ):
        smoke_lava_top_checkout(
            db_session,
            product_slug=product.slug,
            customer_email="buyer@example.com",
            currency="RUB",
        )

    assert prepare_calls == 0


def test_product_resolution_uses_exact_slug(db_session, monkeypatch):
    create_product_with_prices(
        db_session,
        slug="exact-product-slug-extra",
        prices=(("EUR", Decimal("39.00")),),
    )
    prepare_calls = 0

    def unexpected_prepare(*args, **kwargs):
        nonlocal prepare_calls
        prepare_calls += 1

    monkeypatch.setattr(
        "scripts.smoke_lava_top_checkout.prepare_product_payment",
        unexpected_prepare,
    )

    with pytest.raises(
        SmokeCheckoutProductNotFoundError,
        match="Product not found for exact slug: exact-product-slug",
    ):
        smoke_lava_top_checkout(
            db_session,
            product_slug="exact-product-slug",
            customer_email="buyer@example.com",
            currency="EUR",
        )

    assert prepare_calls == 0


def test_cli_rejects_amount_override():
    with pytest.raises(SystemExit) as exc_info:
        build_parser().parse_args(
            [
                "--product-slug",
                "smartbudget-int-standard",
                "--customer-email",
                "buyer@example.com",
                "--currency",
                "EUR",
                "--amount",
                "1.00",
            ]
        )

    assert exc_info.value.code == 2


def test_unscoped_legacy_price_lookup_fails_closed_for_multiple_currencies(
    db_session,
):
    product = create_product_with_prices(
        db_session,
        slug="smoke-unscoped-price-test",
        prices=(("EUR", Decimal("39.00")), ("RUB", Decimal("3900.00"))),
    )

    with pytest.raises(MultipleResultsFound):
        ProductsRepository(db_session).get_product_with_active_price_by_slug(
            product.slug
        )


def test_success_output_omits_sensitive_values_and_creates_no_entitlements(
    db_session,
    monkeypatch,
):
    product = create_product_with_prices(
        db_session,
        slug="smoke-safe-output-test",
        prices=(("EUR", Decimal("39.00")),),
    )
    release = ProductRelease(
        product_id=product.id,
        version="1.0",
        storage_provider="cloudflare_r2",
        storage_key="product-releases/smoke-safe-output/1.0.zip",
        original_filename="SmartBudget_1.0.zip",
        is_active=True,
    )
    db_session.add(release)
    db_session.commit()
    customer_email = "sensitive-buyer@example.com"
    payment_url = "https://pay.example/hosted?token=payment-url-secret"
    api_key = "api-key-must-not-print"
    output = []
    checkout_calls = 0

    def fake_create_lava_top_checkout(db, *, sale):
        nonlocal checkout_calls
        checkout_calls += 1
        assert sale.payment_status == "pending"
        sale.external_payment_id = "invoice-safe-output"
        db.commit()
        return payment_url

    monkeypatch.setattr(settings, "LAVA_TOP_API_KEY", api_key)
    monkeypatch.setattr(
        "scripts.smoke_lava_top_checkout.create_lava_top_checkout",
        fake_create_lava_top_checkout,
    )

    smoke_lava_top_checkout(
        db_session,
        product_slug=product.slug,
        customer_email=customer_email,
        currency="EUR",
        output=output.append,
    )

    rendered_output = "\n".join(output)
    sale = db_session.query(Sale).one()
    assert checkout_calls == 1
    assert sale.payment_status == "pending"
    assert sale.external_payment_id == "invoice-safe-output"
    assert db_session.query(DownloadEntitlement).count() == 0
    assert db_session.query(ConsultationEntitlement).count() == 0
    assert payment_url not in rendered_output
    assert customer_email not in rendered_output
    assert api_key not in rendered_output


def test_controlled_checkout_failure_exits_nonzero_without_sensitive_output(
    db_session,
    monkeypatch,
    capsys,
):
    product = create_product_with_prices(
        db_session,
        slug="smoke-controlled-failure-test",
        prices=(("EUR", Decimal("39.00")),),
    )
    customer_email = "sensitive-buyer@example.com"
    payment_url = "https://pay.example/hosted?token=payment-url-secret"
    api_key = "api-key-must-not-print"

    def fake_prepare_product_payment(db, **kwargs):
        return SimpleNamespace(id=201)

    def fail_checkout(db, *, sale):
        raise PaymentCheckoutError(f"failure {payment_url} {api_key}")

    monkeypatch.setattr(settings, "LAVA_TOP_API_KEY", api_key)
    monkeypatch.setattr(
        "scripts.smoke_lava_top_checkout.SessionLocal",
        lambda: db_session,
    )
    monkeypatch.setattr(
        "scripts.smoke_lava_top_checkout.prepare_product_payment",
        fake_prepare_product_payment,
    )
    monkeypatch.setattr(
        "scripts.smoke_lava_top_checkout.create_lava_top_checkout",
        fail_checkout,
    )

    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "--product-slug",
                product.slug,
                "--customer-email",
                customer_email,
                "--currency",
                "EUR",
            ]
        )

    error_output = capsys.readouterr().err
    assert exc_info.value.code == 1
    assert error_output == "result=failure\nreason=checkout_failed\n"
    assert customer_email not in error_output
    assert payment_url not in error_output
    assert api_key not in error_output


def test_reconciliation_failure_prints_only_required_invoice_identity(
    db_session,
    monkeypatch,
    capsys,
):
    product = create_product_with_prices(
        db_session,
        slug="smoke-reconciliation-test",
        prices=(("EUR", Decimal("39.00")),),
    )
    provider_invoice_id = "invoice-reconciliation-301"

    def fake_prepare_product_payment(db, **kwargs):
        return SimpleNamespace(id=301)

    def fail_checkout(db, *, sale):
        raise PaymentReconciliationRequiredError(provider_invoice_id)

    monkeypatch.setattr(
        "scripts.smoke_lava_top_checkout.SessionLocal",
        lambda: db_session,
    )
    monkeypatch.setattr(
        "scripts.smoke_lava_top_checkout.prepare_product_payment",
        fake_prepare_product_payment,
    )
    monkeypatch.setattr(
        "scripts.smoke_lava_top_checkout.create_lava_top_checkout",
        fail_checkout,
    )

    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "--product-slug",
                product.slug,
                "--customer-email",
                "sensitive-buyer@example.com",
                "--currency",
                "EUR",
            ]
        )

    assert exc_info.value.code == 1
    assert capsys.readouterr().err == (
        "result=reconciliation_required\n"
        f"provider_invoice_id={provider_invoice_id}\n"
    )
