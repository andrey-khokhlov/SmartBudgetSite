from sqlalchemy import CheckConstraint, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ServicePaymentProviderOffer(Base):
    """Provider routing for one standalone service catalog record."""

    __tablename__ = "service_payment_provider_offers"

    id: Mapped[int] = mapped_column(primary_key=True)
    service_addon_id: Mapped[int] = mapped_column(
        ForeignKey("service_addons.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    external_offer_id: Mapped[str] = mapped_column(String(200), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "length(trim(provider)) > 0",
            name="ck_service_payment_provider_offers_provider_non_empty",
        ),
        CheckConstraint(
            "length(trim(external_offer_id)) > 0",
            name="ck_service_payment_provider_offers_external_offer_id_non_empty",
        ),
        UniqueConstraint(
            "service_addon_id",
            "provider",
            name="uq_service_payment_provider_offers_service_provider",
        ),
    )
