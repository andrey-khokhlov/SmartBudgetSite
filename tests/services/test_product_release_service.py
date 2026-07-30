from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from io import BytesIO

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.product import Product
from app.models.product_release import ProductRelease
from app.services.product_release_service import (
    ProductReleaseService,
    ReleaseArchiveTooLargeError,
    ReleaseConflictError,
    ReleaseNotFoundError,
    ReleasePersistenceError,
    ReleaseReconciliationRequiredError,
    ReleaseStorageUnavailableError,
    ReleaseUploadValidationError,
)
from app.services.storage.r2_storage_service import UploadedObject


class FakeReleaseStorage:
    storage_provider = "cloudflare_r2"

    def __init__(self) -> None:
        self.objects: dict[str, tuple[int, str]] = {}
        self.uploaded: list[dict[str, object]] = []
        self.deleted: list[str] = []
        self.upload_error: Exception | None = None
        self.upload_error_after_store = False
        self.verification_override: bool | None = None
        self.verification_calls: list[dict[str, object]] = []
        self.delete_error: Exception | None = None

    def upload_product_release_file(
        self,
        *,
        storage_key,
        file_obj,
        file_size,
        sha256_hash,
    ) -> UploadedObject:
        self.uploaded.append(
            {
                "storage_key": storage_key,
                "file_size": file_size,
                "sha256_hash": sha256_hash,
                "position": file_obj.tell(),
                "content": file_obj.read(),
            }
        )
        if self.upload_error is not None and not self.upload_error_after_store:
            raise self.upload_error
        self.objects[storage_key] = (file_size, sha256_hash)
        if self.upload_error is not None:
            raise self.upload_error
        return UploadedObject(
            storage_provider=self.storage_provider,
            storage_key=storage_key,
        )

    def verify_product_release_object(
        self,
        *,
        storage_key,
        expected_file_size,
        expected_sha256_hash,
    ) -> bool:
        self.verification_calls.append(
            {
                "storage_key": storage_key,
                "expected_file_size": expected_file_size,
                "expected_sha256_hash": expected_sha256_hash,
            }
        )
        if self.verification_override is not None:
            return self.verification_override
        return self.objects.get(storage_key) == (
            expected_file_size,
            expected_sha256_hash,
        )

    def delete_product_release_object(self, *, storage_key) -> None:
        if self.delete_error is not None:
            raise self.delete_error
        self.objects.pop(storage_key, None)
        self.deleted.append(storage_key)


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
    db_session.commit()
    db_session.refresh(product)
    return product


def build_service(
    db_session,
    storage: FakeReleaseStorage,
    *,
    token: str = "a" * 32,
    operation_id: str = "operation-reference",
    ownership_session_factory=None,
) -> ProductReleaseService:
    return ProductReleaseService(
        db_session,
        storage_factory=lambda: storage,
        storage_token_factory=lambda: token,
        operation_id_factory=lambda: operation_id,
        ownership_session_factory=ownership_session_factory,
    )


def upload(
    service: ProductReleaseService,
    product: Product,
    *,
    content: bytes = b"release-content",
    version: str = "1.0",
    filename: str = "release.zip",
    notes: str = " Release notes ",
    max_bytes: int = 1024,
):
    return service.upload_release(
        product_id=product.id,
        version=version,
        release_notes=notes,
        original_filename=filename,
        file_obj=BytesIO(content),
        max_bytes=max_bytes,
    )


@pytest.mark.parametrize("version", ["production", "1.0.0", "../1.0", ""])
def test_invalid_version_never_initializes_storage(
    db_session,
    version,
) -> None:
    product = create_test_product(db_session)
    initialized = False

    def storage_factory():
        nonlocal initialized
        initialized = True
        return FakeReleaseStorage()

    service = ProductReleaseService(db_session, storage_factory=storage_factory)

    with pytest.raises(ReleaseUploadValidationError):
        upload(service, product, version=version)

    assert initialized is False
    assert db_session.query(ProductRelease).count() == 0


