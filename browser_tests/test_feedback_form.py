from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
import uvicorn
from playwright.sync_api import Page, expect, sync_playwright

from app.main import app
from app.dependencies import get_db
from app.services.feedback_prefill_service import DownloadFeedbackPrefillContext


@contextmanager
def _running_app() -> Iterator[str]:
    with socket.socket() as port_socket:
        port_socket.bind(("127.0.0.1", 0))
        port = port_socket.getsockname()[1]

    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="warning",
        )
    )
    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()

    deadline = time.monotonic() + 10
    while not server.started and server_thread.is_alive():
        if time.monotonic() >= deadline:
            raise RuntimeError("Timed out while starting the browser-test server")
        time.sleep(0.05)

    if not server.started:
        raise RuntimeError("Browser-test server stopped before startup completed")

    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        server_thread.join(timeout=10)
        if server_thread.is_alive():
            raise RuntimeError("Timed out while stopping the browser-test server")


def _assert_visibility(page: Page, selector: str, *, visible: bool) -> None:
    locator = page.locator(selector)
    if visible:
        expect(locator).to_be_visible()
    else:
        expect(locator).to_be_hidden()


@pytest.mark.browser
def test_feedback_form_initializes_and_switches_all_message_types() -> None:
    page_errors: list[str] = []
    console_errors: list[str] = []

    with _running_app() as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, channel="chromium")
        page = browser.new_page()
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on(
            "console",
            lambda message: (
                console_errors.append(message.text) if message.type == "error" else None
            ),
        )
        page.route(
            "**/favicon.ico",
            lambda route: route.fulfill(status=204, body=""),
        )

        page.goto(f"{base_url}/feedback", wait_until="networkidle")

        expect(page.locator("script[src$='feedback.js?v=6']")).to_have_count(1)
        expect(page.locator("#email")).to_have_count(1)
        expect(page.locator("#contact_email")).to_have_count(0)
        expect(page.locator("#contactEmailGroup")).to_have_count(0)
        expect(page.locator('[role="status"]')).to_have_count(3)
        expect(page.locator("[aria-live]")).to_have_count(0)
        expect(page.locator("#feedback-status")).to_have_attribute("role", "status")
        expect(page.locator("#feedback-status")).to_have_attribute(
            "aria-atomic", "true"
        )
        expect(page.locator("#purchase-status")).to_have_attribute("role", "status")
        expect(page.locator("#purchase-status")).to_have_attribute(
            "aria-atomic", "true"
        )
        expect(page.locator("#selectedFilesText")).to_have_attribute(
            "role", "status"
        )
        expect(page.locator("#selectedFilesText")).to_have_attribute(
            "aria-atomic", "true"
        )

        visibility_by_type = {
            "site_issue": {
                "form_fields": True,
                "submit_enabled": True,
            },
            "general_question": {
                "form_fields": True,
                "submit_enabled": True,
            },
            "product_feedback": {
                "form_fields": False,
                "submit_enabled": False,
            },
            "purchase_or_download_issue": {
                "form_fields": True,
                "submit_enabled": True,
            },
        }

        for message_type, expected_state in visibility_by_type.items():
            page.locator("#message_type").select_option(message_type)

            _assert_visibility(page, "#email", visible=True)
            _assert_visibility(
                page,
                "#subjectGroup",
                visible=expected_state["form_fields"],
            )
            _assert_visibility(
                page,
                "#messageGroup",
                visible=expected_state["form_fields"],
            )
            _assert_visibility(
                page,
                "#attachmentsGroup",
                visible=expected_state["form_fields"],
            )
            expect(page.locator("#purchaseSelectorGroup")).to_be_hidden()
            expect(page.locator("#purchase_select")).to_be_disabled()
            for selector in ("#subject", "#message", "#attachments"):
                control = page.locator(selector)
                if expected_state["form_fields"]:
                    expect(control).to_be_enabled()
                else:
                    expect(control).to_be_disabled()
            for selector in ("#subject", "#message"):
                control = page.locator(selector)
                if expected_state["form_fields"]:
                    expect(control).to_have_attribute("required", "")
                else:
                    expect(control).not_to_have_attribute("required", "")

            submit = page.locator('button[type="submit"]')
            expect(submit).to_have_count(1)
            if expected_state["submit_enabled"]:
                expect(submit).to_be_enabled()
            else:
                expect(submit).to_be_disabled()

        browser.close()

    assert page_errors == []
    assert console_errors == []


