from contextlib import nullcontext

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.consultation_entitlement import (
    ConsultationEntitlement,
    ConsultationEntitlementStatus as Status,
)
from app.models.enums import PaymentStatus
from app.repositories.consultation_entitlement_repository import (
    ConsultationEntitlementRepository as Repository,
)
from app.schemas.webhooks import NormalizedBookingConfirmedEvent
from app.services.calendly.calendly_api_client import (
    CALENDLY_API_BASE_URL,
    get_resource,
    invitee_path,
    resource_path,
)
from app.services.calendly.share_service import correlation_reference, valid_correlation
from app.services.consultation_cancellation_service import record_cancellation_booking
from app.services.consultation_entitlement_service import (
    _ensure_utc_aware,
    mark_entitlement_as_booked,
    update_rescheduled_booking,
)
from app.services.webhooks.payload_normalizers.calendly_payload_normalizer import (
    invitee_created_at,
)


def _tracking_reference(invitee: dict) -> str | None:
    tracking = invitee.get("tracking")
    return tracking.get("utm_content") if isinstance(tracking, dict) else None


def reconcile_booking_confirmed_event(
    db: Session,
    event: NormalizedBookingConfirmedEvent,
) -> ConsultationEntitlement | None:
    try:
        event_path = resource_path(event.provider_event_uri, "scheduled_events")
        new_path = invitee_path(event.provider_invitee_uri)
        old_path = (
            invitee_path(event.old_invitee_uri) if event.old_invitee_uri else None
        )
    except ValueError:
        return None
    if new_path.rsplit("/invitees/", 1)[0] != event_path or old_path == new_path:
        return None
    event_uri = CALENDLY_API_BASE_URL + event_path
    invitee_uri = CALENDLY_API_BASE_URL + new_path
    linked = Repository.get_by_provider_event_uri(db, event_uri)
    if linked is not None:
        if (
            linked.status == Status.BOOKED
            and linked.provider_invitee_uri == invitee_uri
        ):
            return linked
        return None
    reference = correlation_reference(event.correlation)
    if (
        event.provider != "calendly"
        or event.invitee_status != "active"
        or event.new_invitee_uri
        or not (reference or old_path)
    ):
        return None

    invitee = get_resource(new_path)
    scheduled = get_resource(event_path)
    provider_status = invitee.get("status")
    try:
        if (
            invitee_path(invitee.get("uri")) != new_path
            or resource_path(invitee.get("event"), "scheduled_events") != event_path
            or resource_path(scheduled.get("uri"), "scheduled_events") != event_path
            or provider_status not in ("active", "canceled")
            or scheduled.get("status") != provider_status
            or invitee.get("new_invitee")
            or (
                invitee_path(invitee["old_invitee"])
                if invitee.get("old_invitee")
                else None
            )
            != old_path
        ):
            return None
        event_type = resource_path(scheduled.get("event_type"), "event_types")
        if old_path:
            predecessor = get_resource(old_path)
            if (
                invitee_path(predecessor.get("uri")) != old_path
                or predecessor.get("status") != "canceled"
                or predecessor.get("rescheduled") is not True
                or invitee_path(predecessor.get("new_invitee")) != new_path
            ):
                return None
    except ValueError:
        return None

    provider_correlation = _tracking_reference(invitee)
    original_correlation = provider_correlation
    original_time = invitee_created_at(invitee.get("created_at"))
    recovering = False
    if old_path:
        old_uri = CALENDLY_API_BASE_URL + old_path
        entitlement = Repository.lock_owner_and_entitlement(
            db,
            ConsultationEntitlement.provider_invitee_uri,
            old_uri,
        )
        if entitlement is None:
            evidence_ids = Repository.cancellation_target_ids(db, old_uri)
            if len(evidence_ids) > 1:
                return None
            if evidence_ids:
                entitlement = Repository.lock_owner_and_entitlement(
                    db, ConsultationEntitlement.id, evidence_ids[0],
                )
        if entitlement is None:
            # The predecessor's own tracking and timestamp establish the first booking.
            original_correlation = _tracking_reference(predecessor)
            reference = correlation_reference(original_correlation)
            original_time = invitee_created_at(predecessor.get("created_at"))
            if not reference or original_time is None or predecessor.get("old_invitee"):
                return None
            original_event_path = old_path.rsplit("/invitees/", 1)[0]
            try:
                if (
                    resource_path(predecessor.get("event"), "scheduled_events")
                    != original_event_path
                ):
                    return None
                original_event = get_resource(original_event_path)
                if (
                    resource_path(original_event.get("uri"), "scheduled_events")
                    != original_event_path
                    or resource_path(original_event.get("event_type"), "event_types")
                    != event_type
                ):
                    return None
            except ValueError:
                return None
            entitlement = Repository.lock_owner_and_entitlement(
                db,
                ConsultationEntitlement.provisioning_reference,
                reference,
            )
            recovering = True
    else:
        entitlement = Repository.lock_owner_and_entitlement(
            db,
            ConsultationEntitlement.provisioning_reference,
            reference,
        )
    if (
        entitlement is None
        or not entitlement.calendly_event_type_uri
        or CALENDLY_API_BASE_URL + event_type != entitlement.calendly_event_type_uri
    ):
        return None
    cancellation = entitlement.cancellation
    if provider_status == "canceled" and cancellation is None:
        return None
    payment_status = entitlement.sale_item.sale.payment_status
    if payment_status != PaymentStatus.PAID and not (
        cancellation is not None and payment_status == PaymentStatus.REFUNDED
    ):
        return None
    linked = Repository.get_by_provider_event_uri(db, event_uri)
    if linked is not None:
        return (
            linked
            if linked.id == entitlement.id
            and linked.provider_invitee_uri == invitee_uri
            else None
        )
    if recovering and not valid_correlation(original_correlation, entitlement):
        return None
    if old_path:
        # Calendly may omit tracking on reschedule. Present tracking must agree.
        if any(
            value is not None and not valid_correlation(value, entitlement)
            for value in (event.correlation, provider_correlation)
        ):
            return None
    # The original may have been linked while recovery was verifying it.
    updating = bool(
        old_path
        and entitlement.status == Status.BOOKED
        and entitlement.booking_provider == "calendly"
        and entitlement.provider_invitee_uri == old_uri
    )
    if cancellation is not None:
        if (cancellation.event_uri, cancellation.invitee_uri) == (event_uri, invitee_uri):
            return entitlement
        if old_path and cancellation.invitee_uri == old_uri and not updating:
            record_cancellation_booking(entitlement, event_uri, invitee_uri)
            return entitlement
        if cancellation.invitee_uri and (not old_path or cancellation.invitee_uri != old_uri):
            return None
    if not updating and (
        (old_path and not recovering)
        or (
            entitlement.status not in (Status.AVAILABLE, Status.EXPIRED)
            and not (cancellation is not None and entitlement.status == Status.CANCELLED)
        )
        or entitlement.provider_event_uri
        or entitlement.provider_invitee_uri
        or original_time is None
        or original_time < _ensure_utc_aware(entitlement.created_at)
        or (
            not recovering
            and (
                original_time != event.occurred_at
                or provider_correlation != event.correlation
                or not valid_correlation(provider_correlation, entitlement)
            )
        )
    ):
        return None
    if provider_status == "canceled" or not updating and (
        original_time > _ensure_utc_aware(entitlement.expires_at)
        or entitlement.status == Status.CANCELLED
        or payment_status == PaymentStatus.REFUNDED
    ):
        if cancellation is None:
            return None
        record_cancellation_booking(entitlement, event_uri, invitee_uri)
        return entitlement

    # The existing unique event index also arbitrates claims on different Sales.
    try:
        savepoint = (
            db.begin_nested()
            if db.get_bind().dialect.name == "postgresql"
            else nullcontext()
        )
        with savepoint:
            if updating:
                update_rescheduled_booking(db, entitlement, event_uri, invitee_uri)
            else:
                mark_entitlement_as_booked(
                    db,
                    entitlement,
                    booking_provider="calendly",
                    provider_event_uri=event_uri,
                    provider_invitee_uri=invitee_uri,
                    booked_at=original_time,
                    verified_provider_booking=True,
                )
            record_cancellation_booking(entitlement, event_uri, invitee_uri)
    except IntegrityError as exc:
        constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
        if constraint != "uq_consultation_entitlements_provider_event_uri":
            raise
        return None
    return entitlement
