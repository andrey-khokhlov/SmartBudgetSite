from dataclasses import dataclass
from datetime import UTC, datetime
import logging
from pathlib import Path
from shutil import copyfileobj
from typing import BinaryIO

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.feedback import FeedbackMessage
from app.repositories.feedback_admin_repository import FeedbackAdminRepository
from app.repositories.feedback_repository import FeedbackRepository
from app.services import mail_service
from app.services.feedback_attachment_service import (
    build_feedback_storage_key,
    feedback_storage_root,
    resolve_feedback_storage_path,
)
from app.services.purchase_lookup_service import resolve_verified_product_id
from app.services.support_reference_service import (
    is_valid_download_support_reference,
)

PURCHASE_OR_DOWNLOAD_ISSUE = "purchase_or_download_issue"
PRODUCT_FEEDBACK = "product_feedback"
MAX_FEEDBACK_ATTACHMENT_SIZE = 20 * 1024 * 1024
MAX_FEEDBACK_ATTACHMENTS_SIZE = 25 * 1024 * 1024
MAX_FEEDBACK_ATTACHMENTS = 5
ALLOWED_FEEDBACK_ATTACHMENT_TYPES = {
    "image/png",
    "image/jpeg",
    "image/webp",
    "application/pdf",
}
ALLOWED_FEEDBACK_ATTACHMENT_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".pdf",
}
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FeedbackAttachmentInput:
    filename: str | None
    content_type: str | None
    file: BinaryIO


@dataclass(frozen=True)
class PublicReview:
    subject: str
    message: str
    author_name: str | None
    admin_reply: str | None
    published_at: datetime | None


def list_public_reviews(
    db: Session,
    *,
    product_id: int,
) -> list[PublicReview]:
    """Return only fields approved for public review display."""
    repository = FeedbackAdminRepository(db)
    published_feedback = repository.list_published_product_feedback(product_id)
    return [
        PublicReview(
            subject=feedback.subject,
            message=feedback.message,
            author_name=feedback.name,
            admin_reply=feedback.admin_reply,
            published_at=feedback.published_at,
        )
        for feedback in published_feedback
    ]


def _validate_feedback_attachments(
    attachments: list[FeedbackAttachmentInput],
) -> list[tuple[FeedbackAttachmentInput, str]]:
    if len(attachments) > MAX_FEEDBACK_ATTACHMENTS:
        raise HTTPException(
            status_code=400,
            detail=f"Too many files. Maximum allowed: {MAX_FEEDBACK_ATTACHMENTS}",
        )

    validated = []
    aggregate_size = 0
    for attachment in attachments:
        if not attachment.filename:
            raise HTTPException(status_code=400, detail="File must have a filename")

        extension = Path(attachment.filename).suffix.lower()
        if extension not in ALLOWED_FEEDBACK_ATTACHMENT_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file extension: {extension or 'unknown'}",
            )
        if attachment.content_type not in ALLOWED_FEEDBACK_ATTACHMENT_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type: {attachment.content_type}",
            )

        attachment.file.seek(0, 2)
        size = attachment.file.tell()
        attachment.file.seek(0)
        if size > MAX_FEEDBACK_ATTACHMENT_SIZE:
            raise HTTPException(
                status_code=400,
                detail=f"File too large: {attachment.filename}",
            )
        aggregate_size += size
        validated.append((attachment, extension))

    if aggregate_size > MAX_FEEDBACK_ATTACHMENTS_SIZE:
        raise HTTPException(
            status_code=400,
            detail="Total attachment size is too large",
        )

    return validated


def _remove_submission_files(paths: list[Path]) -> None:
    for path in reversed(paths):
        try:
            path.unlink(missing_ok=True)
        except Exception:
            logger.error(
                "Could not remove failed feedback attachment file name=%r",
                path.name,
            )


def submit_feedback(
    db: Session,
    *,
    message_type: str,
    email: str,
    subject: str,
    message: str,
    name: str | None,
    page_url: str | None,
    user_agent: str | None,
    support_reference: str | None,
    purchase_reference: str | None,
    attachments: list[FeedbackAttachmentInput],
) -> FeedbackMessage:
    """Persist one complete feedback submission and own its transaction."""
    saved_paths: list[Path] = []

    try:
        validated_attachments = _validate_feedback_attachments(attachments)

        product_id = None
        if message_type == PRODUCT_FEEDBACK:
            if not email:
                raise HTTPException(
                    status_code=400,
                    detail="Email is required for product feedback",
                )
            product_id = resolve_verified_product_id(
                db=db,
                email=email,
                purchase_reference=purchase_reference,
            )

        normalized_support_reference = validate_feedback_support_reference(
            message_type=message_type,
            support_reference=support_reference,
        )

        repository = FeedbackRepository(db)
        feedback = repository.create(
            message_type=message_type,
            email=email,
            subject=subject,
            message=message,
            name=name,
            page_url=page_url,
            user_agent=user_agent,
            support_reference=normalized_support_reference,
            product_id=product_id,
        )

        if validated_attachments:
            upload_path = feedback_storage_root()
            upload_path.mkdir(parents=True, exist_ok=True)

            for attachment, extension in validated_attachments:
                storage_key = build_feedback_storage_key(extension)
                file_path = resolve_feedback_storage_path(storage_key)
                saved_paths.append(file_path)
                with file_path.open("wb") as destination:
                    copyfileobj(attachment.file, destination)

                repository.create_attachment(
                    feedback_id=feedback.id,
                    original_filename=attachment.filename or file_path.name,
                    storage_key=storage_key,
                    content_type=attachment.content_type or "application/octet-stream",
                    file_size_bytes=file_path.stat().st_size,
                )

        db.commit()
        db.refresh(feedback)
        return feedback
    except HTTPException:
        db.rollback()
        _remove_submission_files(saved_paths)
        raise
    except Exception as exc:
        db.rollback()
        _remove_submission_files(saved_paths)
        raise HTTPException(
            status_code=500,
            detail="Failed to save feedback submission",
        ) from exc


