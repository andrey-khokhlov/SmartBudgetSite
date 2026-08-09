from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.payment_provider_offer import PaymentProviderOffer


class PaymentProviderOfferRepository:
    """Database access for product-to-payment-provider offer mappings."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_product_and_provider(
        self,
        *,
        product_id: int,
        provider: str,
    ) -> PaymentProviderOffer | None:
        stmt = select(PaymentProviderOffer).where(
            PaymentProviderOffer.product_id == product_id,
            PaymentProviderOffer.provider == provider,
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def create(self, offer: PaymentProviderOffer) -> PaymentProviderOffer:
        self.db.add(offer)
        self.db.flush()
        return offer

    def update_external_offer_id(
        self,
        offer: PaymentProviderOffer,
        *,
        external_offer_id: str,
    ) -> PaymentProviderOffer:
        offer.external_offer_id = external_offer_id
        self.db.flush()
        return offer
