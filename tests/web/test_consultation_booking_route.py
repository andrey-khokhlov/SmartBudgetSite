from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.models.enums import PaymentStatus
from app.models.service_addon import ServiceAddon
from app.services.consultation_entitlement_service import (
    create_consultation_entitlement,
)
from app.services.sale_service import create_standalone_service_sale

CAPABILITY_RESPONSE_HEADERS = {
    "cache-control": "private, no-store, max-age=0",
    "pragma": "no-cache",
    "expires": "0",
    "referrer-policy": "no-referrer",
}


def assert_capability_response_headers(response):
    for name, expected_value in CAPABILITY_RESPONSE_HEADERS.items():
        assert response.headers[name] == expected_value


def test_consultation_booking_page_opens_with_valid_token(
    client, db_session, monkeypatch
):
    """
    Test case: open consultation booking page with valid token.

    What we verify:
    - Route validates backend-owned booking token.
    - Valid entitlement renders booking page.
    - Booking page receives entitlement data.
    """

    service_addon = ServiceAddon(
        code="consultation_1h_int_booking_route_test",
        name="1:1 SmartBudget consultation",
        service_type="consultation",
        usage_type="standalone",
        family_slug="smartbudget",
        package_code="INT",
        currency_code="EUR",
        amount=Decimal("79.00"),
        is_active=True,
    )
    db_session.add(service_addon)
    db_session.flush()

    sale = create_standalone_service_sale(
        db=db_session,
        service_addon_id=service_addon.id,
        service_name=service_addon.name,
        customer_email="customer@example.com",
        amount=service_addon.amount,
        currency=service_addon.currency_code,
        payment_status=PaymentStatus.PAID,
    )
    db_session.flush()

    sale_item = sale.items[0]

    entitlement = create_consultation_entitlement(
        db=db_session,
        sale_item=sale_item,
    )
    db_session.commit()

    monkeypatch.setattr(
        "app.core.config.settings.CALENDLY_CONSULTATION_URL",
        "https://calendly.com/test/smartbudget-consultation",
    )

    response = client.get(f"/consultation/book/{entitlement.booking_token}")

    assert response.status_code == 200
    assert_capability_response_headers(response)
    assert "Your consultation access is active." in response.text
    assert "Please use the button below to schedule your session." in response.text
    assert entitlement.status in response.text
    assert "Book your consultation" in response.text
    assert 'id="consultation-book-button"' in response.text
    assert 'target="_blank"' in response.text
    assert 'rel="noopener noreferrer"' in response.text
    assert "Ref:" in response.text
    assert entitlement.booking_token[:8] in response.text
    assert entitlement.booking_token not in response.text


def test_consultation_booking_fails_closed_after_owning_sale_is_refunded(
    client, db_session
):
    service_addon = ServiceAddon(
        code="consultation_refunded_booking_route_test",
        name="Refunded consultation",
        service_type="consultation",
        usage_type="standalone",
        family_slug="smartbudget",
        package_code="INT",
        currency_code="EUR",
        amount=Decimal("79.00"),
        is_active=True,
    )
    db_session.add(service_addon)
    db_session.flush()
    sale = create_standalone_service_sale(
        db=db_session,
        service_addon_id=service_addon.id,
        service_name=service_addon.name,
        customer_email="refunded@example.com",
        amount=service_addon.amount,
        currency=service_addon.currency_code,
        payment_status=PaymentStatus.PAID,
    )
    db_session.flush()
    entitlement = create_consultation_entitlement(db_session, sale.items[0])
    sale.payment_status = PaymentStatus.REFUNDED
    db_session.commit()

    response = client.get(f"/consultation/book/{entitlement.booking_token}")

    assert response.status_code == 403
    assert_capability_response_headers(response)
    assert response.headers["content-type"].startswith("text/html")
    assert "Consultation booking is unavailable" in response.text
    assert "Access to consultation booking has been cancelled." in response.text
    assert "Contact support" in response.text
    assert "message_type=purchase_or_download_issue" in response.text
    assert entitlement.booking_token not in response.text
    assert '"detail"' not in response.text
    assert "Consultation booking link is no longer available." not in response.text

    localized_response = client.get(
        f"/consultation/book/{entitlement.booking_token}?lang=ru"
    )

    assert localized_response.status_code == 403
    assert_capability_response_headers(localized_response)
    assert localized_response.headers["content-type"].startswith("text/html")
    assert "Запись на консультацию недоступна" in localized_response.text
    assert "Доступ к записи на консультацию был отменён." in localized_response.text
    assert "Обратитесь в поддержку" in localized_response.text
    assert entitlement.booking_token not in localized_response.text
    assert '"detail"' not in localized_response.text


@pytest.mark.parametrize(
    ("status_code", "detail", "expected"),
    [
        (
            404,
            "Consultation booking link was not found.",
            "This consultation booking link is invalid or unavailable.",
        ),
        (
            403,
            "This consultation has already been booked.",
            "This consultation has already been booked.",
        ),
        (
            403,
            "Consultation booking link has expired.",
            "This consultation booking access has expired.",
        ),
        (
            403,
            "Consultation booking link is no longer available.",
            "Access to consultation booking has been cancelled.",
        ),
    ],
)
def test_consultation_booking_errors_receive_capability_protection_headers(
    client,
    monkeypatch,
    status_code,
    detail,
    expected,
):
    def reject(*args, **kwargs):
        raise HTTPException(status_code=status_code, detail=detail)

    monkeypatch.setattr(
        "app.web.routes.get_valid_consultation_entitlement_by_token",
        reject,
    )

    response = client.get("/consultation/book/booking-secret")

    assert response.status_code == status_code
    assert_capability_response_headers(response)
    assert response.headers["content-type"].startswith("text/html")
    assert "Consultation booking is unavailable" in response.text
    assert expected in response.text
    assert "Contact support" in response.text
    assert '"detail"' not in response.text
    assert "booking-secret" not in response.text


def test_consultation_booking_renders_generic_html_for_internal_http_error(
    client,
    monkeypatch,
):
    def reject(*args, **kwargs):
        raise HTTPException(status_code=503, detail="Internal provider failure")

    monkeypatch.setattr(
        "app.web.routes.get_valid_consultation_entitlement_by_token",
        reject,
    )

    response = client.get("/consultation/book/booking-secret")

    assert response.status_code == 503
    assert_capability_response_headers(response)
    assert response.headers["content-type"].startswith("text/html")
    assert "Consultation booking is unavailable" in response.text
    assert "Consultation booking is temporarily unavailable" in response.text
    assert "Internal provider failure" not in response.text
    assert '"detail"' not in response.text
    assert "booking-secret" not in response.text


def test_consultation_unsupported_method_receives_capability_protection_headers(
    client,
):
    response = client.post("/consultation/book/unsupported-method-secret")

    assert response.status_code == 405
    assert_capability_response_headers(response)
    assert "unsupported-method-secret" not in response.text
