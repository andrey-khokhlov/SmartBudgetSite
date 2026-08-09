from __future__ import annotations

import logging
from decimal import Decimal

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.enums import PaymentStatus
from app.models.product import Product
from app.models.sale import Sale
from app.repositories.payment_provider_offer_repository import (
    PaymentProviderOfferRepository,
)
from app.repositories.product_release_repository import ProductReleaseRepository
from app.services import mail_service
from app.services.lava_top.client import LavaTopProviderError, create_invoice
from app.services.sale_service import create_product_sale


logger = logging.getLogger(__name__)


class ProductReleaseUnavailableError(Exception):
    """Raised when payment cannot start because no active release exists."""


class PaymentCheckoutError(Exception):
    """Raised when hosted checkout cannot be created for a pending sale."""


class PaymentReconciliationRequiredError(Exception):
    """Raised when a created provider invoice cannot be persisted locally."""

    def __init__(self, provider_invoice_id: str) -> None:
        super().__init__("Payment reconciliation is required.")
        self.provider_invoice_id = provider_invoice_id


LAVA_TOP_PROVIDER = "lava_top"


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


def create_lava_top_checkout(db: Session, *, sale: Sale) -> str:
    """Create and persist a Lava.top invoice for an already prepared sale."""

    if sale.payment_status != PaymentStatus.PENDING:
        raise PaymentCheckoutError("Checkout requires a pending sale.")
    if sale.payment_provider != LAVA_TOP_PROVIDER or sale.product_id is None:
        raise PaymentCheckoutError(
            "Sale is not prepared for Lava.top product checkout."
        )

    try:
        mapping = PaymentProviderOfferRepository(db).get_by_product_and_provider(
            product_id=sale.product_id,
            provider=LAVA_TOP_PROVIDER,
        )
        if mapping is None:
            raise PaymentCheckoutError(
                "No Lava.top offer is configured for the selected product."
            )

        invoice = create_invoice(
            email=sale.customer_email,
            offer_id=mapping.external_offer_id,
            currency=sale.currency,
            amount=sale.amount,
        )
    except (LavaTopProviderError, PaymentCheckoutError) as exc:
        sale.payment_status = PaymentStatus.FAILED
        sale.external_payment_id = None
        db.commit()
        raise PaymentCheckoutError("Unable to create hosted checkout.") from exc

    sale.external_payment_id = invoice.invoice_id
    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise PaymentReconciliationRequiredError(invoice.invoice_id) from exc

    return invoice.payment_url
