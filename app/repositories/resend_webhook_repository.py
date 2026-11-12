from datetime import datetime

from sqlalchemy import delete, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.models.purchase_delivery_incident import PurchaseDeliveryIncident
from app.models.purchase_email_delivery import PurchaseEmailDelivery
from app.models.resend_webhook_event import ResendWebhookEvent

AWAITING_CONFIRMATION = "awaiting_provider_confirmation"
UNMATCHED = "unmatched"


def insert_receipt(db: Session, values: dict) -> ResendWebhookEvent | None:
    insert = pg_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert
    statement = (
        insert(ResendWebhookEvent)
        .values(**values)
        .on_conflict_do_nothing(index_elements=["svix_id"])
        .returning(ResendWebhookEvent)
    )
    return db.scalar(statement)


def get_receipt_for_update(db: Session, svix_id: str) -> ResendWebhookEvent | None:
    return db.scalar(
        select(ResendWebhookEvent)
        .where(ResendWebhookEvent.svix_id == svix_id)
        .with_for_update()
    )


def has_equivalent_receipt(db: Session, receipt: ResendWebhookEvent) -> bool:
    return (
        db.scalar(
            select(ResendWebhookEvent.svix_id)
            .where(
                ResendWebhookEvent.svix_id != receipt.svix_id,
                ResendWebhookEvent.delivery_id == receipt.delivery_id,
                ResendWebhookEvent.provider_email_id == receipt.provider_email_id,
                ResendWebhookEvent.event_type == receipt.event_type,
                ResendWebhookEvent.provider_event_at == receipt.provider_event_at,
                ResendWebhookEvent.outcome.not_in([UNMATCHED, "duplicate_event"]),
            )
            .limit(1)
        )
        is not None
    )


def get_delivery_by_provider_id_for_update(
    db: Session, provider_email_id: str
) -> PurchaseEmailDelivery | None:
    rows = db.scalars(
        select(PurchaseEmailDelivery)
        .where(PurchaseEmailDelivery.provider_message_id == provider_email_id)
        .order_by(PurchaseEmailDelivery.id)
        .limit(2)
        .with_for_update()
    ).all()
    return rows[0] if len(rows) == 1 else None


def read_pending_receipts(
    db: Session, delivery_id: int, provider_email_id: str, *, expires_before: datetime
):
    other_binding = (
        select(PurchaseEmailDelivery.id)
        .where(
            PurchaseEmailDelivery.id != delivery_id,
            PurchaseEmailDelivery.provider_message_id == provider_email_id,
        )
        .exists()
    )
    tagged = ResendWebhookEvent.delivery_id == delivery_id
    return db.scalars(
        select(ResendWebhookEvent)
        .where(
            ResendWebhookEvent.first_received_at > expires_before,
            or_(
                tagged & (ResendWebhookEvent.outcome == AWAITING_CONFIRMATION),
                (ResendWebhookEvent.outcome == UNMATCHED)
                & (ResendWebhookEvent.provider_email_id == provider_email_id)
                & (
                    tagged | (ResendWebhookEvent.delivery_id.is_(None) & ~other_binding)
                ),
            ),
        )
        .order_by(ResendWebhookEvent.provider_event_at, ResendWebhookEvent.svix_id)
        .with_for_update()
    ).all()


def read_overdue_receipts(db: Session, *, cutoff: datetime, expires_before: datetime):
    return db.execute(
        select(ResendWebhookEvent, PurchaseEmailDelivery.sale_id)
        .join(
            PurchaseEmailDelivery,
            PurchaseEmailDelivery.id == ResendWebhookEvent.delivery_id,
        )
        .where(
            ResendWebhookEvent.outcome == AWAITING_CONFIRMATION,
            ResendWebhookEvent.first_received_at <= cutoff,
            ResendWebhookEvent.first_received_at > expires_before,
            PurchaseEmailDelivery.provider_message_id.is_(None),
        )
    ).all()


def delete_expired_receipts(db: Session, cutoff: datetime) -> int:
    return db.execute(
        delete(ResendWebhookEvent).where(ResendWebhookEvent.first_received_at <= cutoff)
    ).rowcount


def add_operator_incident(
    db: Session,
    *,
    sale_id: int,
    delivery_id: int,
    kind: str,
    event_id: str,
    now: datetime,
) -> int:
    insert = pg_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert
    return db.execute(
        insert(PurchaseDeliveryIncident)
        .values(
            sale_id=sale_id,
            subject_id=delivery_id,
            kind=kind,
            severity="error",
            requires_operator=True,
            originating_event_id=event_id,
            first_detected_at=now,
            last_observed_at=now,
        )
        .on_conflict_do_nothing(
            index_elements=["sale_id", "subject_id", "kind", "originating_event_id"]
        )
    ).rowcount
