from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

import pytest

from app.core.config import settings
from app.models.feedback import FeedbackMessage
from app.models.feedback_attachment import FeedbackAttachment
from app.repositories.feedback_repository import FeedbackRepository
from app.services.feedback_service import (
    FeedbackAttachmentInput,
    save_feedback_reply_draft,
    send_feedback_reply,
    submit_feedback,
    toggle_feedback_publish,
    toggle_feedback_resolved,
)
from fastapi import HTTPException


@pytest.fixture(autouse=True)
def mock_mail_service(monkeypatch):
    monkeypatch.setattr(
        "app.services.mail_service.send_email",
        lambda **kwargs: None,
    )


def test_send_feedback_reply_fails_when_email_missing(db_session):
    """
    Service test: should fail if email is missing
    """

    feedback = FeedbackMessage(
        type="general_question",
        name="Test User",
        email=None,
        subject="Test subject",
        message="Test message",
        page_url="/feedback",
        user_agent="test-agent",
        admin_reply="Test reply",
        is_resolved=False,
        is_published=False,
    )

    db_session.add(feedback)
    db_session.commit()
    db_session.refresh(feedback)

    with pytest.raises(HTTPException) as exc:
        send_feedback_reply(db=db_session, feedback_id=feedback.id)

    assert exc.value.status_code == 400
    assert exc.value.detail == "Cannot send email: user email is missing"

def test_send_feedback_reply_success(db_session):
    """
    Service test: successful email sending
    """

    feedback = FeedbackMessage(
        type="general_question",
        name="Test User",
        email="test@example.com",
        subject="Test subject",
        message="Test message",
        page_url="/feedback",
        user_agent="test-agent",
        admin_reply="Test reply",
        is_resolved=False,
        is_published=False,
    )

    db_session.add(feedback)
    db_session.commit()
    db_session.refresh(feedback)

    # Act
    send_feedback_reply(db=db_session, feedback_id=feedback.id)

    # Reload from DB
    db_session.refresh(feedback)

    # Assert
    assert feedback.reply_sent_at is not None
    assert feedback.reply_sent_to_email == "test@example.com"

def test_toggle_publish_fails_for_non_product_feedback(db_session):
    """
    Should fail if feedback type is not product_feedback
    """

    feedback = FeedbackMessage(
        type="general_question",  # NOT product_feedback
        name="Test User",
        email="test@example.com",
        subject="Test subject",
        message="Test message",
        page_url="/feedback",
        user_agent="test-agent",
        admin_reply="Test reply",
        is_resolved=False,
        is_published=False,
    )

    db_session.add(feedback)
    db_session.commit()
    db_session.refresh(feedback)

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        toggle_feedback_publish(db=db_session, feedback_id=feedback.id)

    assert exc.value.status_code == 400
    assert exc.value.detail == "Only product feedback can be published"
def test_toggle_publish_success(db_session):
    """
    Should successfully publish product feedback
    """

    feedback = FeedbackMessage(
        type="product_feedback",
        name="Test User",
        email="test@example.com",
        subject="Test subject",
        message="Test message",
        page_url="/feedback",
        user_agent="test-agent",
        admin_reply="Test reply",
        is_resolved=False,
        is_published=False,
    )

    db_session.add(feedback)
    db_session.commit()
    db_session.refresh(feedback)

    # Act
    toggle_feedback_publish(db=db_session, feedback_id=feedback.id)

    db_session.refresh(feedback)

    # Assert
    assert feedback.is_published is True
    assert feedback.published_at is not None

def test_send_email_allowed_only_for_private_types(db_session):
    """
    Test case: email sending is restricted by feedback type

    What we verify:
    - Email is allowed only for:
        -> general_question
        -> site_issue
    - Email is NOT allowed for:
        -> product_feedback
    """

    from app.models.feedback import FeedbackMessage
    from app.services.feedback_service import send_feedback_reply
    from fastapi import HTTPException

    # Allowed type
    allowed = FeedbackMessage(
        type="general_question",
        name="Test",
        email="test@example.com",
        subject="Subject",
        message="Message",
        page_url="/feedback",
        user_agent="test-agent",
        admin_reply="Reply",
        is_resolved=False,
        is_published=False,
    )

    db_session.add(allowed)
    db_session.commit()
    db_session.refresh(allowed)

    # Should NOT raise
    send_feedback_reply(db=db_session, feedback_id=allowed.id)

    # Forbidden type
    forbidden = FeedbackMessage(
        type="product_feedback",
        name="Test",
        email="test@example.com",
        subject="Subject",
        message="Message",
        page_url="/feedback",
        user_agent="test-agent",
        admin_reply="Reply",
        is_resolved=False,
        is_published=False,
    )

    db_session.add(forbidden)
    db_session.commit()
    db_session.refresh(forbidden)

    # Should raise
    with pytest.raises(HTTPException) as exc:
        send_feedback_reply(db=db_session, feedback_id=forbidden.id)

    assert exc.value.status_code == 400
    assert "not applicable" in str(exc.value.detail)


