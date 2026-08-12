from __future__ import annotations

import logging
from decimal import Decimal

from pydantic import EmailStr, TypeAdapter, ValidationError
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
from app.repositories.products_repository import ProductsRepository
from app.repositories.service_addon_repository import ServiceAddonRepository
from app.services import mail_service
from app.services.lava_top.client import LavaTopProviderError, create_invoice
from app.services.sale_service import (
    calculate_sale_total,
    create_product_sale,
    create_service_sale_item,
)
from app.utils.product_utils import get_product_package

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


class CheckoutValidationError(Exception):
    """Raised when submitted checkout selection cannot be used safely."""


LAVA_TOP_PROVIDER = "lava_top"
EMAIL_ADAPTER = TypeAdapter(EmailStr)


def initiate_lava_top_product_checkout(
    db: Session,
    *,
    product_slug: str,
    customer_email: str,
    currency: str,
    include_consultation: bool,
) -> str:
    """Resolve checkout data, prepare its sale snapshots, and create checkout."""

    normalized_currency = currency.strip().upper()
    if not normalized_currency:
        raise CheckoutValidationError("Currency is required.")

    try:
        normalized_email = str(
            EMAIL_ADAPTER.validate_python(customer_email.strip().lower())
        )
    except ValidationError as exc:
        raise CheckoutValidationError("A valid customer email is required.") from exc
    if len(normalized_email) > 200:
        raise CheckoutValidationError("A valid customer email is required.")

    products_repository = ProductsRepository(db)
    product = products_repository.get_by_slug(product_slug)
    if product is None or product.status != "in_sale":
        raise CheckoutValidationError("The selected product is unavailable.")

    price = products_repository.get_active_price_by_product_and_currency(
        product_id=product.id,
        currency_code=normalized_currency,
    )
    if price is None:
        raise CheckoutValidationError(
            "The selected product price is unavailable for this currency."
        )

    consultation_addon = None
    if include_consultation:
        consultation_addon = ServiceAddonRepository.get_active_addon(
            db,
            family_slug=product.family_slug,
            package_code=get_product_package(product.slug),
            service_type="consultation",
            usage_type="addon",
            currency_code=normalized_currency,
        )
        if consultation_addon is None:
            raise CheckoutValidationError(
                "The selected consultation add-on is unavailable."
            )

    try:
        sale = prepare_product_payment(
            db,
            product=product,
            customer_email=normalized_email,
            amount=price.amount,
            currency=normalized_currency,
            payment_provider=LAVA_TOP_PROVIDER,
        )

        if consultation_addon is not None:
            db.add(
                create_service_sale_item(
                    sale=sale,
                    service_addon_id=consultation_addon.id,
                    item_name=consultation_addon.name,
                    currency_code=consultation_addon.currency_code,
                    amount=consultation_addon.amount,
                )
            )

        db.flush()
        sale.amount = calculate_sale_total(list(sale.items))
        db.flush()
    except Exception:
        db.rollback()
        raise

    try:
        return create_lava_top_checkout(db, sale=sale)
    except PaymentReconciliationRequiredError as exc:
        logger.error(
            "Lava.top checkout reconciliation required provider_invoice_id=%s",
            exc.provider_invoice_id,
        )
        raise


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
