from decimal import Decimal
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright

from app.models.product import Product
from app.models.product_price import ProductPrice
from app.models.service_addon import ServiceAddon
from browser_tests.test_feedback_form import _running_app


@pytest.mark.browser
@pytest.mark.parametrize("lang", ["ru", "en"])
@pytest.mark.parametrize("width", [1280, 375])
def test_landing_demos_are_readable_accessible_and_localized(
    tmp_path, review_sessions, lang, width
):
    with review_sessions() as db:
        ServiceAddon.__table__.create(db.get_bind())
        for package, currency, amount in (
            ("ru", "RUB", "3217.25"),
            ("int", "EUR", "73.50"),
        ):
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
            db.add(
                ProductPrice(
                    product_id=product.id,
                    currency_code=currency,
                    amount=Decimal(amount),
                )
            )
        db.commit()
    errors = []
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
        page.goto(f"{base_url}/products/smartbudget?lang={lang}")
        page.wait_for_load_state("networkidle")
        expect(page.locator(".sb-landing h1")).to_have_text(
            "Узнайте, как сегодняшние решения повлияют на ваши финансы завтра."
            if lang == "ru"
            else "See how today's decisions could affect your financial future."
        )
        hero = page.locator(".sb-hero__explore")
        expect(hero).to_have_text(
            "Посмотреть, как работает SmartBudget ↓"
            if lang == "ru"
            else "See how SmartBudget works ↓"
        )
        expect(page.locator(".sb-image-open, .sb-image-hint")).to_have_count(0)
        hero.click()
        expect(page).to_have_url(
            f"{base_url}/products/smartbudget?lang={lang}#sb-capabilities"
        )
        expect(page.locator("#sb-reserves-heading")).to_be_in_viewport()
        images = page.locator(".sb-shot")
        expect(images).to_have_count(5)
        for image in images.all():
            assert image.evaluate(
                "element => element.complete && element.naturalWidth > 0"
            )
            assert f"/landing/{lang}/" in image.get_attribute("src")
            assert image.get_attribute("alt")
        expect(page.locator(".sb-reconciliation-pair img")).to_have_count(2)
        expect(page.locator(".sb-consult")).to_have_count(0)
        assert page.evaluate(
            "document.documentElement.scrollWidth <= window.innerWidth"
        )
        viewport = page.locator("#sb-plan-actual .sb-image-viewport")
        viewport.focus()
        expect(viewport).to_be_focused()
        if width == 375:
            assert viewport.evaluate(
                "element => element.scrollWidth > element.clientWidth"
            )
            viewport.press("ArrowRight")
            page.wait_for_function(
                "document.querySelector('#sb-plan-actual .sb-image-viewport').scrollLeft > 0"
            )
        original = page.locator("#sb-plan-actual .sb-image-link")
        original.focus()
        with page.expect_popup() as popup_info:
            original.press("Enter")
        popup = popup_info.value
        popup.wait_for_load_state()
        assert urlsplit(popup.url).path == page.locator(
            "#sb-plan-actual img"
        ).get_attribute("src")
        popup.close()
        page.reload()
        page.wait_for_load_state("networkidle")
        assert page.evaluate(
            "document.documentElement.scrollWidth <= window.innerWidth"
        )
        page.evaluate("window.scrollTo(0, 0)")
        page.screenshot(
            path=str(tmp_path / f"landing-{lang}-{width}.png"), full_page=True
        )
        price = "3 217,25 RUB" if lang == "ru" else "73.50 EUR"
        expect(page.locator(".sb-hero")).not_to_contain_text(price)
        offer = page.locator("#sb-offer")
        expect(offer.locator(".sb-offer__price")).to_have_text(price)
        expect(offer.locator(".sb-offer__price")).to_be_visible()
        compatibility = page.locator("#sb-practical .sb-compatibility")
        expect(compatibility).to_be_visible()
        for requirement in ("Windows 10/11", "Excel", "2019", "VBA", "ActiveX", "Mac"):
            expect(compatibility).to_contain_text(requirement)
        expect(compatibility.get_by_role("link")).to_have_count(0)
        expect(
            page.locator('.sb-landing a[href*="#system-requirements"]')
        ).to_have_count(0)
        offer.get_by_role("link").click()
        expect(page).to_have_url(f"{base_url}/products/smartbudget/buy")
        expect(page.locator("html")).to_have_attribute("lang", lang)
        page.go_back()
        page.locator(".language-switch a").click()
        alternate = "en" if lang == "ru" else "ru"
        expect(page.locator("html")).to_have_attribute("lang", alternate)
        expect(offer.locator(".sb-offer__price")).to_have_text(
            "73.50 EUR" if alternate == "en" else "3 217,25 RUB"
        )
        page.wait_for_load_state("networkidle")
        browser.close()
    assert errors == []
