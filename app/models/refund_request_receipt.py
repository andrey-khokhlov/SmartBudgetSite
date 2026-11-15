from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class RefundRequestReceipt(Base):
    __tablename__ = "refund_request_receipts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'sending', 'accepted', 'failed')",
            name="ck_refund_request_receipt_status",
        ),
        CheckConstraint(
            "attempt_count BETWEEN 0 AND 7", name="ck_refund_request_receipt_attempts"
        ),
        Index("ix_refund_request_receipt_due", "status", "next_attempt_at"),
    )

    request_id: Mapped[int] = mapped_column(
        ForeignKey("refund_requests.id", ondelete="RESTRICT"), primary_key=True
    )
    status: Mapped[str] = mapped_column(String(8), default="pending")
    attempt_count: Mapped[int] = mapped_column(default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sending_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_classification: Mapped[str | None] = mapped_column(String(16))
