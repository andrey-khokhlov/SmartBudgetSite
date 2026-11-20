from datetime import date

import pytest
from playwright.sync_api import expect, sync_playwright

from app.core.config import settings
from browser_tests.test_feedback_form import _running_app


@pytest.mark.browser
@pytest.mark.parametrize("width", [1280, 375])
@pytest.mark.parametrize(
    ("lang", "other", "heading", "footer_label"),
    [
        ("ru", "en", "SmartBudget — Политика отмены и возвратов", "Политика возвратов"),
        ("en", "ru", "SmartBudget — Cancellation and Refund Policy", "Refund Policy"),
    ],
)
def test_refund_policy_layout(
    monkeypatch, tmp_path, width, lang, other, heading, footer_label
):
    monkeypatch.setattr(settings, "REFUND_POLICY_PUBLICATION_DATE", date(2000, 1, 2))
    monkeypatch.setattr(settings, "SELLER_ADDRESS_RU", "Учебный адрес")
    monkeypatch.setattr(settings, "SELLER_ADDRESS_EN", "Fictional Seller Address")
    monkeypatch.setattr(settings, "SELLER_CONTACT_PHONE", "+1 202-555-0147")

    with _running_app() as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, channel="chromium")
        page = browser.new_page(viewport={"width": width, "height": 900})
        path = "/legal/refund-policy"
        response = page.goto(f"{base_url}{path}?lang={lang}")
        assert response.ok
        assert page.reload().ok
        article = page.locator("main article")
        expect(article.get_by_role("heading", level=1)).to_have_text(heading)
        expect(article.get_by_role("heading", level=2)).to_have_count(9)
        assert article.evaluate("(node) => getComputedStyle(node).maxWidth !== 'none'")
        assert page.evaluate(
            "document.documentElement.scrollWidth <= window.innerWidth"
        )
        page.screenshot(path=str(tmp_path / f"policy-{lang}-{width}.png"))

        seller_link = article.locator('a[href="/legal/seller-information"]')
        seller_link.scroll_into_view_if_needed()
        expect(seller_link).to_have_css("text-decoration-line", "underline")
        seller_link.focus()
        expect(seller_link).to_have_css("outline-style", "solid")
        footer = page.locator("footer")
        footer.scroll_into_view_if_needed()
        expect(
            footer.get_by_role("link", name=footer_label, exact=True)
        ).to_have_attribute("aria-current", "page")
        page.screenshot(path=str(tmp_path / f"footer-{lang}-{width}.png"))

        page.locator(f'.language-switch a[hreflang="{other}"]').click()
        expect(page.locator("html")).to_have_attribute("lang", other)
        expect(article.get_by_role("heading", level=2)).to_have_count(9)
        page.wait_for_load_state("networkidle")
        browser.close()
