from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.models.download_entitlement import (
    DownloadEntitlement,
    DownloadEntitlementStatus,
)
from app.models.enums import PaymentStatus
from app.models.product import Product
from app.models.product_release import ProductRelease
from app.repositories.download_entitlement_repository import (
    DownloadEntitlementRepository,
)
from app.services.sale_service import create_product_sale


def create_entitlement(db_session) -> DownloadEntitlement:
    product = Product(
        family_slug="smartbudget",
        slug="smartbudget-download-repository-test",
        name="SmartBudget",
        edition="Standard",
        archive_path="legacy/smartbudget.zip",
        status="in_sale",
    )
    db_session.add(product)
    db_session.flush()
    release = ProductRelease(
        product_id=product.id,
        version="1.0",
        storage_provider="cloudflare_r2",
        storage_key="product-releases/repository-test/1.0.zip",
        original_filename="SmartBudget_1.0.zip",
        is_active=True,
    )
    db_session.add(release)
    db_session.flush()
    sale = create_product_sale(
        db_session,
        product=product,
        product_release=release,
        customer_email="customer@example.com",
        amount=Decimal("39.00"),
        currency="EUR",
        payment_status=PaymentStatus.PAID,
    )
    db_session.flush()
    entitlement = DownloadEntitlement(
        sale_item_id=sale.items[0].id,
        release_id=release.id,
        download_token="repository-lookup-token",
        support_reference="DL-ABCDEFGH",
        status=DownloadEntitlementStatus.AVAILABLE.value,
        expires_at=datetime.now(UTC) + timedelta(hours=12),
        attempt_count=0,
    )
    return DownloadEntitlementRepository(db_session).create(entitlement)


def test_get_download_entitlement_by_token(db_session):
    entitlement = create_entitlement(db_session)

    result = DownloadEntitlementRepository(db_session).get_by_token(
        entitlement.download_token
    )

    assert result is not None
    assert result.id == entitlement.id


def test_get_download_entitlement_by_sale_item_id(db_session):
    entitlement = create_entitlement(db_session)

    result = DownloadEntitlementRepository(db_session).get_by_sale_item_id(
        entitlement.sale_item_id
    )

    assert result is not None
    assert result.id == entitlement.id


def test_get_download_entitlement_by_support_reference(db_session):
    entitlement = create_entitlement(db_session)

    result = DownloadEntitlementRepository(db_session).get_by_support_reference(
        entitlement.support_reference
    )

    assert result is not None
    assert result.id == entitlement.id
