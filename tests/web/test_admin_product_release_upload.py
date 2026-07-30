from __future__ import annotations

import hashlib
from typing import BinaryIO

from fastapi.testclient import TestClient
from httpx import Response

from app.core.config import settings
from app.models.product import Product
from app.models.product_release import ProductRelease
from app.services.product_release_service import ReleaseArchiveTooLargeError
from app.services.storage.r2_storage_service import UploadedObject


def create_product(db_session) -> Product:
    product = Product(
        family_slug="smartbudget",
        slug="smartbudget-upload-test-standard",
        name="SmartBudget",
        archive_path="legacy/path.zip",
        edition="Standard",
        status="in_sale",
    )
    db_session.add(product)
    db_session.commit()
    db_session.refresh(product)
    return product


def post_release(
    auth_client: TestClient,
    *,
    product_id: int,
    content: bytes,
    version: str = "1.0",
    filename: str = "release.zip",
    release_notes: str = "Release notes",
) -> Response:
    return auth_client.post(
        f"/products/{product_id}/releases/new",
        data={"version": version, "release_notes": release_notes},
        files={"release_file": (filename, content, "application/zip")},
        follow_redirects=False,
    )


def test_oversized_release_is_rejected_before_storage_or_persistence(
    auth_client,
    db_session,
    monkeypatch,
) -> None:
    product = create_product(db_session)
    monkeypatch.setattr(settings, "PRODUCT_RELEASE_MAX_UPLOAD_BYTES", 8)

    class UnexpectedStorage:
        def __init__(self) -> None:
            raise AssertionError("R2 storage must not be initialized")

    monkeypatch.setattr(
        "app.services.product_release_service.R2StorageService",
        UnexpectedStorage,
    )

    response = post_release(
        auth_client,
        product_id=product.id,
        content=b"123456789",
    )

    assert response.status_code == 413
    assert response.json() == {"detail": "Release archive exceeds the 8 bytes limit."}
    db_session.expire_all()
    assert db_session.query(ProductRelease).count() == 0


def test_invalid_version_returns_400_without_storage_initialization(
    auth_client,
    db_session,
    monkeypatch,
) -> None:
    product = create_product(db_session)

    class UnexpectedStorage:
        def __init__(self) -> None:
            raise AssertionError("R2 storage must not be initialized")

    monkeypatch.setattr(
        "app.services.product_release_service.R2StorageService",
        UnexpectedStorage,
    )

    response = post_release(
        auth_client,
        product_id=product.id,
        content=b"valid release",
        version="../invalid",
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": "Release version must use format like 1.0 or 1.1."
    }
    assert db_session.query(ProductRelease).count() == 0


def test_default_release_limit_preserves_50_mib_error_contract(
    auth_client,
    db_session,
    monkeypatch,
) -> None:
    product = create_product(db_session)
    monkeypatch.setattr(
        settings,
        "PRODUCT_RELEASE_MAX_UPLOAD_BYTES",
        52_428_800,
    )

    def reject_archive(*args, **kwargs):
        raise ReleaseArchiveTooLargeError

    class UnexpectedStorage:
        def __init__(self) -> None:
            raise AssertionError("R2 storage must not be initialized")

    monkeypatch.setattr(
        "app.services.product_release_service.inspect_release_archive",
        reject_archive,
    )
    monkeypatch.setattr(
        "app.services.product_release_service.R2StorageService",
        UnexpectedStorage,
    )

    response = post_release(
        auth_client,
        product_id=product.id,
        content=b"oversized without allocating 50 MiB",
    )

    assert response.status_code == 413
    assert response.json() == {"detail": "Release archive exceeds the 50 MiB limit."}
    db_session.expire_all()
    assert db_session.query(ProductRelease).count() == 0


