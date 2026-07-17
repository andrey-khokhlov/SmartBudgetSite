import re
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.models.download_entitlement import (
    DownloadEntitlement,
    DownloadEntitlementStatus,
)
from app.models.enums import PaymentStatus, SaleItemType
from app.models.product import Product
from app.models.product_release import ProductRelease
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.models.service_addon import ServiceAddon
from app.services.download_entitlement_service import (
    create_download_entitlement,
    get_valid_download_entitlement_by_token,
    record_download_attempt,
)
from app.services.sale_service import (
    create_product_sale,
    create_standalone_service_sale,
)
from app.services.support_reference_service import (
    is_valid_download_support_reference,
)


def create_product(db_session, suffix: str | None = None) -> Product:
    suffix = suffix or uuid.uuid4().hex
    product = Product(
        family_slug="smartbudget",
        slug=f"smartbudget-download-{suffix}",
        name="SmartBudget",
        edition="Standard",
        archive_path="legacy/smartbudget.zip",
        status="in_sale",
    )
    db_session.add(product)
    db_session.flush()
    return product


def create_release(
    db_session,
    product: Product,
    *,
    version: str = "1.0",
    is_active: bool = True,
) -> ProductRelease:
    release = ProductRelease(
        product_id=product.id,
        version=version,
        storage_provider="cloudflare_r2",
        storage_key=f"product-releases/{product.slug}/{version}.zip",
        original_filename=f"SmartBudget_{version}.zip",
        is_active=is_active,
    )
    db_session.add(release)
    db_session.flush()
    return release


def create_product_item(
    db_session,
    *,
    payment_status: str = PaymentStatus.PAID,
) -> tuple[SaleItem, ProductRelease]:
    product = create_product(db_session)
    release = create_release(db_session, product)
    sale = create_product_sale(
        db_session,
        product=product,
        product_release=release,
        customer_email="customer@example.com",
        amount=Decimal("39.00"),
        currency="EUR",
        payment_status=payment_status,
    )
    db_session.flush()
    return sale.items[0], release


def test_create_download_entitlement_for_paid_product_item(db_session):
    sale_item, release = create_product_item(db_session)

    entitlement = create_download_entitlement(db_session, sale_item)

    assert entitlement.id is not None
    assert entitlement.sale_item_id == sale_item.id
    assert entitlement.release_id == release.id
    assert entitlement.status == DownloadEntitlementStatus.AVAILABLE.value
    assert entitlement.attempt_count == 0
    assert is_valid_download_support_reference(entitlement.support_reference)
    assert entitlement.first_attempt_at is None
    assert entitlement.last_attempt_at is None
    assert entitlement.completed_at is None
    assert sale_item.download_entitlement == entitlement
    assert entitlement in release.download_entitlements


def test_creation_binds_exact_release_stored_on_sale_item(db_session):
    product = create_product(db_session, "exact-release")
    purchased_release = create_release(
        db_session,
        product,
        version="1.0",
        is_active=False,
    )
    create_release(db_session, product, version="1.1", is_active=True)
    sale = create_product_sale(
        db_session,
        product=product,
        product_release=purchased_release,
        customer_email="customer@example.com",
        amount=Decimal("39.00"),
        currency="EUR",
        payment_status=PaymentStatus.PAID,
    )
    db_session.flush()

    entitlement = create_download_entitlement(db_session, sale.items[0])

    assert entitlement.release_id == purchased_release.id


def test_creation_generates_secure_unique_url_safe_tokens(db_session):
    first_item, _ = create_product_item(db_session)
    second_item, _ = create_product_item(db_session)

    first = create_download_entitlement(db_session, first_item)
    second = create_download_entitlement(db_session, second_item)

    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", first.download_token)
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", second.download_token)
    assert first.download_token != second.download_token


def test_database_enforces_unique_sale_item_ownership(db_session):
    sale_item, release = create_product_item(db_session)
    create_download_entitlement(db_session, sale_item)
    duplicate = DownloadEntitlement(
        sale_item_id=sale_item.id,
        release_id=release.id,
        download_token="different-secure-token",
        support_reference="DL-23456789",
        status=DownloadEntitlementStatus.AVAILABLE.value,
        expires_at=datetime.now(UTC) + timedelta(hours=12),
        attempt_count=0,
    )
    db_session.add(duplicate)

    with pytest.raises(IntegrityError):
        db_session.flush()

    db_session.rollback()


