from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.enums import PaymentStatus

if TYPE_CHECKING:
    from app.models.sale_item import SaleItem

class Sale(Base):
    __tablename__ = "sales"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Transitional legacy field.
    # Product ownership must eventually be resolved through SaleItem.
    # Kept temporarily for backward compatibility during migration.
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )

    customer_email: Mapped[str] = mapped_column(String(200), nullable=False, index=True)

    items: Mapped[list["SaleItem"]] = relationship(
        "SaleItem",
        back_populates="sale",
        cascade="all, delete-orphan",
    )

    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")

    payment_provider: Mapped[str | None] = mapped_column(String(50), nullable=True)

    payment_status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        index=True,
        default=PaymentStatus.PENDING,
    )

    external_payment_id: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index(
            "uq_sales_payment_provider_external_payment_id",
            "payment_provider",
            "external_payment_id",
            unique=True,
            postgresql_where=text("external_payment_id IS NOT NULL"),
            sqlite_where=text("external_payment_id IS NOT NULL"),
        ),
    )
