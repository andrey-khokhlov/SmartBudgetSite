from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Callable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.services.feedback_attachment_service import (
    UnsafeFeedbackStorageKey,
    feedback_storage_root,
    is_generated_feedback_storage_key,
    list_feedback_attachments,
    resolve_feedback_storage_path,
    storage_key_for_path,
)


@dataclass(frozen=True)
class ReconciliationReport:
    missing_file_keys: tuple[str, ...]
    orphan_file_keys: tuple[str, ...]
    unsafe_persisted_keys: tuple[str, ...]
    unsafe_file_entries: tuple[str, ...]
    deleted_orphan_keys: tuple[str, ...]


def reconcile_feedback_attachments(
    db: Session,
    *,
    delete_orphans: bool = False,
    output: Callable[[str], None] = print,
) -> ReconciliationReport:
    attachments = list_feedback_attachments(db)
    valid_database_keys: set[str] = set()
    missing_file_keys: list[str] = []
    unsafe_persisted_keys: list[str] = []

    for attachment in attachments:
        try:
            path = resolve_feedback_storage_path(attachment.storage_key)
        except UnsafeFeedbackStorageKey:
            unsafe_persisted_keys.append(attachment.storage_key)
            continue

        valid_database_keys.add(attachment.storage_key)
        if not path.is_file():
            missing_file_keys.append(attachment.storage_key)

    orphan_files: list[tuple[str, Path]] = []
    unsafe_file_entries: list[str] = []
    root = feedback_storage_root()
    if root.exists():
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            try:
                storage_key = storage_key_for_path(path)
            except UnsafeFeedbackStorageKey:
                unsafe_file_entries.append(str(path))
                continue
            if storage_key not in valid_database_keys:
                orphan_files.append((storage_key, path))

    deleted_orphan_keys: list[str] = []
    if delete_orphans:
        for storage_key, path in orphan_files:
            if not is_generated_feedback_storage_key(storage_key):
                continue
            resolved = resolve_feedback_storage_path(storage_key)
            if resolved != path.resolve():
                continue
            resolved.unlink()
            deleted_orphan_keys.append(storage_key)

    orphan_file_keys = [storage_key for storage_key, _ in orphan_files]
    output(f"Database attachment rows: {len(attachments)}")
    output(f"Missing attachment files: {len(missing_file_keys)}")
    for storage_key in missing_file_keys:
        output(f"  missing: {storage_key}")
    output(f"Orphan attachment files: {len(orphan_file_keys)}")
    for storage_key in orphan_file_keys:
        output(f"  orphan: {storage_key}")
    output(f"Unsafe persisted storage keys: {len(unsafe_persisted_keys)}")
    for storage_key in unsafe_persisted_keys:
        output(f"  unsafe key: {storage_key}")
    output(f"Unsafe filesystem entries: {len(unsafe_file_entries)}")
    for entry in unsafe_file_entries:
        output(f"  unsafe file: {entry}")
    if delete_orphans:
        output(f"Deleted validated orphan files: {len(deleted_orphan_keys)}")
    else:
        output("Read-only mode: no files were deleted.")

    return ReconciliationReport(
        missing_file_keys=tuple(missing_file_keys),
        orphan_file_keys=tuple(orphan_file_keys),
        unsafe_persisted_keys=tuple(unsafe_persisted_keys),
        unsafe_file_entries=tuple(unsafe_file_entries),
        deleted_orphan_keys=tuple(deleted_orphan_keys),
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reconcile feedback attachment database rows and local files."
    )
    parser.add_argument(
        "--delete-orphans",
        action="store_true",
        help="Delete only validated orphan files below feedback storage.",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        reconcile_feedback_attachments(
            db,
            delete_orphans=args.delete_orphans,
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
