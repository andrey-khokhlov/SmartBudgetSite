import pytest
from playwright.sync_api import expect, sync_playwright

from app.core.config import settings
from app.core.db import Base
from app.dependencies import ADMIN_COOKIE_NAME
from app.models.consultation_capacity import ConsultationCapacityState
from browser_tests.test_feedback_form import _running_app
from tests.services.test_consultation_capacity import add_available_rights


@pytest.mark.browser
@pytest.mark.parametrize("width", [1280, 390])
def test_capacity_panel_and_controls(review_sessions, monkeypatch, tmp_path, width):
    monkeypatch.setattr(settings, "APP_ENV", "test")
    monkeypatch.setattr(settings, "ADMIN_TOKEN", "test-admin-capacity-panel")
    monkeypatch.setattr(settings, "SECRET_KEY", "test-capacity-panel-csrf")
    monkeypatch.setattr(settings, "CONSULTATION_CAPACITY_LIMIT", 4)
    monkeypatch.setattr(settings, "CONSULTATION_CAPACITY_WARNING_THRESHOLD", 3)
    with review_sessions() as db:
        Base.metadata.create_all(db.get_bind())

    with _running_app() as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chromium")
        page = browser.new_page(viewport={"width": width, "height": 900})
        page.context.add_cookies(
            [
                {
                    "name": ADMIN_COOKIE_NAME,
                    "value": settings.ADMIN_TOKEN,
                    "url": base_url,
                }
            ]
        )
        path = f"{base_url}/admin/consultation-offers"
        page.goto(f"{path}?lang=ru")
        panel = page.get_by_role("region", name="Sales capacity")
        status = panel.locator(".admin-capacity__status")
        outstanding = panel.locator(".admin-capacity__metric")
        suspend = panel.get_by_role("button", name="Suspend consultation sales")
        resume = panel.get_by_role("button", name="Resume consultation sales")
        expect(page.locator("html")).to_have_attribute("lang", "en")
        expect(page.locator("footer a[href*='product_feedback']")).to_have_count(0)
        expect(outstanding).to_have_text("0 / 4")
        expect(status).to_have_text("Available")
        expect(panel.locator(".admin-capacity__details dd")).to_have_text(
            ["3", "Inactive"]
        )
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        panel.screenshot(path=tmp_path / "capacity-available.png")

        suspend.click()
        expect(page).to_have_url(path)
        expect(status).to_have_text("Unavailable")
        expect(outstanding).to_have_text("0 / 4")
        expect(panel.locator(".admin-capacity__details dd").last).to_have_text("Active")
        panel.screenshot(path=tmp_path / "capacity-suspended.png")

        resume.click()
        expect(status).to_have_text("Available")
        expect(suspend).to_be_visible()

        with review_sessions() as db:
            add_available_rights(db, 4)
        page.reload()
        expect(outstanding).to_have_text("4 / 4")
        expect(status).to_have_text("Unavailable")
        expect(panel.locator(".admin-capacity__details dd").last).to_have_text(
            "Inactive"
        )
        expect(suspend).to_be_visible()
        panel.screenshot(path=tmp_path / "capacity-limit-reached.png")

        with review_sessions.begin() as db:
            db.delete(db.get(ConsultationCapacityState, 1))
        page.reload()
        expect(panel).to_contain_text(
            "Capacity state unavailable. New consultation sales are closed."
        )
        expect(panel.get_by_role("button")).to_have_count(0)
        browser.close()
