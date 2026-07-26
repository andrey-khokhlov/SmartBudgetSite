from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import re
import unicodedata
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.feedback_attachment import FeedbackAttachment
from app.repositories.feedback_repository import FeedbackRepository

FEEDBACK_STORAGE_PREFIX = "feedback"
FEEDBACK_RANDOM_FILENAME_PATTERN = re.compile(r"^[0-9a-f]{32}\.[a-z0-9]+$")
DEFAULT_ATTACHMENT_DOWNLOAD_FILENAME = "attachment"


class UnsafeFeedbackStorageKey(ValueError):
    """Raised when a persisted key cannot resolve inside feedback storage."""


@dataclass(frozen=True)
class FeedbackAttachmentDownload:
    path: Path
    filename: str
    content_type: str


def feedback_storage_root() -> Path:
    return (Path(settings.UPLOAD_DIR) / FEEDBACK_STORAGE_PREFIX).resolve()


def build_feedback_storage_key(extension: str) -> str:
    return f"{FEEDBACK_STORAGE_PREFIX}/{uuid4().hex}{extension}"


def resolve_feedback_storage_path(storage_key: str) -> Path:
    if not storage_key or "\\" in storage_key:
        raise UnsafeFeedbackStorageKey("Invalid feedback attachment storage key")

    key = PurePosixPath(storage_key)
    if (
        key.is_absolute()
        or len(key.parts) != 2
        or key.parts[0] != FEEDBACK_STORAGE_PREFIX
        or key.parts[1] in {"", ".", ".."}
    ):
        raise UnsafeFeedbackStorageKey("Invalid feedback attachment storage key")

    root = feedback_storage_root()
    candidate = (Path(settings.UPLOAD_DIR) / Path(*key.parts)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise UnsafeFeedbackStorageKey(
            "Feedback attachment path leaves its storage root"
        ) from exc
    return candidate


def sanitize_attachment_download_filename(filename: str) -> str:
    without_controls = "".join(
        character
        for character in filename
        if not unicodedata.category(character).startswith("C")
    )
    basename = without_controls.replace("\\", "/").rsplit("/", 1)[-1]
    basename = basename.replace('"', "").strip(" .")
    return basename or DEFAULT_ATTACHMENT_DOWNLOAD_FILENAME


def get_feedback_attachment_download(
    db: Session,
    *,
    feedback_id: int,
    attachment_id: int,
) -> FeedbackAttachmentDownload:
    attachment = FeedbackRepository(db).get_attachment_for_feedback(
        feedback_id=feedback_id,
        attachment_id=attachment_id,
    )
    if attachment is None:
        raise HTTPException(status_code=404, detail="Attachment not found")

    try:
        path = resolve_feedback_storage_path(attachment.storage_key)
    except UnsafeFeedbackStorageKey as exc:
        raise HTTPException(status_code=404, detail="Attachment not found") from exc

    if not path.is_file():
        raise HTTPException(status_code=404, detail="Attachment not found")

    return FeedbackAttachmentDownload(
        path=path,
        filename=sanitize_attachment_download_filename(
            attachment.original_filename
        ),
        content_type=attachment.content_type,
    )


def storage_key_for_path(path: Path) -> str:
    root = feedback_storage_root()
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        raise UnsafeFeedbackStorageKey(
            "Feedback attachment path leaves its storage root"
        ) from exc

    if len(relative.parts) != 1:
        raise UnsafeFeedbackStorageKey("Invalid feedback attachment file path")
    return f"{FEEDBACK_STORAGE_PREFIX}/{relative.as_posix()}"


def is_generated_feedback_storage_key(storage_key: str) -> bool:
    try:
        path = resolve_feedback_storage_path(storage_key)
    except UnsafeFeedbackStorageKey:
        return False
    return bool(FEEDBACK_RANDOM_FILENAME_PATTERN.fullmatch(path.name))


def list_feedback_attachments(db: Session) -> list[FeedbackAttachment]:
    return FeedbackRepository(db).list_attachments()
