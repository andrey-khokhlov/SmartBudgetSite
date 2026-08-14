from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base

if TYPE_CHECKING:
    from app.models.sale import Sale


class RefundOperationStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    RECONCILIATION_REQUIRED = "reconciliation_required"


class RefundOperation(Base):
    """Provider-independent persisted full-refund operation for one Sale."""

    __tablename__ = "refund_operations"

    id: Mapped[int] = mapped_column(primary_key=True)
    sale_id: Mapped[int] = mapped_column(
        ForeignKey("sales.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=RefundOperationStatus.PENDING.value,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    payment_provider: Mapped[str] = mapped_column(String(50), nullable=False)
    external_payment_id: Mapped[str] = mapped_column(String(200), nullable=False)
    provider_refund_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    provider_status: Mapped[str | None] = mapped_column(String(100), nullable=True)
    provider_observed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reconciliation_required_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    sale: Mapped["Sale"] = relationship("Sale", back_populates="refund_operation")

    __table_args__ = (
        CheckConstraint(
            status.in_([state.value for state in RefundOperationStatus]),
            name="ck_refund_operations_status",
        ),
        CheckConstraint("amount > 0", name="ck_refund_operations_amount_positive"),
    )
