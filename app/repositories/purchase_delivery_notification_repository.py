from datetime import datetime

from sqlalchemy import literal, or_, select, true, union_all
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.models.purchase_delivery_incident import PurchaseDeliveryIncident
from app.models.purchase_delivery_notification import PurchaseDeliveryNotification


def insert_missing_notifications(db: Session, *, limit: int) -> int:
    incident = PurchaseDeliveryIncident.__table__
    notification = PurchaseDeliveryNotification.__table__
    channels = union_all(
        select(literal("smtp").label("channel")),
        select(literal("telegram").label("channel")),
    ).subquery()
    present = (
        select(notification.c.id)
        .where(
            notification.c.incident_id == incident.c.id,
            notification.c.channel == channels.c.channel,
        )
        .correlate(incident, channels)
        .exists()
    )
    candidates = (
        select(incident.c.id)
        .where(
            incident.c.resolved_at.is_(None),
            select(channels.c.channel).where(~present).correlate(incident).exists(),
        )
        .order_by(incident.c.id)
        .limit(limit)
        .subquery()
    )
    # Order conflict checks consistently across concurrent transactions.
    entries = (
        select(candidates.c.id, channels.c.channel)
        .select_from(candidates.join(channels, true()))
        .where(true())
        .order_by(candidates.c.id, channels.c.channel)
    )
    insert = pg_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert
    statement = (
        insert(notification)
        .from_select(["incident_id", "channel"], entries)
        .on_conflict_do_nothing(index_elements=["incident_id", "channel"])
        .returning(notification.c.id)
    )
    return len(db.scalars(statement).all())


def read_dispatch_candidates(db: Session, *, now: datetime, limit: int) -> list[int]:
    incident = PurchaseDeliveryIncident
    notification = PurchaseDeliveryNotification
    active_send = (
        select(notification.id)
        .where(
            notification.incident_id == incident.id,
            notification.status == "sending",
            notification.next_attempt_at > now,
        )
        .exists()
    )
    actionable = (
        select(notification.id)
        .where(
            notification.incident_id == incident.id,
            or_(
                (notification.status.in_(("pending", "sending")))
                & (
                    (notification.next_attempt_at <= now)
                    | incident.resolved_at.is_not(None)
                ),
                (notification.status == "failed") & incident.resolved_at.is_not(None),
            ),
        )
        .exists()
    )
    return list(
        db.scalars(
            select(incident.id)
            .where(~active_send, actionable)
            .order_by(incident.id)
            .limit(limit)
        )
    )


def lock_dispatch_incident(db: Session, incident_id: int):
    incident = db.scalar(
        select(PurchaseDeliveryIncident)
        .where(PurchaseDeliveryIncident.id == incident_id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    entries = db.scalars(
        select(PurchaseDeliveryNotification)
        .where(PurchaseDeliveryNotification.incident_id == incident_id)
        .execution_options(populate_existing=True)
    ).all()
    return incident, entries