def test_toggle_feedback_resolved_success(db_session):
    """
    Test case: resolve toggle sets feedback as resolved

    What we verify:
    - Initial state: is_resolved = False
    - After toggle:
        -> is_resolved becomes True
    - Change is persisted in the database
    """
    feedback = FeedbackMessage(
        type="general_question",
        name="Test User",
        email=None,
        subject="Test subject",
        message="Test message",
        page_url="/feedback",
        user_agent="test-agent",
        admin_reply="Test reply",
        is_resolved=False,
        is_published=False,
    )
    db_session.add(feedback)
    db_session.commit()
    db_session.refresh(feedback)

    updated = toggle_feedback_resolved(db=db_session, feedback_id=feedback.id)

    assert updated.is_resolved is True

    db_session.refresh(feedback)
    assert feedback.is_resolved is True


def test_toggle_feedback_resolved_back_to_false(db_session):
    """
    Test case: resolve toggle switches back to unresolved

    What we verify:
    - Initial state: is_resolved = True
    - After toggle:
        -> is_resolved becomes False
    - Change is persisted in the database
    """
    feedback = FeedbackMessage(
        type="general_question",
        name="Test User",
        email=None,
        subject="Test subject",
        message="Test message",
        page_url="/feedback",
        user_agent="test-agent",
        admin_reply="Test reply",
        is_resolved=True,
        is_published=False,
    )
    db_session.add(feedback)
    db_session.commit()
    db_session.refresh(feedback)

    updated = toggle_feedback_resolved(
        db=db_session,
        feedback_id=feedback.id,
    )

    assert updated.is_resolved is False

    db_session.refresh(feedback)
    assert feedback.is_resolved is False


def test_send_feedback_reply_fails_if_email_already_sent(db_session):
    """
    Test case: email cannot be sent twice for the same feedback

    What we verify:
    - Feedback already has reply_sent_at populated
    - Attempting to send email again raises HTTPException
    - Error status and message are correct
    """
    feedback = FeedbackMessage(
        type="general_question",
        name="Test User",
        email="test@example.com",
        subject="Test subject",
        message="Test message",
        page_url="/feedback",
        user_agent="test-agent",
        admin_reply="Test reply",
        is_resolved=False,
        is_published=False,
        reply_sent_at=datetime.now(UTC),
        reply_sent_to_email="test@example.com",
    )
    db_session.add(feedback)
    db_session.commit()
    db_session.refresh(feedback)

    with pytest.raises(HTTPException) as exc:
        send_feedback_reply(db=db_session, feedback_id=feedback.id)

    assert exc.value.status_code == 400

def test_send_feedback_reply_fails_without_admin_reply(db_session):
    """
    Test case: email cannot be sent without admin reply

    What we verify:
    - Feedback has no admin_reply
    - Attempting to send email raises HTTPException
    - Error status is 400
    """
    feedback = FeedbackMessage(
        type="general_question",
        name="Test User",
        email="test@example.com",
        subject="Test subject",
        message="Test message",
        page_url="/feedback",
        user_agent="test-agent",
        admin_reply=None,  # ← важно
        is_resolved=False,
        is_published=False,
    )
    db_session.add(feedback)
    db_session.commit()
    db_session.refresh(feedback)

    with pytest.raises(HTTPException) as exc:
        send_feedback_reply(db=db_session, feedback_id=feedback.id)

    assert exc.value.status_code == 400

def test_send_feedback_reply_fails_if_published(db_session):
    """
    Test case: email cannot be sent for published feedback

    What we verify:
    - Feedback is already published
    - Attempting to send email raises HTTPException
    - Error status is 400
    """
    feedback = FeedbackMessage(
        type="general_question",
        name="Test User",
        email="test@example.com",
        subject="Test subject",
        message="Test message",
        page_url="/feedback",
        user_agent="test-agent",
        admin_reply="Test reply",
        is_resolved=False,
        is_published=True,  # ← ключевой момент
    )
    db_session.add(feedback)
    db_session.commit()
    db_session.refresh(feedback)

    with pytest.raises(HTTPException) as exc:
        send_feedback_reply(db=db_session, feedback_id=feedback.id)

    assert exc.value.status_code == 400