def test_creation_retries_duplicate_support_reference(db_session, monkeypatch):
    first_item, _ = create_product_item(db_session)
    second_item, _ = create_product_item(db_session)
    references = iter(["DL-ABCDEFGH", "DL-ABCDEFGH", "DL-JKMNPQRS"])
    monkeypatch.setattr(
        "app.services.download_entitlement_service.generate_download_support_reference",
        lambda: next(references),
    )

    first = create_download_entitlement(db_session, first_item)
    second = create_download_entitlement(db_session, second_item)

    assert first.support_reference == "DL-ABCDEFGH"
    assert second.support_reference == "DL-JKMNPQRS"


def test_database_enforces_unique_support_reference(db_session):
    first_item, _ = create_product_item(db_session)
    second_item, second_release = create_product_item(db_session)
    first = create_download_entitlement(db_session, first_item)
    duplicate = DownloadEntitlement(
        sale_item_id=second_item.id,
        release_id=second_release.id,
        download_token="different-secure-token",
        support_reference=first.support_reference,
        status=DownloadEntitlementStatus.AVAILABLE.value,
        expires_at=datetime.now(UTC) + timedelta(hours=12),
        attempt_count=0,
    )
    db_session.add(duplicate)

    with pytest.raises(IntegrityError):
        db_session.flush()

    db_session.rollback()


def test_creation_rejects_unpaid_sale(db_session):
    sale_item, _ = create_product_item(
        db_session,
        payment_status=PaymentStatus.PENDING,
    )

    with pytest.raises(HTTPException) as exc_info:
        create_download_entitlement(db_session, sale_item)

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Download entitlement requires a paid sale."


def test_creation_rejects_service_sale_item(db_session):
    service = ServiceAddon(
        code=f"consultation_{uuid.uuid4().hex}",
        name="1:1 SmartBudget consultation",
        service_type="consultation",
        usage_type="standalone",
        family_slug="smartbudget",
        package_code="INT",
        currency_code="EUR",
        amount=Decimal("79.00"),
        is_active=True,
    )
    db_session.add(service)
    db_session.flush()
    sale = create_standalone_service_sale(
        db_session,
        service_addon_id=service.id,
        service_name=service.name,
        customer_email="customer@example.com",
        amount=service.amount,
        currency=service.currency_code,
        payment_status=PaymentStatus.PAID,
    )
    db_session.flush()

    with pytest.raises(HTTPException) as exc_info:
        create_download_entitlement(db_session, sale.items[0])

    assert exc_info.value.status_code == 400
    assert (
        exc_info.value.detail
        == "Download entitlement can only be created for product sale items."
    )


def test_creation_rejects_missing_product_release(db_session):
    product = create_product(db_session, "missing-release")
    sale = Sale(
        product_id=product.id,
        customer_email="customer@example.com",
        amount=Decimal("39.00"),
        currency="EUR",
        payment_status=PaymentStatus.PAID,
    )
    db_session.add(sale)
    db_session.flush()
    sale_item = SaleItem(
        sale_id=sale.id,
        item_type=SaleItemType.PRODUCT,
        product_id=product.id,
        product_release_id=None,
        item_name="SmartBudget Standard",
        currency_code="EUR",
        amount=Decimal("39.00"),
        quantity=1,
    )
    db_session.add(sale_item)
    db_session.flush()

    with pytest.raises(HTTPException) as exc_info:
        create_download_entitlement(db_session, sale_item)

    assert exc_info.value.status_code == 400
    assert (
        exc_info.value.detail
        == "Product sale item must have a linked product release."
    )


def test_creation_rejects_duplicate_entitlement(db_session):
    sale_item, _ = create_product_item(db_session)
    create_download_entitlement(db_session, sale_item)

    with pytest.raises(HTTPException) as exc_info:
        create_download_entitlement(db_session, sale_item)

    assert exc_info.value.status_code == 409
    assert (
        exc_info.value.detail
        == "Download entitlement already exists for this sale item."
    )


