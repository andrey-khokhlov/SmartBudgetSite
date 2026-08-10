import hashlib
import logging

logger = logging.getLogger(__name__)


def log_webhook_event(
    provider: str,
    event_type: str,
    status: str,
    *,
    external_payment_id: str | None = None,
    sale_id: int | None = None,
) -> None:
    """
    Log webhook processing lifecycle event.

    Business rules:
    - Webhook observability must remain centralized.
    - Audit logging must not contain sensitive secrets.

    Side effects:
    - Writes structured webhook lifecycle logs.

    Invariants / restrictions:
    - Signing secrets must never be logged.
    - Raw payload bodies should not be logged at INFO level.
    """

    fields = {
        "provider": provider,
        "event_type": event_type,
        "status": status,
    }
    if external_payment_id is not None:
        fields["external_payment_id_hash"] = hashlib.sha256(
            external_payment_id.encode("utf-8")
        ).hexdigest()
    if sale_id is not None:
        fields["sale_id"] = sale_id

    logger.info(
        "Webhook event processed",
        extra=fields,
    )
