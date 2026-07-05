from datetime import datetime, UTC

from app.services.webhooks.reconciliation_service import (
    reconcile_booking_confirmed_event,
)
from app.schemas.webhooks import NormalizedBookingConfirmedEvent

from tests.services.test_consultation_entitlement_service import (
    create_test_consultation_entitlement,
)


def test_reconcile_booking_confirmed_event_resolves_existing_entitlement(db_session):
    """
    Test case: normalized booking event resolves existing entitlement.

    Business rules:
    - Webhook reconciliation uses provider_event_uri.
    - Webhook reconciliation must not create new entitlements.
    - Lifecycle transition is not applied by this lookup-only step.
    """

    entitlement = create_test_consultation_entitlement(db_session)

    entitlement.provider_event_uri = "https://api.calendly.com/scheduled_events/test-event-1"
    db_session.flush()

    event = NormalizedBookingConfirmedEvent(
        provider="calendly",
        provider_event_uri="https://api.calendly.com/scheduled_events/test-event-1",
        provider_invitee_uri="https://api.calendly.com/scheduled_events/test-event-1/invitees/test-invitee-1",
        occurred_at=datetime.now(UTC)
    )

    resolved_entitlement = reconcile_booking_confirmed_event(
        db=db_session,
        event=event,
    )

    assert resolved_entitlement is not None
    assert resolved_entitlement.id == entitlement.id
    assert resolved_entitlement.status == entitlement.status
    assert resolved_entitlement.provider_invitee_uri is None
