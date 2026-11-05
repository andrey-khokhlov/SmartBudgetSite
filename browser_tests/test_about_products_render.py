import pytest
from playwright.sync_api import expect, sync_playwright

from browser_tests.test_feedback_form import _running_app


@pytest.mark.browser
@pytest.mark.usefixtures("review_sessions")
@pytest.mark.parametrize("lang", ["ru", "en"])
@pytest.mark.parametrize("width", [1280, 375])
def test_about_products_are_readable_restrained_and_navigable(tmp_path, lang, width):
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
        page.goto(f"{base_url}/?lang={lang}", wait_until="networkidle")
        expect(page.locator(".about-page h1")).to_have_text(
            "Обо мне" if lang == "ru" else "About Me"
        )
        photo = page.locator(".about-photo")
        expect(photo).to_be_visible()
        assert photo.evaluate("e => e.complete && e.naturalWidth > 0")
        assert photo.bounding_box()["width"] <= 320
        if width == 1280:
            assert photo.bounding_box()["width"] == 320
        expect(page.locator(".about-page section")).to_have_count(4)
        expect(page.locator(".about-activity")).to_have_count(3)
        visuals = page.locator(".about-activity img")
        expect(visuals).to_have_count(3)
        assert visuals.evaluate_all(
            "elements => elements.every(e => e.complete && e.naturalWidth > 0 && e.alt === '')"
        )
        assert page.locator(".about-intro").evaluate(
            "e => getComputedStyle(e).display === 'flow-root'"
        )
        flow = page.locator(".about-intro").evaluate("""intro => {
            const photo = intro.querySelector('img').getBoundingClientRect();
            const heading = intro.querySelector('h1').getBoundingClientRect();
            const paragraphs = intro.querySelectorAll('p');
            function firstCharacter(element) {
                const range = document.createRange();
                range.setStart(element.firstChild, 0);
                range.setEnd(element.firstChild, 1);
                const rect = range.getBoundingClientRect();
                return {x: rect.x, y: rect.y};
            }
            const first = firstCharacter(paragraphs[0]);
            const last = firstCharacter(paragraphs[paragraphs.length - 1]);
            const area = intro.getBoundingClientRect();
            return {left: area.left, bottom: area.bottom,
                photoRight: photo.right, photoBottom: photo.bottom,
                headingLeft: heading.left, headingTop: heading.top, first, last};
        }""")
        activities = page.locator(".about-activity")
        boxes = [activity.bounding_box() for activity in activities.all()]
        if width == 1280:
            assert flow["first"]["x"] > flow["photoRight"]
            assert flow["last"]["y"] > flow["photoBottom"]
            assert abs(flow["last"]["x"] - flow["left"]) < 1
            assert max(box["y"] for box in boxes) - min(box["y"] for box in boxes) < 1
            assert boxes[1]["x"] >= boxes[0]["x"] + boxes[0]["width"]
            assert boxes[2]["x"] >= boxes[1]["x"] + boxes[1]["width"]
        else:
            assert flow["headingTop"] >= flow["photoBottom"]
            assert abs(flow["first"]["x"] - flow["left"]) < 1
            assert max(box["x"] for box in boxes) - min(box["x"] for box in boxes) < 1
            assert boxes[1]["y"] >= boxes[0]["y"] + boxes[0]["height"]
            assert boxes[2]["y"] >= boxes[1]["y"] + boxes[1]["height"]
        assert (
            page.locator('[aria-labelledby="about-story-heading"]').bounding_box()["y"]
            >= flow["bottom"]
        )
        expect(
            page.locator(
                '[aria-labelledby="about-story-heading"] img, [aria-labelledby="about-approach-heading"] img'
            )
        ).to_have_count(0)
        assert page.locator(".about-page p").evaluate_all(
            "elements => elements.every(e => getComputedStyle(e).textAlign === 'left' && e.getBoundingClientRect().width <= 780)"
        )
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(
            path=str(tmp_path / f"about-{lang}-{width}.png"), full_page=True
        )

        page.goto(f"{base_url}/products?lang={lang}", wait_until="networkidle")
        card = page.locator(".product-card")
        expect(card).to_have_count(1)
        expect(card.locator(".product-highlights li")).to_have_count(3)
        expect(card.locator(".product-conditions")).to_contain_text("Windows")
        assert card.evaluate(
            "e => getComputedStyle(e).boxShadow === 'none' && getComputedStyle(e).backgroundImage === 'none'"
        )
        assert page.locator(".products-grid").evaluate(
            "e => getComputedStyle(e).backgroundImage === 'none'"
        )
        expect(
            page.locator(".products-section, .product-card .product-card")
        ).to_have_count(0)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        cta = card.locator(".product-cta")
        expect(cta).to_have_text(
            "Подробнее о SmartBudget" if lang == "ru" else "Explore SmartBudget"
        )
        expect(cta).to_have_attribute("href", "/products/smartbudget")
        assert cta.evaluate(
            "e => getComputedStyle(e).backgroundColor === 'rgba(0, 0, 0, 0)'"
        )
        page.screenshot(
            path=str(tmp_path / f"products-{lang}-{width}.png"), full_page=True
        )
        cta.focus()
        cta.press("Enter")
        page.wait_for_url(f"{base_url}/products/smartbudget")
        page.wait_for_load_state("networkidle")
        expect(page.locator("html")).to_have_attribute("lang", lang)
        expect(page.locator(".sb-landing h1")).to_be_visible()
        browser.close()
    assert errors == []
