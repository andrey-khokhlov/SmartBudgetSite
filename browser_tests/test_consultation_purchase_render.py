from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright

from app.core.db import Base
from browser_tests.test_feedback_form import _running_app
from tests.web.test_public_consultations import seed_consultations


@pytest.mark.browser
@pytest.mark.parametrize("width", [1280, 375])
@pytest.mark.parametrize(
    "lang,currency,price,switched_price",
    [
        ("ru", "RUB", "6 123,45 RUB", "6,123.45 RUB"),
        ("en", "EUR", "101.25 EUR", "101,25 EUR"),
    ],
)
def test_consultation_navigation_and_checkout(
    tmp_path, review_sessions, width, lang, currency, price, switched_price
):
    with review_sessions() as db:
        Base.metadata.create_all(db.get_bind())
        catalog = seed_consultations(db)
    with _running_app() as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, channel="chromium")
        page = browser.new_page(viewport={"width": width, "height": 900})
        page.goto(f"{base_url}/?lang={lang}")
        nav = page.locator(".site-nav > .nav-link")
        assert nav.evaluate_all(
            "links => links.map(link => link.getAttribute('href'))"
        ) == ["/", "/products", "/consultations"]
        nav.last.focus()
        nav.last.press("Enter")
        expect(page).to_have_url(f"{base_url}/consultations")
        expect(nav.last).to_have_attribute("aria-current", "page")
        expect(page.locator("html")).to_have_attribute("lang", lang)
        expect(page.locator(".consultations-price")).to_have_text(price)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(tmp_path / "consultations.png"), full_page=True)

        alternate = "en" if lang == "ru" else "ru"
        switch = page.locator(".language-switch a")
        switch.click()
        expect(page.locator("html")).to_have_attribute("lang", alternate)
        expect(page.locator(".consultations-price")).to_have_text(
            "101.25 EUR" if alternate == "en" else "6 123,45 RUB"
        )
        switch.click()
        expect(page.locator(".consultations-price")).to_have_text(price)

        page.locator(".consultations-offer a").click()
        path = f"/consultations/checkout/{catalog[currency]}"
        expect(page).to_have_url(f"{base_url}{path}?currency={currency}")
        expect(nav.last).to_have_attribute("aria-current", "page")
        expect(page.locator(".checkout-total strong")).to_have_text(price)
        expect(page.locator("#checkout-delivery")).to_contain_text(
            "защищённую ссылку для записи" if lang == "ru" else "secure booking link"
        )
        expect(page.locator("#checkout-email")).to_have_attribute("required", "")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(
            path=str(tmp_path / "consultation-checkout.png"), full_page=True
        )
        switch.click()
        expect(page.locator("html")).to_have_attribute("lang", alternate)
        expect(page.locator(".checkout-total strong")).to_have_text(switched_price)
        assert urlsplit(page.url).path == path
        assert parse_qs(urlsplit(page.url).query) == {
            "currency": [currency],
            "lang": [alternate],
        }
        expect(page.locator('input[name="currency"]')).to_have_value(currency)
        page.wait_for_load_state("networkidle")
        browser.close()
