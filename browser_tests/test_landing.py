from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright

from browser_tests.test_feedback_form import _running_app


@pytest.mark.browser
@pytest.mark.usefixtures("review_sessions")
@pytest.mark.parametrize("lang", ["ru", "en"])
@pytest.mark.parametrize("width", [1280, 375])
def test_landing_demos_are_readable_accessible_and_localized(tmp_path, lang, width):
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
        browser.close()
    assert errors == []
