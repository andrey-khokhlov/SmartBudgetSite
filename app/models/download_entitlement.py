import enum
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base

if TYPE_CHECKING:
    from app.models.product_release import ProductRelease
    from app.models.sale_item import SaleItem


class DownloadEntitlementStatus(str, enum.Enum):
    AVAILABLE = "available"
    COMPLETED = "completed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class DownloadEntitlement(Base):
    """Backend-owned right to download one purchased product release."""

    __tablename__ = "download_entitlements"

    id: Mapped[int] = mapped_column(primary_key=True)

    sale_item_id: Mapped[int] = mapped_column(
        ForeignKey("sale_items.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    release_id: Mapped[int] = mapped_column(
        ForeignKey("product_releases.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    download_token: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        unique=True,
        index=True,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=DownloadEntitlementStatus.AVAILABLE.value,
    )

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    first_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

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

    sale_item: Mapped["SaleItem"] = relationship(
        "SaleItem",
        back_populates="download_entitlement",
    )
    release: Mapped["ProductRelease"] = relationship(
        "ProductRelease",
        back_populates="download_entitlements",
    )

    __table_args__ = (
        CheckConstraint(
            status.in_([state.value for state in DownloadEntitlementStatus]),
            name="ck_download_entitlements_status",
        ),
        CheckConstraint(
            "attempt_count >= 0",
            name="ck_download_entitlements_attempt_count_non_negative",
        ),
    )
