from app.models.product_release import ProductRelease
from app.models.product import Product
from app.repositories.product_release_repository import ProductReleaseRepository


def create_test_product(db_session, slug: str = "smartbudget-test-standard") -> Product:
    product = Product(
        family_slug="smartbudget",
        slug=slug,
        name="SmartBudget",
        archive_path="legacy/path.zip",
        edition="Standard",

        status="in_sale",
    )

    db_session.add(product)
    db_session.flush()

    return product


def test_create_product_release(db_session):
    """Repository creates a new product release."""
    test_product = create_test_product(db_session)

    repository = ProductReleaseRepository(db_session)

    release = ProductRelease(
        product_id=test_product.id,
        version="1.1",
        release_notes="Initial release test",
        storage_provider="cloudflare_r2",
        storage_key="smartbudget/test-product/v1.1.zip",
        original_filename="SmartBudget_v1.1.zip",
        file_size=1024,
        sha256_hash="a" * 64,
    )

    created_release = repository.create(release)

    assert created_release.id is not None
    assert created_release.product_id == test_product.id
    assert created_release.version == "1.1"


def test_list_product_releases_by_product_id(db_session):
    """Repository lists releases belonging to a product."""
    test_product = create_test_product(db_session)

    repository = ProductReleaseRepository(db_session)

    release = ProductRelease(
        product_id=test_product.id,
        version="1.1",
        storage_provider="cloudflare_r2",
        storage_key="smartbudget/test-product/v1.1.zip",
        original_filename="SmartBudget_v1.1.zip",
    )

    repository.create(release)

    releases = repository.list_by_product_id(test_product.id)

    assert len(releases) == 1
    assert releases[0].version == "1.1"


def test_get_active_product_release_by_product_id(db_session):
    """Repository returns the active release for a product."""
    test_product = create_test_product(db_session)

    repository = ProductReleaseRepository(db_session)

    inactive_release = ProductRelease(
        product_id=test_product.id,
        version="1.0",
        storage_provider="cloudflare_r2",
        storage_key="smartbudget/test-product/v1.0.zip",
        original_filename="SmartBudget_v1.0.zip",
        is_active=False,
    )

    active_release = ProductRelease(
        product_id=test_product.id,
        version="1.1",
        storage_provider="cloudflare_r2",
        storage_key="smartbudget/test-product/v1.1.zip",
        original_filename="SmartBudget_v1.1.zip",
        is_active=True,
    )

    repository.create(inactive_release)
    repository.create(active_release)

    found_release = repository.get_active_by_product_id(test_product.id)

    assert found_release is not None
    assert found_release.version == "1.1"


def test_get_product_release_by_id(db_session):
    """Repository returns a release by its identifier."""
    test_product = create_test_product(db_session)

    repository = ProductReleaseRepository(db_session)

    release = ProductRelease(
        product_id=test_product.id,
        version="1.1",
        storage_provider="cloudflare_r2",
        storage_key="smartbudget/test-product/v1.1.zip",
        original_filename="SmartBudget_v1.1.zip",
    )

    created_release = repository.create(release)

    found_release = repository.get_by_id(created_release.id)

    assert found_release is not None
    assert found_release.id == created_release.id
