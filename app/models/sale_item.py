from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base

from app.models.enums import SaleItemType

if TYPE_CHECKING:
    from app.models.product_release import ProductRelease


class SaleItem(Base):
    """
    Purchased item inside a sale/order.

    Business rules:
    - Sale is the order header.
    - SaleItem is one purchased business item.
    - Item price is a historical snapshot and must not depend on current catalog prices.
    - MVP item types are: product, service.

    Side effects:
    - None. This model only defines persistence structure.

    Invariants / restrictions:
    - item_type must be either 'product' or 'service'.
    - quantity must be positive.
    - amount must be non-negative.
    """

    __tablename__ = "sale_items"

    ALLOWED_ITEM_TYPES = {
        SaleItemType.PRODUCT,
        SaleItemType.SERVICE,
    }

    id: Mapped[int] = mapped_column(primary_key=True)

    sale_id: Mapped[int] = mapped_column(
        ForeignKey("sales.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    item_type: Mapped[str] = mapped_column(String(20), nullable=False)

    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )

    product_release_id: Mapped[int | None] = mapped_column(
        ForeignKey("product_releases.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )

    service_addon_id: Mapped[int | None] = mapped_column(
        ForeignKey("service_addons.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )

    item_name: Mapped[str] = mapped_column(String(255), nullable=False)

    currency_code: Mapped[str] = mapped_column(String(3), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    quantity: Mapped[int] = mapped_column(nullable=False, default=1)

    sale = relationship("Sale", back_populates="items")
    product = relationship("Product")
    product_release: Mapped["ProductRelease | None"] = relationship("ProductRelease")
    service_addon = relationship("ServiceAddon")
    consultation_entitlement = relationship(
        "ConsultationEntitlement",
        back_populates="sale_item",
        uselist=False,
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint(
            "item_type IN ('product', 'service')",
            name="ck_sale_items_item_type",
        ),
        CheckConstraint(
            "amount >= 0",
            name="ck_sale_items_amount_non_negative",
        ),
        CheckConstraint(
            "quantity > 0",
            name="ck_sale_items_quantity_positive",
        ),
        CheckConstraint(
            """
            (
                item_type = 'product'
                AND product_id IS NOT NULL
                AND service_addon_id IS NULL
            )
            OR
            (
                item_type = 'service'
                AND product_id IS NULL
                AND service_addon_id IS NOT NULL
            )
            """,
            name="ck_sale_items_exactly_one_reference",
        ),
        Index("ix_sale_items_sale_id_item_type", "sale_id", "item_type"),
    )
