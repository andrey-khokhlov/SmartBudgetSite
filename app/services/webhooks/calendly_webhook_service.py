from sqlalchemy.orm import Session

from app.schemas.webhooks import NormalizedBookingConfirmedEvent
from app.services.webhooks.payload_normalizers.calendly_payload_normalizer import (
    normalize_calendly_invitee_created_event,
)
from app.services.webhooks.reconciliation_service import (
    reconcile_booking_confirmed_event,
)
from app.services.webhooks.webhook_audit_logger import (
    log_webhook_event,
)
from app.services.webhooks.webhook_audit_statuses import (
    WEBHOOK_STATUS_IGNORED,
    WEBHOOK_STATUS_MALFORMED_PAYLOAD,
    WEBHOOK_STATUS_PROCESSED,
    WEBHOOK_STATUS_RECONCILIATION_MISMATCH,
)


def process_calendly_webhook(
    db: Session,
    payload: dict,
) -> NormalizedBookingConfirmedEvent | None:
    """
    Process Calendly webhook payload.

    Business rules:
    - Webhook orchestration belongs to service layer.
    - This service coordinates normalization, reconciliation, and lifecycle handoff.
    - Business lifecycle services must not consume raw provider payloads.

    Side effects:
    - Emits audit log events for processed, ignored, malformed, and mismatch cases.
    - Performs entitlement reconciliation lookup.
    - May mark a resolved consultation entitlement as booked.

    Invariants / restrictions:
    - Unsupported events must be ignored safely.
    - Malformed supported payloads must be logged before rejection.
    - Webhook events must never create consultation entitlements.
    """

    event_type = payload.get("event")

    if event_type == "invitee.created":
        try:
            normalized_event = normalize_calendly_invitee_created_event(payload)
        except (KeyError, TypeError, ValueError):
            log_webhook_event(
                provider="calendly",
                event_type=event_type,
                status=WEBHOOK_STATUS_MALFORMED_PAYLOAD,
            )
            raise

        log_webhook_event(
            provider="calendly", event_type=event_type, status=WEBHOOK_STATUS_PROCESSED,
        )
        resolved_entitlement = reconcile_booking_confirmed_event(
            db=db,
            event=normalized_event,
        )

        if resolved_entitlement is None:
            log_webhook_event(
                provider="calendly",
                event_type=event_type,
                status=WEBHOOK_STATUS_RECONCILIATION_MISMATCH,
            )

            return normalized_event

        return normalized_event

    log_webhook_event(
        provider="calendly",
        event_type=event_type or "unknown",
        status=WEBHOOK_STATUS_IGNORED,
    )

    return None
