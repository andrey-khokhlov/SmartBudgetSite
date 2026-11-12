from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.models.enums import PaymentStatus
from app.models.purchase_email_delivery import (
    PurchaseEmailDelivery,
    PurchaseEmailDeliveryStatus,
    PurchaseEmailFailureClassification,
)
from app.models.resend_webhook_event import ResendWebhookEvent
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.repositories.resend_webhook_repository import AWAITING_CONFIRMATION


@dataclass(frozen=True)
class RecoveryCutoffs:
    pending_before: datetime
    retry_before: datetime
    ambiguous_before: datetime
    max_attempts: int
    allow_sends: bool


def _recovery_candidates(cutoffs: RecoveryCutoffs):
    delivery = PurchaseEmailDelivery
    status = PurchaseEmailDeliveryStatus
    failure = PurchaseEmailFailureClassification
    expired = (delivery.status == status.SENDING) & or_(
        delivery.sending_started_at.is_(None),
        delivery.sending_started_at <= cutoffs.ambiguous_before,
    )
    eligible = expired
    if cutoffs.allow_sends:
        unconfirmed_evidence = (
            select(ResendWebhookEvent.svix_id)
            .where(
                ResendWebhookEvent.delivery_id == delivery.id,
                ResendWebhookEvent.outcome == AWAITING_CONFIRMATION,
            )
            .exists()
        )
        retry_due = delivery.last_attempt_at <= cutoffs.retry_before
        sendable_status = or_(
            (delivery.status == status.PENDING)
            & (delivery.created_at <= cutoffs.pending_before)
            & or_(delivery.last_attempt_at.is_(None), retry_due),
            (delivery.status == status.SENDING)
            & (delivery.sending_started_at > cutoffs.ambiguous_before)
            & or_(
                delivery.failure_classification.is_(None),
                delivery.failure_classification != failure.PERMANENT,
            )
            & retry_due,
            (delivery.status == status.FAILED)
            & (delivery.failure_classification == failure.TRANSIENT)
            & retry_due,
        )
        eligible = expired | (
            (delivery.attempt_count < cutoffs.max_attempts)
            & delivery.provider_message_id.is_(None)
            & delivery.provider_delivery_status.is_(None)
            & delivery.complaint_at.is_(None)
            & ~unconfirmed_evidence
            & sendable_status
        )
    return (
        select(delivery.sale_id, expired.label("expired"))
        .join(Sale, Sale.id == delivery.sale_id)
        .where(Sale.payment_status == PaymentStatus.PAID, eligible)
    )


def read_due_email_recovery(db: Session, cutoffs: RecoveryCutoffs, *, limit: int):
    delivery = PurchaseEmailDelivery
    candidates = _recovery_candidates(cutoffs)
    rows = db.execute(
        candidates.add_columns(func.count().over().label("due_count"))
        .order_by(
            candidates.selected_columns.expired.desc(),
            func.coalesce(delivery.last_attempt_at, delivery.created_at),
            delivery.id,
        )
        .limit(limit)
    ).all()
    return rows[0].due_count if rows else 0, rows


def email_recovery_is_due(
    db: Session, delivery_id: int, cutoffs: RecoveryCutoffs
) -> bool:
    # The caller holds the same delivery row lock used by Resend event handling.
    return (
        db.scalar(
            _recovery_candidates(cutoffs).where(PurchaseEmailDelivery.id == delivery_id)
        )
        is not None
    )


def get_delivery_for_update(
    db: Session,
    *,
    delivery_id: int,
) -> PurchaseEmailDelivery | None:
    stmt = (
        select(PurchaseEmailDelivery)
        .where(PurchaseEmailDelivery.id == delivery_id)
        .with_for_update()
    )
    return db.execute(stmt).scalar_one_or_none()


def get_delivery_by_sale_id_for_update(
    db: Session,
    *,
    sale_id: int,
) -> PurchaseEmailDelivery | None:
    stmt = (
        select(PurchaseEmailDelivery)
        .where(PurchaseEmailDelivery.sale_id == sale_id)
        .with_for_update()
    )
    return db.execute(stmt).scalar_one_or_none()


def get_delivery_with_fulfillment(
    db: Session,
    *,
    delivery_id: int,
) -> PurchaseEmailDelivery | None:
    sale_path = joinedload(PurchaseEmailDelivery.sale)
    stmt = (
        select(PurchaseEmailDelivery)
        .options(
            sale_path.selectinload(Sale.items).joinedload(
                SaleItem.download_entitlement
            ),
            sale_path.selectinload(Sale.items).joinedload(
                SaleItem.consultation_entitlement
            ),
        )
        .where(PurchaseEmailDelivery.id == delivery_id)
    )
    return db.execute(stmt).scalars().unique().one_or_none()
