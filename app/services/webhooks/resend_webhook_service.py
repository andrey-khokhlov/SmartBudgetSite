import json
import re
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.models.purchase_email_delivery import PurchaseEmailDelivery
from app.models.resend_webhook_event import ResendWebhookEvent
from app.repositories.purchase_email_delivery_repository import get_delivery_for_update
from app.repositories.resend_webhook_repository import (
    AWAITING_CONFIRMATION,
    UNMATCHED,
    add_operator_incident,
    get_delivery_by_provider_id_for_update,
    get_receipt_for_update,
    has_equivalent_receipt,
    insert_receipt,
    read_pending_receipts,
)

TERMINAL_FAILURES = {"email.bounced", "email.failed", "email.suppressed"}
EVENT_TYPES = TERMINAL_FAILURES | {
    "email.sent",
    "email.delivered",
    "email.delivery_delayed",
    "email.complained",
}
CONFIRMATION_TIMEOUT = timedelta(minutes=5)
RECEIPT_RETENTION = timedelta(days=90)
IDENTIFIER = re.compile(r"[A-Za-z0-9_-]+")


def valid_identifier(value: object, limit: int) -> bool:
    return (
        isinstance(value, str)
        and len(value) <= limit
        and IDENTIFIER.fullmatch(value) is not None
    )


def _parse_event(raw_body: bytes) -> tuple[dict, int | None]:
    try:
        payload = json.loads(raw_body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError
        event_type = payload.get("type")
        if not isinstance(event_type, str):
            raise ValueError
        if event_type not in EVENT_TYPES:
            return {"outcome": "unsupported"}, None
        data = payload.get("data")
        if not isinstance(data, dict) or not valid_identifier(
            data.get("email_id"), 255
        ):
            raise ValueError
        event_at = datetime.fromisoformat(payload["created_at"])
        if event_at.utcoffset() is None:
            raise ValueError
        event_at = event_at.astimezone(UTC)
        tags = data.get("tags")
        if tags is None:
            tags = {}
        if not isinstance(tags, dict):
            raise ValueError
        delivery_id = None
        if "purchase_email_delivery_id" in tags:
            tag = tags["purchase_email_delivery_id"]
            if not isinstance(tag, str) or not re.fullmatch(r"[1-9][0-9]{0,9}", tag):
                raise ValueError
            delivery_id = int(tag)
            if delivery_id > 2_147_483_647:
                raise ValueError
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError):
        return {"outcome": "malformed"}, None
    return {
        "event_type": event_type,
        "provider_email_id": data["email_id"],
        "provider_event_at": event_at,
        "outcome": UNMATCHED,
    }, delivery_id


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _apply_confirmed_receipt(
    db: Session,
    delivery: PurchaseEmailDelivery,
    receipt: ResendWebhookEvent,
    now: datetime,
) -> None:
    if receipt.provider_email_id != delivery.provider_message_id:
        receipt.outcome = "correlation_conflict"
        kind = "email_provider_correlation_conflict"
    else:
        event_at = receipt.provider_event_at
        if event_at is None or receipt.event_type is None:
            raise ValueError("Confirmed Resend receipt is missing event metadata.")
        is_complaint = receipt.event_type == "email.complained"
        last_event_at = (
            delivery.complaint_at if is_complaint else delivery.provider_event_at
        )
        provider_status = receipt.event_type.removeprefix("email.")
        kind = (
            f"email_provider_{provider_status}"
            if receipt.event_type in TERMINAL_FAILURES
            else None
        )
        # Terminal failures remain actionable even when a later event owns the state.
        if last_event_at is not None and _as_utc(event_at) <= _as_utc(last_event_at):
            receipt.outcome = "not_newer"
        else:
            receipt.outcome = "applied"
            if is_complaint:
                delivery.complaint_at = event_at
                delivery.complaint_event_id = receipt.svix_id
                kind = "email_provider_complaint"
            else:
                delivery.provider_delivery_status = provider_status
                delivery.provider_event_at = event_at
                delivery.provider_event_id = receipt.svix_id
    if kind is not None:
        add_operator_incident(
            db,
            sale_id=delivery.sale_id,
            delivery_id=delivery.id,
            kind=kind,
            event_id=receipt.svix_id,
            now=now,
        )


def _correlate_receipt(
    db: Session,
    delivery: PurchaseEmailDelivery,
    receipt: ResendWebhookEvent,
    now: datetime,
) -> None:
    receipt.delivery_id = delivery.id
    if has_equivalent_receipt(db, receipt):
        receipt.outcome = "duplicate_event"
    elif delivery.provider_message_id is None:
        receipt.outcome = AWAITING_CONFIRMATION
    else:
        _apply_confirmed_receipt(db, delivery, receipt, now)


def _matches_unmatched_replay(
    receipt: ResendWebhookEvent, values: dict, tag: int | None, now: datetime
) -> bool:
    return (
        receipt.outcome == UNMATCHED
        and receipt.delivery_id == tag
        and receipt.event_type == values["event_type"]
        and receipt.provider_email_id == values["provider_email_id"]
        and receipt.provider_event_at is not None
        and _as_utc(receipt.provider_event_at) == values["provider_event_at"]
        and _as_utc(receipt.first_received_at) > now - RECEIPT_RETENTION
    )


def process_resend_webhook(
    db: Session, *, svix_id: str, raw_body: bytes, now: datetime | None = None
) -> None:
    """Persist one verified receipt and applicable changes in the caller's transaction."""
    received_at = now or datetime.now(UTC)
    values, tag = _parse_event(raw_body)
    delivery = None
    if values["outcome"] == UNMATCHED:
        if tag is not None:
            delivery = get_delivery_for_update(db, delivery_id=tag)
        else:
            delivery = get_delivery_by_provider_id_for_update(
                db, values["provider_email_id"]
            )
    # Retain a supplied tag even if its candidate does not exist. An unmatched
    # tagged event must never later take the untagged fallback path.
    receipt = insert_receipt(
        db,
        dict(values, svix_id=svix_id, delivery_id=tag, first_received_at=received_at),
    )
    if delivery is None:
        return
    if receipt is None:
        receipt = get_receipt_for_update(db, svix_id)
        if receipt is None or not _matches_unmatched_replay(
            receipt, values, tag, received_at
        ):
            return
    _correlate_receipt(db, delivery, receipt, received_at)


def apply_pending_resend_receipts(
    db: Session, delivery: PurchaseEmailDelivery, *, now: datetime
) -> None:
    """Process eligible receipts while send completion holds the delivery row lock."""
    if delivery.provider_message_id is None:
        return
    for receipt in read_pending_receipts(
        db,
        delivery.id,
        delivery.provider_message_id,
        expires_before=now - RECEIPT_RETENTION,
    ):
        _correlate_receipt(db, delivery, receipt, now)
        db.flush()
