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
                console_errors.append(message.text)
                if message.type == "error"
                else None
            ),
        )
        page.route(
            "**/favicon.ico",
            lambda route: route.fulfill(status=204, body=""),
        )

        page.goto(f"{base_url}/feedback", wait_until="networkidle")

        expect(page.locator("script[src$='feedback.js?v=2']")).to_have_count(1)
        expect(page.locator("#email")).to_have_count(1)
        expect(page.locator("#contact_email")).to_have_count(0)
        expect(page.locator("#contactEmailGroup")).to_have_count(0)

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
            _assert_visibility(page, "#purchaseSelectorGroup", visible=False)

            submit = page.locator('button[type="submit"]')
            expect(submit).to_have_count(1)
            if expected_state["submit_enabled"]:
                expect(submit).to_be_enabled()
            else:
                expect(submit).to_be_disabled()

        browser.close()

    assert page_errors == []
    assert console_errors == []
