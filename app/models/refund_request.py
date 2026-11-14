from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.sale import Sale


class RefundRequest(Base):
    __tablename__ = "refund_requests"
    __table_args__ = (
        UniqueConstraint(
            "submission_token", name="uq_refund_requests_submission_token"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    submission_token: Mapped[str] = mapped_column(String(64))
    sale_id: Mapped[int] = mapped_column(
        ForeignKey("sales.id", ondelete="RESTRICT"), index=True
    )
    sale: Mapped[Sale] = relationship()
    purchase_reference: Mapped[str] = mapped_column(String(18))
    customer_email: Mapped[str] = mapped_column(String(200))
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    language: Mapped[str] = mapped_column(String(2))
    message: Mapped[str | None] = mapped_column(Text)
    composition: Mapped[str] = mapped_column(String(16))
    window_status: Mapped[str | None] = mapped_column(String(16))
    window_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16))
