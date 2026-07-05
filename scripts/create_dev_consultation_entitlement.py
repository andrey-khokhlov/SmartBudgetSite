from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from decimal import Decimal

from app.core.db import SessionLocal
from app.models.service_addon import ServiceAddon
from app.services.sale_service import create_standalone_service_sale
from app.services.consultation_entitlement_service import (
    create_consultation_entitlement,
)


def main() -> None:
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
        )
        db.flush()

        entitlement = create_consultation_entitlement(
            db=db,
            sale_item=sale.items[0],
        )

        db.commit()

        print("Created dev consultation entitlement")
        print(f"Booking token: {entitlement.booking_token}")
        print(f"Booking URL: /consultation/book/{entitlement.booking_token}")

    finally:
        db.close()


if __name__ == "__main__":
    main()
