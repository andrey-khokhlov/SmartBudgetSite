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
@pytest.mark.parametrize("width", [1280, 375, 390, 320])
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
        mobile = width <= 640
        title = page.locator(".sb-landing h1")
        expect(title).to_have_text(
            "Узнайте, как сегодняшние решения повлияют на ваши финансы завтра."
            if lang == "ru"
            else "See how today's decisions could affect your financial future."
        )
        hero = page.locator(".sb-hero__explore")
        hero_faq = page.locator(".sb-hero__explore + .sb-hero__faq a")
        expect(hero_faq).to_have_attribute("href", "/faq")
        headings = page.locator(".sb-landing h1, .sb-landing h2")
        expect(headings).to_have_count(7)
        for heading in headings.all():
            expect(heading).to_have_css("text-align", "center" if mobile else "start")
        if lang == "ru":
            practical_heading = page.locator("#sb-practical-heading")
            assert "\u00a0—" in practical_heading.text_content()
            assert practical_heading.evaluate("""element => {
                const text = element.firstChild;
                const dash = text.data.indexOf("—");
                const range = new Range();
                range.setStart(text, dash - 2);
                range.setEnd(text, dash + 1);
                return new Set(Array.from(range.getClientRects(), rect => rect.top)).size === 1;
            }""")
        assert page.locator(".sb-landing p, .sb-landing h3").evaluate_all(
            "elements => elements.every(e => getComputedStyle(e).textAlign === 'start')"
        )
        expect(page.locator(".sb-image-open, .sb-image-hint")).to_have_count(0)
        if mobile:
            expect(title).to_have_css("font-size", "23px")
            for heading in page.locator(".sb-section h2").all():
                expect(heading).to_have_css("font-size", "21px")
                expect(heading).to_have_css("font-weight", "600")
            expect(hero).to_have_accessible_name(
                "Как работает SmartBudget"
                if lang == "ru"
                else "See how SmartBudget works"
            )
            arrow = hero.locator(".sb-hero__explore-arrow")
            expect(arrow).to_be_visible()
            expect(arrow).to_have_attribute("aria-hidden", "true")
            expect(hero).to_have_css("border-top-width", "0px")
            assert hero.bounding_box()["height"] >= 44
            hero.focus()
            page.keyboard.press("Tab")
            expect(hero_faq).to_be_focused()
            page.keyboard.press("Shift+Tab")
            expect(hero).to_be_focused()
            expect(hero).to_have_css("outline-style", "solid")
            page.keyboard.press("Enter")
        else:
            expect(hero).to_have_accessible_name(
                "Посмотреть, как работает SmartBudget ↓"
                if lang == "ru"
                else "See how SmartBudget works ↓"
            )
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
            assert image.evaluate("""element => {
                const {width, height} = element.getBoundingClientRect();
                return Math.abs(height - width * element.naturalHeight / element.naturalWidth) <= 1;
            }""")
            assert f"/landing/{lang}/" in image.get_attribute("src")
            assert image.get_attribute("alt")
        reconciliation = page.locator("#sb-reconciliation")
        comparison = reconciliation.locator(".sb-reconciliation-pair")
        figures = comparison.locator("figure")
        expect(figures).to_have_count(2)
        expect(comparison.locator("img")).to_have_count(2)
        pair_box = comparison.bounding_box()
        text_box = reconciliation.locator(".sb-section__text").bounding_box()
        assert pair_box["x"] == text_box["x"]
        assert pair_box["width"] == text_box["width"]
        first, second = [figure.bounding_box() for figure in figures.all()]
        assert first["width"] == second["width"]
        if mobile:
            assert first["width"] == pair_box["width"]
            assert first["x"] == second["x"]
            assert second["y"] >= first["y"] + first["height"]
        else:
            assert first["y"] == second["y"]
            assert second["x"] - first["x"] - first["width"] == 24
        assert figures.evaluate_all("""figures => figures.every(figure => {
            const caption = figure.querySelector("figcaption");
            const viewport = figure.querySelector(".sb-image-viewport");
            return caption.getBoundingClientRect().x === viewport.getBoundingClientRect().x &&
                viewport.scrollWidth <= viewport.clientWidth;
        })""")
        expect(page.locator(".sb-consult")).to_have_count(0)
        assert page.evaluate(
            "document.documentElement.scrollWidth <= window.innerWidth"
        )
        viewport = page.locator("#sb-plan-actual .sb-image-viewport")
        viewport.focus()
        expect(viewport).to_be_focused()
        if mobile:
            chart = page.locator("#sb-capabilities .sb-image-viewport")
            assert chart.evaluate("e => e.scrollWidth <= e.clientWidth")
            for section, preview_width in (
                ("sb-future-expense", 580),
                ("sb-plan-actual", 520),
            ):
                preview = page.locator(f"#{section} .sb-image-viewport")
                expect(preview.locator("a")).to_have_css(
                    "min-width", f"{preview_width}px"
                )
                assert preview.evaluate("e => e.scrollWidth > e.clientWidth")
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
        if width in (390, 1280):
            comparison.screenshot(
                path=str(tmp_path / f"reconciliation-{lang}-{width}.png")
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
        buy = offer.get_by_role("link")
        if mobile:
            assert offer.evaluate("""element => {
                const heading = element.querySelector('h2').getBoundingClientRect();
                const product = element.querySelector('h3').getBoundingClientRect();
                return product.top - heading.bottom >= 32;
            }""")
            expect(buy).to_have_css("text-align", "center")
            assert buy.evaluate(
                "element => Math.abs(element.offsetWidth - element.parentElement.clientWidth) <= 1"
            )
        buy.click()
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
