"""
Feedback service layer

Responsibility:
- Contains ALL business logic for feedback handling
- Validates rules (email, type, publish restrictions, etc.)
- Works with repository
- Raises HTTPException for invalid operations

Important:
- Routes must NOT contain business logic
- Routes only call service functions and return responses
"""


from datetime import datetime, UTC
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.repositories.feedback_admin_repository import FeedbackAdminRepository
from app.models.feedback import FeedbackMessage
from app.services import mail_service
from app.core.config import settings
from app.services.support_reference_service import (
    is_valid_download_support_reference,
)

PURCHASE_OR_DOWNLOAD_ISSUE = "purchase_or_download_issue"


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

