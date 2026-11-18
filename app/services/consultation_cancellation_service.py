from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.models.consultation_cancellation import ConsultationCancellation
from app.models.consultation_entitlement import ConsultationEntitlement
from app.models.enums import PaymentStatus
from app.repositories.consultation_entitlement_repository import (
    ConsultationEntitlementRepository,
)
from app.repositories.refund_operation_repository import RefundOperationRepository
from app.services.calendly.calendly_api_client import (
    CALENDLY_API_BASE_URL,
    CalendlyAPIError,
    api_request,
    get_resource,
    invitee_path,
    resource_path,
)
from app.services.consultation_entitlement_service import _ensure_utc_aware
from app.services.webhooks.payload_normalizers.calendly_payload_normalizer import (
    invitee_created_at,
)

VERIFIED_OUTCOMES = {"cancelled", "elapsed"}


def close_consultation_access(
    entitlement: ConsultationEntitlement,
    now: datetime,
    *,
    request_id: int | None = None,
) -> None:
    if entitlement.cancellation is None:
        entitlement.cancellation = ConsultationCancellation(
            access_closed_at=now,
            refund_request_id=request_id,
            event_uri=entitlement.provider_event_uri,
            invitee_uri=entitlement.provider_invitee_uri,
        )
    elif request_id is not None and entitlement.cancellation.refund_request_id is None:
        entitlement.cancellation.refund_request_id = request_id


def record_cancellation_booking(
    entitlement: ConsultationEntitlement,
    event_uri: str,
    invitee_uri: str,
) -> None:
    row = entitlement.cancellation
    if row is None or (row.event_uri, row.invitee_uri) == (event_uri, invitee_uri):
        return
    row.event_uri, row.invitee_uri = event_uri, invitee_uri
    row.provider_outcome = None
    row.verified_at = None
    row.next_attempt_at = None


def consultation_disposition(entitlement: ConsultationEntitlement | None) -> str:
    if entitlement is None:
        return "ownership_unresolved"
    if entitlement.cancellation is None:
        return "coordination_required"
    row = entitlement.cancellation
    if (
        row.event_uri
        or row.invitee_uri
        or entitlement.booked_at
        or entitlement.status == "booked"
    ):
        if row.verified_at and row.provider_outcome in VERIFIED_OUTCOMES:
            return "verified"
        if (
            row.provider_outcome == "checking"
            and row.next_attempt_at
            and _ensure_utc_aware(row.next_attempt_at) <= datetime.now(UTC)
        ):
            return "provider_unavailable"
        return row.provider_outcome or "meeting_pending"
    if entitlement.calendly_revoked_at:
        return "verified"
    if entitlement.calendly_share_uri or entitlement.provisioning_claimed_at:
        return entitlement.calendly_revoke_outcome or "share_pending"
    return "verified"


def disposition_unavailable(outcome: str) -> bool:
    return outcome in {
        "ownership_unresolved",
        "provider_unavailable",
        "provider_not_found",
        "provider_conflict",
        "provider_booked",
        "unauthorized",
        "forbidden",
        "rate_limited",
        "temporary_error",
        "ambiguous_timeout",
        "ambiguous_transport",
        "unexpected_response",
    }


def _verify_meeting(event_uri, invitee_uri, event_type_uri, *, predecessor_uri=None):
    event_path = resource_path(event_uri, "scheduled_events")
    person_path = invitee_path(invitee_uri)
    if person_path.rsplit("/invitees/", 1)[0] != event_path:
        return "ownership_unresolved", event_path, None
    event = get_resource(event_path)
    person = get_resource(person_path)
    if (
        resource_path(event.get("uri"), "scheduled_events") != event_path
        or invitee_path(person.get("uri")) != person_path
        or resource_path(person.get("event"), "scheduled_events") != event_path
        or resource_path(event.get("event_type"), "event_types")
        != resource_path(event_type_uri, "event_types")
        or (
            predecessor_uri is not None
            and invitee_path(person.get("old_invitee")) != invitee_path(predecessor_uri)
        )
    ):
        return "ownership_unresolved", event_path, None
    if person.get("new_invitee") or person.get("rescheduled") is True:
        if person.get("status") != "canceled" or person.get("rescheduled") is not True:
            return "ownership_unresolved", event_path, None
        successor = invitee_path(person.get("new_invitee"))
        return "replacement_pending", event_path, successor
    if person.get("rescheduled") is not False or "new_invitee" not in person:
        return "ownership_unresolved", event_path, None
    if event.get("status") == person.get("status") == "canceled":
        return "cancelled", event_path, None
    if event.get("status") != "active" or person.get("status") != "active":
        return "ownership_unresolved", event_path, None
    start = invitee_created_at(event.get("start_time"))
    end = invitee_created_at(event.get("end_time"))
    if start is None or end is None or end <= start:
        return "ownership_unresolved", event_path, None
    now = datetime.now(UTC)
    if end <= now:
        return "elapsed", event_path, None
    if start <= now:
        return "in_progress", event_path, None
    event_type = get_resource(resource_path(event_type_uri, "event_types"))
    if (
        resource_path(event_type.get("uri"), "event_types")
        != resource_path(event_type_uri, "event_types")
        or event_type.get("kind") != "solo"
        or "pooling_type" not in event_type
        or event_type.get("pooling_type") is not None
        or not isinstance(event.get("invitees_counter"), dict)
        or event["invitees_counter"].get("active") != 1
    ):
        return "ownership_unresolved", event_path, None
    if start <= datetime.now(UTC):
        return "in_progress", event_path, None
    return "active", event_path, None


