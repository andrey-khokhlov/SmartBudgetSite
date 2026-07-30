from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.models.download_entitlement import DownloadEntitlement
from app.models.enums import PaymentStatus, SaleItemType
from app.models.product import Product
from app.models.product_release import ProductRelease
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.services.storage.r2_storage_service import (
    R2StorageOperationError,
    StoredObject,
)
from scripts.reconcile_product_releases import reconcile_product_releases

NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)
OLD = NOW - timedelta(days=2)


class FakeReconciliationStorage:
    def __init__(self) -> None:
        self.listed: list[StoredObject] = []
        self.heads: dict[str, StoredObject | None | Exception] = {}
        self.deleted: list[str] = []
        self.delete_failures: set[str] = set()

    def list_product_release_objects(self) -> list[StoredObject]:
        return list(self.listed)

    def head_product_release_object(self, *, storage_key: str):
        result = self.heads.get(storage_key)
        if isinstance(result, Exception):
            raise result
        return result

    def delete_product_release_object(self, *, storage_key: str) -> None:
        if storage_key in self.delete_failures:
            raise R2StorageOperationError("safe failure")
        self.deleted.append(storage_key)


def create_product(db_session, suffix: str) -> Product:
    product = Product(
        family_slug="smartbudget",
        slug=f"smartbudget-reconcile-{suffix}",
        name="SmartBudget",
        archive_path="legacy/path.zip",
        edition="Standard",
        status="in_sale",
    )
    db_session.add(product)
    db_session.flush()
    return product


def create_release(
    db_session,
    product: Product,
    *,
    version: str,
    storage_key: str,
    file_size: int = 10,
    sha256_hash: str = "a" * 64,
    is_active: bool = False,
) -> ProductRelease:
    release = ProductRelease(
        product_id=product.id,
        version=version,
        storage_provider="cloudflare_r2",
        storage_key=storage_key,
        original_filename=f"release-{version}.zip",
        file_size=file_size,
        sha256_hash=sha256_hash,
        is_active=is_active,
    )
    db_session.add(release)
    db_session.flush()
    return release


def stored(
    storage_key: str,
    *,
    size: int = 10,
    sha256_hash: str | None = "a" * 64,
    last_modified: datetime = OLD,
) -> StoredObject:
    return StoredObject(
        storage_key=storage_key,
        content_length=size,
        sha256_hash=sha256_hash,
        last_modified=last_modified,
    )


def test_reconciliation_reports_missing_orphan_and_metadata_mismatches(
    db_session,
) -> None:
    product = create_product(db_session, "report")
    missing_key = f"product-releases/{product.id}/1.0/{'a' * 32}"
    size_key = f"product-releases/{product.id}/1.1/{'b' * 32}"
    sha_key = f"product-releases/{product.id}/1.2/{'c' * 32}"
    outside_key = "legacy-outside-prefix/release.zip"
    for version, key in (
        ("1.0", missing_key),
        ("1.1", size_key),
        ("1.2", sha_key),
        ("1.3", outside_key),
    ):
        create_release(
            db_session,
            product,
            version=version,
            storage_key=key,
        )
    db_session.commit()

    orphan_key = f"product-releases/{product.id}/2.0/{'d' * 32}"
    unexpected_key = "product-releases/legacy/manual-file.zip"
    storage = FakeReconciliationStorage()
    storage.listed = [
        stored(size_key, size=11),
        stored(sha_key, sha256_hash="b" * 64),
        stored(outside_key),
        stored(orphan_key),
        stored(unexpected_key),
    ]
    storage.heads = {
        missing_key: None,
        size_key: stored(size_key, size=11),
        sha_key: stored(sha_key, sha256_hash="b" * 64),
        outside_key: stored(outside_key),
    }

    report = reconcile_product_releases(
        db_session,
        storage=storage,
        output=lambda line: None,
    )

    assert report.missing_owned_keys == (missing_key,)
    assert report.orphan_keys == (orphan_key, unexpected_key)
    assert report.size_mismatch_keys == (size_key,)
    assert report.sha_mismatch_keys == (sha_key,)
    assert report.unexpected_database_keys == (outside_key,)
    assert report.unexpected_object_keys == (unexpected_key,)
    assert storage.deleted == []