@pytest.mark.parametrize(
    "filename",
    ["../release.zip", "folder/release.zip", "folder\\release.zip", "bad\nname.zip"],
)
def test_unsafe_filename_never_initializes_storage(
    db_session,
    filename,
) -> None:
    product = create_test_product(db_session)
    initialized = False

    def storage_factory():
        nonlocal initialized
        initialized = True
        return FakeReleaseStorage()

    service = ProductReleaseService(db_session, storage_factory=storage_factory)

    with pytest.raises(ReleaseUploadValidationError):
        upload(service, product, filename=filename)

    assert initialized is False


def test_exact_boundary_upload_uses_opaque_key_metadata_and_commits(db_session):
    product = create_test_product(db_session)
    storage = FakeReleaseStorage()
    content = b"exact-boundary"
    service = build_service(db_session, storage)

    result = upload(
        service,
        product,
        content=content,
        filename="customer archive.zip",
        max_bytes=len(content),
    )

    assert result.created is True
    assert len(storage.uploaded) == 1
    observed = storage.uploaded[0]
    assert observed["storage_key"] == (f"product-releases/{product.id}/1.0/{'a' * 32}")
    assert "customer archive.zip" not in str(observed["storage_key"])
    assert observed["file_size"] == len(content)
    assert observed["sha256_hash"] == hashlib.sha256(content).hexdigest()
    assert observed["position"] == 0
    assert observed["content"] == content

    db_session.expire_all()
    release = db_session.query(ProductRelease).one()
    assert release.original_filename == "customer archive.zip"
    assert release.release_notes == "Release notes"
    assert release.is_active is False


def test_storage_keys_are_unique_per_attempt(db_session):
    first_product = create_test_product(db_session)
    second_product = Product(
        family_slug="smartbudget",
        slug="smartbudget-test-second",
        name="SmartBudget Second",
        archive_path="legacy/second.zip",
        edition="Standard",
        status="in_sale",
    )
    db_session.add(second_product)
    db_session.commit()
    storage = FakeReleaseStorage()

    upload(build_service(db_session, storage, token="a" * 32), first_product)
    upload(build_service(db_session, storage, token="b" * 32), second_product)

    keys = [str(item["storage_key"]) for item in storage.uploaded]
    assert len(set(keys)) == 2
    assert all(key.startswith("product-releases/") for key in keys)


def test_oversize_is_rejected_before_storage_and_database(db_session):
    product = create_test_product(db_session)
    initialized = False

    def storage_factory():
        nonlocal initialized
        initialized = True
        return FakeReleaseStorage()

    service = ProductReleaseService(db_session, storage_factory=storage_factory)

    with pytest.raises(ReleaseArchiveTooLargeError):
        upload(service, product, content=b"12345", max_bytes=4)

    assert initialized is False
    assert db_session.query(ProductRelease).count() == 0


@pytest.mark.parametrize("ambiguous", [False, True])
def test_upload_failure_compensates_and_creates_no_row(
    db_session,
    ambiguous,
) -> None:
    product = create_test_product(db_session)
    storage = FakeReleaseStorage()
    storage.upload_error = RuntimeError("provider detail")
    storage.upload_error_after_store = ambiguous
    service = build_service(db_session, storage)

    with pytest.raises(ReleaseStorageUnavailableError):
        upload(service, product)

    assert storage.deleted == [f"product-releases/{product.id}/1.0/{'a' * 32}"]
    assert db_session.query(ProductRelease).count() == 0


def test_head_mismatch_compensates_and_creates_no_row(db_session):
    product = create_test_product(db_session)
    storage = FakeReleaseStorage()
    storage.verification_override = False
    service = build_service(db_session, storage)

    with pytest.raises(ReleaseStorageUnavailableError):
        upload(service, product)

    assert len(storage.deleted) == 1
    assert db_session.query(ProductRelease).count() == 0


def test_database_flush_failure_rolls_back_and_deletes_attempt_object(
    db_session,
    monkeypatch,
) -> None:
    product = create_test_product(db_session)
    storage = FakeReleaseStorage()
    service = build_service(db_session, storage)

    def fail_create(release):
        raise RuntimeError("database detail")

    monkeypatch.setattr(service.product_release_repository, "create", fail_create)

    with pytest.raises(ReleasePersistenceError):
        upload(service, product)

    assert len(storage.deleted) == 1
    assert db_session.query(ProductRelease).count() == 0


