from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.service_payment_provider_offer import ServicePaymentProviderOffer


class ServicePaymentProviderOfferRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_service_and_provider(
        self, *, service_addon_id: int, provider: str
    ) -> ServicePaymentProviderOffer | None:
        return self.db.scalars(
            select(ServicePaymentProviderOffer).where(
                ServicePaymentProviderOffer.service_addon_id == service_addon_id,
                ServicePaymentProviderOffer.provider == provider,
            )
        ).one_or_none()

    def create(
        self, *, service_addon_id: int, provider: str, external_offer_id: str
    ) -> None:
        self.db.add(
            ServicePaymentProviderOffer(
                service_addon_id=service_addon_id,
                provider=provider,
                external_offer_id=external_offer_id,
            )
        )
        self.db.flush()

    def update_external_offer_id(
        self, mapping: ServicePaymentProviderOffer, *, external_offer_id: str
    ) -> None:
        mapping.external_offer_id = external_offer_id
        self.db.flush()