def test_exact_boundary_disk_spooled_release_uploads_and_persists_metadata(
    auth_client,
    db_session,
    monkeypatch,
) -> None:
    product = create_product(db_session)
    content = b"a" * (1024 * 1024 + 1)
    monkeypatch.setattr(
        settings,
        "PRODUCT_RELEASE_MAX_UPLOAD_BYTES",
        len(content),
    )
    upload_observation: dict[str, object] = {}

    class RecordingStorage:
        storage_provider = "cloudflare_r2"

        def upload_product_release_file(
            self,
            *,
            storage_key: str,
            file_obj: BinaryIO,
            file_size: int,
            sha256_hash: str,
        ) -> UploadedObject:
            upload_observation.update(
                {
                    "storage_key": storage_key,
                    "file_size": file_size,
                    "sha256_hash": sha256_hash,
                    "position": file_obj.tell(),
                    "rolled": getattr(file_obj, "_rolled", False),
                    "content": file_obj.read(),
                }
            )
            return UploadedObject(
                storage_provider="cloudflare_r2",
                storage_key=storage_key,
            )

        def verify_product_release_object(self, **kwargs) -> bool:
            return True

        def delete_product_release_object(self, **kwargs) -> None:
            raise AssertionError("Successful upload must not be deleted")

    monkeypatch.setattr(
        "app.services.product_release_service.R2StorageService",
        RecordingStorage,
    )

    response = post_release(
        auth_client,
        product_id=product.id,
        content=content,
    )

    assert response.status_code == 303
    assert response.headers["location"] == f"/products/{product.id}/releases"
    assert str(upload_observation["storage_key"]).startswith(
        f"product-releases/{product.id}/1.0/"
    )
    assert "release.zip" not in str(upload_observation["storage_key"])
    assert upload_observation["file_size"] == len(content)
    assert upload_observation["sha256_hash"] == hashlib.sha256(content).hexdigest()
    assert upload_observation["position"] == 0
    assert upload_observation["rolled"] is True
    assert upload_observation["content"] == content
    db_session.expire_all()
    release = db_session.query(ProductRelease).one()
    assert release.file_size == len(content)
    assert release.sha256_hash == hashlib.sha256(content).hexdigest()


def test_storage_failure_returns_safe_503_and_creates_no_row(
    auth_client,
    db_session,
    monkeypatch,
) -> None:
    product = create_product(db_session)

    class FailingStorage:
        storage_provider = "cloudflare_r2"

        def upload_product_release_file(self, **kwargs) -> UploadedObject:
            raise RuntimeError("provider secret detail")

        def delete_product_release_object(self, **kwargs) -> None:
            return None

    monkeypatch.setattr(
        "app.services.product_release_service.R2StorageService",
        FailingStorage,
    )

    response = post_release(
        auth_client,
        product_id=product.id,
        content=b"valid release",
    )

    assert response.status_code == 503
    assert "Release storage is temporarily unavailable" in response.text
    assert "provider secret detail" not in response.text
    db_session.expire_all()
    assert db_session.query(ProductRelease).count() == 0


def test_duplicate_version_with_different_content_returns_rendered_409(
    auth_client,
    db_session,
    monkeypatch,
) -> None:
    product = create_product(db_session)

    class WorkingStorage:
        storage_provider = "cloudflare_r2"
        objects: dict[str, tuple[int, str]] = {}

        def upload_product_release_file(
            self,
            *,
            storage_key,
            file_obj,
            file_size,
            sha256_hash,
        ) -> UploadedObject:
            self.objects[storage_key] = (file_size, sha256_hash)
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
            return self.objects.get(storage_key) == (
                expected_file_size,
                expected_sha256_hash,
            )

        def delete_product_release_object(self, **kwargs) -> None:
            raise AssertionError("Owned objects must not be deleted")

    monkeypatch.setattr(
        "app.services.product_release_service.R2StorageService",
        WorkingStorage,
    )

    first_response = post_release(
        auth_client,
        product_id=product.id,
        content=b"first release",
    )
    conflict_response = post_release(
        auth_client,
        product_id=product.id,
        content=b"different release",
    )

    assert first_response.status_code == 303
    assert conflict_response.status_code == 409
    assert "already exists with different release details" in conflict_response.text
    assert db_session.query(ProductRelease).count() == 1


def test_cleanup_failure_returns_safe_reconciliation_response(
    auth_client,
    db_session,
    monkeypatch,
) -> None:
    product = create_product(db_session)

    class CleanupFailingStorage:
        storage_provider = "cloudflare_r2"

        def upload_product_release_file(self, **kwargs) -> UploadedObject:
            raise RuntimeError("raw upload provider detail")

        def delete_product_release_object(self, **kwargs) -> None:
            raise RuntimeError("raw delete provider detail")

    monkeypatch.setattr(
        "app.services.product_release_service.R2StorageService",
        CleanupFailingStorage,
    )

    response = post_release(
        auth_client,
        product_id=product.id,
        content=b"valid release",
        filename="private-customer-name.zip",
    )

    assert response.status_code == 500
    assert "run release reconciliation before retrying" in response.text
    assert "Operation reference:" in response.text
    assert "raw upload provider detail" not in response.text
    assert "raw delete provider detail" not in response.text
    assert "private-customer-name.zip" not in response.text
    assert db_session.query(ProductRelease).count() == 0