def test_compensation_never_deletes_database_owned_object(
    db_session,
    caplog,
) -> None:
    product = create_test_product(db_session)
    storage_key = f"product-releases/{product.id}/1.0/{'a' * 32}"
    owned_release = ProductRelease(
        product_id=product.id,
        version="2.0",
        release_notes=None,
        storage_provider="cloudflare_r2",
        storage_key=storage_key,
        original_filename="owned.zip",
        file_size=5,
        sha256_hash=hashlib.sha256(b"owned").hexdigest(),
        is_active=False,
    )
    db_session.add(owned_release)
    db_session.commit()

    storage = FakeReleaseStorage()
    storage.upload_error = RuntimeError("provider detail")
    service = build_service(db_session, storage)

    with caplog.at_level("INFO"), pytest.raises(ReleaseReconciliationRequiredError):
        upload(service, product)

    assert storage.deleted == []
    assert any(
        record.outcome == "ownership_preserved"
        for record in caplog.records
        if record.name == "app.services.product_release_service"
    )
    assert (
        db_session.query(ProductRelease)
        .filter(ProductRelease.storage_key == storage_key)
        .one()
        .id
        == owned_release.id
    )


def test_compensation_with_unknown_ownership_never_deletes(db_session) -> None:
    product = create_test_product(db_session)
    storage = FakeReleaseStorage()
    storage.verification_override = False
    service = build_service(
        db_session,
        storage,
        ownership_session_factory=lambda: (_ for _ in ()).throw(
            RuntimeError("database unavailable")
        ),
    )

    with pytest.raises(ReleaseReconciliationRequiredError):
        upload(service, product)

    assert storage.deleted == []


def test_compensation_with_proven_nonownership_deletes(db_session) -> None:
    product = create_test_product(db_session)
    storage = FakeReleaseStorage()
    storage.verification_override = False
    service = build_service(db_session, storage)

    with pytest.raises(ReleaseStorageUnavailableError):
        upload(service, product)

    assert storage.deleted == [f"product-releases/{product.id}/1.0/{'a' * 32}"]


def test_commit_failure_with_unavailable_ownership_check_does_not_delete(
    db_session,
    monkeypatch,
) -> None:
    product = create_test_product(db_session)
    storage = FakeReleaseStorage()
    service = build_service(
        db_session,
        storage,
        ownership_session_factory=lambda: (_ for _ in ()).throw(
            RuntimeError("database unavailable")
        ),
    )
    monkeypatch.setattr(
        db_session,
        "commit",
        lambda: (_ for _ in ()).throw(RuntimeError("commit failed")),
    )

    with pytest.raises(ReleaseReconciliationRequiredError):
        upload(service, product)

    assert storage.deleted == []


def test_commit_exception_confirms_committed_ownership_without_delete(
    db_session,
    monkeypatch,
) -> None:
    product = create_test_product(db_session)
    storage = FakeReleaseStorage()
    service = build_service(db_session, storage)
    real_commit = db_session.commit

    def commit_then_raise():
        real_commit()
        raise RuntimeError("response lost after commit")

    monkeypatch.setattr(db_session, "commit", commit_then_raise)

    result = upload(service, product)

    assert result.created is True
    assert storage.deleted == []
    assert db_session.query(ProductRelease).count() == 1


def test_commit_failure_with_proven_nonownership_compensates(
    db_session,
    monkeypatch,
) -> None:
    product = create_test_product(db_session)
    storage = FakeReleaseStorage()
    service = build_service(db_session, storage)
    monkeypatch.setattr(
        db_session,
        "commit",
        lambda: (_ for _ in ()).throw(RuntimeError("commit failed")),
    )

    with pytest.raises(ReleasePersistenceError):
        upload(service, product)

    assert len(storage.deleted) == 1


def test_compensation_failure_preserves_reconciliation_outcome(db_session):
    product = create_test_product(db_session)
    storage = FakeReleaseStorage()
    storage.verification_override = False
    storage.delete_error = RuntimeError("delete provider detail")
    service = build_service(
        db_session,
        storage,
        operation_id="safe-operation-id",
    )

    with pytest.raises(ReleaseReconciliationRequiredError) as exc_info:
        upload(service, product)

    assert exc_info.value.operation_id == "safe-operation-id"
    assert db_session.query(ProductRelease).count() == 0


