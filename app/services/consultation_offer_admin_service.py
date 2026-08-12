from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import uuid4

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.service_addon import ServiceAddon
from app.repositories.products_repository import ProductsRepository
from app.repositories.service_addon_repository import ServiceAddonRepository

CONSULTATION_SERVICE_TYPE = "consultation"
ALLOWED_CONSULTATION_USAGE_TYPES = ("addon", "standalone")
ALLOWED_CONSULTATION_PACKAGE_CODES = ("RU", "INT")
ALLOWED_CONSULTATION_CURRENCIES = ("RUB", "EUR")


class ConsultationOfferInputError(ValueError):
    """Raised when founder-provided catalog input is invalid."""


class ConsultationOfferNotFoundError(Exception):
    """Raised when a consultation offer does not exist."""


class ConsultationOfferPersistenceError(Exception):
    """Raised when an offer change cannot preserve catalog invariants."""


@dataclass(frozen=True)
class ConsultationOfferFormOptions:
    family_slugs: tuple[str, ...]
    package_codes: tuple[str, ...] = ALLOWED_CONSULTATION_PACKAGE_CODES
    usage_types: tuple[str, ...] = ALLOWED_CONSULTATION_USAGE_TYPES
    currencies: tuple[str, ...] = ALLOWED_CONSULTATION_CURRENCIES


def get_consultation_offer_form_options(
    db: Session,
) -> ConsultationOfferFormOptions:
    return ConsultationOfferFormOptions(
        family_slugs=tuple(ProductsRepository(db).list_family_slugs()),
    )


def list_consultation_offers(db: Session) -> list[ServiceAddon]:
    return ServiceAddonRepository.list_consultation_offers(db)


def get_consultation_offer(db: Session, offer_id: int) -> ServiceAddon:
    offer = ServiceAddonRepository.get_consultation_offer_by_id(db, offer_id)
    if offer is None or offer.service_type != "consultation":
        raise ConsultationOfferNotFoundError
    return offer


def create_consultation_offer(
    db: Session,
    *,
    family_slug: str,
    package_code: str,
    service_type: str,
    usage_type: str,
    currency_code: str,
    name: str,
    amount: Decimal,
    is_active: bool,
) -> ServiceAddon:
    options = get_consultation_offer_form_options(db)
    normalized_family_slug = family_slug.strip().lower()
    normalized_package_code = package_code.strip().upper()
    normalized_service_type = service_type.strip().lower()
    normalized_usage_type = usage_type.strip().lower()
    normalized_currency_code = currency_code.strip().upper()
    normalized_name = name.strip()

    if not options.family_slugs or normalized_family_slug not in options.family_slugs:
        raise ConsultationOfferInputError("Select an existing product family.")
    if normalized_package_code not in options.package_codes:
        raise ConsultationOfferInputError("Select a supported package.")
    if normalized_service_type != CONSULTATION_SERVICE_TYPE:
        raise ConsultationOfferInputError("Select a supported service type.")
    if normalized_usage_type not in options.usage_types:
        raise ConsultationOfferInputError("Select a supported usage type.")
    if normalized_currency_code not in options.currencies:
        raise ConsultationOfferInputError("Select a supported currency.")
    _validate_mutable_fields(name=normalized_name, amount=amount)

    offer = ServiceAddon(
        code=str(uuid4()),
        family_slug=normalized_family_slug,
        package_code=normalized_package_code,
        service_type=normalized_service_type,
        usage_type=normalized_usage_type,
        currency_code=normalized_currency_code,
        name=normalized_name,
        amount=amount,
        is_active=is_active,
    )

    try:
        identity_offers = ServiceAddonRepository.lock_business_identity(
            db,
            family_slug=offer.family_slug,
            package_code=offer.package_code,
            service_type=offer.service_type,
            usage_type=offer.usage_type,
            currency_code=offer.currency_code,
        )
        if is_active:
            _deactivate_other_offers(identity_offers)
            db.flush()
        ServiceAddonRepository.create(db, offer)
        db.commit()
        db.refresh(offer)
    except SQLAlchemyError as exc:
        db.rollback()
        raise ConsultationOfferPersistenceError from exc

    return offer


def update_consultation_offer(
    db: Session,
    *,
    offer_id: int,
    name: str,
    amount: Decimal,
    is_active: bool,
) -> ServiceAddon:
    normalized_name = name.strip()
    _validate_mutable_fields(name=normalized_name, amount=amount)

    offer = get_consultation_offer(db, offer_id)
    try:
        identity_offers = ServiceAddonRepository.lock_business_identity(
            db,
            family_slug=offer.family_slug,
            package_code=offer.package_code,
            service_type=offer.service_type,
            usage_type=offer.usage_type,
            currency_code=offer.currency_code,
        )
        locked_offer = next(
            (candidate for candidate in identity_offers if candidate.id == offer.id),
            None,
        )
        if locked_offer is None:
            raise ConsultationOfferNotFoundError
        if is_active:
            _deactivate_other_offers(identity_offers, selected_id=locked_offer.id)
            db.flush()
        locked_offer.name = normalized_name
        locked_offer.amount = amount
        locked_offer.is_active = is_active
        db.flush()
        db.commit()
        db.refresh(locked_offer)
    except ConsultationOfferNotFoundError:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise ConsultationOfferPersistenceError from exc

    return locked_offer


def _validate_mutable_fields(*, name: str, amount: Decimal) -> None:
    if not name or len(name) > 200:
        raise ConsultationOfferInputError("Name must be between 1 and 200 characters.")
    if not amount.is_finite() or amount <= 0 or amount.as_tuple().exponent < -2:
        raise ConsultationOfferInputError(
            "Amount must be positive and use at most two decimal places."
        )
    if amount > Decimal("99999999.99"):
        raise ConsultationOfferInputError("Amount exceeds the supported range.")


def _deactivate_other_offers(
    offers: list[ServiceAddon],
    *,
    selected_id: int | None = None,
) -> None:
    for offer in offers:
        if offer.id != selected_id and offer.is_active:
            offer.is_active = False
