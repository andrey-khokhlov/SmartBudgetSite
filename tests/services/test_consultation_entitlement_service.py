import uuid

import pytest
from fastapi import HTTPException
from decimal import Decimal
from datetime import timedelta, UTC, datetime

from app.models.consultation_entitlement import ConsultationEntitlementStatus, ConsultationEntitlement
from app.models.service_addon import ServiceAddon
from app.models.product import Product
from app.models.product_release import ProductRelease
from app.services.consultation_entitlement_service import (
    DEFAULT_CONSULTATION_BOOKING_WINDOW_DAYS,
    create_consultation_entitlement,
    get_valid_consultation_entitlement_by_token,
    mark_entitlement_as_booked,
)
from app.services.sale_service import create_product_sale, create_standalone_service_sale


def create_test_consultation_entitlement(db_session):
    """
    Create a paid standalone consultation entitlement for service tests.

    Business rules:
    - Entitlement is created only for a consultation service sale item.
    - Returned entitlement starts in AVAILABLE status.

    Side effects:
    - Inserts ServiceAddon, Sale, SaleItem, and ConsultationEntitlement.
    - Flushes DB session through service calls.

    Invariants/restrictions:
    - Helper is test-only and must not be used by production code.
    """

    service_addon = ServiceAddon(
        code=f"consultation_1h_int_test_{uuid.uuid4()}",
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
    )
    db_session.flush()

    return create_consultation_entitlement(
        db=db_session,
        sale_item=sale.items[0],
    )


def test_create_consultation_entitlement_for_consultation_service_item(db_session):
    """
    Test case: create consultation entitlement for purchased consultation service item.

    What we verify:
    - Entitlement is created for the correct sale item.
    - Status is available.
    - Booking token is generated.
    - Expiration date is populated.
    - ORM relationship between sale item and entitlement works.
    """

    service_addon = ServiceAddon(
        code="consultation_1h_int_standalone_test",
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
    )
    db_session.flush()

    sale_item = sale.items[0]

    entitlement = create_consultation_entitlement(
        db=db_session,
        sale_item=sale_item,
    )

    actual_delta = entitlement.expires_at - entitlement.created_at

    assert actual_delta >= timedelta(days=DEFAULT_CONSULTATION_BOOKING_WINDOW_DAYS) - timedelta(seconds=1)
    assert actual_delta <= timedelta(days=DEFAULT_CONSULTATION_BOOKING_WINDOW_DAYS) + timedelta(seconds=1)

    assert entitlement.id is not None
    assert entitlement.sale_item_id == sale_item.id
    assert entitlement.status == ConsultationEntitlementStatus.AVAILABLE.value
    assert entitlement.booking_token is not None
    assert len(entitlement.booking_token) == 36
    assert entitlement.expires_at is not None

    assert sale_item.consultation_entitlement == entitlement


def test_create_consultation_entitlement_rejects_product_sale_item(db_session):
    """
    Test case: reject entitlement creation for product sale item.

    What we verify:
    - Product sale items cannot receive consultation entitlements.
    - Service raises HTTP 400.
    """

    product = Product(
        family_slug="smartbudget",
        slug="smartbudget-int-standard-entitlement-reject-test",
        name="SmartBudget",
        edition="Standard",

        archive_path="downloads/smartbudget-int-standard.zip",
        status="in_sale",
    )
    db_session.add(product)
    db_session.flush()

    release = ProductRelease(
        product_id=product.id,
        version="1.0",
        storage_provider="cloudflare_r2",
        storage_key="product-releases/entitlement-reject/1.0.zip",
        original_filename="SmartBudget_1.0.zip",
        is_active=True,
    )
    db_session.add(release)
    db_session.flush()

    sale = create_product_sale(
        db=db_session,
        product=product,
        product_release=release,
        customer_email="customer@example.com",
        amount=Decimal("39.00"),
        currency="EUR",
    )
    db_session.flush()

    sale_item = sale.items[0]

    with pytest.raises(HTTPException) as exc_info:
        create_consultation_entitlement(
            db=db_session,
            sale_item=sale_item,
        )

    assert exc_info.value.status_code == 400
    assert (
        exc_info.value.detail
        == "Consultation entitlement can only be created for service sale items."
    )


def test_create_consultation_entitlement_rejects_duplicate_creation(db_session):
    """
    Test case: reject duplicate entitlement creation for the same consultation sale item.

    What we verify:
    - One consultation sale item may have only one entitlement.
    - Second entitlement creation attempt raises HTTP 409.
    """

    service_addon = ServiceAddon(
        code="consultation_1h_int_duplicate_test",
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
    )
    db_session.flush()

    sale_item = sale.items[0]

    create_consultation_entitlement(
        db=db_session,
        sale_item=sale_item,
    )

    with pytest.raises(HTTPException) as exc_info:
        create_consultation_entitlement(
            db=db_session,
            sale_item=sale_item,
        )

    assert exc_info.value.status_code == 409
    assert (
        exc_info.value.detail
        == "Consultation entitlement already exists for this sale item."
    )