@pytest.mark.browser
def test_one_verified_product_purchase_is_selected_without_visible_selector() -> None:
    with _running_app() as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, channel="chromium")
        page = browser.new_page()
        page.route(
            "**/v1/check-purchase",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=(
                    '{"verified": true, "purchases": [{'
                    '"purchase_reference": "FP-one",'
                    '"product_name": "SmartBudget",'
                    '"edition": "Standard"'
                    "}]} "
                ),
            ),
        )
        page.goto(f"{base_url}/feedback", wait_until="networkidle")

        page.locator("#message_type").select_option("product_feedback")
        page.locator("#email").fill("buyer@example.com")
        page.locator("#email").press("Enter")

        expect(page.locator("#purchase-status")).to_have_class(
            "feedback-purchase-status success"
        )
        expect(page.locator("#subjectGroup")).to_be_visible()
        expect(page.locator("#messageGroup")).to_be_visible()
        expect(page.locator("#attachmentsGroup")).to_be_visible()
        expect(page.locator('button[type="submit"]')).to_be_enabled()
        expect(page.locator("#purchaseSelectorGroup")).to_be_hidden()
        expect(page.locator("#purchase_select")).to_have_value("FP-one")
        expect(page.locator("#purchase_select")).to_be_enabled()
        assert page.evaluate(
            "new FormData(document.querySelector('#feedback-form'))"
            ".get('purchase_reference') === 'FP-one'"
        )
        assert not page.evaluate(
            "new FormData(document.querySelector('#feedback-form')).has('sale_id')"
        )

        browser.close()


@pytest.mark.browser
def test_multiple_verified_product_purchases_display_required_selector() -> None:
    with _running_app() as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, channel="chromium")
        page = browser.new_page()
        page.route(
            "**/v1/check-purchase",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=(
                    '{"verified": true, "purchases": ['
                    '{"purchase_reference": "FP-standard",'
                    '"product_name": "SmartBudget", "edition": "Standard"},'
                    '{"purchase_reference": "FP-pro",'
                    '"product_name": "SmartBudget", "edition": "Pro"}'
                    "]}"
                ),
            ),
        )
        page.goto(f"{base_url}/feedback", wait_until="networkidle")

        page.locator("#message_type").select_option("product_feedback")
        page.locator("#email").fill("multi@example.com")
        page.locator("#email").press("Enter")

        expect(page.locator("#purchaseSelectorGroup")).to_be_visible()
        expect(page.locator("#purchase_select")).to_be_enabled()
        expect(page.locator("#purchase_select")).to_have_value("")
        expect(page.locator("#purchase_select option")).to_have_count(3)
        expect(page.locator("#purchase_select")).to_have_attribute("required", "")
        expect(page.locator("#purchase_select")).to_have_attribute(
            "aria-describedby", "purchase-status"
        )
        expect(page.locator("#purchase_select")).to_be_focused()
        expect(page.locator('button[type="submit"]')).to_be_disabled()

        page.locator("#purchase_select").select_option("FP-pro")

        expect(page.locator('button[type="submit"]')).to_be_enabled()
        assert page.evaluate(
            "new FormData(document.querySelector('#feedback-form'))"
            ".get('purchase_reference') === 'FP-pro'"
        )
        assert not page.evaluate(
            "new FormData(document.querySelector('#feedback-form')).has('product_id')"
        )

        browser.close()


