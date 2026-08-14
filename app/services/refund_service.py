from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.consultation_entitlement import ConsultationEntitlementStatus
from app.models.download_entitlement import DownloadEntitlementStatus
from app.models.enums import PaymentStatus
from app.models.refund_operation import RefundOperation, RefundOperationStatus
from app.models.sale import Sale
from app.repositories.refund_operation_repository import RefundOperationRepository


class RefundNotFoundError(Exception):
    pass


class RefundEligibilityError(ValueError):
    pass


class RefundVerificationRequiredError(RefundEligibilityError):
    pass


class RefundConflictError(Exception):
    pass


class RefundPersistenceError(Exception):
    pass


class RefundActionResult(StrEnum):
    APPLIED = "applied"
    IDEMPOTENT = "idempotent"


@dataclass(frozen=True)
class RefundConfirmationResult:
    operation: RefundOperation
    result: RefundActionResult


def get_refund_sale_for_admin(db: Session, sale_id: int) -> Sale:
    sale = RefundOperationRepository(db).get_sale_for_admin(sale_id)
    if sale is None:
        raise RefundNotFoundError
    return sale


def start_full_refund(db: Session, *, sale_id: int) -> RefundOperation:
    """Persist one pending full-refund snapshot and own its transaction."""
    repository = RefundOperationRepository(db)
    try:
        with db.begin():
            sale = repository.lock_sale(sale_id)
            if sale is None:
                raise RefundNotFoundError
            existing = repository.lock_by_sale_id(sale_id)
            if existing is not None:
                return existing
            _validate_start_eligibility(sale)
            operation = repository.create(
                RefundOperation(
                    sale_id=sale.id,
                    status=RefundOperationStatus.PENDING.value,
                    amount=sale.amount,
                    currency=sale.currency,
                    payment_provider=sale.payment_provider,
                    external_payment_id=sale.external_payment_id,
                )
            )
    except (RefundNotFoundError, RefundEligibilityError):
        raise
    except IntegrityError as exc:
        db.rollback()
        existing = repository.get_by_sale_id(sale_id)
        if existing is not None:
            return existing
        raise RefundPersistenceError from exc
    except SQLAlchemyError as exc:
        raise RefundPersistenceError from exc
    return operation


def confirm_full_refund(
    db: Session,
    *,
    sale_id: int,
    provider_refund_verified: bool = False,
) -> RefundConfirmationResult:
    """Confirm a founder-verified provider refund and reconcile access atomically."""
    if not provider_refund_verified:
        raise RefundVerificationRequiredError(
            "Explicit provider refund verification is required."
        )
    repository = RefundOperationRepository(db)
    try:
        with db.begin():
            sale = repository.lock_sale(sale_id)
            if sale is None:
                raise RefundNotFoundError
            operation = repository.lock_by_sale_id(sale_id)
            if operation is None:
                raise RefundNotFoundError

            _validate_snapshot(operation, sale)
            if (
                operation.status == RefundOperationStatus.CONFIRMED.value
                and sale.payment_status == PaymentStatus.REFUNDED
            ):
                return RefundConfirmationResult(
                    operation, RefundActionResult.IDEMPOTENT
                )
            if operation.status != RefundOperationStatus.PENDING.value:
                raise RefundConflictError("Refund operation is not pending.")
            if sale.payment_status != PaymentStatus.PAID:
                raise RefundConflictError("Sale is not paid.")

            downloads = repository.lock_download_entitlements(sale_id)
            consultations = repository.lock_consultation_entitlements(sale_id)
            for entitlement in downloads:
                if entitlement.status == DownloadEntitlementStatus.AVAILABLE.value:
                    entitlement.status = DownloadEntitlementStatus.CANCELLED.value
            for entitlement in consultations:
                if entitlement.status == ConsultationEntitlementStatus.AVAILABLE.value:
                    entitlement.status = ConsultationEntitlementStatus.CANCELLED.value

            now = datetime.now(UTC)
            operation.status = RefundOperationStatus.CONFIRMED.value
            operation.confirmed_at = now
            sale.payment_status = PaymentStatus.REFUNDED
            db.flush()
    except (RefundNotFoundError, RefundConflictError):
        raise
    except SQLAlchemyError as exc:
        raise RefundPersistenceError from exc
    return RefundConfirmationResult(operation, RefundActionResult.APPLIED)


def _validate_start_eligibility(sale: Sale) -> None:
    if sale.payment_status != PaymentStatus.PAID:
        raise RefundEligibilityError("Only a paid Sale can start a refund.")
    if not (sale.payment_provider or "").strip():
        raise RefundEligibilityError("Sale payment provider is required.")
    if not (sale.external_payment_id or "").strip():
        raise RefundEligibilityError("Sale external payment identity is required.")


def _validate_snapshot(operation: RefundOperation, sale: Sale) -> None:
    if operation.sale_id != sale.id:
        raise RefundConflictError("Refund operation does not belong to the Sale.")
    if (
        operation.amount != sale.amount
        or operation.currency != sale.currency
        or operation.payment_provider != sale.payment_provider
        or operation.external_payment_id != sale.external_payment_id
    ):
        raise RefundConflictError("Refund snapshot no longer matches the Sale.")
