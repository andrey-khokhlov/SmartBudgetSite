from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.core.db import Base

if TYPE_CHECKING:
    from app.models.product import Product

ALLOWED_STORAGE_PROVIDERS = {
    "cloudflare_r2",
}


class ProductRelease(Base):
    __tablename__ = "product_releases"

    __table_args__ = (
        UniqueConstraint(
            "product_id",
            "version",
            name="uq_product_releases_product_id_version",
        ),
        Index(
            "uq_product_releases_active_product_id",
            "product_id",
            unique=True,
            postgresql_where=text("is_active IS TRUE"),
            sqlite_where=text("is_active IS TRUE"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    product: Mapped["Product"] = relationship(
        "Product",
        back_populates="releases",
    )

    version: Mapped[str] = mapped_column(String(50), nullable=False, index=True)

    release_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    storage_provider: Mapped[str] = mapped_column(String(50), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)

    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)

    file_size: Mapped[int | None] = mapped_column(nullable=True)
    sha256_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)

    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # download_entitlements: Mapped[list["DownloadEntitlement"]] = relationship(
    #     "DownloadEntitlement",
    #     back_populates="product_release",
    # )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    @validates("storage_provider")
    def validate_storage_provider(self, key, value):
        if value not in ALLOWED_STORAGE_PROVIDERS:
            raise ValueError(f"Invalid storage provider: {value}")
        return value
