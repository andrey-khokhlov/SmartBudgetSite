import pytest
from playwright.sync_api import expect, sync_playwright

from browser_tests.test_feedback_form import _running_app


@pytest.mark.browser
@pytest.mark.parametrize("lang", ["ru", "en"])
@pytest.mark.parametrize("width", [1280, 375])
def test_faq_groups_native_accordions_and_products_anchor(tmp_path, lang, width):
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
        page.goto(f"{base_url}/faq?lang={lang}", wait_until="networkidle")
        expect(page.locator("details[open]")).to_have_count(0)
        page.goto(f"{base_url}/faq?lang={lang}&open=unknown", wait_until="networkidle")
        expect(page.locator("details[open]")).to_have_count(0)
        page.goto(f"{base_url}/products?lang={lang}", wait_until="networkidle")
        expect(page.locator(".product-card")).to_have_count(1)
        expect(page.locator(".product-highlights li")).to_have_count(3)
        expect(page.locator(".product-cta")).to_have_attribute(
            "href", "/products/smartbudget"
        )
        assert page.locator(".product-card").evaluate(
            "e => getComputedStyle(e).boxShadow === 'none'"
        )
        requirements = page.locator(".product-requirements a")
        expect(requirements).to_have_text(
            "Полные системные требования"
            if lang == "ru"
            else "Full System Requirements"
        )
        expect(requirements).to_have_attribute(
            "href", "/faq?open=system-requirements#system-requirements-question"
        )
        assert requirements.evaluate(
            "e => getComputedStyle(e).backgroundColor === 'rgba(0, 0, 0, 0)'"
        )
        page.screenshot(
            path=str(tmp_path / f"products-{lang}-{width}.png"), full_page=True
        )
        requirements.focus()
        requirements.press("Enter")
        page.wait_for_url(
            f"{base_url}/faq?open=system-requirements#system-requirements-question"
        )
        page.wait_for_load_state("networkidle")
        expect(page.locator("html")).to_have_attribute("lang", lang)
        expect(page.locator("h1")).to_have_text(
            "Частые вопросы" if lang == "ru" else "Frequently Asked Questions"
        )
        expect(page.locator(".faq-group h2")).to_have_text(
            ["О SmartBudget", "Перед покупкой"]
            if lang == "ru"
            else ["About SmartBudget", "Before You Buy"]
        )
        target = page.locator("#system-requirements-question")
        expect(target).to_have_attribute("open", "")
        expect(page.locator("details[open]")).to_have_count(1)
        expect(target.locator("summary")).to_have_text(
            "Что необходимо для работы со SmartBudget?"
            if lang == "ru"
            else "What do I need to use SmartBudget?"
        )
        heading = target.locator("summary")
        expect(heading).to_be_in_viewport()
        assert (
            heading.bounding_box()["y"]
            >= page.locator(".site-header").bounding_box()["height"]
        )
        expect(page.locator("#about-smartbudget details")).to_have_count(4)
        expect(page.locator("#system-requirements details")).to_have_count(7)
        expect(page.locator("details details")).to_have_count(0)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(tmp_path / f"faq-target-{lang}-{width}.png"))
        target.locator("summary").click()
        expect(page.locator("details[open]")).to_have_count(0)
        page.evaluate("window.scrollTo(0, 0)")
        page.screenshot(
            path=str(tmp_path / f"faq-closed-{lang}-{width}.png"), full_page=True
        )
        first = page.locator("#about-smartbudget summary").first
        first.focus()
        first.press("Enter")
        expect(page.locator("#about-smartbudget details").first).to_have_attribute(
            "open", ""
        )
        first.press("Space")
        expect(page.locator("#about-smartbudget details").first).not_to_have_attribute(
            "open", ""
        )
        config = page.locator("#system-requirements details").last
        config.locator("summary").focus()
        config.locator("summary").press("Enter")
        page.keyboard.press("Tab")
        microsoft_link = config.locator("a").first
        expect(microsoft_link).to_be_focused()
        assert microsoft_link.evaluate(
            "e => getComputedStyle(e).outlineStyle !== 'none'"
        )
        expect(microsoft_link).to_have_attribute("target", "_blank")
        expect(microsoft_link).to_have_attribute("rel", "noopener")
        for details in page.locator("details").all():
            if details.get_attribute("open") is None:
                details.locator("summary").click()
        assert page.locator(".faq-item__answer").evaluate_all(
            "elements => elements.every(e => e.scrollWidth <= e.clientWidth + 1 && !['auto', 'scroll'].includes(getComputedStyle(e).overflowY))"
        )
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.evaluate(
            "() => Promise.all(document.getAnimations().map(animation => animation.finished))"
        )
        config.screenshot(path=str(tmp_path / f"faq-activex-{lang}-{width}.png"))
        page.evaluate("window.scrollTo(0, 0)")
        page.screenshot(
            path=str(tmp_path / f"faq-open-{lang}-{width}.png"), full_page=True
        )
        browser.close()
    assert errors == []