def test_release_workflow_logs_only_safe_storage_metadata(db_session, caplog):
    product = create_test_product(db_session)
    storage = FakeReleaseStorage()
    storage.upload_error = RuntimeError("provider secret detail")
    service = build_service(
        db_session,
        storage,
        operation_id="safe-operation-id",
    )

    with caplog.at_level("INFO"), pytest.raises(ReleaseStorageUnavailableError):
        upload(
            service,
            product,
            filename="private-customer-name.zip",
        )

    rendered = "\n".join(record.getMessage() for record in caplog.records)
    assert "provider secret detail" not in rendered
    assert "private-customer-name.zip" not in rendered
    assert f"product-releases/{product.id}" not in rendered
    record = next(
        record
        for record in caplog.records
        if record.name == "app.services.product_release_service"
    )
    assert record.operation_id == "safe-operation-id"
    assert record.product_id == product.id
    assert len(record.storage_key_digest) == 64


def create_existing_release(
    db_session,
    product: Product,
    storage: FakeReleaseStorage,
    *,
    content: bytes = b"release-content",
    filename: str = "release.zip",
    notes: str | None = "Release notes",
) -> ProductRelease:
    storage_key = f"historical/{product.id}/1.0/release.zip"
    digest = hashlib.sha256(content).hexdigest()
    release = ProductRelease(
        product_id=product.id,
        version="1.0",
        release_notes=notes,
        storage_provider="cloudflare_r2",
        storage_key=storage_key,
        original_filename=filename,
        file_size=len(content),
        sha256_hash=digest,
        is_active=False,
    )
    db_session.add(release)
    db_session.commit()
    db_session.refresh(release)
    storage.objects[storage_key] = (len(content), digest)
    return release


def test_identical_committed_retry_returns_existing_without_upload_or_delete(
    db_session,
) -> None:
    product = create_test_product(db_session)
    storage = FakeReleaseStorage()
    existing = create_existing_release(db_session, product, storage)
    service = build_service(db_session, storage)

    result = upload(service, product)

    assert result == type(result)(release_id=existing.id, created=False)
    assert storage.uploaded == []
    assert storage.deleted == []


@pytest.mark.parametrize(
    ("content", "filename", "notes"),
    [
        (b"different-content", "release.zip", " Release notes "),
        (b"release-content", "different.zip", " Release notes "),
        (b"release-content", "release.zip", "Different notes"),
    ],
)
def test_existing_material_difference_conflicts_without_storage_mutation(
    db_session,
    content,
    filename,
    notes,
) -> None:
    product = create_test_product(db_session)
    storage = FakeReleaseStorage()
    create_existing_release(db_session, product, storage)
    service = build_service(db_session, storage)

    with pytest.raises(ReleaseConflictError):
        upload(
            service,
            product,
            content=content,
            filename=filename,
            notes=notes,
        )

    assert storage.uploaded == []
    assert storage.deleted == []


@pytest.mark.parametrize("same_content", [True, False])
def test_concurrent_duplicate_race_deletes_only_losing_object(
    db_session,
    monkeypatch,
    same_content,
) -> None:
    product = create_test_product(db_session)
    storage = FakeReleaseStorage()
    winner_content = b"release-content" if same_content else b"winner-content"
    winner = create_existing_release(
        db_session,
        product,
        storage,
        content=winner_content,
    )
    service = build_service(db_session, storage)
    lookup_count = 0

    def simulated_lookup(product_id, version):
        nonlocal lookup_count
        lookup_count += 1
        return None if lookup_count == 1 else winner

    monkeypatch.setattr(
        service.product_release_repository,
        "get_by_product_id_and_version",
        simulated_lookup,
    )
    monkeypatch.setattr(
        service.product_release_repository,
        "create",
        lambda release: (_ for _ in ()).throw(
            IntegrityError("insert", {}, RuntimeError("duplicate"))
        ),
    )

    if same_content:
        result = upload(service, product)
        assert result.release_id == winner.id
        assert result.created is False
    else:
        with pytest.raises(ReleaseConflictError):
            upload(service, product)

    assert storage.deleted == [f"product-releases/{product.id}/1.0/{'a' * 32}"]
    assert winner.storage_key not in storage.deleted


