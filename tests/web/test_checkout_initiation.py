from decimal import Decimal

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.core.rate_limiting import RollingWindowRateLimiter
from app.dependencies import get_db
from app.main import app
from app.models.consultation_entitlement import ConsultationEntitlement
from app.models.download_entitlement import DownloadEntitlement
from app.models.payment_provider_offer import PaymentProviderOffer
from app.models.product import Product
from app.models.product_price import ProductPrice
from app.models.product_release import ProductRelease
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.models.service_addon import ServiceAddon
from app.services.lava_top.client import LavaTopInvoice, LavaTopRequestError


def create_checkout_catalog(
    db_session,
    *,
    slug: str,
    currency: str = "EUR",
    amount: Decimal = Decimal("39.00"),
    with_price: bool = True,
    with_release: bool = True,
    with_offer: bool = True,
) -> Product:
    product = Product(
        family_slug="smartbudget",
        slug=slug,
        name="SmartBudget",
        edition="Standard",
        archive_path="",
        status="in_sale",
    )
    db_session.add(product)
    db_session.flush()

    if with_price:
        db_session.add(
            ProductPrice(
                product_id=product.id,
                currency_code=currency,
                amount=amount,
                is_active=True,
            )
        )
    if with_release:
        db_session.add(
            ProductRelease(
                product_id=product.id,
                version="1.0",
                storage_provider="cloudflare_r2",
                storage_key=f"product-releases/{slug}/1.0.zip",
                original_filename="SmartBudget_1.0.zip",
                is_active=True,
            )
        )
    if with_offer:
        db_session.add(
            PaymentProviderOffer(
                product_id=product.id,
                provider="lava_top",
                external_offer_id=f"offer-{slug}",
            )
        )

    db_session.commit()
    return product


def install_successful_provider(monkeypatch, captured: dict) -> str:
    payment_url = "https://pay.example/hosted?token=redirect-only-secret"

    def fake_create_invoice(**kwargs):
        captured.update(kwargs)
        return LavaTopInvoice(
            invoice_id="invoice-checkout-route-123",
            payment_url=payment_url,
        )

    monkeypatch.setattr(
        "app.services.payment_service.create_invoice",
        fake_create_invoice,
    )
    return payment_url


