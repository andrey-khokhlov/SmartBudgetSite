import secrets
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.download_entitlement import (
    DownloadEntitlement,
    DownloadEntitlementStatus,
)
from app.models.enums import PaymentStatus, SaleItemType
from app.models.sale_item import SaleItem
from app.repositories.download_entitlement_repository import (
    DownloadEntitlementRepository,
)
from app.services.support_reference_service import (
    generate_download_support_reference,
)

DOWNLOAD_TOKEN_BYTES = 32
MAX_TOKEN_GENERATION_ATTEMPTS = 10
MAX_SUPPORT_REFERENCE_GENERATION_ATTEMPTS = 10


def _ensure_utc_aware(value: datetime) -> datetime:
    """Treat naive database datetimes as UTC and normalize aware values to UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _generate_unique_token(repository: DownloadEntitlementRepository) -> str:
    for _ in range(MAX_TOKEN_GENERATION_ATTEMPTS):
        token = secrets.token_urlsafe(DOWNLOAD_TOKEN_BYTES)
        if repository.get_by_token(token) is None:
            return token

    raise RuntimeError("Could not generate a unique download token.")


def _generate_unique_support_reference(
    repository: DownloadEntitlementRepository,
) -> str:
    for _ in range(MAX_SUPPORT_REFERENCE_GENERATION_ATTEMPTS):
        support_reference = generate_download_support_reference()
        if repository.get_by_support_reference(support_reference) is None:
            return support_reference

    raise RuntimeError("Could not generate a unique download support reference.")


def create_download_entitlement(
    db: Session,
    sale_item: SaleItem,
) -> DownloadEntitlement:
    """Create download access for one paid product sale item without committing."""
    repository = DownloadEntitlementRepository(db)

    if sale_item.item_type != SaleItemType.PRODUCT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Download entitlement can only be created for product sale items.",
        )

    if sale_item.sale is None or sale_item.sale.payment_status != PaymentStatus.PAID:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Download entitlement requires a paid sale.",
        )

    if sale_item.product_release_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Product sale item must have a linked product release.",
        )

    if repository.get_by_sale_item_id(sale_item.id) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Download entitlement already exists for this sale item.",
        )

    now = datetime.now(UTC)
    entitlement = DownloadEntitlement(
        sale_item_id=sale_item.id,
        release_id=sale_item.product_release_id,
        download_token=_generate_unique_token(repository),
        support_reference=_generate_unique_support_reference(repository),
        status=DownloadEntitlementStatus.AVAILABLE.value,
        expires_at=now + timedelta(hours=settings.DOWNLOAD_TOKEN_TTL_HOURS),
        attempt_count=0,
        created_at=now,
        updated_at=now,
    )

    return repository.create(entitlement)


def get_download_entitlement_by_support_reference(
    db: Session,
    support_reference: str,
) -> DownloadEntitlement | None:
    """Resolve a download entitlement by its safe public support reference."""
    return DownloadEntitlementRepository(db).get_by_support_reference(support_reference)


def get_download_support_reference_by_token(
    db: Session,
    download_token: str,
) -> str | None:
    """Resolve only the public support reference for a private access token."""
    entitlement = DownloadEntitlementRepository(db).get_by_token(download_token)
    return entitlement.support_reference if entitlement is not None else None


def get_valid_download_entitlement_by_token(
    db: Session,
    download_token: str,
) -> DownloadEntitlement:
    """Resolve and validate a currently available download entitlement."""
    entitlement = DownloadEntitlementRepository(db).get_by_token(download_token)

    if entitlement is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Download link was not found.",
        )

    if entitlement.status == DownloadEntitlementStatus.COMPLETED.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This download has already been completed.",
        )

    if entitlement.status == DownloadEntitlementStatus.CANCELLED.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Download link has been cancelled.",
        )

    if entitlement.status == DownloadEntitlementStatus.EXPIRED.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Download link has expired.",
        )

    if entitlement.status != DownloadEntitlementStatus.AVAILABLE.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Download link is no longer available.",
        )

    if _ensure_utc_aware(entitlement.expires_at) <= datetime.now(UTC):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Download link has expired.",
        )

    if entitlement.attempt_count >= settings.DOWNLOAD_MAX_ATTEMPTS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Download attempt limit has been reached.",
        )

    if entitlement.release is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Download release was not found.",
        )

    return entitlement


def record_download_attempt(
    db: Session,
    download_token: str,
) -> DownloadEntitlement:
    """Validate and record one signed-URL issuance attempt without committing."""
    entitlement = get_valid_download_entitlement_by_token(db, download_token)
    now = datetime.now(UTC)

    entitlement.attempt_count += 1

    if entitlement.first_attempt_at is None:
        entitlement.first_attempt_at = now

    entitlement.last_attempt_at = now
    entitlement.updated_at = now

    db.flush()
    return entitlement