@pytest.mark.browser
@pytest.mark.parametrize(
    ("response_status", "response_body", "email_is_invalid"),
    (
        (200, '{"verified": false}', True),
        (200, '{"verified": "false"}', True),
        (500, '{"detail": "Purchase check failed"}', False),
    ),
)
def test_unverified_or_failed_product_purchase_keeps_feedback_closed(
    response_status: int,
    response_body: str,
    email_is_invalid: bool,
) -> None:
    with _running_app() as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, channel="chromium")
        page = browser.new_page()
        page.route(
            "**/v1/check-purchase",
            lambda route: route.fulfill(
                status=response_status,
                content_type="application/json",
                body=response_body,
            ),
        )
        page.goto(f"{base_url}/feedback", wait_until="networkidle")

        page.locator("#message_type").select_option("product_feedback")
        page.locator("#email").fill("buyer@example.com")
        page.locator("#email").press("Enter")

        expect(page.locator("#purchase-status")).to_have_class(
            "feedback-purchase-status error"
        )
        expect(page.locator("#purchase-status")).to_have_attribute("role", "alert")
        expect(page.locator("#purchase-status")).to_have_attribute(
            "aria-atomic", "true"
        )
        assert page.locator("#purchase-status").get_attribute("aria-live") is None
        expect(page.locator("#email")).to_have_attribute(
            "aria-describedby", "email-hint purchase-status"
        )
        if email_is_invalid:
            expect(page.locator("#email")).to_have_attribute("aria-invalid", "true")
        else:
            expect(page.locator("#email")).not_to_have_attribute(
                "aria-invalid", "true"
            )
        expect(page.locator("#subjectGroup")).to_be_hidden()
        expect(page.locator("#messageGroup")).to_be_hidden()
        expect(page.locator("#attachmentsGroup")).to_be_hidden()
        expect(page.locator('button[type="submit"]')).to_be_disabled()
        expect(page.locator("#purchaseSelectorGroup")).to_be_hidden()
        expect(page.locator("#purchase_select")).to_be_disabled()
        assert not page.evaluate(
            "new FormData(document.querySelector('#feedback-form'))"
            ".has('purchase_reference')"
        )
        assert not page.evaluate(
            "new FormData(document.querySelector('#feedback-form')).has('sale_id')"
        )

        browser.close()


def _download_prefill_context() -> DownloadFeedbackPrefillContext:
    return DownloadFeedbackPrefillContext(
        message_type="purchase_or_download_issue",
        customer_email="browser-prefill@example.com",
        support_reference="DL-ABCDEFGH",
        product_name="SmartBudget Browser",
        product_edition="Standard",
        release_version="5.0.0",
        purchase_date="2026-07-18",
        subject="Help with downloading SmartBudget Browser (Standard)",
        message="Safe browser prefill message",
    )


def _install_download_prefill(monkeypatch: pytest.MonkeyPatch) -> None:
    context = _download_prefill_context()
    monkeypatch.setattr(
        "app.web.routes.get_download_feedback_prefill_context",
        lambda db, support_reference, lang: context,
    )
    app.dependency_overrides[get_db] = lambda: object()


@pytest.mark.browser
def test_download_prefill_survives_initialization_and_message_type_switches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _download_prefill_context()
    _install_download_prefill(monkeypatch)

    try:
        with _running_app() as base_url, sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, channel="chromium")
            page = browser.new_page()
            page.route(
                "**/v1/check-purchase",
                lambda route: route.fulfill(
                    status=200,
                    content_type="application/json",
                    body='{"verified": false}',
                ),
            )
            page.goto(
                f"{base_url}/feedback?message_type=purchase_or_download_issue"
                "&support_reference=DL-ABCDEFGH",
                wait_until="networkidle",
            )

            expect(page.locator("#message_type")).to_have_value(
                "purchase_or_download_issue"
            )
            expect(page.locator("#email")).to_have_value("browser-prefill@example.com")
            expect(page.locator("#support_reference")).to_have_value("DL-ABCDEFGH")
            expect(page.locator("#subject")).to_have_value(context.subject)
            expect(page.locator("#message")).to_have_value(context.message)
            expect(page.locator("#subjectGroup")).to_be_visible()
            expect(page.locator("#messageGroup")).to_be_visible()

            reference = page.locator("#support_reference")
            expect(reference).to_be_visible()
            expect(reference).to_be_enabled()
            expect(reference).to_have_attribute("readonly", "")
            assert page.evaluate(
                "new FormData(document.querySelector('#feedback-form'))"
                ".has('support_reference')"
            )

            for message_type in (
                "site_issue",
                "general_question",
                "product_feedback",
            ):
                page.locator("#message_type").select_option(message_type)
                expect(reference).to_be_hidden()
                expect(reference).to_be_disabled()
                assert not page.evaluate(
                    "new FormData(document.querySelector('#feedback-form'))"
                    ".has('support_reference')"
                )

            page.locator("#message_type").select_option("purchase_or_download_issue")
            expect(reference).to_be_visible()
            expect(reference).to_be_enabled()
            expect(reference).to_have_attribute("readonly", "")
            expect(reference).to_have_value("DL-ABCDEFGH")
            expect(page.locator("#email")).to_have_value("browser-prefill@example.com")
            expect(page.locator("#subject")).to_have_value(context.subject)
            expect(page.locator("#message")).to_have_value(context.message)
            expect(page.locator("#subjectGroup")).to_be_visible()
            expect(page.locator("#messageGroup")).to_be_visible()
            assert page.evaluate(
                "new FormData(document.querySelector('#feedback-form'))"
                ".get('support_reference') === 'DL-ABCDEFGH'"
            )

            browser.close()
    finally:
        app.dependency_overrides.clear()


