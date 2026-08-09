from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy.orm import Session  # noqa: E402

from app.core.db import SessionLocal  # noqa: E402
from app.repositories.products_repository import ProductsRepository  # noqa: E402
from app.services.payment_service import (  # noqa: E402
    LAVA_TOP_PROVIDER,
    PaymentCheckoutError,
    PaymentReconciliationRequiredError,
    ProductReleaseUnavailableError,
    create_lava_top_checkout,
    prepare_product_payment,
)


class SmokeCheckoutInputError(ValueError):
    """Raised when smoke-checkout input is invalid."""


class SmokeCheckoutProductNotFoundError(Exception):
    """Raised when the exact product slug does not exist."""


class SmokeCheckoutPriceNotFoundError(Exception):
    """Raised when the requested currency has no active catalog price."""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create one deliberate live Lava.top checkout invoice.",
    )
    parser.add_argument("--product-slug", required=True)
    parser.add_argument("--customer-email", required=True)
    parser.add_argument("--currency", required=True)
    return parser


def smoke_lava_top_checkout(
    db: Session,
    *,
    product_slug: str,
    customer_email: str,
    currency: str,
    output: Callable[[str], None] = print,
) -> None:
    normalized_customer_email = customer_email.strip()
    normalized_currency = currency.strip().upper()
    if not normalized_customer_email:
        raise SmokeCheckoutInputError("Customer email must not be empty.")
    if not normalized_currency:
        raise SmokeCheckoutInputError("Currency must not be empty.")

    repository = ProductsRepository(db)
    product = repository.get_by_slug(product_slug)
    if product is None:
        raise SmokeCheckoutProductNotFoundError(
            f"Product not found for exact slug: {product_slug}"
        )

    price = repository.get_active_price_by_product_and_currency(
        product_id=product.id,
        currency_code=normalized_currency,
    )
    if price is None:
        raise SmokeCheckoutPriceNotFoundError(
            f"No active catalog price for requested currency: {normalized_currency}"
        )

    sale = prepare_product_payment(
        db,
        product=product,
        customer_email=normalized_customer_email,
        amount=price.amount,
        currency=price.currency_code,
        payment_provider=LAVA_TOP_PROVIDER,
    )
    payment_url = create_lava_top_checkout(db, sale=sale)
    del payment_url

    output("result=success")
    output(f"sale_id={sale.id}")
    output(f"payment_status={sale.payment_status}")
    output(f"external_payment_id={sale.external_payment_id}")
    output(f"amount={sale.amount}")
    output(f"currency={sale.currency}")


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    db = SessionLocal()
    try:
        smoke_lava_top_checkout(
            db,
            product_slug=args.product_slug,
            customer_email=args.customer_email,
            currency=args.currency,
        )
    except PaymentReconciliationRequiredError as exc:
        print("result=reconciliation_required", file=sys.stderr)
        print(
            f"provider_invoice_id={exc.provider_invoice_id}",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
    except SmokeCheckoutInputError:
        print("result=failure", file=sys.stderr)
        print("reason=invalid_input", file=sys.stderr)
        raise SystemExit(1) from None
    except SmokeCheckoutProductNotFoundError:
        print("result=failure", file=sys.stderr)
        print("reason=product_not_found", file=sys.stderr)
        raise SystemExit(1) from None
    except SmokeCheckoutPriceNotFoundError:
        print("result=failure", file=sys.stderr)
        print("reason=active_price_not_found", file=sys.stderr)
        raise SystemExit(1) from None
    except ProductReleaseUnavailableError:
        print("result=failure", file=sys.stderr)
        print("reason=product_release_unavailable", file=sys.stderr)
        raise SystemExit(1) from None
    except PaymentCheckoutError:
        print("result=failure", file=sys.stderr)
        print("reason=checkout_failed", file=sys.stderr)
        raise SystemExit(1) from None
    finally:
        db.close()


if __name__ == "__main__":
    main()