def test_get_valid_consultation_entitlement_by_token_returns_entitlement(
    db_session,
):
    """
    Test case: validate active consultation booking token.

    What we verify:
    - Existing available token returns entitlement.
    - Returned entitlement matches created entitlement.
    """

    service_addon = ServiceAddon(
        code="consultation_1h_int_token_test",
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
    )
    db_session.flush()

    sale_item = sale.items[0]

    entitlement = create_consultation_entitlement(
        db=db_session,
        sale_item=sale_item,
    )

    result = get_valid_consultation_entitlement_by_token(
        db=db_session,
        booking_token=entitlement.booking_token,
    )

    assert result.id == entitlement.id
    assert result.booking_token == entitlement.booking_token
    assert (
        result.status
        == ConsultationEntitlementStatus.AVAILABLE.value
    )


def test_get_valid_consultation_entitlement_by_token_rejects_unknown_token(
    db_session,
):
    """
    Test case: reject unknown consultation booking token.

    What we verify:
    - Unknown token does not grant booking access.
    - Service raises HTTP 404.
    """

    with pytest.raises(HTTPException) as exc_info:
        get_valid_consultation_entitlement_by_token(
            db=db_session,
            booking_token="00000000-0000-0000-0000-000000000000",
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Consultation booking link was not found."


def test_get_valid_consultation_entitlement_by_token_rejects_expired_token(
    db_session,
):
    """
    Test case: reject expired consultation booking token.

    What we verify:
    - Expired entitlement cannot access booking flow.
    - Service raises HTTP 403.
    """

    service_addon = ServiceAddon(
        code="consultation_1h_int_expired_test",
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
    )
    db_session.flush()

    sale_item = sale.items[0]

    entitlement = create_consultation_entitlement(
        db=db_session,
        sale_item=sale_item,
    )

    entitlement.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db_session.flush()

    with pytest.raises(HTTPException) as exc_info:
        get_valid_consultation_entitlement_by_token(
            db=db_session,
            booking_token=entitlement.booking_token,
        )

    assert exc_info.value.status_code == 403
    assert (
        exc_info.value.detail
        == "Consultation booking link has expired."
    )


def test_get_valid_consultation_entitlement_by_token_rejects_booked_token(
    db_session,
):
    """
    Test case: reject already booked consultation booking token.

    What we verify:
    - Booked entitlement cannot access booking flow.
    - Service raises HTTP 403 with a booked-specific message.
    """

    entitlement = create_test_consultation_entitlement(db_session)
    entitlement.status = ConsultationEntitlementStatus.BOOKED.value
    db_session.flush()

    with pytest.raises(HTTPException) as exc_info:
        get_valid_consultation_entitlement_by_token(
            db=db_session,
            booking_token=entitlement.booking_token,
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "This consultation has already been booked."


def test_mark_entitlement_as_booked_happy_path(db_session):
    """
    Test case: mark consultation entitlement as booked.

    What we verify:
    - AVAILABLE entitlement transitions to BOOKED.
    - Booking timestamp is persisted.
    - Provider metadata is persisted.
    - Booking state survives DB reload.
    """

    service_addon = ServiceAddon(
        code="consultation_1h_int_standalone_booking_test",
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
    )
    db_session.flush()

    sale_item = sale.items[0]

    entitlement = create_consultation_entitlement(
        db=db_session,
        sale_item=sale_item,
    )

    booked_at = datetime(2026, 5, 19, 12, 0, tzinfo=UTC)

    result = mark_entitlement_as_booked(
        db=db_session,
        entitlement=entitlement,
        booking_provider="calendly",
        provider_event_uri="https://api.calendly.com/scheduled_events/test-event",
        provider_invitee_uri=(
            "https://api.calendly.com/"
            "scheduled_events/test-event/invitees/test-invitee"
        ),
        booked_at=booked_at,
    )

    db_session.expire_all()

    refreshed = db_session.get(
        ConsultationEntitlement,
        entitlement.id,
    )

    assert result.id == entitlement.id

    assert refreshed.status == ConsultationEntitlementStatus.BOOKED.value

    assert refreshed.booked_at.replace(tzinfo=UTC) == booked_at

    assert refreshed.booking_provider == "calendly"

    assert (
        refreshed.provider_event_uri
        == "https://api.calendly.com/scheduled_events/test-event"
    )

    assert (
        refreshed.provider_invitee_uri
        == "https://api.calendly.com/"
           "scheduled_events/test-event/invitees/test-invitee"
    )


def test_mark_entitlement_as_booked_is_idempotent(db_session):
    """
    Test case: repeated booking confirmation for already booked entitlement.

    What we verify:
    - Repeated booking confirmation does not fail.
    - Original booked_at is preserved.
    - Original provider metadata is preserved.
    """

    service_addon = ServiceAddon(
        code="consultation_1h_int_standalone_booking_idempotent_test",
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
    )
    db_session.flush()

    entitlement = create_consultation_entitlement(
        db=db_session,
        sale_item=sale.items[0],
    )

    first_booked_at = datetime(2026, 5, 19, 12, 0, tzinfo=UTC)

    mark_entitlement_as_booked(
        db=db_session,
        entitlement=entitlement,
        booking_provider="calendly",
        provider_event_uri="https://api.calendly.com/scheduled_events/original-event",
        provider_invitee_uri=(
            "https://api.calendly.com/"
            "scheduled_events/original-event/invitees/original-invitee"
        ),
        booked_at=first_booked_at,
    )

    second_booked_at = datetime(2026, 5, 20, 12, 0, tzinfo=UTC)

    result = mark_entitlement_as_booked(
        db=db_session,
        entitlement=entitlement,
        booking_provider="calendly",
        provider_event_uri="https://api.calendly.com/scheduled_events/duplicate-event",
        provider_invitee_uri=(
            "https://api.calendly.com/"
            "scheduled_events/duplicate-event/invitees/duplicate-invitee"
        ),
        booked_at=second_booked_at,
    )

    db_session.expire_all()

    refreshed = db_session.get(
        ConsultationEntitlement,
        entitlement.id,
    )

    assert result.id == entitlement.id
    assert refreshed.status == ConsultationEntitlementStatus.BOOKED.value
    assert refreshed.booked_at.replace(tzinfo=UTC) == first_booked_at
    assert refreshed.booking_provider == "calendly"

    assert (
        refreshed.provider_event_uri
        == "https://api.calendly.com/scheduled_events/original-event"
    )

    assert (
        refreshed.provider_invitee_uri
        == "https://api.calendly.com/"
           "scheduled_events/original-event/invitees/original-invitee"
    )


def test_expired_entitlement_cannot_be_marked_as_booked(db_session):
    """
    Test case: expired entitlement cannot transition to booked.

    What we verify:
    - EXPIRED entitlement cannot become BOOKED.
    - Service raises HTTPException.
    - Booking metadata is not persisted.
    """

    service_addon = ServiceAddon(
        code="consultation_1h_int_expired_booking_test",
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
    )
    db_session.flush()

    entitlement = create_consultation_entitlement(
        db=db_session,
        sale_item=sale.items[0],
    )

    entitlement.status = ConsultationEntitlementStatus.EXPIRED.value

    db_session.flush()

    with pytest.raises(HTTPException) as exc_info:
        mark_entitlement_as_booked(
            db=db_session,
            entitlement=entitlement,
            booking_provider="calendly",
            provider_event_uri="https://api.calendly.com/scheduled_events/test-event",
            provider_invitee_uri=(
                "https://api.calendly.com/"
                "scheduled_events/test-event/invitees/test-invitee"
            ),
            booked_at=datetime(2026, 5, 19, 12, 0, tzinfo=UTC),
        )

    db_session.expire_all()

    refreshed = db_session.get(
        ConsultationEntitlement,
        entitlement.id,
    )

    assert exc_info.value.status_code == 400

    assert (
        exc_info.value.detail
        == "Consultation entitlement is not available for booking."
    )

    assert refreshed.status == ConsultationEntitlementStatus.EXPIRED.value
    assert refreshed.booked_at is None
    assert refreshed.booking_provider is None
    assert refreshed.provider_event_uri is None
    assert refreshed.provider_invitee_uri is None


def test_cancelled_entitlement_cannot_be_marked_as_booked(db_session):
    """
    Test case: cancelled entitlement cannot transition to booked.

    What we verify:
    - CANCELLED entitlement cannot become BOOKED.
    - Service raises HTTPException.
    - Booking metadata is not persisted.
    """

    entitlement = create_test_consultation_entitlement(db_session)

    entitlement.status = ConsultationEntitlementStatus.CANCELLED.value
    db_session.flush()

    with pytest.raises(HTTPException) as exc_info:
        mark_entitlement_as_booked(
            db=db_session,
            entitlement=entitlement,
            booking_provider="calendly",
        )

    assert exc_info.value.status_code == 400
    assert (
        exc_info.value.detail
        == "Consultation entitlement is not available for booking."
    )