@pytest.mark.browser
def test_successful_download_prefill_submission_clears_active_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_download_prefill(monkeypatch)
    submissions: list[str] = []

    def capture_feedback_submission(route) -> None:
        submissions.append(route.request.post_data or "")
        route.fulfill(
            status=200,
            content_type="application/json",
            body='{"status": "ok", "id": 42}',
        )

    try:
        with _running_app() as base_url, sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, channel="chromium")
            page = browser.new_page()
            page.route("**/v1/feedback", capture_feedback_submission)
            page.goto(
                f"{base_url}/feedback?message_type=purchase_or_download_issue"
                "&support_reference=DL-ABCDEFGH",
                wait_until="networkidle",
            )

            page.locator('button[type="submit"]').click()

            expect(page.locator("#feedback-status")).to_contain_text(
                "Sent successfully. Message ID: 42"
            )
            expect(page.locator("#feedback-status")).to_have_attribute(
                "role", "status"
            )
            expect(page.locator("#feedback-status")).to_have_attribute(
                "aria-atomic", "true"
            )
            assert page.locator("#feedback-status").get_attribute("aria-live") is None
            assert len(submissions) == 1
            assert 'name="support_reference"' in submissions[0]
            assert "DL-ABCDEFGH" in submissions[0]

            expect(page.locator("#message_type")).to_have_value("site_issue")
            expect(page.locator("#email")).to_have_value("")
            expect(page.locator("#subject")).to_have_value("")
            expect(page.locator("#message")).to_have_value("")
            expect(page.locator("#support_reference")).to_have_value("")
            expect(page.locator("#support_reference")).to_be_hidden()
            expect(page.locator("#support_reference")).to_be_disabled()
            expect(page.locator("#subjectGroup")).to_be_visible()
            expect(page.locator("#messageGroup")).to_be_visible()
            expect(page.locator('button[type="submit"]')).to_be_enabled()
            expect(page.locator("#email")).not_to_have_attribute(
                "aria-invalid", "true"
            )
            expect(page.locator("#subject")).not_to_have_attribute(
                "aria-invalid", "true"
            )
            expect(page.locator("#message")).not_to_have_attribute(
                "aria-invalid", "true"
            )
            expect(page.locator("#attachments")).not_to_have_attribute(
                "aria-invalid", "true"
            )
            assert not page.evaluate(
                "new FormData(document.querySelector('#feedback-form'))"
                ".has('support_reference')"
            )
            assert page.evaluate("document.querySelector('#email').defaultValue") == ""
            assert (
                page.evaluate("document.querySelector('#subject').defaultValue") == ""
            )
            assert (
                page.evaluate("document.querySelector('#message').defaultValue") == ""
            )
            assert (
                page.evaluate(
                    "document.querySelector('#support_reference').defaultValue"
                )
                == ""
            )

            page.locator('button[type="submit"]').click()
            page.wait_for_timeout(100)
            assert len(submissions) == 1

            browser.close()
    finally:
        app.dependency_overrides.clear()


