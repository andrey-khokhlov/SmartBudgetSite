from __future__ import annotations

import logging
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.enums import PaymentStatus
from app.models.product import Product
from app.models.sale import Sale
from app.repositories.product_release_repository import ProductReleaseRepository
from app.services import mail_service
from app.services.sale_service import create_product_sale


logger = logging.getLogger(__name__)


class ProductReleaseUnavailableError(Exception):
    """Raised when payment cannot start because no active release exists."""


def prepare_product_payment(
    db: Session,
    *,
    product: Product,
    customer_email: str,
    amount: Decimal,
    currency: str,
    payment_provider: str,
) -> Sale:
    """
    Prepare a pending product sale before payment-provider interaction.

    This service validates release availability and creates the pending sale
    snapshot, but it never commits the transaction or communicates with the
    payment provider. The caller owns the transaction boundary.
    """
    active_release = ProductReleaseRepository(db).get_active_by_product_id(product.id)

    if active_release is None:
        try:
            mail_service.send_email(
                to_email=settings.ADMIN_NOTIFICATION_EMAIL,
                subject=f"{settings.MAIL_FROM_NAME}: product unavailable for payment",
                body=(
                    "Payment initiation was blocked because no active product release exists.\n\n"
                    f"Product ID: {product.id}\n"
                    f"Product slug: {product.slug}\n"
                    f"Customer email: {customer_email}\n"
                    f"Payment provider: {payment_provider}"
                ),
            )
        except Exception:
            logger.exception(
                "Failed to send missing active product release notification",
                extra={"product_id": product.id, "product_slug": product.slug},
            )

        raise ProductReleaseUnavailableError(
            "The selected product is temporarily unavailable."
        )

    sale = create_product_sale(
        db,
        product=product,
        product_release=active_release,
        customer_email=customer_email,
        amount=amount,
        currency=currency,
        payment_provider=payment_provider,
        external_payment_id=None,
        payment_status=PaymentStatus.PENDING,
    )
    db.flush()
    return sale
