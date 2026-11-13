from datetime import UTC, datetime

import pytest
from playwright.sync_api import expect, sync_playwright

from app.core.db import Base
from app.main import app
from browser_tests.test_feedback_form import _running_app
from tests.web.test_download_routes import create_download


@pytest.mark.browser
@pytest.mark.parametrize(
    ("zone", "lang", "month", "day", "local_time", "offset"),
    [
        ("Asia/Kolkata", "ru", 3, 9, "17:30:00", "+05:30"),
        ("America/New_York", "en", 3, 9, "07:00:00", "-05:00"),
        ("America/New_York", "en", 3, 10, "08:00:00", "-04:00"),
        ("Asia/Tokyo", "en", 3, 10, "21:00:00", "+09:00"),
    ],
)
def test_expiry_uses_browser_zone(
    review_sessions, zone, lang, month, day, local_time, offset
):
    expiry = datetime(2030, month, day, 12, tzinfo=UTC)
    with review_sessions() as db:
        Base.metadata.create_all(db.get_bind())
        entitlement, _ = create_download(db)
        entitlement.expires_at = expiry
        db.commit()
        token = entitlement.download_token

    try:
        with _running_app() as base_url, sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chromium")
            page = browser.new_page(timezone_id=zone)
            page.goto(f"{base_url}/download/{token}?lang={lang}")
            timestamp = page.locator("#download-expiry")
            expect(timestamp).to_have_attribute(
                "datetime", expiry.isoformat(timespec="milliseconds")
            )
            expect(timestamp).to_contain_text(local_time)
            expect(timestamp).to_contain_text(offset.replace("-", "−") if lang == "ru" else offset)
            browser_zone = page.evaluate("Intl.DateTimeFormat().resolvedOptions().timeZone")
            expect(timestamp).to_contain_text(browser_zone)
            page.wait_for_load_state("networkidle")
            browser.close()
    finally:
        app.state.rate_limiter.reset()


@pytest.mark.browser
@pytest.mark.parametrize("lang", ["en", "ru"])
def test_utc_fallback_and_download_without_javascript(review_sessions, monkeypatch, lang):
    with review_sessions() as db:
        Base.metadata.create_all(db.get_bind())
        entitlement, _ = create_download(db)
        token = entitlement.download_token
        expiry = entitlement.expires_at

    class FakeStorage:
        def generate_signed_get_url(self, **kwargs):
            return "https://r2.example/download"

    monkeypatch.setattr("app.web.routes.R2StorageService", FakeStorage)

    try:
        with _running_app() as base_url, sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chromium")
            page = browser.new_page(java_script_enabled=False, timezone_id="Asia/Kolkata")
            page.route("https://r2.example/download", lambda route: route.fulfill(body="file"))
            page.goto(f"{base_url}/download/{token}?lang={lang}")
            expect(page.locator("#download-expiry")).to_have_text(
                expiry.strftime("%d.%m.%Y %H:%M:%S UTC")
            )
            page.locator(".download-button").click()
            expect(page).to_have_url("https://r2.example/download")
            page.wait_for_load_state("networkidle")
            browser.close()
    finally:
        app.state.rate_limiter.reset()
