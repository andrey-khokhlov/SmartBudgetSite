from __future__ import annotations

import argparse
import hashlib
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.db import SessionLocal  # noqa: E402
from app.repositories.product_release_repository import (  # noqa: E402
    ProductReleaseRepository,
)
from app.services.storage.r2_storage_service import (  # noqa: E402
    R2StorageOperationError,
    R2StorageService,
    is_managed_product_release_key,
    is_within_product_release_prefix,
)

DEFAULT_MINIMUM_ORPHAN_AGE = timedelta(hours=24)


@dataclass(frozen=True)
class ReconciliationReport:
    missing_owned_keys: tuple[str, ...]
    orphan_keys: tuple[str, ...]
    size_mismatch_keys: tuple[str, ...]
    sha_mismatch_keys: tuple[str, ...]
    unexpected_database_keys: tuple[str, ...]
    unexpected_object_keys: tuple[str, ...]
    inspection_failure_keys: tuple[str, ...]
    too_recent_orphan_keys: tuple[str, ...]
    deleted_orphan_keys: tuple[str, ...]
    delete_failure_keys: tuple[str, ...]


def reconcile_product_releases(
    db: Session,
    *,
    storage: R2StorageService,
    delete_orphans: bool = False,
    minimum_orphan_age: timedelta = DEFAULT_MINIMUM_ORPHAN_AGE,
    now: datetime | None = None,
    output: Callable[[str], None] = print,
) -> ReconciliationReport:
    if minimum_orphan_age < timedelta(0):
        raise ValueError("minimum_orphan_age must not be negative")

    checked_at = now or datetime.now(UTC)
    if checked_at.tzinfo is None:
        checked_at = checked_at.replace(tzinfo=UTC)

    repository = ProductReleaseRepository(db)
    releases = repository.list_all()
    database_keys = {release.storage_key for release in releases}
    listed_objects = storage.list_product_release_objects()
    listed_by_key = {stored.storage_key: stored for stored in listed_objects}

    missing_owned_keys: list[str] = []
    size_mismatch_keys: list[str] = []
    sha_mismatch_keys: list[str] = []
    unexpected_database_keys: list[str] = []
    inspection_failure_keys: list[str] = []

    for release in releases:
        if not is_within_product_release_prefix(release.storage_key):
            unexpected_database_keys.append(release.storage_key)

        try:
            stored = storage.head_product_release_object(
                storage_key=release.storage_key
            )
        except R2StorageOperationError:
            inspection_failure_keys.append(release.storage_key)
            continue

        if stored is None:
            missing_owned_keys.append(release.storage_key)
            continue

        if release.file_size is None or stored.content_length != release.file_size:
            size_mismatch_keys.append(release.storage_key)
        if release.sha256_hash is None or stored.sha256_hash != release.sha256_hash:
            sha_mismatch_keys.append(release.storage_key)

    orphan_objects = [
        stored
        for storage_key, stored in listed_by_key.items()
        if storage_key not in database_keys
    ]
    orphan_keys = [stored.storage_key for stored in orphan_objects]
    unexpected_object_keys = [
        stored.storage_key
        for stored in orphan_objects
        if not is_managed_product_release_key(stored.storage_key)
    ]

    too_recent_orphan_keys: list[str] = []
    deleted_orphan_keys: list[str] = []
    delete_failure_keys: list[str] = []

    if delete_orphans:
        for stored in orphan_objects:
            storage_key = stored.storage_key
            if not is_managed_product_release_key(storage_key):
                continue

            last_modified = _as_aware_utc(stored.last_modified)
            if last_modified is None or checked_at - last_modified < minimum_orphan_age:
                too_recent_orphan_keys.append(storage_key)
                continue

            db.rollback()
            if repository.get_by_storage_key(storage_key) is not None:
                continue

            try:
                storage.delete_product_release_object(storage_key=storage_key)
            except R2StorageOperationError:
                delete_failure_keys.append(storage_key)
                continue

            deleted_orphan_keys.append(storage_key)

    _write_report(
        output=output,
        database_count=len(releases),
        listed_count=len(listed_objects),
        missing_owned_keys=missing_owned_keys,
        orphan_keys=orphan_keys,
        size_mismatch_keys=size_mismatch_keys,
        sha_mismatch_keys=sha_mismatch_keys,
        unexpected_database_keys=unexpected_database_keys,
        unexpected_object_keys=unexpected_object_keys,
        inspection_failure_keys=inspection_failure_keys,
        too_recent_orphan_keys=too_recent_orphan_keys,
        deleted_orphan_keys=deleted_orphan_keys,
        delete_failure_keys=delete_failure_keys,
        delete_orphans=delete_orphans,
    )

    return ReconciliationReport(
        missing_owned_keys=tuple(missing_owned_keys),
        orphan_keys=tuple(orphan_keys),
        size_mismatch_keys=tuple(size_mismatch_keys),
        sha_mismatch_keys=tuple(sha_mismatch_keys),
        unexpected_database_keys=tuple(unexpected_database_keys),
        unexpected_object_keys=tuple(unexpected_object_keys),
        inspection_failure_keys=tuple(inspection_failure_keys),
        too_recent_orphan_keys=tuple(too_recent_orphan_keys),
        deleted_orphan_keys=tuple(deleted_orphan_keys),
        delete_failure_keys=tuple(delete_failure_keys),
    )