def test_toggle_feedback_publish_fails_without_admin_reply(db_session):
    """
    Test case: product feedback cannot be published without admin reply

    What we verify:
    - Feedback type is product_feedback
    - admin_reply is empty
    - Attempting to publish raises HTTPException
    - Error status is 400
    """
    feedback = FeedbackMessage(
        type="product_feedback",
        name="Test User",
        email="test@example.com",
        subject="Test subject",
        message="Test message",
        page_url="/feedback",
        user_agent="test-agent",
        admin_reply=None,
        is_resolved=False,
        is_published=False,
    )
    db_session.add(feedback)
    db_session.commit()
    db_session.refresh(feedback)

    with pytest.raises(HTTPException) as exc:
        toggle_feedback_publish(db=db_session, feedback_id=feedback.id)

    assert exc.value.status_code == 400

def test_toggle_feedback_publish_publish_then_unpublish(db_session):
    """
    Test case: product feedback can be published and then unpublished

    What we verify:
    - Initial state: is_published = False
    - First toggle:
        -> becomes True
        -> published_at is set
    - Second toggle:
        -> becomes False
        -> published_at is cleared
    """
    feedback = FeedbackMessage(
        type="product_feedback",
        name="Test User",
        email="test@example.com",
        subject="Test subject",
        message="Test message",
        page_url="/feedback",
        user_agent="test-agent",
        admin_reply="Test reply",
        is_resolved=False,
        is_published=False,
    )
    db_session.add(feedback)
    db_session.commit()
    db_session.refresh(feedback)

    # publish
    updated = toggle_feedback_publish(db=db_session, feedback_id=feedback.id)
    assert updated.is_published is True
    assert updated.published_at is not None

    # unpublish
    updated = toggle_feedback_publish(db=db_session, feedback_id=feedback.id)
    assert updated.is_published is False
    assert updated.published_at is None

def test_save_feedback_reply_draft_success(db_session):
    """
    Test case: admin reply draft is saved correctly

    What we verify:
    - admin_reply is initially None
    - After saving draft:
        -> admin_reply is updated
    - Change is persisted in the database
    """
    feedback = FeedbackMessage(
        type="general_question",
        name="Test User",
        email="test@example.com",
        subject="Test subject",
        message="Test message",
        page_url="/feedback",
        user_agent="test-agent",
        admin_reply=None,
        is_resolved=False,
        is_published=False,
    )
    db_session.add(feedback)
    db_session.commit()
    db_session.refresh(feedback)

    updated = save_feedback_reply_draft(
        db=db_session,
        feedback_id=feedback.id,
        admin_reply="New reply",
    )

    assert updated.admin_reply == "New reply"

    db_session.refresh(feedback)
    assert feedback.admin_reply == "New reply"

def test_save_feedback_reply_draft_empty_string_becomes_none(db_session):
    """
    Test case: empty admin reply draft is normalized to None

    What we verify:
    - Input contains only whitespace
    - After saving draft:
        -> admin_reply becomes None
    - Change is persisted in the database
    """
    feedback = FeedbackMessage(
        type="general_question",
        name="Test User",
        email="test@example.com",
        subject="Test subject",
        message="Test message",
        page_url="/feedback",
        user_agent="test-agent",
        admin_reply="Old reply",
        is_resolved=False,
        is_published=False,
    )
    db_session.add(feedback)
    db_session.commit()
    db_session.refresh(feedback)

    updated = save_feedback_reply_draft(
        db=db_session,
        feedback_id=feedback.id,
        admin_reply="   ",
    )

    assert updated.admin_reply is None

    db_session.refresh(feedback)
    assert feedback.admin_reply is None


def test_purchase_or_download_issue_supports_one_time_email_reply(db_session):
    feedback = FeedbackMessage(
        type="purchase_or_download_issue",
        email="customer@example.com",
        subject="Download problem",
        message="The download is unavailable.",
        support_reference="DL-ABCDEFGH",
        admin_reply="I have checked your download access.",
        is_resolved=False,
        is_published=False,
    )
    db_session.add(feedback)
    db_session.commit()

    send_feedback_reply(db=db_session, feedback_id=feedback.id)
    db_session.refresh(feedback)

    assert feedback.reply_sent_at is not None
    assert feedback.reply_sent_to_email == "customer@example.com"

    with pytest.raises(HTTPException) as exc:
        send_feedback_reply(db=db_session, feedback_id=feedback.id)
    assert exc.value.status_code == 400
    assert exc.value.detail == "Email already sent"


def _submission_kwargs(**overrides):
    values = {
        "message_type": "general_question",
        "email": "service@example.com",
        "subject": "Service submission",
        "message": "This submission has enough content for service validation.",
        "name": "Service User",
        "page_url": "/feedback",
        "user_agent": "service-test-agent",
        "support_reference": None,
        "purchase_reference": None,
        "attachments": [],
    }
    values.update(overrides)
    return values


def _attachment(filename: str, content: bytes) -> FeedbackAttachmentInput:
    return FeedbackAttachmentInput(
        filename=filename,
        content_type="application/pdf",
        file=BytesIO(content),
    )


