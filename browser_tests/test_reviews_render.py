import pytest
from playwright.sync_api import expect, sync_playwright

from app.models.product import Product
from browser_tests.test_feedback_form import _running_app
from tests.web.test_reviews_page import create_feedback, create_product


@pytest.mark.browser
@pytest.mark.parametrize("lang,package", [("en", "int"), ("ru", "ru")])
@pytest.mark.parametrize("width", [1280, 375])
def test_reviews_visibility_and_layout(tmp_path, review_sessions, lang, package, width):
    slug = f"smartbudget-{package}-standard"
    empty_text = (
        "Пока нет опубликованных отзывов о SmartBudget."
        if lang == "ru"
        else "There are no published SmartBudget reviews yet."
    )
    with review_sessions() as db:
        product_id = create_product(db, slug=slug).id

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
        landing_url = f"{base_url}/products/smartbudget?lang={lang}"
        reviews_url = f"{base_url}/reviews/{slug}?lang={lang}"

        page.goto(landing_url, wait_until="networkidle")
        reviews_link = page.locator(".sb-hero__reviews a")
        expect(reviews_link).to_have_count(0)
        expect(page.locator('.sb-hero a[href="/faq"]')).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(tmp_path / "landing-empty.png"), full_page=True)

        response = page.goto(reviews_url, wait_until="networkidle")
        assert response.status == 200
        expect(page.locator("html")).to_have_attribute("lang", lang)
        expect(page.locator("h1")).to_have_count(1)
        expect(page.locator(".reviews-empty p")).to_have_text(empty_text)
        expect(page.get_by_text(empty_text, exact=True)).to_have_count(1)
        expect(page.locator(".review-card, .reviews-page__intro")).to_have_count(0)
        back_link = page.locator(".reviews-action")
        expect(back_link).to_have_attribute("href", "/products/smartbudget")
        expect(back_link).to_have_css("border-top-color", "rgb(148, 163, 184)")
        expect(back_link).to_have_css("margin-top", "24px")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(tmp_path / "reviews-empty.png"), full_page=True)
        back_link.click()
        expect(page.locator("html")).to_have_attribute("lang", lang)
        expect(reviews_link).to_have_count(0)

        with review_sessions() as db:
            create_feedback(
                db,
                db.get(Product, product_id),
                subject="Планирование бюджета" if lang == "ru" else "Planning ahead",
                message=(
                    "Прогноз помог мне оценить последствия крупной покупки."
                    if lang == "ru"
                    else "The forecast helped me assess the impact of a large purchase."
                ),
                name=None,
                admin_reply=(
                    "Спасибо за отзыв." if lang == "ru" else "Thank you for sharing."
                ),
            )

        page.reload(wait_until="networkidle")
        expect(reviews_link).to_be_visible()
        expect(reviews_link).to_have_attribute("href", "/reviews")
        reviews_link.click()
        expect(page).to_have_url(reviews_url)
        page.wait_for_load_state("networkidle")
        expect(page.locator(".review-card")).to_have_count(1)
        expect(page.locator(".reviews-page__intro")).to_have_count(0)
        expect(page.locator(".review-admin-reply")).to_be_visible()
        expect(page.locator(".reviews-empty")).to_have_count(0)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(tmp_path / "reviews-published.png"), full_page=True)
        browser.close()

    assert errors == []
