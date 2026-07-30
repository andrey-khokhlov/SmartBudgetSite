from __future__ import annotations

import hashlib

from app.models.product import Product
from app.models.product_release import ProductRelease


class PublicationStorage:
    storage_provider = "cloudflare_r2"

    def __init__(self) -> None:
        self.objects: dict[str, tuple[int, str]] = {}
        self.verification_calls: list[str] = []

    def verify_product_release_object(
        self,
        *,
        storage_key: str,
        expected_file_size: int,
        expected_sha256_hash: str,
    ) -> bool:
        self.verification_calls.append(storage_key)
        return self.objects.get(storage_key) == (
            expected_file_size,
            expected_sha256_hash,
        )


def create_publication_candidates(db_session, storage: PublicationStorage):
    product = Product(
        family_slug="smartbudget",
        slug="smartbudget-publication-standard",
        name="SmartBudget",
        archive_path="legacy/path.zip",
        edition="Standard",
        status="in_sale",
    )
    db_session.add(product)
    db_session.flush()

    releases = []
    for version, content, active in (
        ("1.0", b"old release", True),
        ("1.1", b"new release", False),
    ):
        digest = hashlib.sha256(content).hexdigest()
        release = ProductRelease(
            product_id=product.id,
            version=version,
            storage_provider="cloudflare_r2",
            storage_key=f"private/{version}/sensitive-object-key",
            original_filename=f"SmartBudget-{version}.zip",
            file_size=len(content),
            sha256_hash=digest,
            is_active=active,
        )
        db_session.add(release)
        releases.append(release)
        storage.objects[release.storage_key] = (len(content), digest)

    db_session.commit()
    return product, releases[0], releases[1]


def test_admin_publication_control_publishes_release_and_redirects(
    auth_client,
    db_session,
    monkeypatch,
) -> None:
    storage = PublicationStorage()
    product, old_release, selected_release = create_publication_candidates(
        db_session,
        storage,
    )
    monkeypatch.setattr(
        "app.services.product_release_service.R2StorageService",
        lambda: storage,
    )

    page = auth_client.get(f"/products/{product.id}/releases")
    response = auth_client.post(
        f"/products/{product.id}/releases/{selected_release.id}/publish",
        follow_redirects=False,
    )

    assert page.status_code == 200
    assert (
        f'action="/products/{product.id}/releases/{selected_release.id}/publish"'
        in page.text
    )
    assert response.status_code == 303
    assert response.headers["location"] == (
        f"/products/{product.id}/releases?published=1"
    )
    success_page = auth_client.get(response.headers["location"])
    assert success_page.status_code == 200
    assert "Release published successfully." in success_page.text
    db_session.expire_all()
    assert db_session.get(ProductRelease, old_release.id).is_active is False
    persisted = db_session.get(ProductRelease, selected_release.id)
    assert persisted.is_active is True
    assert persisted.released_at is not None
    assert storage.verification_calls == [selected_release.storage_key]


def test_admin_publication_verification_failure_is_safe_and_atomic(
    auth_client,
    db_session,
    monkeypatch,
) -> None:
    storage = PublicationStorage()
    product, old_release, selected_release = create_publication_candidates(
        db_session,
        storage,
    )
    storage.objects[selected_release.storage_key] = (
        selected_release.file_size,
        "f" * 64,
    )
    monkeypatch.setattr(
        "app.services.product_release_service.R2StorageService",
        lambda: storage,
    )

    response = auth_client.post(
        f"/products/{product.id}/releases/{selected_release.id}/publish",
    )

    assert response.status_code == 409
    assert "stored release could not be verified" in response.text
    assert selected_release.storage_key not in response.text
    assert selected_release.sha256_hash not in response.text
    db_session.expire_all()
    assert db_session.get(ProductRelease, old_release.id).is_active is True
    persisted = db_session.get(ProductRelease, selected_release.id)
    assert persisted.is_active is False
    assert persisted.released_at is None


def test_admin_publication_storage_failure_returns_safe_error(
    auth_client,
    db_session,
    monkeypatch,
) -> None:
    storage = PublicationStorage()
    product, old_release, selected_release = create_publication_candidates(
        db_session,
        storage,
    )

    class UnavailableStorage:
        def __init__(self) -> None:
            raise RuntimeError("provider credential secret")

    monkeypatch.setattr(
        "app.services.product_release_service.R2StorageService",
        UnavailableStorage,
    )

    response = auth_client.post(
        f"/products/{product.id}/releases/{selected_release.id}/publish",
    )

    assert response.status_code == 503
    assert "storage is temporarily unavailable" in response.text
    assert "provider credential secret" not in response.text
    db_session.expire_all()
    assert db_session.get(ProductRelease, old_release.id).is_active is True
    assert db_session.get(ProductRelease, selected_release.id).is_active is False


def test_admin_publication_unknown_release_returns_404(
    auth_client,
    db_session,
) -> None:
    storage = PublicationStorage()
    product, _, _ = create_publication_candidates(db_session, storage)

    response = auth_client.post(
        f"/products/{product.id}/releases/999999/publish",
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Product release not found"}