def validate_feedback_support_reference(
    *,
    message_type: str,
    support_reference: str | None,
) -> str | None:
    """Normalize and validate the structured public support reference."""
    normalized = (support_reference or "").strip() or None
    if normalized is None:
        return None

    if message_type != PURCHASE_OR_DOWNLOAD_ISSUE:
        raise HTTPException(
            status_code=400,
            detail="Support reference is only allowed for purchase or download issues",
        )

    if len(normalized) > 64 or not is_valid_download_support_reference(normalized):
        raise HTTPException(status_code=400, detail="Invalid support reference")

    return normalized


def send_feedback_reply(db: Session, feedback_id: int) -> None:
    """
    Send admin reply to user by email.

    Business rules:
    - Feedback must exist
    - Email reply is allowed only for private message types
    - Reply text must be present
    - User email must be present
    - Email cannot be sent more than once
    - Email cannot be sent for published feedback
    """

    repo = FeedbackAdminRepository(db)
    item = repo.get_feedback_by_id(feedback_id)

    if not item:
        raise HTTPException(status_code=404, detail="Feedback not found")

    if item.type not in (
        "general_question",
        "site_issue",
        PURCHASE_OR_DOWNLOAD_ISSUE,
    ):
        raise HTTPException(
            status_code=400,
            detail="Email reply is not applicable for this feedback type",
        )

    if not item.admin_reply:
        raise HTTPException(
            status_code=400,
            detail="Cannot send email without reply text",
        )

    if not item.email:
        raise HTTPException(
            status_code=400,
            detail="Cannot send email: user email is missing",
        )

    if item.reply_sent_at:
        raise HTTPException(
            status_code=400,
            detail="Email already sent",
        )

    if item.is_published:
        raise HTTPException(
            status_code=400,
            detail="Cannot send email for published review",
        )

    # Send email (stub for now)
    mail_service.send_email(
        to_email=item.email,
        subject=f"{settings.MAIL_FROM_NAME}: reply to your message",
        body=item.admin_reply,
    )

    item.reply_sent_at = datetime.now(UTC)
    item.reply_sent_to_email = item.email

    db.commit()


def toggle_feedback_publish(db: Session, feedback_id: int) -> FeedbackMessage:
    """
    Toggle public review publication for product feedback.

    Business rules:
    - Feedback must exist
    - Only product_feedback can be published
    - Admin reply must be present before publication
    - When published:
        -> is_published = True
        -> published_at is set
    - When unpublished:
        -> is_published = False
        -> published_at = None
    """

    repo = FeedbackAdminRepository(db)
    item = repo.get_feedback_by_id(feedback_id)

    if not item:
        raise HTTPException(status_code=404, detail="Feedback not found")

    if item.type != "product_feedback":
        raise HTTPException(
            status_code=400,
            detail="Only product feedback can be published",
        )

    if not item.admin_reply:
        raise HTTPException(
            status_code=400,
            detail="Cannot publish without admin reply",
        )

    item.is_published = not item.is_published
    item.published_at = datetime.now(UTC) if item.is_published else None

    db.commit()
    db.refresh(item)

    return item


def toggle_feedback_resolved(db: Session, feedback_id: int):
    """
    Toggle resolved status for a feedback message.
    """
    repo = FeedbackAdminRepository(db)
    item = repo.get_feedback_by_id(feedback_id)

    if not item:
        raise HTTPException(status_code=404, detail="Feedback not found")

    repo.update_resolved_status(
        feedback_id=feedback_id,
        is_resolved=not item.is_resolved,
    )

    return item


def save_feedback_reply_draft(db: Session, feedback_id: int, admin_reply: str):
    """
    Save or update admin reply draft.
    """
    repo = FeedbackAdminRepository(db)
    item = repo.get_feedback_by_id(feedback_id)

    if not item:
        raise HTTPException(status_code=404, detail="Feedback not found")

    item.admin_reply = admin_reply.strip() or None
    db.commit()
    db.refresh(item)

    return item