def _as_aware_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _safe_key_reference(storage_key: str) -> str:
    return hashlib.sha256(storage_key.encode("utf-8")).hexdigest()[:16]


def _write_key_group(
    output: Callable[[str], None],
    label: str,
    keys: list[str],
) -> None:
    output(f"{label}: {len(keys)}")
    for storage_key in keys:
        output(f"  key-ref: {_safe_key_reference(storage_key)}")


def _write_report(
    *,
    output: Callable[[str], None],
    database_count: int,
    listed_count: int,
    missing_owned_keys: list[str],
    orphan_keys: list[str],
    size_mismatch_keys: list[str],
    sha_mismatch_keys: list[str],
    unexpected_database_keys: list[str],
    unexpected_object_keys: list[str],
    inspection_failure_keys: list[str],
    too_recent_orphan_keys: list[str],
    deleted_orphan_keys: list[str],
    delete_failure_keys: list[str],
    delete_orphans: bool,
) -> None:
    output(f"Database release rows: {database_count}")
    output(f"R2 objects under managed prefix: {listed_count}")
    _write_key_group(output, "Missing owned objects", missing_owned_keys)
    _write_key_group(output, "Orphan objects", orphan_keys)
    _write_key_group(output, "Size mismatches", size_mismatch_keys)
    _write_key_group(output, "SHA metadata mismatches", sha_mismatch_keys)
    _write_key_group(output, "Unexpected database keys", unexpected_database_keys)
    _write_key_group(output, "Unexpected orphan keys", unexpected_object_keys)
    _write_key_group(output, "Inspection failures", inspection_failure_keys)
    if delete_orphans:
        _write_key_group(output, "Too-recent orphan objects", too_recent_orphan_keys)
        _write_key_group(output, "Deleted orphan objects", deleted_orphan_keys)
        _write_key_group(output, "Orphan delete failures", delete_failure_keys)
    else:
        output("Read-only mode: no R2 objects were deleted.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reconcile ProductRelease rows with private R2 objects."
    )
    parser.add_argument(
        "--delete-orphans",
        action="store_true",
        help="Delete only validated old orphan objects under the managed prefix.",
    )
    parser.add_argument(
        "--minimum-age-hours",
        type=float,
        default=DEFAULT_MINIMUM_ORPHAN_AGE.total_seconds() / 3600,
        help="Minimum orphan age required for explicit deletion (default: 24).",
    )
    args = parser.parse_args()
    if args.minimum_age_hours < 0:
        parser.error("--minimum-age-hours must not be negative")

    db = SessionLocal()
    try:
        reconcile_product_releases(
            db,
            storage=R2StorageService(),
            delete_orphans=args.delete_orphans,
            minimum_orphan_age=timedelta(hours=args.minimum_age_hours),
        )
    except Exception:
        print(
            "Product release reconciliation could not complete safely.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
    finally:
        db.close()


if __name__ == "__main__":
    main()
