import re

from sqlalchemy.orm import Session
from datetime import UTC, datetime
from fastapi import HTTPException, status

from app.models.product_release import ProductRelease

from app.repositories.product_release_repository import ProductReleaseRepository


RELEASE_VERSION_PATTERN = re.compile(r"^\d+\.\d+$")


class ProductReleaseService:
    """
    Business logic for product release lifecycle.
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self.product_release_repository = ProductReleaseRepository(db)

    def publish_release(self, release_id: int) -> ProductRelease:
        release = self.product_release_repository.get_by_id(release_id)

        if release is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Product release not found.",
            )

        releases = self.product_release_repository.list_by_product_id(release.product_id)

        now = datetime.now(UTC)

        for product_release in releases:
            product_release.is_active = product_release.id == release.id

            if product_release.id == release.id and product_release.released_at is None:
                product_release.released_at = now

        self.db.flush()

        return release

    def create_release(
        self,
        *,
        product_id: int,
        version: str,
        storage_provider: str,
        storage_key: str,
        original_filename: str,
        release_notes: str | None = None,
        file_size: int | None = None,
        sha256_hash: str | None = None,
    ) -> ProductRelease:

        normalized_version = version.strip()

        if not RELEASE_VERSION_PATTERN.fullmatch(normalized_version):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Release version must use format like 1.0 or 1.1.",
            )

        release = ProductRelease(
            product_id=product_id,
            version=normalized_version,
            release_notes=release_notes,
            storage_provider=storage_provider,
            storage_key=storage_key,
            original_filename=original_filename,
            file_size=file_size,
            sha256_hash=sha256_hash,
            is_active=False,
        )

        return self.product_release_repository.create(release)

    def list_releases_by_product_id(
            self,
            product_id: int,
    ) -> list[ProductRelease]:
        """Return all releases belonging to a product."""

        return self.product_release_repository.list_by_product_id(product_id)