def check_consultation_cancellation(
    db: Session,
    sale_id: int,
    entitlement_id: int,
    *,
    allow_cancel: bool = True,
) -> bool:
    """Run one founder-initiated verification or cancellation outside row locks."""
    repository = RefundOperationRepository(db)
    with db.begin():
        sale = repository.lock_sale(sale_id)
        if sale is None or sale.payment_status not in (
            PaymentStatus.PAID,
            PaymentStatus.REFUNDED,
        ):
            return False
        entitlement = next(
            (
                row
                for row in repository.lock_consultation_entitlements(sale_id)
                if row.id == entitlement_id
            ),
            None,
        )
        if entitlement is None or entitlement.cancellation is None:
            return False
        row = entitlement.cancellation
        now = datetime.now(UTC)
        if not (
            row.event_uri
            or row.invitee_uri
            or entitlement.status == "booked"
            or entitlement.booked_at
        ):
            return False
        if row.next_attempt_at and _ensure_utc_aware(row.next_attempt_at) > now:
            return False
        target = (row.event_uri, row.invitee_uri)
        event_type = entitlement.calendly_event_type_uri
        claim = now + timedelta(minutes=2)
        row.next_attempt_at = claim
        row.provider_outcome = "checking"
        row.verified_at = None

    retry_at = None
    verified_target = target
    try:
        outcome, event_path, successor = _verify_meeting(*target, event_type)
        seen = {invitee_path(target[1])}
        for _ in range(3):
            if successor is None:
                break
            if successor in seen:
                raise ValueError("Calendly rescheduling cycle.")
            seen.add(successor)
            candidate = (
                CALENDLY_API_BASE_URL + successor.rsplit("/invitees/", 1)[0],
                CALENDLY_API_BASE_URL + successor,
            )
            outcome, event_path, successor = _verify_meeting(
                *candidate,
                event_type,
                predecessor_uri=verified_target[1],
            )
            if outcome == "ownership_unresolved":
                break
            verified_target = candidate
        if outcome == "active" and allow_cancel:
            api_request(
                "POST", event_path + "/cancellation", expected_status=201, json={}
            )
            outcome, _, _ = _verify_meeting(*verified_target, event_type)
            if outcome == "active":
                outcome = "provider_unavailable"
    except CalendlyAPIError as error:
        outcome, retry_at = error.outcome, error.retry_at
    except (ValueError, TypeError):
        outcome = "ownership_unresolved"

    with db.begin():
        entitlement = ConsultationEntitlementRepository.lock_owner_and_entitlement(
            db,
            ConsultationEntitlement.id,
            entitlement_id,
        )
        row = entitlement.cancellation if entitlement is not None else None
        if (
            row is None
            or (row.event_uri, row.invitee_uri) != target
            or row.next_attempt_at is None
            or _ensure_utc_aware(row.next_attempt_at) != claim
        ):
            return False
        now = datetime.now(UTC)
        row.event_uri, row.invitee_uri = verified_target
        row.provider_outcome = outcome
        row.verified_at = now if outcome in VERIFIED_OUTCOMES else None
        row.next_attempt_at = (
            None
            if row.verified_at
            else max(now + timedelta(minutes=1), retry_at or now)
        )
    return True
