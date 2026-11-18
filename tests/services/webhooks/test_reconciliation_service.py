from datetime import datetime, timedelta, UTC

import pytest

from app.services.webhooks.reconciliation_service import (
    reconcile_booking_confirmed_event,
)
from app.schemas.webhooks import NormalizedBookingConfirmedEvent
from app.models.consultation_entitlement import ConsultationEntitlementStatus
from app.core.config import settings
from app.models.enums import PaymentStatus
from app.services.calendly.calendly_api_client import CalendlyAPIError
from app.services.calendly.share_service import signed_correlation
from app.services.webhooks import reconciliation_service as reconciliation

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
    entitlement.provider_invitee_uri = entitlement.provider_event_uri + "/invitees/test-invitee-1"
    entitlement.status = ConsultationEntitlementStatus.BOOKED
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
    assert resolved_entitlement.provider_invitee_uri == event.provider_invitee_uri


def verified_booking(entitlement, event_id, booked_at, *, old_invitee=None):
    event_uri = f"https://api.calendly.com/scheduled_events/{event_id}"
    invitee_uri = event_uri + "/invitees/INVITEE"
    correlation = signed_correlation(entitlement.calendly_share_uri, entitlement.provisioning_reference)
    event = NormalizedBookingConfirmedEvent(
        provider="calendly", provider_event_uri=event_uri, provider_invitee_uri=invitee_uri,
        occurred_at=booked_at, invitee_status="active", correlation=correlation,
        old_invitee_uri=old_invitee,
    )
    provider_event = {"uri": event_uri, "status": "active", "event_type": entitlement.calendly_event_type_uri}
    provider_invitee = {
        "uri": invitee_uri, "event": event_uri, "status": "active",
        "created_at": booked_at.isoformat(), "tracking": {"utm_content": correlation},
        "old_invitee": old_invitee,
    }
    resources = {
        uri.removeprefix("https://api.calendly.com"): value
        for uri, value in ((event_uri, provider_event), (invitee_uri, provider_invitee))
    }
    if old_invitee:
        resources[old_invitee.removeprefix("https://api.calendly.com")] = {
            "uri": old_invitee, "status": "canceled", "rescheduled": True,
            "new_invitee": invitee_uri,
        }
    return event, resources


def pin_share(entitlement):
    entitlement.calendly_event_type_uri = "https://api.calendly.com/event_types/TEST"
    entitlement.calendly_share_uri = "https://api.calendly.com/shares/TEST"
    entitlement.provisioning_reference = "A" * 22


@pytest.mark.parametrize(
    "case",
    ["valid", "expired", "late", "inactive", "wrong_type", "wrong_share", "tampered",
     "missing", "provider_failed", "cancelled", "refunded", "missing_time"],
)
def test_first_verified_booking(db_session, monkeypatch, case):
    monkeypatch.setattr(settings, "SECRET_KEY", "signed-booking-test")
    entitlement = create_test_consultation_entitlement(db_session)
    pin_share(entitlement)
    expiry = entitlement.expires_at.replace(tzinfo=UTC)
    booked_at = expiry + timedelta(seconds=1) if case == "late" else expiry
    event, resources = verified_booking(entitlement, "FIRST", booked_at)
    invitee = resources["/scheduled_events/FIRST/invitees/INVITEE"]
    scheduled = resources["/scheduled_events/FIRST"]
    if case == "expired":
        entitlement.status = "expired"
    if case == "cancelled":
        entitlement.status = "cancelled"
    if case == "refunded":
        entitlement.sale_item.sale.payment_status = PaymentStatus.REFUNDED
    if case == "inactive":
        invitee["status"] = "canceled"
    if case == "wrong_type":
        scheduled["event_type"] += "-OTHER"
    if case == "wrong_share":
        entitlement.calendly_share_uri += "-OTHER"
    if case == "tampered":
        event.correlation = event.correlation[:-1] + ("X" if event.correlation[-1] != "X" else "Y")
        invitee["tracking"]["utm_content"] = event.correlation
    if case == "missing":
        event.correlation = None
    if case == "missing_time":
        invitee["created_at"] = None
    db_session.flush()
    monkeypatch.setattr(reconciliation, "get_resource", resources.__getitem__)
    if case == "provider_failed":
        def fail(_):
            raise CalendlyAPIError("timeout")
        monkeypatch.setattr(reconciliation, "get_resource", fail)
        with pytest.raises(CalendlyAPIError):
            reconcile_booking_confirmed_event(db_session, event)
    else:
        result = reconcile_booking_confirmed_event(db_session, event)
        assert (result is not None) == (case in {"valid", "expired"})
    if case in {"valid", "expired"}:
        assert entitlement.status == "booked"
        assert entitlement.booked_at == booked_at
        assert reconcile_booking_confirmed_event(db_session, event).id == entitlement.id
    else:
        assert entitlement.provider_event_uri is None


