from decimal import Decimal
from unittest.mock import Mock

import pytest

from app.models.consultation_entitlement import ConsultationEntitlement
from app.models.download_entitlement import DownloadEntitlement
from app.models.enums import PaymentStatus
from app.models.sale import Sale
from app.services.lava_top.client import LavaTopInvoice, LavaTopRequestError
from app.services.payment_provider_offer_service import set_lava_top_standalone_offer
from app.services.payment_service import PaymentReconciliationRequiredError
from tests.services.test_standalone_consultation_payment import add_offer


@pytest.fixture
def catalog(db_session):
    return seed_consultations(db_session)


def seed_consultations(db):
    catalog = {}
    for currency, amount in (("RUB", "3456.75"), ("EUR", "72.50")):
        catalog[currency] = add_offer(db, currency)
        catalog[f"{currency}_addon"] = add_offer(
            db,
            currency,
            code=f"addon-{currency}",
            usage_type="addon",
            amount=Decimal(amount),
        )
        set_lava_top_standalone_offer(
            db,
            service_addon_id=catalog[currency],
            external_offer_id=f"private-{currency}",
        )
    return catalog


@pytest.mark.parametrize(
    "lang,currency,price,addon,title",
    [
        (
            "ru",
            "RUB",
            "6 123,45 RUB",
            "3 456,75 RUB",
            "Персональные консультации по SmartBudget",
        ),
        ("en", "EUR", "101.25 EUR", "72.50 EUR", "Personal SmartBudget Consultations"),
    ],
)
@pytest.mark.parametrize("bundles_enabled", [False, True])
def test_localized_catalog_and_checkout(
    client, catalog, lang, currency, price, addon, title, bundles_enabled, monkeypatch
):
    monkeypatch.setattr("app.core.config.settings.BUNDLE_CHECKOUT_ENABLED", bundles_enabled)
    page = client.get("/consultations", params={"lang": lang})
    path = f"/consultations/checkout/{catalog[currency]}"
    assert page.status_code == 200
    assert title in page.text and price in page.text
    assert (addon in page.text) is bundles_enabled
    assert page.text.count('href="/consultations/checkout/') == 1
    assert f'href="{path}?currency={currency}"' in page.text
    assert "private-" not in page.text
    checkout = client.get(f"{path}?currency={currency}")
    assert checkout.status_code == 200
    assert price in checkout.text and addon not in checkout.text
    assert f'<html lang="{lang}">' in checkout.text
    assert f'action="{path}?lang={lang}"' in checkout.text
    assert (
        "защищённую ссылку для записи" if lang == "ru" else "secure booking link"
    ) in checkout.text
    assert "secure link to download" not in checkout.text
    assert "ссылку для скачивания" not in checkout.text
    other = "en" if lang == "ru" else "ru"
    switched = client.get(f"{path}?currency={currency}&lang={other}")
    assert switched.context["offer"].id == catalog[currency]
    assert switched.context["offer"].currency_code == currency


@pytest.mark.parametrize("condition", ["missing", "inactive", "unmapped", "ambiguous"])
def test_catalog_withholds_purchase_when_unavailable(client, db_session, condition):
    if condition != "missing":
        offer_id = add_offer(db_session, is_active=condition != "inactive")
        if condition != "unmapped":
            set_lava_top_standalone_offer(
                db_session, service_addon_id=offer_id, external_offer_id="offer"
            )
        if condition == "ambiguous":
            add_offer(db_session, "EUR", package_code="RU")
    page = client.get("/consultations?lang=ru")
    assert page.status_code == 200
    assert 'href="/consultations/checkout/' not in page.text
    assert "Оформление консультации сейчас недоступно." in page.text


@pytest.fixture
def provider(monkeypatch):
    stub = Mock(
        return_value=LavaTopInvoice("private-invoice", "https://pay.example/hosted")
    )
    monkeypatch.setattr("app.services.payment_service.create_invoice", stub)
    return stub


