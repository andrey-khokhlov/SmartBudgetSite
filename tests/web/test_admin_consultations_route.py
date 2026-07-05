def test_admin_consultations_page_opens(auth_client):
    """
    Test case: open protected consultation entitlements admin page.

    What we verify:
    - Admin consultations route is reachable with a valid admin cookie.
    - Admin protection accepts ADMIN_TOKEN from settings.
    - Template renders empty state.
    """
    response = auth_client.get(
        "/admin/consultations",
    )

    assert response.status_code == 200
    assert "Consultation entitlements" in response.text
    assert "No consultation entitlements found." in response.text
