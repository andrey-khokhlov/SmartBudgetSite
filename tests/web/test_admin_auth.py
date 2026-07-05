from app.core.config import settings

def test_admin_login_cookie_expires_after_8_hours(client):
    """
    Test case: admin login cookie has finite lifetime.

    What we verify:
    - Successful admin login sets auth cookie.
    - Admin cookie expires after 8 hours.
    """

    response = client.post(
        "/admin/login",
        data={"token": settings.ADMIN_TOKEN},
        follow_redirects=False,
    )

    set_cookie_header = response.headers.get("set-cookie", "")

    assert response.status_code == 303
    assert "admin_token=" in set_cookie_header
    assert "Max-Age=28800" in set_cookie_header