def test_submit_feedback_without_attachments_commits_complete_result(db_session):
    feedback = submit_feedback(db_session, **_submission_kwargs())

    db_session.expire_all()
    saved = db_session.get(FeedbackMessage, feedback.id)
    assert saved is not None
    assert saved.attachments == []


def test_submit_feedback_with_multiple_attachments_commits_complete_result(
    db_session,
):
    feedback = submit_feedback(
        db_session,
        **_submission_kwargs(
            attachments=[
                _attachment("first.pdf", b"%PDF first"),
                _attachment("second.pdf", b"%PDF second"),
            ]
        ),
    )

    saved = db_session.get(FeedbackMessage, feedback.id)
    assert saved is not None
    assert {item.original_filename for item in saved.attachments} == {
        "first.pdf",
        "second.pdf",
    }
    assert len(list(Path(settings.UPLOAD_DIR).iterdir())) == 2


def test_submit_feedback_validation_failure_leaves_no_feedback(db_session):
    with pytest.raises(HTTPException) as exc:
        submit_feedback(
            db_session,
            **_submission_kwargs(
                attachments=[
                    FeedbackAttachmentInput(
                        filename="malware.exe",
                        content_type="application/octet-stream",
                        file=BytesIO(b"not allowed"),
                    )
                ]
            ),
        )

    assert exc.value.status_code == 400
    assert db_session.query(FeedbackMessage).count() == 0


def test_submit_feedback_attachment_persistence_failure_is_atomic(
    db_session,
    monkeypatch,
):
    def fail_attachment(*args, **kwargs):
        raise RuntimeError("simulated attachment persistence failure")

    monkeypatch.setattr(FeedbackRepository, "create_attachment", fail_attachment)

    with pytest.raises(HTTPException) as exc:
        submit_feedback(
            db_session,
            **_submission_kwargs(
                attachments=[_attachment("failure.pdf", b"%PDF failure")]
            ),
        )

    assert exc.value.status_code == 500
    assert db_session.query(FeedbackMessage).count() == 0
    assert db_session.query(FeedbackAttachment).count() == 0
    assert list(Path(settings.UPLOAD_DIR).iterdir()) == []


def test_submit_feedback_later_attachment_failure_compensates_earlier_files(
    db_session,
    monkeypatch,
):
    original = FeedbackRepository.create_attachment
    calls = 0

    def fail_second_attachment(self, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("simulated second attachment failure")
        return original(self, **kwargs)

    monkeypatch.setattr(
        FeedbackRepository,
        "create_attachment",
        fail_second_attachment,
    )

    with pytest.raises(HTTPException):
        submit_feedback(
            db_session,
            **_submission_kwargs(
                attachments=[
                    _attachment("first.pdf", b"%PDF first"),
                    _attachment("second.pdf", b"%PDF second"),
                ]
            ),
        )

    assert db_session.query(FeedbackMessage).count() == 0
    assert db_session.query(FeedbackAttachment).count() == 0
    assert list(Path(settings.UPLOAD_DIR).iterdir()) == []


def test_submit_feedback_commit_failure_rolls_back_and_compensates_files(
    db_session,
    monkeypatch,
):
    def fail_commit():
        raise RuntimeError("simulated commit failure")

    monkeypatch.setattr(db_session, "commit", fail_commit)

    with pytest.raises(HTTPException) as exc:
        submit_feedback(
            db_session,
            **_submission_kwargs(
                attachments=[_attachment("commit-failure.pdf", b"%PDF failure")]
            ),
        )

    assert exc.value.status_code == 500
    assert db_session.query(FeedbackMessage).count() == 0
    assert db_session.query(FeedbackAttachment).count() == 0
    assert list(Path(settings.UPLOAD_DIR).iterdir()) == []


def test_feedback_repository_create_flushes_without_committing(
    db_session,
    monkeypatch,
):
    commit_calls = 0

    def record_commit():
        nonlocal commit_calls
        commit_calls += 1

    monkeypatch.setattr(db_session, "commit", record_commit)
    created = FeedbackRepository(db_session).create(
        message_type="general_question",
        email="repository@example.com",
        subject="Repository transaction",
        message="The repository must leave commit ownership to its caller.",
    )

    assert created.id is not None
    assert commit_calls == 0


def test_purchase_or_download_issue_cannot_be_published(db_session):
    feedback = FeedbackMessage(
        type="purchase_or_download_issue",
        email="customer@example.com",
        subject="Download problem",
        message="The download is unavailable.",
        support_reference="DL-ABCDEFGH",
        admin_reply="I have checked your download access.",
        is_resolved=False,
        is_published=False,
    )
    db_session.add(feedback)
    db_session.commit()

    with pytest.raises(HTTPException) as exc:
        toggle_feedback_publish(db=db_session, feedback_id=feedback.id)

    assert exc.value.status_code == 400
    assert exc.value.detail == "Only product feedback can be published"
