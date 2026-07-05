from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from decimal import Decimal

from app.core.db import SessionLocal
from app.models.enums import PaymentStatus
from app.models.product import Product
from app.services.sale_service import create_product_sale


def main() -> None:
    """
    Create one development SmartBudget product sale.

    Business rules:
    - This script is for local development only.
    - It creates a realistic product sale through the sale service layer.
    - Product catalog data is created only if missing.
    - SaleItem must be created from service logic, not manual SQL.

    Side effects:
    - Inserts Product if needed.
    - Inserts Sale and SaleItem.
    - Commits the transaction.

    Invariants / restrictions:
    - Must not be used in production.
    - Does not create consultation entitlement.
    """

    db = SessionLocal()

    try:
        product = (
            db.query(Product)
            .filter(Product.slug == "smartbudget-int-standard")
            .one_or_none()
        )

        if product is None:
            product = Product(
                family_slug="smartbudget",
                slug="smartbudget-int-standard",
                name="SmartBudget",
                edition="Standard",

                archive_path="dev/smartbudget-int-standard.zip",
                status="in_sale",
            )
            db.add(product)
            db.flush()

        sale = create_product_sale(
            db=db,
            product=product,
            customer_email="dev.product.customer@example.com",
            amount=Decimal("49.00"),
            currency="EUR",
            payment_provider="dev",
            external_payment_id="dev_product_sale_001",
            payment_status=PaymentStatus.PAID,
        )

        db.commit()

        print("Created dev product sale")
        print(f"Sale ID: {sale.id}")
        print(f"Customer: {sale.customer_email}")
        print(f"Total: {sale.amount} {sale.currency}")

    finally:
        db.close()


if __name__ == "__main__":
    main()
