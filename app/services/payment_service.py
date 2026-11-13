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
from app.models.service_addon import ServiceAddon
from app.models.service_payment_provider_offer import ServicePaymentProviderOffer
from app.repositories.payment_provider_offer_repository import (
    PaymentProviderOfferRepository,
)
from app.repositories.product_release_repository import ProductReleaseRepository
from app.repositories.products_repository import ProductsRepository
from app.repositories.service_addon_repository import ServiceAddonRepository
from app.repositories.service_payment_provider_offer_repository import (
    ServicePaymentProviderOfferRepository,
)
from app.services import mail_service
from app.services.consultation_offer_admin_service import (
    ALLOWED_CONSULTATION_CURRENCIES,
)
from app.services.lava_top.client import LavaTopProviderError, create_invoice
from app.services.sale_service import (
    calculate_sale_total,
    create_product_sale,
    create_service_sale_item,
    create_standalone_service_sale,
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


def _normalize_checkout_email(customer_email: str) -> str:
    try:
        normalized_email = str(
            EMAIL_ADAPTER.validate_python(customer_email.strip().lower())
        )
    except ValidationError as exc:
        raise CheckoutValidationError("A valid customer email is required.") from exc
    if len(normalized_email) > 200:
        raise CheckoutValidationError("A valid customer email is required.")
    return normalized_email


def initiate_lava_top_product_checkout(
    db: Session,
    *,
    product_slug: str,
    customer_email: str,
    currency: str,
    include_consultation: bool,
    purchase_language: str = "en",
) -> str:
    """Resolve checkout data, prepare its sale snapshots, and create checkout."""

    if include_consultation and not settings.BUNDLE_CHECKOUT_ENABLED:
        raise CheckoutValidationError("Bundle checkout is unavailable.")

    normalized_currency = currency.strip().upper()
    if not normalized_currency:
        raise CheckoutValidationError("Currency is required.")

    normalized_email = _normalize_checkout_email(customer_email)

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
            purchase_language=purchase_language,
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


def resolve_standalone_consultation_checkout(
    db: Session,
    *,
    service_addon_id: int,
    currency: str,
) -> tuple[ServiceAddon, ServicePaymentProviderOffer]:
    """Read the exact service and provider mapping without starting checkout."""
    normalized_currency = currency.strip().upper()
    if normalized_currency not in ALLOWED_CONSULTATION_CURRENCIES:
        raise CheckoutValidationError("Select a supported consultation currency.")
    service = ServiceAddonRepository.get_consultation_offer_by_id(db, service_addon_id)
    if (
        service is None
        or not service.is_active
        or service.service_type != "consultation"
        or service.usage_type != "standalone"
        or service.currency_code != normalized_currency
        or not service.amount.is_finite()
        or service.amount <= 0
    ):
        raise CheckoutValidationError(
            "The selected standalone consultation is unavailable."
        )

    mapping = ServicePaymentProviderOfferRepository(db).get_by_service_and_provider(
        service_addon_id=service.id, provider=LAVA_TOP_PROVIDER
    )
    if mapping is None or not mapping.external_offer_id.strip():
        raise CheckoutValidationError(
            "No Lava.top offer is configured for this consultation."
        )
    return service, mapping


def initiate_lava_top_standalone_consultation_checkout(
    db: Session,
    *,
    service_addon_id: int,
    customer_email: str,
    currency: str,
    purchase_language: str = "en",
) -> str:
    """Start hosted checkout for one exact standalone consultation catalog record."""
    normalized_email = _normalize_checkout_email(customer_email)
    try:
        service, mapping = resolve_standalone_consultation_checkout(
            db, service_addon_id=service_addon_id, currency=currency
        )
        sale = create_standalone_service_sale(
            db,
            service_addon_id=service.id,
            service_name=service.name,
            customer_email=normalized_email,
            purchase_language=purchase_language,
            amount=service.amount,
            currency=service.currency_code,
            payment_provider=LAVA_TOP_PROVIDER,
        )
        db.flush()
        sale.amount = calculate_sale_total(list(sale.items))
        db.flush()
    except (CheckoutValidationError, SQLAlchemyError):
        db.rollback()
        raise

    return _create_and_persist_lava_top_invoice(
        db, sale=sale, external_offer_id=mapping.external_offer_id
    )


def prepare_product_payment(
    db: Session,
    *,
    product: Product,
    customer_email: str,
    amount: Decimal,
    currency: str,
    payment_provider: str,
    purchase_language: str = "en",
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
        purchase_language=purchase_language,
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

    mapping = PaymentProviderOfferRepository(db).get_by_product_and_provider(
        product_id=sale.product_id,
        provider=LAVA_TOP_PROVIDER,
    )
    return _create_and_persist_lava_top_invoice(
        db, sale=sale, external_offer_id=mapping.external_offer_id if mapping else None
    )


def _create_and_persist_lava_top_invoice(
    db: Session, *, sale: Sale, external_offer_id: str | None
) -> str:
    try:
        if external_offer_id is None:
            raise PaymentCheckoutError(
                "No Lava.top offer is configured for the selected product."
            )

        invoice = create_invoice(
            email=sale.customer_email,
            offer_id=external_offer_id,
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
