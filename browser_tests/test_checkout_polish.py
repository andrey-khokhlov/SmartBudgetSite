from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db import Base
from app.dependencies import get_db
from app.main import app
from app.models.product import Product
from app.models.product_price import ProductPrice
from app.models.service_addon import ServiceAddon
from browser_tests.test_feedback_form import _running_app


@pytest.mark.browser
@pytest.mark.parametrize("width", [1280, 375])
@pytest.mark.parametrize(
    "lang,package,currency,amount,addon_amount,total",
    [
        ("en", "int", "EUR", "49.00", "69.00", "118.00 EUR"),
        ("ru", "ru", "RUB", "2990.00", "3900.00", "6 890,00 RUB"),
    ],
)
def test_localized_buy_checkout_and_review_navigation(
    tmp_path,
    width,
    lang,
    package,
    currency,
    amount,
    addon_amount,
    total,
):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    sessions = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    with sessions() as db:
        product = Product(
            family_slug="smartbudget",
            slug=f"smartbudget-{package}-standard",
            name="SmartBudget",
            edition="Standard",
            archive_path="",
            status="in_sale",
        )
        db.add(product)
        db.flush()
        db.add_all(
            [
                ProductPrice(
                    product_id=product.id,
                    currency_code=currency,
                    amount=Decimal(amount),
                    is_active=True,
                ),
                ServiceAddon(
                    code=f"consultation-{package}",
                    name="Consultation",
                    service_type="consultation",
                    usage_type="addon",
                    family_slug="smartbudget",
                    package_code=package.upper(),
                    currency_code=currency,
                    amount=Decimal(addon_amount),
                    is_active=True,
                ),
            ]
        )
        db.commit()

    def review_db():
        with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = review_db
    errors = []
    try:
        with _running_app() as base_url, sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, channel="chromium")
            page = browser.new_page(viewport={"width": width, "height": 900})
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "console",
                lambda message: (
                    errors.append(message.text) if message.type == "error" else None
                ),
            )
            page.route("**/favicon.ico", lambda route: route.fulfill(status=204))
            opposite = "ru" if lang == "en" else "en"
            page.goto(f"{base_url}/products/smartbudget?lang={opposite}")
            page.goto(f"{base_url}/products/smartbudget/buy?lang={lang}")
            page.locator(".product-addon__checkbox").check()
            page.locator(".checkout-link").click()
            expect(page.locator("html")).to_have_attribute("lang", lang)
            expect(page.locator(".checkout-total strong")).to_have_text(total)
            expect(page.locator(".checkout-summary strong")).to_have_count(1)
            expect(page.locator(".checkout-value")).to_have_count(5)
            value_weight = page.locator(".checkout-value").first.evaluate(
                "element => Number(getComputedStyle(element).fontWeight)"
            )
            total_weight = page.locator(".checkout-total strong").evaluate(
                "element => Number(getComputedStyle(element).fontWeight)"
            )
            assert total_weight > value_weight
            assert page.evaluate(
                "document.documentElement.scrollWidth <= window.innerWidth"
            )
            expect(
                page.locator('.site-nav > a[aria-current="page"]')
            ).to_have_attribute("href", "/products")
            expect(page.locator(".language-switch__segment")).to_have_count(2)
            current_language = page.locator('.language-switch [aria-current="true"]')
            expect(current_language).to_have_text(lang.upper())
            assert current_language.evaluate("element => element.tagName") == "SPAN"

            page.locator("#checkout-email").fill("unsent@example.test")
            original_url = page.url
            current_language.click()
            assert page.url == original_url
            expect(page.locator("#checkout-email")).to_have_value("unsent@example.test")

            switch = page.locator(".language-switch a")
            switch.focus()
            expect(switch).to_be_focused()
            switch.press("Enter")
            expect(page.locator("html")).to_have_attribute("lang", opposite)
            assert urlsplit(page.url).path == urlsplit(original_url).path
            assert parse_qs(urlsplit(page.url).query) == {
                "currency": [currency],
                "consultation": ["1"],
                "lang": [opposite],
            }
            switched_total = "118,00 EUR" if lang == "en" else "6,890.00 RUB"
            expect(page.locator(".checkout-total strong")).to_have_text(switched_total)
            expect(page.locator('input[name="currency"]')).to_have_value(currency)
            expect(page.locator('input[name="consultation"]')).to_have_value("1")
            expect(page.locator("#checkout-email")).to_have_value("")
            assert "unsent@example.test" not in page.url
            assert page.evaluate("Object.keys(localStorage)") == []
            assert page.evaluate("Object.keys(sessionStorage)") == []
            assert {cookie["name"] for cookie in page.context.cookies()} == {"sb_lang"}
            assert page.evaluate(
                "document.documentElement.scrollWidth <= window.innerWidth"
            )

            page.locator(".language-switch a").click()
            expect(page.locator("html")).to_have_attribute("lang", lang)
            expect(page.locator(".checkout-total strong")).to_have_text(total)
            page.reload()
            expect(page.locator("html")).to_have_attribute("lang", lang)
            expect(page.locator(".checkout-total strong")).to_have_text(total)
            page.screenshot(path=str(tmp_path / "checkout.png"), full_page=True)
            page.goto(f"{base_url}/products/smartbudget")
            page.locator(".sb-hero__reviews a").click()
            expect(page).to_have_url(
                f"{base_url}/reviews/smartbudget-{package}-standard?lang={lang}"
            )
            expect(page.locator("html")).to_have_attribute("lang", lang)
            page.locator(".reviews-action").click()
            expect(page).to_have_url(f"{base_url}/products/smartbudget")
            page.wait_for_load_state("networkidle")
            browser.close()
        assert errors == []
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.state.rate_limiter.reset()
        engine.dispose()
