from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright

from app.core.db import Base
from app.services.consultation_capacity_service import set_consultation_sales_suspended
from browser_tests.test_feedback_form import _running_app
from tests.web.test_public_consultations import seed_consultations


@pytest.mark.browser
@pytest.mark.usefixtures("checkout_legal_pages")
@pytest.mark.parametrize("width", [1280, 390, 320])
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
        content = page.locator(".consultations-page")
        heading = content.get_by_role("heading", level=1)
        mobile = width <= 767
        expect(heading).to_have_css("text-align", "center" if mobile else "start")
        if mobile:
            expect(heading).to_have_css("font-size", "23px")
        if width == 390:
            assert heading.evaluate("""element => {
                const text = document.createRange();
                text.selectNodeContents(element);
                return new Set(Array.from(text.getClientRects(), rect => rect.top)).size;
            }""") == 2
        paragraphs = content.locator(":scope > p")
        expect(paragraphs).to_have_count(7)
        assert paragraphs.evaluate_all("""paragraphs => {
            const bodyStyle = getComputedStyle(paragraphs[1]);
            const properties = ["fontSize", "lineHeight", "marginBlockStart", "marginBlockEnd"];
            return paragraphs.every(paragraph => {
                const style = getComputedStyle(paragraph);
                return style.textAlign === "start" &&
                    properties.every(property => style[property] === bodyStyle[property]) &&
                    paragraph.getBoundingClientRect().width >= paragraph.parentElement.clientWidth - 1;
            });
        }""")
        assert content.bounding_box()["width"] >= min(width - 48, 736)
        offer = content.locator(".consultations-offer")
        expect(offer.get_by_role("heading", level=2)).to_be_visible()
        assert offer.evaluate("card => card.scrollWidth <= card.clientWidth")
        notice = page.locator(".consultations-unavailable")
        expect(notice).to_have_count(0)
        booking = page.locator("#consultation-booking-heading + p")
        expect(booking).to_be_visible()
        booking_copy = booking.inner_text()
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

        offer.get_by_role("link").click()
        path = f"/consultations/checkout/{catalog[currency]}"
        expect(page).to_have_url(f"{base_url}{path}?currency={currency}")
        expect(nav.last).to_have_attribute("aria-current", "page")
        expect(page.locator(".checkout-total strong")).to_have_text(price)
        expect(page.locator("#checkout-delivery")).to_have_text(booking_copy)
        expect(page.locator("#checkout-email")).to_have_attribute("required", "")
        expect(page.locator(".checkout-legal a")).to_have_text(
            ["Политика возвратов", "Юридическая информация"]
            if lang == "ru"
            else ["Refund Policy", "Legal Information"]
        )
        expect(page.locator(".checkout-legal + button")).to_be_enabled()
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

        with review_sessions() as db:
            set_consultation_sales_suspended(db, suspended=True)
        page.goto(f"{base_url}/consultations?lang={lang}")
        expect(booking).to_have_text(booking_copy)
        expect(notice).to_be_visible()
        expect(notice).to_have_text(
            "Оформление консультации сейчас недоступно."
            if lang == "ru"
            else "Consultation checkout is currently unavailable."
        )
        expect(notice).to_have_css("background-color", "rgb(246, 247, 249)")
        expect(notice).to_have_css("color", "rgb(71, 85, 105)")
        expect(notice).to_have_css("text-align", "center" if mobile else "start")
        expect(offer.get_by_role("link")).to_have_count(0)
        assert offer.evaluate("card => card.scrollWidth <= card.clientWidth")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(
            path=str(tmp_path / "consultations-unavailable.png"), full_page=True
        )
        browser.close()