def test_publish_release_verifies_object_and_deactivates_previous(db_session):
    product = create_test_product(db_session)
    storage = FakeReleaseStorage()
    old_release = create_existing_release(db_session, product, storage)
    old_release.is_active = True
    new_content = b"new-release"
    new_digest = hashlib.sha256(new_content).hexdigest()
    new_release = ProductRelease(
        product_id=product.id,
        version="1.1",
        storage_provider="cloudflare_r2",
        storage_key="historical/new-release.zip",
        original_filename="new-release.zip",
        file_size=len(new_content),
        sha256_hash=new_digest,
        is_active=False,
    )
    db_session.add(new_release)
    db_session.flush()
    new_release_id = new_release.id
    new_release_storage_key = new_release.storage_key
    db_session.commit()
    storage.objects[new_release_storage_key] = (len(new_content), new_digest)
    service = build_service(db_session, storage)

    published = service.publish_release(new_release_id)

    assert published.id == new_release_id
    assert new_release.is_active is True
    assert old_release.is_active is False
    assert new_release.released_at is not None
    db_session.close()
    persisted = db_session.get(ProductRelease, new_release_id)
    assert persisted is not None
    assert persisted.is_active is True


@pytest.mark.parametrize("storage_state", ["missing", "size_mismatch", "sha_mismatch"])
def test_publish_release_rejects_missing_or_mismatched_object(
    db_session,
    storage_state,
) -> None:
    product = create_test_product(db_session)
    storage = FakeReleaseStorage()
    release = create_existing_release(db_session, product, storage)
    release_id = release.id
    release_storage_key = release.storage_key
    release_file_size = release.file_size
    release_sha256_hash = release.sha256_hash
    if storage_state == "missing":
        storage.objects.clear()
    elif storage_state == "size_mismatch":
        storage.objects[release_storage_key] = (
            release_file_size + 1,
            release_sha256_hash,
        )
    else:
        storage.objects[release_storage_key] = (
            release_file_size,
            "b" * 64,
        )
    db_session.commit()
    service = build_service(
        db_session,
        storage,
        operation_id="publish-operation",
    )

    with pytest.raises(ReleaseReconciliationRequiredError):
        service.publish_release(release_id)

    db_session.expire_all()
    persisted = db_session.get(ProductRelease, release_id)
    assert persisted is not None
    assert persisted.is_active is False


def test_republishing_active_release_is_idempotent_and_preserves_timestamp(db_session):
    product = create_test_product(db_session)
    storage = FakeReleaseStorage()
    release = create_existing_release(db_session, product, storage)
    original_released_at = datetime(2026, 7, 1, tzinfo=UTC)
    release.is_active = True
    release.released_at = original_released_at
    release_id = release.id
    db_session.commit()

    published = build_service(db_session, storage).publish_release(release_id)

    assert published.id == release_id
    assert published.is_active is True
    assert published.released_at.replace(tzinfo=UTC) == original_released_at
    assert len(storage.verification_calls) == 1


def test_publish_rejects_release_from_different_product_before_storage(db_session):
    product = create_test_product(db_session)
    other_product = Product(
        family_slug="smartbudget",
        slug="smartbudget-test-other",
        name="SmartBudget",
        archive_path="legacy/path.zip",
        edition="Pro",
        status="in_sale",
    )
    db_session.add(other_product)
    db_session.flush()
    other_product_id = other_product.id
    db_session.commit()
    storage = FakeReleaseStorage()
    release = create_existing_release(db_session, product, storage)
    release_id = release.id
    db_session.commit()

    with pytest.raises(ReleaseNotFoundError):
        build_service(db_session, storage).publish_release(
            release_id,
            product_id=other_product_id,
        )

    assert storage.verification_calls == []


def test_database_rejects_two_active_releases_for_same_product(db_session):
    product = create_test_product(db_session)
    releases = [
        ProductRelease(
            product_id=product.id,
            version=version,
            storage_provider="cloudflare_r2",
            storage_key=f"historical/{version}.zip",
            original_filename=f"SmartBudget_v{version}.zip",
            file_size=10,
            sha256_hash="a" * 64,
            is_active=True,
        )
        for version in ("1.0", "1.1")
    ]
    db_session.add_all(releases)

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_publish_release_raises_not_found_for_unknown_release(db_session):
    service = build_service(db_session, FakeReleaseStorage())

    with pytest.raises(ReleaseNotFoundError):
        service.publish_release(999999)
