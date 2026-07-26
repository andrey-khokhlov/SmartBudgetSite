from pathlib import Path

from app.core.config import settings
from app.models.feedback import FeedbackMessage
from app.models.feedback_attachment import FeedbackAttachment
from app.services.feedback_attachment_service import (
    feedback_storage_root,
    resolve_feedback_storage_path,
)


def _create_feedback_attachment(
    db_session,
    *,
    original_filename: str = "evidence.pdf",
    storage_key: str = "feedback/0123456789abcdef0123456789abcdef.pdf",
    write_file: bool = True,
):
    feedback = FeedbackMessage(
        type="general_question",
        email="admin-download@example.com",
        subject="Attachment download",
        message="This feedback has an attachment for admin review.",
    )
    db_session.add(feedback)
    db_session.flush()
    attachment = FeedbackAttachment(
        feedback_id=feedback.id,
        original_filename=original_filename,
        storage_type="local",
        storage_key=storage_key,
        content_type="application/pdf",
        file_size_bytes=9,
    )
    db_session.add(attachment)
    db_session.commit()
    if write_file:
        path = resolve_feedback_storage_path(storage_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"%PDF test")
    return feedback, attachment


def test_admin_attachment_download_requires_authentication(
    client,
    db_session,
):
    feedback, attachment = _create_feedback_attachment(db_session)

    response = client.get(
        f"/admin/feedback/{feedback.id}/attachments/{attachment.id}"
    )

    assert response.status_code == 403


def test_admin_attachment_download_succeeds_with_safe_headers(
    auth_client,
    db_session,
):
    feedback, attachment = _create_feedback_attachment(
        db_session,
        original_filename='C:\\private\\customer\\evidence\r\n".pdf',
    )

    response = auth_client.get(
        f"/admin/feedback/{feedback.id}/attachments/{attachment.id}"
    )

    assert response.status_code == 200
    assert response.content == b"%PDF test"
    assert response.headers["x-content-type-options"] == "nosniff"
    disposition = response.headers["content-disposition"]
    assert "attachment" in disposition
    assert "evidence.pdf" in disposition
    assert "private" not in disposition
    assert "\r" not in disposition
    assert "\n" not in disposition
    assert attachment.storage_key not in str(response.url)


def test_admin_attachment_download_rejects_wrong_feedback_owner(
    auth_client,
    db_session,
):
    feedback, attachment = _create_feedback_attachment(db_session)
    other = FeedbackMessage(
        type="general_question",
        email="other@example.com",
        subject="Other feedback",
        message="This is another feedback message.",
    )
    db_session.add(other)
    db_session.commit()

    response = auth_client.get(
        f"/admin/feedback/{other.id}/attachments/{attachment.id}"
    )

    assert response.status_code == 404


def test_admin_attachment_download_rejects_missing_row(
    auth_client,
    db_session,
):
    feedback = FeedbackMessage(
        type="general_question",
        email="missing@example.com",
        subject="Missing attachment",
        message="The requested attachment row does not exist.",
    )
    db_session.add(feedback)
    db_session.commit()

    response = auth_client.get(
        f"/admin/feedback/{feedback.id}/attachments/999999"
    )

    assert response.status_code == 404


def test_admin_attachment_download_handles_missing_file(
    auth_client,
    db_session,
):
    feedback, attachment = _create_feedback_attachment(
        db_session,
        write_file=False,
    )

    response = auth_client.get(
        f"/admin/feedback/{feedback.id}/attachments/{attachment.id}"
    )

    assert response.status_code == 404
    assert "storage_key" not in response.text
    assert str(feedback_storage_root()) not in response.text


def test_admin_attachment_download_rejects_unsafe_persisted_key(
    auth_client,
    db_session,
):
    feedback, attachment = _create_feedback_attachment(
        db_session,
        storage_key=str(Path(settings.UPLOAD_DIR).resolve() / "outside.pdf"),
        write_file=False,
    )

    response = auth_client.get(
        f"/admin/feedback/{feedback.id}/attachments/{attachment.id}"
    )

    assert response.status_code == 404


def test_admin_feedback_detail_links_owned_attachment(
    auth_client,
    db_session,
):
    feedback, attachment = _create_feedback_attachment(db_session)

    response = auth_client.get(f"/admin/feedback/{feedback.id}")

    assert response.status_code == 200
    assert (
        f"/admin/feedback/{feedback.id}/attachments/{attachment.id}"
        in response.text
    )
    assert attachment.storage_key not in response.text