@pytest.mark.parametrize("language", ["ru", "en"])
def test_post_creates_only_pending_service_sale(
    client, db_session, catalog, provider, language
):
    offer_id = catalog["EUR"]
    path = f"/consultations/checkout/{offer_id}"
    checkout = client.get(path, params={"currency": "EUR", "lang": language})
    assert checkout.status_code == 200
    action = f"{path}?lang={language}"
    assert f'action="{action}"' in checkout.text
    client.cookies.set("sb_lang", "en" if language == "ru" else "ru")
    response = client.post(
        action,
        data={
            "currency": " eur ",
            "customer_email": " BUYER@example.com ",
            "amount": "0.01",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "https://pay.example/hosted"
    provider.assert_called_once_with(
        email="buyer@example.com",
        offer_id="private-EUR",
        currency="EUR",
        amount=Decimal("101.25"),
    )
    sale = db_session.query(Sale).one()
    assert sale.payment_status == PaymentStatus.PENDING
    assert sale.purchase_language == language
    assert sale.external_payment_id == "private-invoice"
    (item,) = sale.items
    assert sale.product_id is item.product_id is item.product_release_id is None
    assert item.service_addon_id == offer_id
    assert db_session.query(ConsultationEntitlement).count() == 0
    assert db_session.query(DownloadEntitlement).count() == 0


@pytest.mark.parametrize(
    "case",
    [
        "addon",
        "inactive",
        "missing",
        "mapping",
        "currency",
        "blank_currency",
        "email",
        "blank_email",
    ],
)
def test_invalid_checkout_fails_closed(client, db_session, catalog, provider, case):
    offer_id = catalog["EUR"]
    if case == "addon":
        offer_id = catalog["EUR_addon"]
    elif case in {"inactive", "mapping"}:
        offer_id = add_offer(
            db_session,
            "EUR",
            code="unavailable",
            package_code="RU",
            is_active=case != "inactive",
        )
    elif case == "missing":
        offer_id = 0
    path = f"/consultations/checkout/{offer_id}"
    currency = {"currency": "RUB", "blank_currency": ""}.get(case, "EUR")
    email = {"email": "invalid", "blank_email": ""}.get(case, "buyer@example.com")
    if case not in {"email", "blank_email"}:
        assert client.get(path, params={"currency": currency}).status_code == 404
    response = client.post(path, data={"currency": currency, "customer_email": email})
    assert response.status_code == 400
    provider.assert_not_called()
    assert db_session.query(Sale).count() == 0


def test_rate_limit_is_shared_and_blocks_before_initiation(
    client, catalog, monkeypatch
):
    start = Mock(side_effect=AssertionError("Checkout should not run"))
    monkeypatch.setattr(
        "app.web.routes.initiate_lava_top_standalone_consultation_checkout", start
    )
    assert client.post("/checkout/invalid").status_code == 400
    for _ in range(7):
        assert client.post("/consultations/checkout/malformed").status_code == 422
    response = client.post(
        f"/consultations/checkout/{catalog['EUR']}",
        data={"currency": "EUR", "customer_email": "buyer@example.com"},
    )
    assert response.status_code == 429
    assert "retry-after" in response.headers
    start.assert_not_called()


def test_provider_failure_is_safe(client, catalog, provider, db_session):
    provider.side_effect = LavaTopRequestError("private provider message")
    response = client.post(
        f"/consultations/checkout/{catalog['EUR']}?lang=en",
        data={"currency": "EUR", "customer_email": "buyer@example.com"},
    )
    assert response.status_code == 503
    assert "Checkout is temporarily unavailable" in response.text
    assert "private provider message" not in response.text
    assert db_session.query(Sale).one().payment_status == PaymentStatus.FAILED


def test_reconciliation_failure_keeps_invoice_id_internal(
    client, catalog, monkeypatch, caplog
):
    monkeypatch.setattr(
        "app.web.routes.initiate_lava_top_standalone_consultation_checkout",
        Mock(side_effect=PaymentReconciliationRequiredError("private-invoice")),
    )
    response = client.post(
        f"/consultations/checkout/{catalog['EUR']}?lang=en",
        data={"currency": "EUR", "customer_email": "buyer@example.com"},
    )
    assert response.status_code == 503
    assert "private-invoice" not in response.text
    assert (
        "consultation checkout requires reconciliation provider_invoice_id=private-invoice"
        in caplog.text
    )
