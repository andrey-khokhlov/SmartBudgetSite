import pytest

from fastapi import HTTPException, status

from app.models.product import Product
from app.models.product_release import ProductRelease
from app.services.product_release_service import ProductReleaseService


def create_test_product(db_session) -> Product:
    product = Product(
        family_slug="smartbudget",
        slug="smartbudget-test-standard",
        name="SmartBudget",
        archive_path="legacy/path.zip",
        edition="Standard",

        status="in_sale",
    )

    db_session.add(product)
    db_session.flush()

    return product


def test_publish_release_deactivates_previous_active_release(db_session):
    """Publishing a release deactivates the previously active release."""
    product = create_test_product(db_session)

    old_release = ProductRelease(
        product_id=product.id,
        version="1.0",
        storage_provider="cloudflare_r2",
        storage_key="smartbudget/test-product/v1.0.zip",
        original_filename="SmartBudget_v1.0.zip",
        is_active=True,
    )

    new_release = ProductRelease(
        product_id=product.id,
        version="1.1",
        storage_provider="cloudflare_r2",
        storage_key="smartbudget/test-product/v1.1.zip",
        original_filename="SmartBudget_v1.1.zip",
        is_active=False,
    )

    db_session.add_all([old_release, new_release])
    db_session.flush()

    service = ProductReleaseService(db_session)

    published_release = service.publish_release(new_release.id)

    assert published_release.id == new_release.id
    assert new_release.is_active is True
    assert old_release.is_active is False
    assert new_release.released_at is not None


def test_publish_release_raises_404_for_unknown_release(db_session):
    """Publishing an unknown release raises HTTP 404."""

    service = ProductReleaseService(db_session)

    with pytest.raises(HTTPException) as exc:
        service.publish_release(999999)

    assert exc.value.status_code == status.HTTP_404_NOT_FOUND


def test_create_release_creates_inactive_release(db_session):
    """Creating a release stores it as an inactive release candidate."""

    product = create_test_product(db_session)
    service = ProductReleaseService(db_session)

    release = service.create_release(
        product_id=product.id,
        version="1.1",
        storage_provider="cloudflare_r2",
        storage_key="smartbudget/test-product/v1.1.zip",
        original_filename="SmartBudget_v1.1.zip",
        release_notes="Test release notes",
        file_size=1024,
        sha256_hash="a" * 64,
    )

    assert release.id is not None
    assert release.product_id == product.id
    assert release.version == "1.1"
    assert release.is_active is False
    assert release.released_at is None
