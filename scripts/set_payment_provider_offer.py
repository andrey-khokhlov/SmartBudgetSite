from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from pathlib import Path
import sys
from typing import Literal

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy.exc import SQLAlchemyError  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.db import SessionLocal  # noqa: E402
from app.models.payment_provider_offer import PaymentProviderOffer  # noqa: E402
from app.repositories.payment_provider_offer_repository import (  # noqa: E402
    PaymentProviderOfferRepository,
)
from app.repositories.products_repository import ProductsRepository  # noqa: E402


PaymentProviderOfferChange = Literal["created", "updated", "unchanged"]


class PaymentProviderOfferInputError(ValueError):
    """Raised when provider mapping input is invalid."""


class PaymentProviderOfferProductNotFoundError(Exception):
    """Raised when the requested product slug does not exist."""


class PaymentProviderOfferPersistenceError(Exception):
    """Raised when the mapping change cannot be persisted."""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create or update one product payment-provider offer mapping.",
    )
    parser.add_argument("--product-slug", required=True)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--external-offer-id", required=True)
    return parser


def set_payment_provider_offer(
    db: Session,
    *,
    product_slug: str,
    provider: str,
    external_offer_id: str,
    output: Callable[[str], None] = print,
) -> PaymentProviderOfferChange:
    normalized_provider = provider.strip()
    normalized_external_offer_id = external_offer_id.strip()

    if not normalized_provider:
        raise PaymentProviderOfferInputError("Provider must not be empty.")
    if not normalized_external_offer_id:
        raise PaymentProviderOfferInputError(
            "External offer ID must not be empty."
        )

    try:
        product = ProductsRepository(db).get_by_slug(product_slug)
        if product is None:
            raise PaymentProviderOfferProductNotFoundError(
                f"Product not found for exact slug: {product_slug}"
            )

        repository = PaymentProviderOfferRepository(db)
        offer = repository.get_by_product_and_provider(
            product_id=product.id,
            provider=normalized_provider,
        )

        if offer is None:
            repository.create(
                PaymentProviderOffer(
                    product_id=product.id,
                    provider=normalized_provider,
                    external_offer_id=normalized_external_offer_id,
                )
            )
            change: PaymentProviderOfferChange = "created"
        elif offer.external_offer_id != normalized_external_offer_id:
            repository.update_external_offer_id(
                offer,
                external_offer_id=normalized_external_offer_id,
            )
            change = "updated"
        else:
            change = "unchanged"

        if change != "unchanged":
            db.commit()
    except PaymentProviderOfferProductNotFoundError:
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise PaymentProviderOfferPersistenceError(
            "Payment-provider offer mapping could not be persisted."
        ) from exc

    output(
        f"{change}: product={product_slug} provider={normalized_provider} "
        f"external_offer_id={normalized_external_offer_id}"
    )
    return change


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    db = SessionLocal()
    try:
        set_payment_provider_offer(
            db,
            product_slug=args.product_slug,
            provider=args.provider,
            external_offer_id=args.external_offer_id,
        )
    except (
        PaymentProviderOfferInputError,
        PaymentProviderOfferProductNotFoundError,
        PaymentProviderOfferPersistenceError,
    ) as exc:
        print(f"failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    finally:
        db.close()


if __name__ == "__main__":
    main()
