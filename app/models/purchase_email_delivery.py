import enum
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base

if TYPE_CHECKING:
    from app.models.sale import Sale


class PurchaseEmailDeliveryStatus(str, enum.Enum):
    PENDING = "pending"
    SENDING = "sending"
    SENT = "sent"
    FAILED = "failed"
    RECONCILIATION_REQUIRED = "reconciliation_required"


class PurchaseEmailDelivery(Base):
    """Durable delivery state for one Sale's purchase email."""

    __tablename__ = "purchase_email_deliveries"

    id: Mapped[int] = mapped_column(primary_key=True)
    sale_id: Mapped[int] = mapped_column(
        ForeignKey("sales.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=PurchaseEmailDeliveryStatus.PENDING.value,
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sending_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    provider_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Store only bounded, sanitized diagnostics; never secrets or delivery URLs.
    last_error: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=func.now(),
    )

    sale: Mapped["Sale"] = relationship(
        "Sale",
        back_populates="purchase_email_delivery",
    )

    __table_args__ = (
        CheckConstraint(
            status.in_([state.value for state in PurchaseEmailDeliveryStatus]),
            name="ck_purchase_email_deliveries_status",
        ),
        CheckConstraint(
            "attempt_count >= 0",
            name="ck_purchase_email_deliveries_attempt_count_non_negative",
        ),
    )
