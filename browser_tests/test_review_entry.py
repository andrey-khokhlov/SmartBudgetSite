import pytest
from playwright.sync_api import expect, sync_playwright

from app.core.db import Base
from app.main import app
from app.models.feedback import FeedbackMessage
from browser_tests.test_feedback_form import _running_app
from tests.test_feedback_api import _create_paid_product_purchase


@pytest.mark.browser
@pytest.mark.parametrize(
    ("lang", "alternate", "link_label", "no_purchase", "purchase_confirmed"),
    [
        ("en", "ru", "Leave a review", "No purchase found", "Purchase confirmed"),
        (
            "ru",
            "en",
            "Оставить отзыв",
            "Покупка не найдена",
            "Покупка подтверждена",
        ),
    ],
)
@pytest.mark.parametrize("width", [1280, 390])
def test_public_review_entry(
    review_sessions,
    checkout_legal_pages,
    tmp_path,
    lang,
    alternate,
    link_label,
    no_purchase,
    purchase_confirmed,
    width,
):
    buyer_email = "review-buyer@example.com"
    with review_sessions() as db:
        Base.metadata.create_all(db.get_bind())
        product = _create_paid_product_purchase(
            db, email=buyer_email, slug="smartbudget-review-entry"
        )
        product_id = product.id

    app.state.rate_limiter.reset()
    try:
        with _running_app() as base_url, sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chromium")
            page = browser.new_page(viewport={"width": width, "height": 900})
            page.goto(f"{base_url}/products?lang={lang}")
            footer = page.locator("footer")
            link = footer.get_by_role("link", name=link_label, exact=True)
            expect(link).to_have_attribute(
                "href", "/feedback?message_type=product_feedback"
            )
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            footer.screenshot(path=tmp_path / f"review-footer-{lang}-{width}.png")
            link.click()
            expect(page.locator("html")).to_have_attribute("lang", lang)
            form = page.locator("#feedback-form")
            email = form.locator("#email")
            topic = form.locator("#message_type")
            subject = form.locator("#subject")
            submit = form.locator('button[type="submit"]')
            purchase_status = form.locator("#purchase-status")
            switch = page.locator(".language-switch a")
            expect(topic).to_have_value("product_feedback")
            expect(email).to_have_value("")
            expect(email).to_have_attribute("required", "")
            expect(subject).to_be_hidden()
            expect(submit).to_be_disabled()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.screenshot(
                path=tmp_path / f"review-entry-{lang}-{width}.png", full_page=True
            )

            switch.click()
            expect(page.locator("html")).to_have_attribute("lang", alternate)
            expect(topic).to_have_value("product_feedback")
            expect(submit).to_be_disabled()
            switch.click()
            expect(page.locator("html")).to_have_attribute("lang", lang)
            expect(topic).to_have_value("product_feedback")

            email.fill("unverified@example.com")
            email.press("Enter")
            expect(purchase_status).to_have_text(no_purchase)
            expect(subject).to_be_hidden()
            expect(submit).to_be_disabled()

            email.fill(buyer_email)
            # Tab uses the same blur-triggered lookup as a customer.
            page.keyboard.press("Tab")
            expect(purchase_status).to_have_text(purchase_confirmed)
            expect(subject).to_be_visible()
            expect(submit).to_be_enabled()
            page.evaluate("window.scrollTo(0, 0)")
            page.screenshot(
                path=tmp_path / f"review-verified-{lang}-{width}.png", full_page=True
            )
            subject.fill("Review from browser test")
            form.locator("#message").fill(
                "A review of the purchased SmartBudget product."
            )
            submit.click()
            expect(form.locator(".feedback-form__status--success")).to_be_visible()
            expect(topic).to_have_value("")
            browser.close()
    finally:
        app.state.rate_limiter.reset()

    with review_sessions() as db:
        review = db.query(FeedbackMessage).one()
        assert (review.type, review.product_id) == ("product_feedback", product_id)
        assert review.email == buyer_email
        assert not review.is_published
