from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class PurchaseDeliveryNotification(Base):
    """One durable notification identity for an incident and channel."""

    __tablename__ = "purchase_delivery_notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_delivery_incidents.id", ondelete="RESTRICT")
    )
    channel: Mapped[str] = mapped_column(String(8))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    attempt_count: Mapped[int] = mapped_column(server_default="0")
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(12), server_default="pending")
    last_error: Mapped[str | None] = mapped_column(String(24))
    skip_reason: Mapped[str | None] = mapped_column(String(32))

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'sending', 'delivered', 'skipped', 'failed')",
            name="ck_purchase_delivery_notifications_status",
        ),
        UniqueConstraint(
            "incident_id",
            "channel",
            name="uq_purchase_delivery_notifications_incident_channel",
        ),
        CheckConstraint(
            "channel IN ('smtp', 'telegram')",
            name="ck_purchase_delivery_notifications_channel",
        ),
        CheckConstraint(
            "attempt_count >= 0", name="ck_purchase_delivery_notifications_attempts"
        ),
    )
