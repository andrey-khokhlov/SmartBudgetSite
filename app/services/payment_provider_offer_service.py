from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.payment_provider_offer import PaymentProviderOffer
from app.models.product import Product
from app.repositories.payment_provider_offer_repository import (
    PaymentProviderOfferRepository,
)
from app.repositories.product_release_repository import ProductReleaseRepository
from app.repositories.products_repository import ProductsRepository

LAVA_TOP_PROVIDER = "lava_top"
MAX_EXTERNAL_OFFER_ID_LENGTH = 200

PaymentProviderOfferChange = Literal["created", "updated", "unchanged"]


class PaymentProviderOfferInputError(ValueError):
    """Raised when provider-offer configuration input is invalid."""


class PaymentProviderOfferProductNotFoundError(Exception):
    """Raised when provider configuration targets a missing product."""


class PaymentProviderOfferPersistenceError(Exception):
    """Raised when provider-offer configuration cannot be persisted."""


@dataclass(frozen=True)
class CheckoutReadiness:
    is_ready: bool
    missing_prerequisites: tuple[str, ...]


@dataclass(frozen=True)
class LavaTopProductConfiguration:
    mapping: PaymentProviderOffer | None
    readiness: CheckoutReadiness


def get_lava_top_product_configuration(
    db: Session,
    *,
    product: Product,
) -> LavaTopProductConfiguration:
    """Return the operator-facing Lava.top mapping and checkout readiness."""
    products_repository = ProductsRepository(db)
    mapping = PaymentProviderOfferRepository(db).get_by_product_and_provider(
        product_id=product.id,
        provider=LAVA_TOP_PROVIDER,
    )
    missing_prerequisites = []

    if product.status != "in_sale":
        missing_prerequisites.append("status is not in_sale")
    if not products_repository.has_active_price(product.id):
        missing_prerequisites.append("active ProductPrice")
    if ProductReleaseRepository(db).get_active_by_product_id(product.id) is None:
        missing_prerequisites.append("active ProductRelease")
    if mapping is None:
        missing_prerequisites.append("Lava.top PaymentProviderOffer")

    return LavaTopProductConfiguration(
        mapping=mapping,
        readiness=CheckoutReadiness(
            is_ready=not missing_prerequisites,
            missing_prerequisites=tuple(missing_prerequisites),
        ),
    )


def set_lava_top_product_offer(
    db: Session,
    *,
    product_id: int,
    external_offer_id: str,
) -> PaymentProviderOfferChange:
    """Create or update one product's explicit Lava.top offer mapping."""
    normalized_external_offer_id = external_offer_id.strip()
    if not normalized_external_offer_id:
        raise PaymentProviderOfferInputError("External offer ID must not be empty.")
    if len(normalized_external_offer_id) > MAX_EXTERNAL_OFFER_ID_LENGTH:
        raise PaymentProviderOfferInputError("External offer ID is too long.")

    product = ProductsRepository(db).get_by_id(product_id)
    if product is None:
        raise PaymentProviderOfferProductNotFoundError

    repository = PaymentProviderOfferRepository(db)
    mapping = repository.get_by_product_and_provider(
        product_id=product.id,
        provider=LAVA_TOP_PROVIDER,
    )

    try:
        if mapping is None:
            repository.create(
                PaymentProviderOffer(
                    product_id=product.id,
                    provider=LAVA_TOP_PROVIDER,
                    external_offer_id=normalized_external_offer_id,
                )
            )
            change: PaymentProviderOfferChange = "created"
        elif mapping.external_offer_id != normalized_external_offer_id:
            repository.update_external_offer_id(
                mapping,
                external_offer_id=normalized_external_offer_id,
            )
            change = "updated"
        else:
            change = "unchanged"

        if change != "unchanged":
            db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise PaymentProviderOfferPersistenceError from exc

    return change
