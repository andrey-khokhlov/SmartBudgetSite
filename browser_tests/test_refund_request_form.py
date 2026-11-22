import pytest
from playwright.sync_api import expect, sync_playwright

from app.core.config import settings
from app.core.db import Base
from app.main import app
from app.models.enums import PaymentStatus
from app.models.refund_operation import RefundOperation
from app.models.refund_request import RefundRequest
from app.services import refund_request_service
from browser_tests.test_feedback_form import _running_app
from tests.services.test_payment_reconciliation_service import create_pending_sale


@pytest.fixture
def refund_purchase(review_sessions, monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "test")
    monkeypatch.setattr(
        refund_request_service,
        "deliver_refund_request_receipt",
        lambda db, request_id: None,
    )
    with review_sessions() as db:
        Base.metadata.create_all(db.get_bind())
        sale = create_pending_sale(db)
        sale.payment_status = PaymentStatus.PAID
        db.commit()
        email, reference = sale.customer_email, sale.sale_reference
    app.state.rate_limiter.reset()
    try:
        yield email, reference
    finally:
        app.state.rate_limiter.reset()


@pytest.mark.browser
@pytest.mark.parametrize(
    ("lang", "hint", "error_text", "success_text"),
    [
        pytest.param(
            "ru",
            "Номер покупки указан в письме с подтверждением оплаты. Он начинается с PAY-.",
            "Проверьте адрес электронной почты и номер покупки и повторите попытку.",
            "Ваш запрос зарегистрирован. Решение о возврате будет рассмотрено отдельно.",
            id="ru",
        ),
        pytest.param(
            "en",
            "You can find your purchase reference in the confirmation email sent after payment. It starts with PAY-.",
            "Check the purchase email and purchase reference and try again.",
            "Your request has been registered. Any refund will be reviewed separately.",
            id="en",
        ),
    ],
)
@pytest.mark.parametrize("width", [320, 390, 1280])
def test_refund_request_form(
    review_sessions,
    refund_purchase,
    tmp_path,
    lang,
    hint,
    error_text,
    success_text,
    width,
):
    buyer_email, purchase_reference = refund_purchase

    with _running_app() as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chromium")
        page = browser.new_page(viewport={"width": width, "height": 900})
        form_url = f"{base_url}/refund-request?lang={lang}"
        page.goto(form_url)
        heading = page.get_by_role("heading", level=1)
        form = page.locator("main form")
        email = page.locator("#refund-email")
        reference = page.locator("#refund-reference")
        message = page.locator("#refund-message")
        reference_hint = page.locator("#refund-reference + #refund-reference-hint")
        submit = form.get_by_role("button")
        no_page_overflow = "document.documentElement.scrollWidth <= innerWidth"

        expect(page.locator("html")).to_have_attribute("lang", lang)
        expect(heading).to_have_css("font-size", "28px" if width == 1280 else "24px")
        expect(reference_hint).to_have_text(hint)
        expect(reference).to_have_accessible_description(hint)
        expect(message).to_have_accessible_description(
            page.locator("#refund-message-hint").inner_text()
        )
        expect(
            page.locator(
                'header a[href^="/refund-request"], footer a[href^="/refund-request"]'
            )
        ).to_have_count(0)
        for element in (
            heading,
            form.locator("label").first,
            reference_hint,
            email,
            reference,
            message,
        ):
            expect(element).to_have_css("text-align", "left")
        form_width = form.bounding_box()["width"]
        for field in (email, reference, message, submit):
            assert field.bounding_box()["width"] == pytest.approx(form_width)
        assert message.bounding_box()["height"] >= 120
        expect(submit).to_have_css("background-color", "rgb(37, 99, 235)")
        assert page.evaluate(no_page_overflow)
        page.screenshot(
            path=tmp_path / f"refund-request-{lang}-{width}.png", full_page=True
        )

        page.locator(".language-switch a").focus()
        for field in (email, reference, message, submit):
            page.keyboard.press("Tab")
            expect(field).to_be_focused()
            expect(field).to_have_css("outline-style", "solid")
            expect(field).to_have_css("outline-width", "2px")
        submit.hover()
        expect(submit).to_have_css("background-color", "rgb(29, 78, 216)")
        submit.click()
        expect(email).to_be_focused()
        assert email.evaluate("field => field.validity.valueMissing")
        email.fill("invalid-email")
        submit.click()
        assert email.evaluate("field => field.validity.typeMismatch")
        email.fill(buyer_email)
        submit.click()
        expect(reference).to_be_focused()
        assert reference.evaluate("field => field.validity.valueMissing")
        expect(page).to_have_url(form_url)

        reference.fill("not-a-reference")
        submit.click()
        error = page.locator("main").get_by_role("alert")
        expect(error).to_have_text(error_text)
        expect(error).to_have_css("text-align", "left")
        assert page.evaluate(no_page_overflow)
        page.screenshot(
            path=tmp_path / f"refund-request-error-{lang}-{width}.png", full_page=True
        )
        with review_sessions() as db:
            assert db.query(RefundRequest).count() == 0

        email.fill(buyer_email)
        reference.fill(purchase_reference)
        submit.click()
        expect(page).to_have_url(f"{base_url}/refund-request/received?lang={lang}")
        success = page.get_by_role("status")
        expect(success).to_have_text(success_text)
        expect(success).to_have_css("text-align", "left")
        expect(form).to_have_count(0)
        assert page.evaluate(no_page_overflow)
        page.screenshot(
            path=tmp_path / f"refund-request-success-{lang}-{width}.png", full_page=True
        )
        browser.close()

    with review_sessions() as db:
        saved = db.query(RefundRequest).one()
        assert saved.purchase_reference == purchase_reference
        assert saved.language == lang
        assert saved.message is None
        assert saved.sale.payment_status == PaymentStatus.PAID
        assert db.query(RefundOperation).count() == 0
