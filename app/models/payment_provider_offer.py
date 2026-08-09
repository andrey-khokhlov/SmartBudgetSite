from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base

if TYPE_CHECKING:
    from app.models.product import Product


class PaymentProviderOffer(Base):
    """Provider-specific checkout offer mapped to an internal product."""

    __tablename__ = "payment_provider_offers"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    external_offer_id: Mapped[str] = mapped_column(String(200), nullable=False)

    product: Mapped["Product"] = relationship(
        "Product",
        back_populates="payment_provider_offers",
    )

    __table_args__ = (
        CheckConstraint(
            "length(trim(provider)) > 0",
            name="ck_payment_provider_offers_provider_non_empty",
        ),
        CheckConstraint(
            "length(trim(external_offer_id)) > 0",
            name="ck_payment_provider_offers_external_offer_id_non_empty",
        ),
        UniqueConstraint(
            "product_id",
            "provider",
            name="uq_payment_provider_offers_product_provider",
        ),
        UniqueConstraint(
            "provider",
            "external_offer_id",
            name="uq_payment_provider_offers_provider_external_offer_id",
        ),
    )