def test_reconciliation_is_read_only_by_default(db_session) -> None:
    orphan_key = f"product-releases/1/1.0/{'a' * 32}"
    storage = FakeReconciliationStorage()
    storage.listed = [stored(orphan_key)]

    report = reconcile_product_releases(
        db_session,
        storage=storage,
        output=lambda line: None,
    )

    assert report.orphan_keys == (orphan_key,)
    assert report.deleted_orphan_keys == ()
    assert storage.deleted == []


def test_explicit_deletion_is_age_gated_and_rejects_unexpected_keys(
    db_session,
) -> None:
    old_key = f"product-releases/1/1.0/{'a' * 32}"
    recent_key = f"product-releases/1/1.0/{'b' * 32}"
    unexpected_key = "product-releases/legacy/manual.zip"
    storage = FakeReconciliationStorage()
    storage.listed = [
        stored(old_key),
        stored(recent_key, last_modified=NOW - timedelta(hours=1)),
        stored(unexpected_key),
    ]

    report = reconcile_product_releases(
        db_session,
        storage=storage,
        delete_orphans=True,
        minimum_orphan_age=timedelta(hours=24),
        now=NOW,
        output=lambda line: None,
    )

    assert report.deleted_orphan_keys == (old_key,)
    assert report.too_recent_orphan_keys == (recent_key,)
    assert report.unexpected_object_keys == (unexpected_key,)
    assert storage.deleted == [old_key]


def test_reconciliation_never_deletes_database_owned_active_or_referenced_object(
    db_session,
) -> None:
    product = create_product(db_session, "owned")
    owned_key = f"product-releases/{product.id}/1.0/{'a' * 32}"
    release = create_release(
        db_session,
        product,
        version="1.0",
        storage_key=owned_key,
        is_active=True,
    )
    sale = Sale(
        customer_email="owner@example.com",
        amount=Decimal("39.00"),
        currency="EUR",
        payment_status=PaymentStatus.PAID,
    )
    db_session.add(sale)
    db_session.flush()
    item = SaleItem(
        sale_id=sale.id,
        item_type=SaleItemType.PRODUCT,
        product_id=product.id,
        product_release_id=release.id,
        item_name="SmartBudget",
        currency_code="EUR",
        amount=Decimal("39.00"),
        quantity=1,
    )
    db_session.add(item)
    db_session.flush()
    db_session.add(
        DownloadEntitlement(
            sale_item_id=item.id,
            release_id=release.id,
            download_token="token",
            support_reference="DL-ABC12345",
            status="available",
            expires_at=NOW + timedelta(hours=1),
            attempt_count=0,
        )
    )
    db_session.commit()

    storage = FakeReconciliationStorage()
    storage.listed = [stored(owned_key)]
    storage.heads = {owned_key: stored(owned_key)}

    report = reconcile_product_releases(
        db_session,
        storage=storage,
        delete_orphans=True,
        now=NOW,
        output=lambda line: None,
    )

    assert report.orphan_keys == ()
    assert report.deleted_orphan_keys == ()
    assert storage.deleted == []


def test_delete_failure_is_reported_without_database_mutation(db_session) -> None:
    orphan_key = f"product-releases/1/1.0/{'a' * 32}"
    storage = FakeReconciliationStorage()
    storage.listed = [stored(orphan_key)]
    storage.delete_failures.add(orphan_key)

    report = reconcile_product_releases(
        db_session,
        storage=storage,
        delete_orphans=True,
        now=NOW,
        output=lambda line: None,
    )

    assert report.delete_failure_keys == (orphan_key,)
    assert report.deleted_orphan_keys == ()
    assert db_session.query(ProductRelease).count() == 0


def test_report_output_uses_only_non_reversible_key_references(db_session) -> None:
    orphan_key = f"product-releases/1/1.0/{'a' * 32}"
    storage = FakeReconciliationStorage()
    storage.listed = [stored(orphan_key)]
    output: list[str] = []

    reconcile_product_releases(
        db_session,
        storage=storage,
        output=output.append,
    )

    assert all(orphan_key not in line for line in output)
    assert any("key-ref:" in line for line in output)