def test_valid_token_lookup_returns_entitlement(db_session):
    sale_item, _ = create_product_item(db_session)
    entitlement = create_download_entitlement(db_session, sale_item)

    result = get_valid_download_entitlement_by_token(
        db_session,
        entitlement.download_token,
    )

    assert result.id == entitlement.id


def test_valid_token_lookup_rejects_unknown_token(db_session):
    with pytest.raises(HTTPException) as exc_info:
        get_valid_download_entitlement_by_token(db_session, "unknown-token")

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Download link was not found."


def test_valid_token_lookup_rejects_expired_token_without_mutating_status(db_session):
    sale_item, _ = create_product_item(db_session)
    entitlement = create_download_entitlement(db_session, sale_item)
    entitlement.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.flush()

    with pytest.raises(HTTPException) as exc_info:
        get_valid_download_entitlement_by_token(
            db_session,
            entitlement.download_token,
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Download link has expired."
    assert entitlement.status == DownloadEntitlementStatus.AVAILABLE.value


def test_valid_token_lookup_rejects_completed_token(db_session):
    sale_item, _ = create_product_item(db_session)
    entitlement = create_download_entitlement(db_session, sale_item)
    entitlement.status = DownloadEntitlementStatus.COMPLETED.value
    db_session.flush()

    with pytest.raises(HTTPException) as exc_info:
        get_valid_download_entitlement_by_token(
            db_session,
            entitlement.download_token,
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "This download has already been completed."


def test_valid_token_lookup_rejects_cancelled_token(db_session):
    sale_item, _ = create_product_item(db_session)
    entitlement = create_download_entitlement(db_session, sale_item)
    entitlement.status = DownloadEntitlementStatus.CANCELLED.value
    db_session.flush()

    with pytest.raises(HTTPException) as exc_info:
        get_valid_download_entitlement_by_token(
            db_session,
            entitlement.download_token,
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Download link has been cancelled."


def test_record_first_download_attempt_sets_counter_and_timestamps(
    db_session,
    monkeypatch,
):
    monkeypatch.setattr(settings, "DOWNLOAD_MAX_ATTEMPTS", 3)
    sale_item, _ = create_product_item(db_session)
    entitlement = create_download_entitlement(db_session, sale_item)

    result = record_download_attempt(db_session, entitlement.download_token)

    assert result.attempt_count == 1
    assert result.first_attempt_at is not None
    assert result.last_attempt_at == result.first_attempt_at
    assert result.status == DownloadEntitlementStatus.AVAILABLE.value
    assert result.completed_at is None


def test_record_repeated_attempt_preserves_first_timestamp(db_session, monkeypatch):
    monkeypatch.setattr(settings, "DOWNLOAD_MAX_ATTEMPTS", 3)
    sale_item, _ = create_product_item(db_session)
    entitlement = create_download_entitlement(db_session, sale_item)
    first_time = datetime.now(UTC) - timedelta(minutes=5)
    entitlement.attempt_count = 1
    entitlement.first_attempt_at = first_time
    entitlement.last_attempt_at = first_time
    db_session.flush()

    result = record_download_attempt(db_session, entitlement.download_token)

    assert result.attempt_count == 2
    assert result.first_attempt_at == first_time
    assert result.last_attempt_at > first_time
    assert result.status == DownloadEntitlementStatus.AVAILABLE.value


def test_record_download_attempt_rejects_attempt_limit(db_session, monkeypatch):
    monkeypatch.setattr(settings, "DOWNLOAD_MAX_ATTEMPTS", 3)
    sale_item, _ = create_product_item(db_session)
    entitlement = create_download_entitlement(db_session, sale_item)
    entitlement.attempt_count = 3
    db_session.flush()

    with pytest.raises(HTTPException) as exc_info:
        record_download_attempt(db_session, entitlement.download_token)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Download attempt limit has been reached."
    assert entitlement.attempt_count == 3


def test_creation_uses_configured_twelve_hour_lifetime(db_session, monkeypatch):
    monkeypatch.setattr(settings, "DOWNLOAD_TOKEN_TTL_HOURS", 12)
    sale_item, _ = create_product_item(db_session)

    entitlement = create_download_entitlement(db_session, sale_item)
    lifetime = entitlement.expires_at - entitlement.created_at

    assert lifetime == timedelta(hours=12)
