import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app

TEST_ADMIN_TOKEN = "test-admin-token"


def test_production_login_sets_secure_admin_cookie(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "APP_ENV", "prod")
    monkeypatch.setattr(settings, "ADMIN_TOKEN", TEST_ADMIN_TOKEN)

    with TestClient(app, base_url="https://testserver") as client:
        response = client.post(
            "/admin/login",
            data={"token": TEST_ADMIN_TOKEN},
            follow_redirects=False,
        )

    set_cookie_header = response.headers["set-cookie"]

    assert response.status_code == 303
    assert "admin_token=" in set_cookie_header
    assert "Secure" in set_cookie_header
    assert "HttpOnly" in set_cookie_header
    assert "SameSite=lax" in set_cookie_header
    assert "Path=/" in set_cookie_header
    assert "Max-Age=28800" in set_cookie_header


def test_development_login_cookie_authenticates_over_http(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "APP_ENV", "dev")
    monkeypatch.setattr(settings, "ADMIN_TOKEN", TEST_ADMIN_TOKEN)

    response = client.post(
        "/admin/login",
        data={"token": TEST_ADMIN_TOKEN},
        follow_redirects=False,
    )

    set_cookie_header = response.headers["set-cookie"]
    protected_response = client.get("/admin")

    assert response.status_code == 303
    assert "Secure" not in set_cookie_header
    assert protected_response.status_code == 200


def test_production_https_logout_deletes_secure_admin_cookie(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "APP_ENV", "prod")
    monkeypatch.setattr(settings, "ADMIN_TOKEN", TEST_ADMIN_TOKEN)

    with TestClient(app, base_url="https://testserver") as client:
        login_response = client.post(
            "/admin/login",
            data={"token": TEST_ADMIN_TOKEN},
            follow_redirects=False,
        )
        authenticated_response = client.get("/admin")
        logout_response = client.post("/admin/logout", follow_redirects=False)
        protected_response = client.get("/admin")

    delete_cookie_header = logout_response.headers["set-cookie"]

    assert login_response.status_code == 303
    assert authenticated_response.status_code == 200
    assert logout_response.status_code == 303
    assert "admin_token=" in delete_cookie_header
    assert "Max-Age=0" in delete_cookie_header
    assert "Path=/" in delete_cookie_header
    assert protected_response.status_code == 403


def test_invalid_admin_login_does_not_set_cookie(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "APP_ENV", "dev")
    monkeypatch.setattr(settings, "ADMIN_TOKEN", TEST_ADMIN_TOKEN)

    response = client.post(
        "/admin/login",
        data={"token": "incorrect-admin-token"},
        follow_redirects=False,
    )

    assert response.status_code == 403
    assert "set-cookie" not in response.headers
