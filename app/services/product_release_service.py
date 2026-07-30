from __future__ import annotations

import hashlib
import logging
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import BinaryIO, Protocol
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.models.product import Product
from app.models.product_release import ProductRelease
from app.repositories.product_release_repository import ProductReleaseRepository
from app.services.storage.r2_storage_service import (
    R2StorageService,
    UploadedObject,
    build_product_release_storage_key,
)

RELEASE_VERSION_PATTERN = re.compile(r"^\d+\.\d+$")
RELEASE_ARCHIVE_INSPECTION_CHUNK_SIZE = 1024 * 1024

logger = logging.getLogger(__name__)


class ReleaseArchiveTooLargeError(Exception):
    """Raised when a product release archive exceeds its configured limit."""


class ReleaseUploadValidationError(Exception):
    """Raised before storage access when release input is invalid."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class ReleaseProductNotFoundError(Exception):
    """Raised when an upload targets an unknown product."""


class ReleaseConflictError(Exception):
    """Raised when one product/version identity has different material input."""


class ReleaseStorageUnavailableError(Exception):
    """Raised when R2 cannot complete or verify an upload safely."""


class ReleasePersistenceError(Exception):
    """Raised when persistence fails after successful storage compensation."""


class ReleaseReconciliationRequiredError(Exception):
    """Raised when the upload outcome requires explicit reconciliation."""

    def __init__(self, operation_id: str) -> None:
        super().__init__("Product release reconciliation is required.")
        self.operation_id = operation_id


class ReleaseNotFoundError(Exception):
    """Raised when a publication target does not exist."""


class ReleasePublicationConflictError(Exception):
    """Raised when publication cannot preserve the active-release invariant."""


@dataclass(frozen=True)
class ReleaseArchiveMetadata:
    file_size: int
    sha256_hash: str


@dataclass(frozen=True)
class ReleaseUploadResult:
    release_id: int
    created: bool


class ReleaseStorage(Protocol):
    storage_provider: str

    def upload_product_release_file(
        self,
        *,
        storage_key: str,
        file_obj: BinaryIO,
        file_size: int,
        sha256_hash: str,
    ) -> UploadedObject: ...

    def verify_product_release_object(
        self,
        *,
        storage_key: str,
        expected_file_size: int,
        expected_sha256_hash: str,
    ) -> bool: ...

    def delete_product_release_object(self, *, storage_key: str) -> None: ...


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


def normalize_release_version(version: str) -> str:
    normalized_version = version.strip()
    if not RELEASE_VERSION_PATTERN.fullmatch(normalized_version):
        raise ReleaseUploadValidationError(
            "Release version must use format like 1.0 or 1.1."
        )
    return normalized_version


def normalize_release_filename(filename: str | None) -> str:
    normalized_filename = (filename or "").strip()
    if (
        not normalized_filename
        or len(normalized_filename) > 255
        or normalized_filename in {".", ".."}
        or "/" in normalized_filename
        or "\\" in normalized_filename
        or any(
            unicodedata.category(character).startswith("C")
            for character in normalized_filename
        )
    ):
        raise ReleaseUploadValidationError("Release filename is invalid.")
    return normalized_filename


def normalize_release_notes(release_notes: str) -> str | None:
    return release_notes.strip() or None


class ProductReleaseService:
    """Own product-release validation, storage, persistence, and compensation."""

    def __init__(
        self,
        db: Session,
        *,
        storage_factory: Callable[[], ReleaseStorage] | None = None,
        ownership_session_factory: Callable[[], Session] | None = None,
        storage_token_factory: Callable[[], str] = lambda: uuid4().hex,
        operation_id_factory: Callable[[], str] = lambda: uuid4().hex,
    ) -> None:
        self.db = db
        self.product_release_repository = ProductReleaseRepository(db)
        self._storage_factory = storage_factory or R2StorageService
        self._ownership_session_factory = ownership_session_factory or sessionmaker(
            bind=db.get_bind(),
            autocommit=False,
            autoflush=False,
        )
        self._storage_token_factory = storage_token_factory
        self._operation_id_factory = operation_id_factory

    def upload_release(
        self,
        *,
        product_id: int,
        version: str,
        release_notes: str,
        original_filename: str | None,
        file_obj: BinaryIO,
        max_bytes: int,
    ) -> ReleaseUploadResult:
        operation_id = self._operation_id_factory()
        product = self.db.get(Product, product_id)
        if product is None:
            raise ReleaseProductNotFoundError

        normalized_version = normalize_release_version(version)
        normalized_filename = normalize_release_filename(original_filename)
        normalized_notes = normalize_release_notes(release_notes)
        archive_metadata = inspect_release_archive(file_obj, max_bytes=max_bytes)

        existing = self.product_release_repository.get_by_product_id_and_version(
            product_id,
            normalized_version,
        )
        if existing is not None:
            return self._resolve_existing_release(
                existing,
                metadata=archive_metadata,
                original_filename=normalized_filename,
                release_notes=normalized_notes,
                operation_id=operation_id,
            )

        try:
            storage_key = build_product_release_storage_key(
                product_id=product_id,
                version=normalized_version,
                token=self._storage_token_factory(),
            )
            storage = self._storage_factory()
        except Exception as exc:
            self._log_release_event(
                operation_id=operation_id,
                product_id=product_id,
                phase="storage_initialization",
                outcome="unavailable",
            )
            raise ReleaseStorageUnavailableError from exc

        key_digest = self._storage_key_digest(storage_key)
        try:
            uploaded_object = storage.upload_product_release_file(
                storage_key=storage_key,
                file_obj=file_obj,
                file_size=archive_metadata.file_size,
                sha256_hash=archive_metadata.sha256_hash,
            )
        except Exception as exc:
            self._raise_after_compensation(
                storage=storage,
                storage_key=storage_key,
                operation_id=operation_id,
                product_id=product_id,
                phase="upload",
                original_error=exc,
                compensated_error=ReleaseStorageUnavailableError(),
            )

        try:
            verified = storage.verify_product_release_object(
                storage_key=storage_key,
                expected_file_size=archive_metadata.file_size,
                expected_sha256_hash=archive_metadata.sha256_hash,
            )
        except Exception as exc:
            self._raise_after_compensation(
                storage=storage,
                storage_key=storage_key,
                operation_id=operation_id,
                product_id=product_id,
                phase="verification",
                original_error=exc,
                compensated_error=ReleaseStorageUnavailableError(),
            )

        if not verified:
            self._raise_after_compensation(
                storage=storage,
                storage_key=storage_key,
                operation_id=operation_id,
                product_id=product_id,
                phase="verification",
                original_error=ReleaseStorageUnavailableError(),
                compensated_error=ReleaseStorageUnavailableError(),
            )

        try:
            release = self._create_release(
                product_id=product_id,
                version=normalized_version,
                release_notes=normalized_notes,
                uploaded_object=uploaded_object,
                original_filename=normalized_filename,
                metadata=archive_metadata,
            )
        except Exception as exc:
            self._rollback_safely(
                operation_id=operation_id,
                product_id=product_id,
                phase="persistence",
            )
            cleanup_succeeded = self._compensate_object(
                storage=storage,
                storage_key=storage_key,
                operation_id=operation_id,
                product_id=product_id,
                phase="persistence",
            )
            if not cleanup_succeeded:
                raise ReleaseReconciliationRequiredError(operation_id) from exc

            winner = self.product_release_repository.get_by_product_id_and_version(
                product_id,
                normalized_version,
            )
            if winner is not None:
                return self._resolve_race_winner(
                    winner,
                    metadata=archive_metadata,
                    original_filename=normalized_filename,
                    release_notes=normalized_notes,
                    operation_id=operation_id,
                )

            self._log_release_event(
                operation_id=operation_id,
                product_id=product_id,
                phase="persistence",
                outcome="failed_compensated",
                storage_provider=storage.storage_provider,
                storage_key_digest=key_digest,
            )
            raise ReleasePersistenceError from exc

        release_id = release.id
        try:
            self.db.commit()
        except Exception as exc:
            self._rollback_safely(
                operation_id=operation_id,
                product_id=product_id,
                phase="commit",
            )
            ownership = self._find_storage_owner(storage_key)
            if isinstance(ownership, ProductRelease):
                self._log_release_event(
                    operation_id=operation_id,
                    product_id=product_id,
                    phase="commit",
                    outcome="ownership_confirmed",
                    storage_provider=storage.storage_provider,
                    storage_key_digest=key_digest,
                )
                return ReleaseUploadResult(
                    release_id=ownership.id,
                    created=True,
                )

            if ownership is False:
                cleanup_succeeded = self._compensate_object(
                    storage=storage,
                    storage_key=storage_key,
                    operation_id=operation_id,
                    product_id=product_id,
                    phase="commit",
                )
                if cleanup_succeeded:
                    raise ReleasePersistenceError from exc

            self._log_release_event(
                operation_id=operation_id,
                product_id=product_id,
                phase="commit",
                outcome="reconciliation_required",
                storage_provider=storage.storage_provider,
                storage_key_digest=key_digest,
            )
            raise ReleaseReconciliationRequiredError(operation_id) from exc

        self._log_release_event(
            operation_id=operation_id,
            product_id=product_id,
            phase="complete",
            outcome="created",
            storage_provider=storage.storage_provider,
            storage_key_digest=key_digest,
        )
        return ReleaseUploadResult(release_id=release_id, created=True)

    def publish_release(
        self,
        release_id: int,
        *,
        product_id: int | None = None,
    ) -> ProductRelease:
        operation_id = self._operation_id_factory()
        try:
            with self.db.begin():
                product = self.product_release_repository.lock_product_for_release(
                    release_id
                )
                if product is None:
                    raise ReleaseNotFoundError
                if product_id is not None and product.id != product_id:
                    raise ReleaseNotFoundError

                releases = (
                    self.product_release_repository.list_by_product_id_for_update(
                        product.id
                    )
                )
                release = next(
                    (
                        product_release
                        for product_release in releases
                        if product_release.id == release_id
                    ),
                    None,
                )
                if release is None:
                    raise ReleaseNotFoundError

                storage = self._create_storage_for_existing_release(
                    operation_id=operation_id,
                    product_id=product.id,
                )
                if (
                    release.file_size is None
                    or release.sha256_hash is None
                    or not self._verify_release_object(storage, release)
                ):
                    raise ReleaseReconciliationRequiredError(operation_id)

                now = datetime.now(UTC)
                for product_release in releases:
                    product_release.is_active = product_release.id == release.id
                    if (
                        product_release.id == release.id
                        and product_release.released_at is None
                    ):
                        product_release.released_at = now

                self.db.flush()
        except IntegrityError as exc:
            raise ReleasePublicationConflictError from exc

        return release

    def list_releases_by_product_id(
        self,
        product_id: int,
    ) -> list[ProductRelease]:
        return self.product_release_repository.list_by_product_id(product_id)

    def _create_release(
        self,
        *,
        product_id: int,
        version: str,
        release_notes: str | None,
        uploaded_object: UploadedObject,
        original_filename: str,
        metadata: ReleaseArchiveMetadata,
    ) -> ProductRelease:
        release = ProductRelease(
            product_id=product_id,
            version=version,
            release_notes=release_notes,
            storage_provider=uploaded_object.storage_provider,
            storage_key=uploaded_object.storage_key,
            original_filename=original_filename,
            file_size=metadata.file_size,
            sha256_hash=metadata.sha256_hash,
            is_active=False,
        )
        return self.product_release_repository.create(release)

    def _resolve_existing_release(
        self,
        release: ProductRelease,
        *,
        metadata: ReleaseArchiveMetadata,
        original_filename: str,
        release_notes: str | None,
        operation_id: str,
    ) -> ReleaseUploadResult:
        if not self._material_inputs_match(
            release,
            metadata=metadata,
            original_filename=original_filename,
            release_notes=release_notes,
        ):
            raise ReleaseConflictError

        storage = self._create_storage_for_existing_release(
            operation_id=operation_id,
            product_id=release.product_id,
        )
        if not self._verify_release_object(storage, release):
            self._log_release_event(
                operation_id=operation_id,
                product_id=release.product_id,
                phase="idempotency",
                outcome="reconciliation_required",
                storage_provider=release.storage_provider,
                storage_key_digest=self._storage_key_digest(release.storage_key),
            )
            raise ReleaseReconciliationRequiredError(operation_id)

        return ReleaseUploadResult(release_id=release.id, created=False)

    def _resolve_race_winner(
        self,
        release: ProductRelease,
        *,
        metadata: ReleaseArchiveMetadata,
        original_filename: str,
        release_notes: str | None,
        operation_id: str,
    ) -> ReleaseUploadResult:
        if not self._material_inputs_match(
            release,
            metadata=metadata,
            original_filename=original_filename,
            release_notes=release_notes,
        ):
            raise ReleaseConflictError

        storage = self._create_storage_for_existing_release(
            operation_id=operation_id,
            product_id=release.product_id,
        )
        if not self._verify_release_object(storage, release):
            raise ReleaseReconciliationRequiredError(operation_id)
        return ReleaseUploadResult(release_id=release.id, created=False)

    def _create_storage_for_existing_release(
        self,
        *,
        operation_id: str,
        product_id: int,
    ) -> ReleaseStorage:
        try:
            return self._storage_factory()
        except Exception as exc:
            self._log_release_event(
                operation_id=operation_id,
                product_id=product_id,
                phase="storage_initialization",
                outcome="unavailable",
            )
            raise ReleaseStorageUnavailableError from exc

    @staticmethod
    def _material_inputs_match(
        release: ProductRelease,
        *,
        metadata: ReleaseArchiveMetadata,
        original_filename: str,
        release_notes: str | None,
    ) -> bool:
        return (
            release.sha256_hash == metadata.sha256_hash
            and release.file_size == metadata.file_size
            and release.original_filename == original_filename
            and release.release_notes == release_notes
        )

    @staticmethod
    def _verify_release_object(
        storage: ReleaseStorage,
        release: ProductRelease,
    ) -> bool:
        if release.file_size is None or release.sha256_hash is None:
            return False
        try:
            return storage.verify_product_release_object(
                storage_key=release.storage_key,
                expected_file_size=release.file_size,
                expected_sha256_hash=release.sha256_hash,
            )
        except Exception as exc:
            raise ReleaseStorageUnavailableError from exc

    def _raise_after_compensation(
        self,
        *,
        storage: ReleaseStorage,
        storage_key: str,
        operation_id: str,
        product_id: int,
        phase: str,
        original_error: Exception,
        compensated_error: Exception,
    ) -> None:
        self._rollback_safely(
            operation_id=operation_id,
            product_id=product_id,
            phase=phase,
        )
        if self._compensate_object(
            storage=storage,
            storage_key=storage_key,
            operation_id=operation_id,
            product_id=product_id,
            phase=phase,
        ):
            raise compensated_error from original_error
        raise ReleaseReconciliationRequiredError(operation_id) from original_error

    def _compensate_object(
        self,
        *,
        storage: ReleaseStorage,
        storage_key: str,
        operation_id: str,
        product_id: int,
        phase: str,
    ) -> bool:
        key_digest = self._storage_key_digest(storage_key)
        ownership = self._find_storage_owner(storage_key)
        if isinstance(ownership, ProductRelease):
            self._log_release_event(
                operation_id=operation_id,
                product_id=product_id,
                phase=phase,
                outcome="ownership_preserved",
                storage_provider=storage.storage_provider,
                storage_key_digest=key_digest,
            )
            return False
        if ownership is None:
            self._log_release_event(
                operation_id=operation_id,
                product_id=product_id,
                phase=phase,
                outcome="ownership_unknown",
                storage_provider=storage.storage_provider,
                storage_key_digest=key_digest,
            )
            return False

        try:
            storage.delete_product_release_object(storage_key=storage_key)
        except Exception:
            self._log_release_event(
                operation_id=operation_id,
                product_id=product_id,
                phase=phase,
                outcome="cleanup_failed",
                storage_provider=storage.storage_provider,
                storage_key_digest=key_digest,
            )
            return False

        self._log_release_event(
            operation_id=operation_id,
            product_id=product_id,
            phase=phase,
            outcome="compensated",
            storage_provider=storage.storage_provider,
            storage_key_digest=key_digest,
        )
        return True

    def _rollback_safely(
        self,
        *,
        operation_id: str,
        product_id: int,
        phase: str,
    ) -> bool:
        try:
            self.db.rollback()
        except Exception:
            self._log_release_event(
                operation_id=operation_id,
                product_id=product_id,
                phase=phase,
                outcome="rollback_failed",
            )
            return False
        return True

    def _find_storage_owner(
        self,
        storage_key: str,
    ) -> ProductRelease | bool | None:
        ownership_db: Session | None = None
        try:
            ownership_db = self._ownership_session_factory()
            owner = ProductReleaseRepository(ownership_db).get_by_storage_key(
                storage_key
            )
            if owner is None:
                return False
            ownership_db.expunge(owner)
            return owner
        except Exception:
            return None
        finally:
            if ownership_db is not None:
                ownership_db.close()

    @staticmethod
    def _storage_key_digest(storage_key: str) -> str:
        return hashlib.sha256(storage_key.encode("utf-8")).hexdigest()

    @staticmethod
    def _log_release_event(
        *,
        operation_id: str,
        product_id: int,
        phase: str,
        outcome: str,
        storage_provider: str = "cloudflare_r2",
        storage_key_digest: str = "none",
    ) -> None:
        logger.info(
            "Product release workflow event",
            extra={
                "operation_id": operation_id,
                "product_id": product_id,
                "workflow_phase": phase,
                "storage_provider": storage_provider,
                "outcome": outcome,
                "storage_key_digest": storage_key_digest,
            },
        )
