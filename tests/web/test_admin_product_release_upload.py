from __future__ import annotations

import hashlib
from typing import BinaryIO

from botocore.exceptions import ClientError
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
) -> Response:
    return auth_client.post(
        f"/products/{product_id}/releases/new",
        data={"version": "1.0", "release_notes": "Release notes"},
        files={"release_file": ("release.zip", content, "application/zip")},
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

    monkeypatch.setattr("app.web.routes.R2StorageService", UnexpectedStorage)

    response = post_release(
        auth_client,
        product_id=product.id,
        content=b"123456789",
    )

    assert response.status_code == 413
    assert response.json() == {"detail": "Release archive exceeds the 8 bytes limit."}
    db_session.expire_all()
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

    monkeypatch.setattr("app.web.routes.inspect_release_archive", reject_archive)
    monkeypatch.setattr("app.web.routes.R2StorageService", UnexpectedStorage)

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
        def upload_product_release_file(
            self,
            *,
            product_slug: str,
            version: str,
            filename: str,
            file_obj: BinaryIO,
        ) -> UploadedObject:
            upload_observation.update(
                {
                    "product_slug": product_slug,
                    "version": version,
                    "filename": filename,
                    "position": file_obj.tell(),
                    "rolled": getattr(file_obj, "_rolled", False),
                    "content": file_obj.read(),
                }
            )
            return UploadedObject(
                storage_provider="cloudflare_r2",
                storage_key="product-releases/test/1.0/release.zip",
            )

    monkeypatch.setattr("app.web.routes.R2StorageService", RecordingStorage)

    response = post_release(
        auth_client,
        product_id=product.id,
        content=content,
    )

    assert response.status_code == 303
    assert response.headers["location"] == f"/products/{product.id}/releases"
    assert upload_observation == {
        "product_slug": product.slug,
        "version": "1.0",
        "filename": "release.zip",
        "position": 0,
        "rolled": True,
        "content": content,
    }
    db_session.expire_all()
    release = db_session.query(ProductRelease).one()
    assert release.file_size == len(content)
    assert release.sha256_hash == hashlib.sha256(content).hexdigest()


def test_storage_failure_preserves_existing_redirect_contract(
    auth_client,
    db_session,
    monkeypatch,
) -> None:
    product = create_product(db_session)

    class FailingStorage:
        def upload_product_release_file(self, **kwargs) -> UploadedObject:
            raise ClientError(
                {"Error": {"Code": "ServiceUnavailable", "Message": "failed"}},
                "PutObject",
            )

    monkeypatch.setattr("app.web.routes.R2StorageService", FailingStorage)

    response = post_release(
        auth_client,
        product_id=product.id,
        content=b"valid release",
    )

    assert response.status_code == 303
    assert response.headers["location"] == (
        f"/products/{product.id}/releases/new?error=r2_upload_failed"
    )
    db_session.expire_all()
    assert db_session.query(ProductRelease).count() == 0
