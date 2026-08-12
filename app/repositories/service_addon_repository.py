from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.service_addon import ServiceAddon


class ServiceAddonRepository:
    """
    Repository for service add-ons.

    Business rules:
    - Only active add-ons should be used in checkout.
    - Add-ons are selected by their full business identity, including currency.

    Side effects:
    - None. Pure DB access layer.

    Invariants/restrictions:
    - Assumes DB constraints enforce uniqueness of code.
    """

    @staticmethod
    def get_active_addon(
        db: Session,
        *,
        family_slug: str,
        package_code: str,
        service_type: str,
        usage_type: str,
        currency_code: str,
    ) -> ServiceAddon | None:
        """
        Get the active add-on for one full business identity.
        """

        return (
            db.query(ServiceAddon)
            .filter(ServiceAddon.is_active.is_(True))
            .filter(ServiceAddon.family_slug == family_slug)
            .filter(ServiceAddon.package_code == package_code)
            .filter(ServiceAddon.service_type == service_type)
            .filter(ServiceAddon.usage_type == usage_type)
            .filter(ServiceAddon.currency_code == currency_code)
            .one_or_none()
        )

    @staticmethod
    def list_consultation_offers(db: Session) -> list[ServiceAddon]:
        return (
            db.query(ServiceAddon)
            .filter(ServiceAddon.service_type == "consultation")
            .order_by(
                ServiceAddon.family_slug,
                ServiceAddon.package_code,
                ServiceAddon.usage_type,
                ServiceAddon.currency_code,
                ServiceAddon.id.desc(),
            )
            .all()
        )

    @staticmethod
    def get_consultation_offer_by_id(
        db: Session,
        offer_id: int,
    ) -> ServiceAddon | None:
        return db.get(ServiceAddon, offer_id)

    @staticmethod
    def lock_business_identity(
        db: Session,
        *,
        family_slug: str,
        package_code: str,
        service_type: str,
        usage_type: str,
        currency_code: str,
    ) -> list[ServiceAddon]:
        statement = (
            select(ServiceAddon)
            .where(
                ServiceAddon.family_slug == family_slug,
                ServiceAddon.package_code == package_code,
                ServiceAddon.service_type == service_type,
                ServiceAddon.usage_type == usage_type,
                ServiceAddon.currency_code == currency_code,
            )
            .order_by(ServiceAddon.id)
            .with_for_update()
        )
        return list(db.scalars(statement).all())

    @staticmethod
    def create(db: Session, offer: ServiceAddon) -> ServiceAddon:
        db.add(offer)
        db.flush()
        return offer
