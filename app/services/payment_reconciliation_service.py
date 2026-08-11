from dataclasses import dataclass
from enum import StrEnum

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.enums import PaymentStatus, SaleItemType
from app.models.purchase_email_delivery import PurchaseEmailDelivery
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.repositories.sales_repository import get_sale_for_payment_reconciliation
from app.schemas.webhooks import NormalizedPaymentEvent, PaymentOutcome
from app.services.consultation_entitlement_service import (
    CONSULTATION_SERVICE_TYPE,
    create_consultation_entitlement,
)
from app.services.download_entitlement_service import create_download_entitlement


class PaymentReconciliationResult(StrEnum):
    APPLIED = "applied"
    IDEMPOTENT = "idempotent"


class PaymentReconciliationError(Exception):
    """Base class for controlled reconciliation failures."""


class PaymentReconciliationMismatchError(PaymentReconciliationError):
    """Raised when an event cannot be matched safely to its persisted Sale."""


class PaymentReconciliationConflictError(PaymentReconciliationError):
    """Raised when an event conflicts with terminal persisted history."""


class PaymentFulfillmentError(PaymentReconciliationError):
    """Raised when all required SaleItem fulfillment cannot be completed."""


@dataclass(frozen=True)
class PaymentReconciliationOutcome:
    result: PaymentReconciliationResult
    sale_id: int


def reconcile_payment_event(
    db: Session,
    event: NormalizedPaymentEvent,
    *,
    expected_sale_id: int | None = None,
) -> PaymentReconciliationOutcome:
    """Apply one authoritative payment result without committing."""

    sale = get_sale_for_payment_reconciliation(
        db,
        payment_provider=event.provider,
        external_payment_id=event.external_payment_id,
    )
    if sale is None:
        raise PaymentReconciliationMismatchError(
            "No Sale matches the provider invoice identity."
        )
    if expected_sale_id is not None and sale.id != expected_sale_id:
        raise PaymentReconciliationMismatchError(
            "Provider invoice identity does not match the expected Sale."
        )

    _validate_sale_snapshot(sale, event)
    if event.outcome == PaymentOutcome.FAILED:
        return _apply_failed(db, sale)
    return _apply_success(db, sale)


def _validate_sale_snapshot(sale: Sale, event: NormalizedPaymentEvent) -> None:
    if event.currency is not None and sale.currency.upper() != event.currency:
        raise PaymentReconciliationMismatchError(
            "Provider currency does not match the Sale snapshot."
        )
    if event.amount is not None and sale.amount != event.amount:
        raise PaymentReconciliationMismatchError(
            "Provider amount does not match the Sale snapshot."
        )


def _apply_failed(
    db: Session,
    sale: Sale,
) -> PaymentReconciliationOutcome:
    if sale.payment_status == PaymentStatus.FAILED:
        return PaymentReconciliationOutcome(
            PaymentReconciliationResult.IDEMPOTENT,
            sale.id,
        )
    if sale.payment_status != PaymentStatus.PENDING:
        raise PaymentReconciliationConflictError(
            "Payment failure conflicts with terminal Sale history."
        )

    sale.payment_status = PaymentStatus.FAILED
    db.flush()
    return PaymentReconciliationOutcome(
        PaymentReconciliationResult.APPLIED,
        sale.id,
    )


def _apply_success(
    db: Session,
    sale: Sale,
) -> PaymentReconciliationOutcome:
    if sale.payment_status in {PaymentStatus.FAILED, PaymentStatus.REFUNDED}:
        raise PaymentReconciliationConflictError(
            "Payment success conflicts with terminal Sale history."
        )

    if sale.payment_status == PaymentStatus.PAID:
        _validate_existing_fulfillment(sale)
        _ensure_purchase_email_delivery(db, sale)
        db.flush()
        return PaymentReconciliationOutcome(
            PaymentReconciliationResult.IDEMPOTENT,
            sale.id,
        )

    if sale.payment_status != PaymentStatus.PENDING:
        raise PaymentReconciliationConflictError(
            "Payment success conflicts with unsupported Sale history."
        )

    if not sale.items:
        raise PaymentFulfillmentError("Sale has no fulfillable items.")

    sale.payment_status = PaymentStatus.PAID
    for item in sale.items:
        _fulfill_sale_item(db, item)
    _ensure_purchase_email_delivery(db, sale)
    db.flush()
    return PaymentReconciliationOutcome(
        PaymentReconciliationResult.APPLIED,
        sale.id,
    )


def _fulfill_sale_item(db: Session, item: SaleItem) -> None:
    try:
        if item.item_type == SaleItemType.PRODUCT:
            if item.download_entitlement is None:
                create_download_entitlement(db, item)
            elif item.download_entitlement.release_id != item.product_release_id:
                raise PaymentFulfillmentError(
                    "Product entitlement does not match the purchased release."
                )
            if item.consultation_entitlement is not None:
                raise PaymentFulfillmentError(
                    "Product item has an incompatible consultation entitlement."
                )
            return

        if item.item_type == SaleItemType.SERVICE:
            if (
                item.service_addon is None
                or item.service_addon.service_type != CONSULTATION_SERVICE_TYPE
            ):
                raise PaymentFulfillmentError(
                    "Unsupported service item cannot be fulfilled."
                )
            if item.consultation_entitlement is None:
                create_consultation_entitlement(db, item)
            if item.download_entitlement is not None:
                raise PaymentFulfillmentError(
                    "Service item has an incompatible download entitlement."
                )
            return

        raise PaymentFulfillmentError("Unsupported SaleItem type cannot be fulfilled.")
    except HTTPException as exc:
        raise PaymentFulfillmentError(
            "SaleItem fulfillment validation failed."
        ) from exc


def _validate_existing_fulfillment(sale: Sale) -> None:
    if not sale.items:
        raise PaymentFulfillmentError("Paid Sale has no fulfillable items.")
    for item in sale.items:
        if item.item_type == SaleItemType.PRODUCT:
            if (
                item.download_entitlement is None
                or item.download_entitlement.release_id != item.product_release_id
                or item.consultation_entitlement is not None
            ):
                raise PaymentFulfillmentError(
                    "Paid product item has incomplete fulfillment."
                )
        elif item.item_type == SaleItemType.SERVICE:
            if (
                item.service_addon is None
                or item.service_addon.service_type != CONSULTATION_SERVICE_TYPE
                or item.consultation_entitlement is None
                or item.download_entitlement is not None
            ):
                raise PaymentFulfillmentError(
                    "Paid service item has incomplete fulfillment."
                )
        else:
            raise PaymentFulfillmentError(
                "Paid Sale contains an unsupported item type."
            )


def _ensure_purchase_email_delivery(db: Session, sale: Sale) -> None:
    if sale.purchase_email_delivery is None:
        db.add(PurchaseEmailDelivery(sale=sale))
