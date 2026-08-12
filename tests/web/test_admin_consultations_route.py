from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.models.consultation_entitlement import (
    ConsultationEntitlement,
    ConsultationEntitlementStatus,
)
from app.models.enums import PaymentStatus
from app.models.sale_item import SaleItem
from app.models.service_addon import ServiceAddon
from app.services.consultation_entitlement_service import (
    create_consultation_entitlement,
)
from app.services.sale_service import create_standalone_service_sale


def add_entitlement(db_session, *, status: str, expires_at: datetime, email: str):
    addon = db_session.query(ServiceAddon).first()
    if addon is None:
        addon = ServiceAddon(
            code="admin-expiration-consultation",
            name="Consultation",
            service_type="consultation",
            usage_type="standalone",
            family_slug="smartbudget",
            package_code="INT",
            currency_code="EUR",
            amount=Decimal("79.00"),
            is_active=True,
        )
        db_session.add(addon)
        db_session.flush()
    sale = create_standalone_service_sale(
        db=db_session,
        service_addon_id=addon.id,
        service_name=addon.name,
        customer_email=email,
        amount=addon.amount,
        currency=addon.currency_code,
        payment_status=PaymentStatus.PAID,
    )
    db_session.flush()
    sale_item = db_session.query(SaleItem).filter(SaleItem.sale_id == sale.id).one()
    entitlement = create_consultation_entitlement(db_session, sale_item)
    entitlement.status = status
    entitlement.expires_at = expires_at
    db_session.commit()
    return entitlement


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


def test_admin_reconciles_all_due_available_before_filtering_and_pagination(
    auth_client,
    db_session,
):
    now = datetime.now(UTC)
    due = add_entitlement(
        db_session,
        status=ConsultationEntitlementStatus.AVAILABLE.value,
        expires_at=now - timedelta(minutes=1),
        email="due@example.com",
    )
    future = add_entitlement(
        db_session,
        status=ConsultationEntitlementStatus.AVAILABLE.value,
        expires_at=now + timedelta(days=1),
        email="future@example.com",
    )
    booked = add_entitlement(
        db_session,
        status=ConsultationEntitlementStatus.BOOKED.value,
        expires_at=now - timedelta(days=1),
        email="booked@example.com",
    )
    cancelled = add_entitlement(
        db_session,
        status=ConsultationEntitlementStatus.CANCELLED.value,
        expires_at=now - timedelta(days=1),
        email="cancelled@example.com",
    )

    available_response = auth_client.get(
        "/admin/consultations?status=available&page=2"
    )

    assert available_response.status_code == 200
    db_session.expire_all()
    assert db_session.get(ConsultationEntitlement, due.id).status == "expired"
    assert db_session.get(ConsultationEntitlement, future.id).status == "available"
    assert db_session.get(ConsultationEntitlement, booked.id).status == "booked"
    assert db_session.get(ConsultationEntitlement, cancelled.id).status == "cancelled"

    available_first_page = auth_client.get("/admin/consultations?status=available")
    assert "future@example.com" in available_first_page.text
    assert "due@example.com" not in available_first_page.text

    expired_response = auth_client.get("/admin/consultations?status=expired")
    assert "due@example.com" in expired_response.text
    assert "future@example.com" not in expired_response.text
