from decimal import Decimal

from app.models.enums import PaymentStatus
from app.models.service_addon import ServiceAddon
from app.services.consultation_entitlement_service import (
    create_consultation_entitlement,
)
from app.services.sale_service import create_standalone_service_sale


def test_consultation_booking_page_opens_with_valid_token(client, db_session, monkeypatch):
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

    response = client.get(
        f"/consultation/book/{entitlement.booking_token}"
    )

    assert response.status_code == 200
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