@pytest.mark.browser
def test_purchase_success_clears_stale_email_error_state() -> None:
    lookup_count = 0

    def fulfill_purchase_lookup(route) -> None:
        nonlocal lookup_count
        lookup_count += 1
        if lookup_count == 1:
            body = '{"verified": false}'
        else:
            body = (
                '{"verified": true, "purchases": [{'
                '"purchase_reference": "FP-retry",'
                '"product_name": "SmartBudget",'
                '"edition": "Standard"'
                "}]} "
            )
        route.fulfill(status=200, content_type="application/json", body=body)

    with _running_app() as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, channel="chromium")
        page = browser.new_page()
        page.route("**/v1/check-purchase", fulfill_purchase_lookup)
        page.goto(f"{base_url}/feedback", wait_until="networkidle")

        page.locator("#message_type").select_option("product_feedback")
        page.locator("#email").fill("first@example.com")
        page.locator("#email").press("Enter")

        expect(page.locator("#email")).to_have_attribute("aria-invalid", "true")
        expect(page.locator("#purchase-status")).to_have_attribute("role", "alert")

        page.locator("#email").fill("second@example.com")

        expect(page.locator("#email")).not_to_have_attribute("aria-invalid", "true")
        expect(page.locator("#email")).to_have_attribute(
            "aria-describedby", "email-hint"
        )
        expect(page.locator("#purchase-status")).to_be_hidden()

        page.locator("#email").press("Enter")

        expect(page.locator("#purchase-status")).to_have_text("Purchase confirmed")
        expect(page.locator("#purchase-status")).to_have_attribute("role", "status")
        expect(page.locator("#purchase-status")).to_have_attribute(
            "aria-atomic", "true"
        )
        assert page.locator("#purchase-status").get_attribute("aria-live") is None
        expect(page.locator("#email")).not_to_have_attribute("aria-invalid", "true")
        expect(page.locator("#email")).to_have_attribute(
            "aria-describedby", "email-hint purchase-status"
        )
        expect(page.locator("#email")).to_be_focused()

        browser.close()


@pytest.mark.browser
def test_submission_progress_success_and_repeated_failure_are_announced() -> None:
    pending_routes = []

    with _running_app() as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, channel="chromium")
        page = browser.new_page()
        page.route("**/v1/feedback", lambda route: pending_routes.append(route))
        page.goto(f"{base_url}/feedback", wait_until="networkidle")

        page.evaluate(
            """
            window.feedbackStatusMutations = 0;
            new MutationObserver(() => {
                window.feedbackStatusMutations += 1;
            }).observe(document.querySelector("#feedback-status"), {
                childList: true
            });
            """
        )
        page.locator("#subject").fill("Accessible status")
        page.locator("#message").fill("A complete feedback message")
        page.locator('button[type="submit"]').click()

        expect(page.locator("#feedback-status")).to_have_text("Sending...")
        expect(page.locator("#feedback-status")).to_have_attribute("role", "status")
        expect(page.locator("#feedback-status")).to_have_attribute(
            "aria-atomic", "true"
        )
        assert page.locator("#feedback-status").get_attribute("aria-live") is None
        expect(page.locator("#feedback-form")).to_have_attribute("aria-busy", "true")
        assert len(pending_routes) == 1

        pending_routes.pop(0).fulfill(
            status=200,
            content_type="application/json",
            body='{"status": "ok", "id": 84}',
        )

        expect(page.locator("#feedback-status")).to_have_text(
            "Sent successfully. Message ID: 84"
        )
        expect(page.locator("#feedback-form")).not_to_have_attribute(
            "aria-busy", "true"
        )

        for _ in range(2):
            page.locator("#subject").fill("Retry status")
            page.locator("#message").fill("A repeated failed feedback message")
            page.locator('button[type="submit"]').click()
            expect(page.locator("#feedback-status")).to_have_text("Sending...")
            assert len(pending_routes) == 1
            pending_routes.pop(0).fulfill(
                status=500,
                content_type="application/json",
                body='{"detail": "failed"}',
            )
            expect(page.locator("#feedback-status")).to_have_text(
                "Failed to send. Please try again."
            )
            expect(page.locator("#feedback-status")).to_have_attribute("role", "alert")
            expect(page.locator("#feedback-status")).to_have_attribute(
                "aria-atomic", "true"
            )
            assert page.locator("#feedback-status").get_attribute("aria-live") is None
            expect(page.locator('button[type="submit"]')).to_be_enabled()

        assert page.evaluate("window.feedbackStatusMutations") >= 6
        browser.close()