def test_product_only_checkout_uses_normalized_authoritative_catalog_data(
    client,
    db_session,
    monkeypatch,
):
    product = create_checkout_catalog(
        db_session,
        slug="smartbudget-int-standard-product-checkout-test",
    )
    captured = {}
    payment_url = install_successful_provider(monkeypatch, captured)

    response = client.post(
        f"/checkout/{product.slug}",
        data={
            "customer_email": " Buyer@Example.com ",
            "currency": " eur ",
            "consultation": "0",
            "amount": "0.01",
            "total": "0.01",
            "payment_provider": "browser-provider",
            "provider_offer_id": "browser-offer",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == payment_url
    sale = db_session.query(Sale).one()
    items = db_session.query(SaleItem).filter_by(sale_id=sale.id).all()
    assert sale.customer_email == "buyer@example.com"
    assert sale.amount == Decimal("39.00")
    assert sale.currency == "EUR"
    assert sale.payment_provider == "lava_top"
    assert sale.payment_status == "pending"
    assert len(items) == 1
    assert items[0].item_type == "product"
    assert items[0].amount == Decimal("39.00")
    assert captured == {
        "email": "buyer@example.com",
        "offer_id": f"offer-{product.slug}",
        "currency": "EUR",
        "amount": Decimal("39.00"),
    }


def test_checkout_with_consultation_persists_separate_snapshot_and_total(
    client,
    db_session,
    monkeypatch,
):
    product = create_checkout_catalog(
        db_session,
        slug="smartbudget-int-standard-addon-initiation-test",
    )
    addon = ServiceAddon(
        code="checkout_consultation_addon_initiation_test",
        name="SmartBudget setup consultation",
        service_type="consultation",
        usage_type="addon",
        family_slug=product.family_slug,
        package_code="INT",
        currency_code="EUR",
        amount=Decimal("35.00"),
        is_active=True,
    )
    db_session.add(addon)
    db_session.commit()
    captured = {}
    install_successful_provider(monkeypatch, captured)

    response = client.post(
        f"/checkout/{product.slug}",
        data={
            "customer_email": "buyer@example.com",
            "currency": "EUR",
            "consultation": "1",
            "addon_amount": "0.01",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    sale = db_session.query(Sale).one()
    items = (
        db_session.query(SaleItem)
        .filter_by(sale_id=sale.id)
        .order_by(SaleItem.item_type)
        .all()
    )
    assert sale.amount == Decimal("74.00")
    assert [(item.item_type, item.amount, item.quantity) for item in items] == [
        ("product", Decimal("39.00"), 1),
        ("service", Decimal("35.00"), 1),
    ]
    service_item = next(item for item in items if item.item_type == "service")
    assert service_item.service_addon_id == addon.id
    assert service_item.item_name == "SmartBudget setup consultation"
    assert service_item.currency_code == "EUR"
    assert captured["amount"] == Decimal("74.00")


def test_checkout_selects_consultation_in_exact_product_currency(
    client,
    db_session,
    monkeypatch,
):
    product = create_checkout_catalog(
        db_session,
        slug="smartbudget-int-standard-exact-addon-currency-test",
        currency="RUB",
        amount=Decimal("500.00"),
    )
    eur_addon = ServiceAddon(
        code="exact-addon-currency-eur",
        name="EUR consultation",
        service_type="consultation",
        usage_type="addon",
        family_slug=product.family_slug,
        package_code="INT",
        currency_code="EUR",
        amount=Decimal("35.00"),
        is_active=True,
    )
    rub_addon = ServiceAddon(
        code="exact-addon-currency-rub",
        name="RUB consultation",
        service_type="consultation",
        usage_type="addon",
        family_slug=product.family_slug,
        package_code="INT",
        currency_code="RUB",
        amount=Decimal("50.00"),
        is_active=True,
    )
    db_session.add_all([eur_addon, rub_addon])
    db_session.commit()
    captured = {}
    install_successful_provider(monkeypatch, captured)

    response = client.post(
        f"/checkout/{product.slug}",
        data={
            "customer_email": "buyer@example.com",
            "currency": "RUB",
            "consultation": "1",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    service_item = db_session.query(SaleItem).filter_by(item_type="service").one()
    assert service_item.service_addon_id == rub_addon.id
    assert service_item.currency_code == "RUB"
    assert captured["amount"] == Decimal("550.00")


@pytest.mark.parametrize("submitted_currency", ["RUB", "   "])
def test_checkout_missing_or_invalid_active_price_is_controlled(
    client,
    db_session,
    monkeypatch,
    submitted_currency,
):
    product = create_checkout_catalog(
        db_session,
        slug=f"smartbudget-int-standard-price-error-{submitted_currency.strip() or 'blank'}",
        with_price=False,
    )
    provider_called = False

    def unexpected_provider_call(**kwargs):
        nonlocal provider_called
        provider_called = True

    monkeypatch.setattr(
        "app.services.payment_service.create_invoice",
        unexpected_provider_call,
    )

    response = client.post(
        f"/checkout/{product.slug}",
        data={
            "customer_email": "buyer@example.com",
            "currency": submitted_currency,
            "consultation": "0",
        },
    )

    assert response.status_code == 400
    assert "Checkout is temporarily unavailable" in response.text
    assert db_session.query(Sale).count() == 0
    assert provider_called is False


def test_checkout_missing_active_release_is_controlled(
    client,
    db_session,
    monkeypatch,
):
    product = create_checkout_catalog(
        db_session,
        slug="smartbudget-int-standard-missing-release-initiation-test",
        with_release=False,
    )
    provider_called = False

    def unexpected_provider_call(**kwargs):
        nonlocal provider_called
        provider_called = True

    monkeypatch.setattr(
        "app.services.payment_service.create_invoice",
        unexpected_provider_call,
    )

    response = client.post(
        f"/checkout/{product.slug}",
        data={
            "customer_email": "buyer@example.com",
            "currency": "EUR",
            "consultation": "0",
        },
    )

    assert response.status_code == 503
    assert "Checkout is temporarily unavailable" in response.text
    assert db_session.query(Sale).count() == 0
    assert provider_called is False


def test_checkout_missing_form_data_uses_controlled_customer_result(
    client,
    db_session,
):
    product = create_checkout_catalog(
        db_session,
        slug="smartbudget-int-standard-missing-form-data-test",
    )

    response = client.post(
        f"/checkout/{product.slug}",
        data={"currency": "EUR", "consultation": "unexpected"},
    )

    assert response.status_code == 400
    assert response.headers["content-type"].startswith("text/html")
    assert "Checkout is temporarily unavailable" in response.text
    assert db_session.query(Sale).count() == 0


def test_checkout_missing_provider_offer_marks_sale_failed_without_exposure(
    client,
    db_session,
):
    product = create_checkout_catalog(
        db_session,
        slug="smartbudget-int-standard-missing-offer-initiation-test",
        with_offer=False,
    )

    response = client.post(
        f"/checkout/{product.slug}",
        data={
            "customer_email": "buyer@example.com",
            "currency": "EUR",
            "consultation": "0",
        },
    )

    assert response.status_code == 503
    assert "offer" not in response.text.lower()
    sale = db_session.query(Sale).one()
    assert sale.payment_status == "failed"
    assert sale.external_payment_id is None


def test_checkout_provider_failure_returns_controlled_result(
    client,
    db_session,
    monkeypatch,
):
    product = create_checkout_catalog(
        db_session,
        slug="smartbudget-int-standard-provider-failure-route-test",
    )
    monkeypatch.setattr(
        "app.services.payment_service.create_invoice",
        lambda **kwargs: (_ for _ in ()).throw(
            LavaTopRequestError("secret provider payload")
        ),
    )

    response = client.post(
        f"/checkout/{product.slug}",
        data={
            "customer_email": "buyer@example.com",
            "currency": "EUR",
            "consultation": "0",
        },
    )

    assert response.status_code == 503
    assert "secret provider payload" not in response.text
    sale = db_session.query(Sale).one()
    assert sale.payment_status == "failed"
    assert sale.external_payment_id is None


def test_checkout_identity_commit_failure_logs_reconciliation_without_exposure(
    client,
    db_session,
    monkeypatch,
    caplog,
):
    product = create_checkout_catalog(
        db_session,
        slug="smartbudget-int-standard-reconciliation-route-test",
    )
    provider_invoice_id = "invoice-reconciliation-route-427"
    payment_url = "https://pay.example/hosted?token=must-remain-opaque"
    provider_calls = 0

    def fake_create_invoice(**kwargs):
        nonlocal provider_calls
        provider_calls += 1
        return LavaTopInvoice(
            invoice_id=provider_invoice_id,
            payment_url=payment_url,
        )

    def fail_identity_commit():
        raise SQLAlchemyError("simulated identity commit failure")

    def override_failing_db():
        yield db_session

    app.dependency_overrides[get_db] = override_failing_db
    monkeypatch.setattr(
        "app.services.payment_service.create_invoice",
        fake_create_invoice,
    )
    monkeypatch.setattr(db_session, "commit", fail_identity_commit)

    with caplog.at_level("ERROR", logger="app.services.payment_service"):
        response = client.post(
            f"/checkout/{product.slug}",
            data={
                "customer_email": "buyer@example.com",
                "currency": "EUR",
                "consultation": "0",
            },
        )

    assert response.status_code == 503
    assert "Checkout is temporarily unavailable" in response.text
    assert provider_invoice_id not in response.text
    assert payment_url not in response.text
    assert "simulated identity commit failure" not in response.text
    assert provider_calls == 1
    assert caplog.messages == [
        "Lava.top checkout reconciliation required "
        f"provider_invoice_id={provider_invoice_id}"
    ]
    assert payment_url not in caplog.text
    assert "buyer@example.com" not in caplog.text


def test_checkout_rate_limit_blocks_before_sale_and_provider_work(
    client,
    db_session,
    monkeypatch,
    caplog,
):
    product = create_checkout_catalog(
        db_session,
        slug="smartbudget-int-standard-private-checkout-rate-limit-test",
    )
    limiter = RollingWindowRateLimiter(max_identities=100, clock=lambda: 1000.0)
    monkeypatch.setattr(app.state, "rate_limiter", limiter)
    customer_email = "private-checkout-buyer@example.com"
    payment_url = "https://pay.example/hosted?token=private-checkout-token"
    provider_calls = 0

    def fake_create_invoice(**kwargs):
        nonlocal provider_calls
        provider_calls += 1
        return LavaTopInvoice(
            invoice_id=f"invoice-rate-limit-{provider_calls}",
            payment_url=payment_url,
        )

    monkeypatch.setattr(
        "app.services.payment_service.create_invoice",
        fake_create_invoice,
    )
    payload = {
        "customer_email": customer_email,
        "currency": "EUR",
        "consultation": "0",
    }

    assert limiter.active_identity_count == 0
    for _ in range(8):
        response = client.post(
            f"/checkout/{product.slug}",
            data=payload,
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"] == payment_url

    assert provider_calls == 8
    assert db_session.query(Sale).count() == 8
    assert db_session.query(SaleItem).count() == 8

    caplog.clear()
    with caplog.at_level("WARNING", logger="app.core.rate_limiting"):
        denied = client.post(
            f"/checkout/{product.slug}",
            data=payload,
            follow_redirects=False,
        )

    assert denied.status_code == 429
    assert denied.headers["retry-after"] == "600"
    assert "Too many requests" in denied.text
    assert customer_email not in denied.text
    assert product.slug not in denied.text
    assert f"offer-{product.slug}" not in denied.text
    assert payment_url not in denied.text
    assert provider_calls == 8
    assert db_session.query(Sale).count() == 8
    assert db_session.query(SaleItem).count() == 8

    records = [
        record
        for record in caplog.records
        if record.name == "app.core.rate_limiting"
        and record.getMessage() == "Request rate limited"
    ]
    assert len(records) == 1
    assert records[0].policy_name == "checkout_ip_10m"
    assert records[0].route_template == "/checkout/{slug}"
    assert records[0].identity_kind == "client_ip"
    assert customer_email not in records[0].__dict__.values()
    assert product.slug not in records[0].__dict__.values()
    assert payment_url not in records[0].__dict__.values()


@pytest.mark.parametrize("addon_currency", [None, "RUB"])
def test_checkout_rejects_unavailable_consultation_addon(
    client,
    db_session,
    monkeypatch,
    addon_currency,
):
    product = create_checkout_catalog(
        db_session,
        slug=f"smartbudget-int-standard-addon-error-{addon_currency or 'missing'}",
    )
    if addon_currency is None:
        db_session.add(
            ServiceAddon(
                code="checkout_standalone_not_addon_test",
                name="Standalone consultation",
                service_type="consultation",
                usage_type="standalone",
                family_slug=product.family_slug,
                package_code="INT",
                currency_code="EUR",
                amount=Decimal("79.00"),
                is_active=True,
            )
        )
        db_session.commit()
    else:
        db_session.add(
            ServiceAddon(
                code=f"checkout_addon_error_{addon_currency.lower()}",
                name="Unavailable consultation",
                service_type="consultation",
                usage_type="addon",
                family_slug=product.family_slug,
                package_code="INT",
                currency_code=addon_currency,
                amount=Decimal("35.00"),
                is_active=True,
            )
        )
        db_session.commit()
    provider_called = False

    def unexpected_provider_call(**kwargs):
        nonlocal provider_called
        provider_called = True

    monkeypatch.setattr(
        "app.services.payment_service.create_invoice",
        unexpected_provider_call,
    )

    response = client.post(
        f"/checkout/{product.slug}",
        data={
            "customer_email": "buyer@example.com",
            "currency": "EUR",
            "consultation": "1",
        },
    )

    assert response.status_code == 400
    assert db_session.query(Sale).count() == 0
    assert provider_called is False


def test_payment_result_page_is_non_authoritative_and_creates_no_fulfillment(
    client,
    db_session,
):
    sale = Sale(
        product_id=None,
        customer_email="buyer@example.com",
        amount=Decimal("39.00"),
        currency="EUR",
        payment_provider="lava_top",
        payment_status="pending",
        external_payment_id="invoice-result-page-test",
    )
    db_session.add(sale)
    db_session.commit()

    response = client.get("/payment/result")

    assert response.status_code == 200
    assert "Payment confirmation is pending" in response.text
    assert "does not by itself confirm payment" in response.text
    db_session.refresh(sale)
    assert sale.payment_status == "pending"
    assert db_session.query(DownloadEntitlement).count() == 0
    assert db_session.query(ConsultationEntitlement).count() == 0
