from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ConsultationCapacityState(Base):
    __tablename__ = "consultation_capacity_state"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_consultation_capacity_singleton"),
        CheckConstraint(
            "observed_level IN ('normal', 'warning', 'exhausted')",
            name="ck_consultation_capacity_observed_level",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    manually_suspended: Mapped[bool] = mapped_column()
    observed_level: Mapped[str] = mapped_column(String(9))


class ConsultationCapacityNotification(Base):
    __tablename__ = "consultation_capacity_notifications"
    __table_args__ = (
        UniqueConstraint(
            "episode_id", "channel", name="uq_consultation_capacity_channel"
        ),
        Index("ix_consultation_capacity_notification_due", "status", "next_attempt_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    episode_id: Mapped[UUID] = mapped_column()
    kind: Mapped[str] = mapped_column(String(9))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    channel: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(12), default="pending")
    attempt_count: Mapped[int] = mapped_column(default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(24))
