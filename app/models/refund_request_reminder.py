from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class RefundRequestReminder(Base):
    __tablename__ = "refund_request_reminders"
    __table_args__ = (
        UniqueConstraint(
            "request_id", "cycle_date", name="uq_refund_request_reminder_cycle"
        ),
        Index("ix_refund_request_reminders_status_cycle", "status", "cycle_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(
        ForeignKey("refund_requests.id", ondelete="RESTRICT")
    )
    cycle_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(12), default="pending")
    telegram_attempts: Mapped[int] = mapped_column(default=0)
    smtp_attempts: Mapped[int] = mapped_column(default=0)
    telegram_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    smtp_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    claim_channel: Mapped[str | None] = mapped_column(String(8))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(24))
