import argparse
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.db import SessionLocal  # noqa: E402
from app.models.enums import PaymentStatus  # noqa: E402
from app.models.service_addon import ServiceAddon  # noqa: E402
from app.services.sale_service import create_standalone_service_sale  # noqa: E402
from app.services.consultation_entitlement_service import (  # noqa: E402
    create_consultation_entitlement,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create one local development consultation entitlement.",
    )
    parser.add_argument(
        "--show-full-capability",
        action="store_true",
        help=(
            "Print the full sensitive booking token and URL. "
            "Use only when immediately opening the local development capability."
        ),
    )
    return parser


def mask_booking_token(booking_token: str) -> str:
    """Return a diagnostic-safe representation of a booking token."""
    return f"{booking_token[:8]}..." if booking_token else "[unavailable]"


def print_booking_access(
    booking_token: str,
    *,
    show_full_capability: bool,
) -> None:
    """Print masked access by default and the sensitive capability only by opt-in."""
    print("Created dev consultation entitlement")
    if show_full_capability:
        print("Sensitive booking capability (do not copy into logs or support text):")
        print(f"Booking token: {booking_token}")
        print(f"Booking URL: /consultation/book/{booking_token}")
        return

    print(f"Masked booking reference: {mask_booking_token(booking_token)}")
    print(
        "Full booking capability hidden. "
        "Re-run with --show-full-capability only when it is required."
    )


def main(argv: Sequence[str] | None = None) -> None:
    """
    Create one development consultation entitlement.

    Business rules:
    - This script is for local development only.
    - It creates a standalone consultation sale and one entitlement.
    - It should not be used in production.

    Side effects:
    - Inserts ServiceAddon if needed.
    - Inserts Sale, SaleItem, and ConsultationEntitlement.
    - Commits the transaction.
    """

    args = build_parser().parse_args(argv)
    db = SessionLocal()

    try:
        service_addon = (
            db.query(ServiceAddon)
            .filter(ServiceAddon.code == "dev_consultation_1h_int")
            .one_or_none()
        )

        if service_addon is None:
            service_addon = ServiceAddon(
                code="dev_consultation_1h_int",
                name="Dev 1:1 SmartBudget consultation",
                service_type="consultation",
                usage_type="standalone",
                family_slug="smartbudget",
                package_code="INT",
                currency_code="EUR",
                amount=Decimal("79.00"),
                is_active=True,
            )
            db.add(service_addon)
            db.flush()

        sale = create_standalone_service_sale(
            db=db,
            service_addon_id=service_addon.id,
            service_name=service_addon.name,
            customer_email="dev.customer@example.com",
            amount=service_addon.amount,
            currency=service_addon.currency_code,
            payment_status=PaymentStatus.PAID,
        )
        db.flush()

        entitlement = create_consultation_entitlement(
            db=db,
            sale_item=sale.items[0],
        )

        db.commit()

        print_booking_access(
            entitlement.booking_token,
            show_full_capability=args.show_full_capability,
        )

    finally:
        db.close()


if __name__ == "__main__":
    main()
