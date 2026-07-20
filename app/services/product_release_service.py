import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import BinaryIO

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.product_release import ProductRelease
from app.repositories.product_release_repository import ProductReleaseRepository

RELEASE_VERSION_PATTERN = re.compile(r"^\d+\.\d+$")
RELEASE_ARCHIVE_INSPECTION_CHUNK_SIZE = 1024 * 1024


class ReleaseArchiveTooLargeError(Exception):
    """Raised when a product release archive exceeds its configured limit."""


@dataclass(frozen=True)
class ReleaseArchiveMetadata:
    file_size: int
    sha256_hash: str


def inspect_release_archive(
    file_obj: BinaryIO,
    *,
    max_bytes: int,
) -> ReleaseArchiveMetadata:
    """Calculate bounded release archive metadata and rewind the input stream."""
    if max_bytes <= 0:
        raise ValueError("max_bytes must be greater than zero")

    sha256 = hashlib.sha256()
    file_size = 0

    file_obj.seek(0)

    try:
        while True:
            remaining_with_overflow_byte = max_bytes - file_size + 1
            read_size = min(
                RELEASE_ARCHIVE_INSPECTION_CHUNK_SIZE,
                remaining_with_overflow_byte,
            )
            chunk = file_obj.read(read_size)

            if not chunk:
                break

            file_size += len(chunk)

            if file_size > max_bytes:
                raise ReleaseArchiveTooLargeError

            sha256.update(chunk)

        return ReleaseArchiveMetadata(
            file_size=file_size,
            sha256_hash=sha256.hexdigest(),
        )
    finally:
        file_obj.seek(0)


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

        releases = self.product_release_repository.list_by_product_id(
            release.product_id
        )

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