def test_reschedule_preserves_first_booking_after_deadline(db_session, monkeypatch):
    monkeypatch.setattr(settings, "SECRET_KEY", "signed-booking-test")
    entitlement = create_test_consultation_entitlement(db_session)
    pin_share(entitlement)
    booked_at = entitlement.expires_at.replace(tzinfo=UTC)
    first, resources = verified_booking(entitlement, "ORIGINAL", booked_at)
    db_session.flush()
    monkeypatch.setattr(reconciliation, "get_resource", resources.__getitem__)
    assert reconcile_booking_confirmed_event(db_session, first) is not None
    other, other_resources = verified_booking(entitlement, "UNRELATED", booked_at)
    resources.update(other_resources)
    assert reconcile_booking_confirmed_event(db_session, other) is None
    new, new_resources = verified_booking(
        entitlement, "RESCHEDULE", booked_at + timedelta(days=7),
        old_invitee=first.provider_invitee_uri,
    )
    resources.update(new_resources)
    assert reconcile_booking_confirmed_event(db_session, new) is not None
    assert entitlement.provider_invitee_uri == new.provider_invitee_uri
    assert entitlement.status == "booked"
    assert entitlement.booked_at.replace(tzinfo=UTC) == booked_at
    assert reconcile_booking_confirmed_event(db_session, new) is not None
    assert reconcile_booking_confirmed_event(db_session, first) is None


@pytest.mark.parametrize(("case", "accepted"), [
    ("A-first", True), ("B-first", True), ("A-already-canceled", True), ("expired", True),
    ("ordinary-cancellation", False), ("wrong-successor", False), ("wrong-predecessor", False),
    ("invalid-tracking", False), ("missing-tracking", False), ("late", False),
    ("cancelled", False), ("refunded", False), ("already-claimed", False),
])
def test_reschedule_delivery_order_and_recovery_guards(db_session, monkeypatch, case, accepted):
    monkeypatch.setattr(settings, "SECRET_KEY", "signed-booking-test")
    entitlement = create_test_consultation_entitlement(db_session)
    pin_share(entitlement)
    original_time = entitlement.expires_at.replace(tzinfo=UTC)
    original, resources = verified_booking(entitlement, "A", original_time)
    replacement, replacement_resources = verified_booking(
        entitlement, "B", original_time + timedelta(days=7),
        old_invitee=original.provider_invitee_uri,
    )
    db_session.flush()
    monkeypatch.setattr(reconciliation, "get_resource", resources.__getitem__)
    if case == "A-first":
        assert reconcile_booking_confirmed_event(db_session, original) is not None
    if case == "already-claimed":
        other, other_resources = verified_booking(entitlement, "OTHER", original_time)
        resources.update(other_resources)
        assert reconcile_booking_confirmed_event(db_session, other) is not None
    if case in ("expired", "cancelled"):
        entitlement.status = case
    if case == "refunded":
        entitlement.sale_item.sale.payment_status = PaymentStatus.REFUNDED

    original_invitee = resources["/scheduled_events/A/invitees/INVITEE"]
    resources.update({
        path: data for path, data in replacement_resources.items() if path.startswith("/scheduled_events/B")
    })
    original_invitee.update(
        status="canceled", rescheduled=True, new_invitee=replacement.provider_invitee_uri,
    )
    resources["/scheduled_events/A"]["status"] = "canceled"
    # Recovery must work even if Calendly omits tracking on the replacement.
    replacement.correlation = None
    replacement_invitee = resources["/scheduled_events/B/invitees/INVITEE"]
    replacement_invitee["tracking"] = None
    if case == "ordinary-cancellation":
        original_invitee["rescheduled"] = False
    if case == "wrong-successor":
        original_invitee["new_invitee"] += "-OTHER"
    if case == "wrong-predecessor":
        replacement_invitee["old_invitee"] += "-OTHER"
    if case == "invalid-tracking":
        entitlement.calendly_share_uri += "-OTHER"
    if case == "missing-tracking":
        original_invitee["tracking"] = None
    if case == "late":
        original_invitee["created_at"] = (original_time + timedelta(seconds=1)).isoformat()
    db_session.flush()
    if case == "A-already-canceled":
        assert reconcile_booking_confirmed_event(db_session, original) is None
    db_session.refresh(entitlement)
    previous = (entitlement.status, entitlement.provider_invitee_uri, entitlement.booked_at)
    result = reconcile_booking_confirmed_event(db_session, replacement)
    assert (result is not None) == accepted
    if not accepted:
        assert (entitlement.status, entitlement.provider_invitee_uri, entitlement.booked_at) == previous
        return

    for _ in range(2):
        assert reconcile_booking_confirmed_event(db_session, original) is None
        assert reconcile_booking_confirmed_event(db_session, replacement) is not None
    assert entitlement.status == "booked"
    assert entitlement.provider_event_uri == replacement.provider_event_uri
    assert entitlement.provider_invitee_uri == replacement.provider_invitee_uri
    assert entitlement.booked_at.replace(tzinfo=UTC) == original_time