@pytest.mark.browser
def test_attachment_selection_updates_one_accessible_status() -> None:
    with _running_app() as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, channel="chromium")
        page = browser.new_page()
        page.goto(f"{base_url}/feedback", wait_until="networkidle")

        attachments = page.locator("#attachments")
        selected_files = page.locator("#selectedFilesText")
        attachments.set_input_files(
            {
                "name": "unsafe.exe",
                "mimeType": "application/octet-stream",
                "buffer": b"not allowed",
            }
        )

        expect(selected_files).to_have_text("Invalid file type selected")
        expect(selected_files).to_have_attribute("role", "alert")
        expect(selected_files).to_have_attribute("aria-atomic", "true")
        assert selected_files.get_attribute("aria-live") is None
        expect(attachments).to_have_attribute("aria-invalid", "true")
        assert "fakepath" not in selected_files.inner_text().lower()

        attachments.set_input_files(
            [
                {
                    "name": "C:\\private\\screen.png",
                    "mimeType": "image/png",
                    "buffer": b"png",
                },
                {
                    "name": "notes.pdf",
                    "mimeType": "application/pdf",
                    "buffer": b"pdf",
                },
            ]
        )

        expect(selected_files).to_have_text("screen.png, notes.pdf")
        expect(selected_files).to_have_attribute("role", "status")
        expect(selected_files).to_have_attribute("aria-atomic", "true")
        assert selected_files.get_attribute("aria-live") is None
        expect(attachments).not_to_have_attribute("aria-invalid", "true")
        assert "fakepath" not in selected_files.inner_text().lower()

        attachments.set_input_files([])
        expect(selected_files).to_have_text("No files selected")
        expect(selected_files).to_have_attribute("role", "status")

        browser.close()


@pytest.mark.browser
def test_hidden_controls_and_type_changes_clear_obsolete_invalid_state() -> None:
    with _running_app() as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, channel="chromium")
        page = browser.new_page()
        page.route(
            "**/v1/check-purchase",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body='{"verified": false}',
            ),
        )
        page.goto(f"{base_url}/feedback", wait_until="networkidle")

        page.locator('button[type="submit"]').click()
        expect(page.locator("#subject")).to_have_attribute("aria-invalid", "true")

        page.locator("#message_type").select_option("product_feedback")

        for selector in ("#subject", "#message", "#attachments"):
            expect(page.locator(selector)).to_be_disabled()
            expect(page.locator(selector)).not_to_have_attribute(
                "aria-invalid", "true"
            )
        for selector in ("#subject", "#message"):
            expect(page.locator(selector)).not_to_have_attribute("required", "")

        page.locator("#email").fill("missing@example.com")
        page.locator("#email").press("Enter")
        expect(page.locator("#email")).to_have_attribute("aria-invalid", "true")
        expect(page.locator("#email")).to_have_attribute(
            "aria-describedby", "email-hint purchase-status"
        )

        page.locator("#message_type").select_option("general_question")

        expect(page.locator("#email")).not_to_have_attribute("aria-invalid", "true")
        expect(page.locator("#email")).to_have_attribute(
            "aria-describedby", "email-hint"
        )
        expect(page.locator("#purchase-status")).to_be_hidden()
        expect(page.locator("#purchase-status")).to_have_text("")
        for selector in ("#subject", "#message"):
            expect(page.locator(selector)).to_be_enabled()
            expect(page.locator(selector)).to_have_attribute("required", "")

        browser.close()
