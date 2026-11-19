from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.consultation_capacity import (
    ConsultationCapacityNotification,
    ConsultationCapacityState,
)
from app.models.consultation_entitlement import (
    ConsultationEntitlement,
    ConsultationEntitlementStatus,
)
from app.models.enums import PaymentStatus, SaleItemType
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.models.service_addon import ServiceAddon


def _outstanding_workload(now: datetime):
    return (
        select(func.count(ConsultationEntitlement.id))
        .join(SaleItem, SaleItem.id == ConsultationEntitlement.sale_item_id)
        .join(Sale, Sale.id == SaleItem.sale_id)
        .join(ServiceAddon, ServiceAddon.id == SaleItem.service_addon_id)
        .where(
            Sale.payment_status == PaymentStatus.PAID,
            SaleItem.item_type == SaleItemType.SERVICE,
            ServiceAddon.service_type == "consultation",
            ConsultationEntitlement.status == ConsultationEntitlementStatus.AVAILABLE,
            ConsultationEntitlement.expires_at > now,
            ~ConsultationEntitlement.cancellation.has(),
        )
    )


def read_capacity(db: Session, *, now: datetime) -> tuple[bool, int] | None:
    row = db.execute(
        select(
            ConsultationCapacityState.manually_suspended,
            _outstanding_workload(now).scalar_subquery(),
        ).where(ConsultationCapacityState.id == 1)
    ).one_or_none()
    return (row[0], row[1]) if row is not None else None


def count_outstanding(db: Session, *, now: datetime) -> int:
    return db.execute(_outstanding_workload(now)).scalar_one()


def lock_capacity_state(db: Session) -> ConsultationCapacityState | None:
    return db.scalar(
        select(ConsultationCapacityState)
        .where(ConsultationCapacityState.id == 1)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def list_due_episodes(db: Session, *, now: datetime, limit: int) -> list[UUID]:
    notification = ConsultationCapacityNotification
    return list(
        db.scalars(
            select(notification.episode_id)
            .where(
                notification.status.in_(("pending", "sending")),
                notification.next_attempt_at <= now,
            )
            .group_by(notification.episode_id)
            .order_by(func.min(notification.next_attempt_at), notification.episode_id)
            .limit(limit)
        )
    )


def lock_episode_notifications(
    db: Session, episode_id: UUID
) -> list[ConsultationCapacityNotification]:
    notification = ConsultationCapacityNotification
    return list(
        db.scalars(
            select(notification)
            .where(notification.episode_id == episode_id)
            .order_by(notification.id)
            .with_for_update()
        )
    )
