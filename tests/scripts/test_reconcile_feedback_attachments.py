from pathlib import Path

from app.models.feedback import FeedbackMessage
from app.models.feedback_attachment import FeedbackAttachment
from app.services.feedback_attachment_service import (
    feedback_storage_root,
    resolve_feedback_storage_path,
)
from scripts.reconcile_feedback_attachments import (
    reconcile_feedback_attachments,
)

VALID_KEY = "feedback/0123456789abcdef0123456789abcdef.pdf"
ORPHAN_KEY = "feedback/fedcba9876543210fedcba9876543210.pdf"


def _create_attachment_row(db_session, storage_key: str) -> FeedbackAttachment:
    feedback = FeedbackMessage(
        type="general_question",
        email="reconcile@example.com",
        subject="Reconciliation test",
        message="This feedback owns a reconciliation attachment row.",
    )
    db_session.add(feedback)
    db_session.flush()
    attachment = FeedbackAttachment(
        feedback_id=feedback.id,
        original_filename="evidence.pdf",
        storage_type="local",
        storage_key=storage_key,
        content_type="application/pdf",
        file_size_bytes=9,
    )
    db_session.add(attachment)
    db_session.commit()
    return attachment


def test_reconciliation_reports_missing_files_and_unsafe_keys(
    db_session,
):
    _create_attachment_row(db_session, VALID_KEY)
    _create_attachment_row(db_session, "C:/unsafe/legacy.pdf")
    output = []

    report = reconcile_feedback_attachments(
        db_session,
        output=output.append,
    )

    assert report.missing_file_keys == (VALID_KEY,)
    assert report.unsafe_persisted_keys == ("C:/unsafe/legacy.pdf",)
    assert any("Missing attachment files: 1" in line for line in output)
    assert any("Unsafe persisted storage keys: 1" in line for line in output)


def test_reconciliation_reports_orphans_and_is_read_only_by_default(
    db_session,
):
    orphan = resolve_feedback_storage_path(ORPHAN_KEY)
    orphan.parent.mkdir(parents=True)
    orphan.write_bytes(b"orphan")

    report = reconcile_feedback_attachments(db_session, output=lambda line: None)

    assert report.orphan_file_keys == (ORPHAN_KEY,)
    assert report.deleted_orphan_keys == ()
    assert orphan.exists()


def test_reconciliation_delete_flag_removes_only_validated_orphans(
    db_session,
    tmp_path,
):
    orphan = resolve_feedback_storage_path(ORPHAN_KEY)
    orphan.parent.mkdir(parents=True)
    orphan.write_bytes(b"orphan")
    unvalidated = feedback_storage_root() / "manual-file.pdf"
    unvalidated.write_bytes(b"keep")
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"outside")

    report = reconcile_feedback_attachments(
        db_session,
        delete_orphans=True,
        output=lambda line: None,
    )

    assert report.deleted_orphan_keys == (ORPHAN_KEY,)
    assert not orphan.exists()
    assert unvalidated.exists()
    assert outside.exists()


def test_reconciliation_does_not_delete_files_for_database_rows(
    db_session,
):
    _create_attachment_row(db_session, VALID_KEY)
    owned = resolve_feedback_storage_path(VALID_KEY)
    owned.parent.mkdir(parents=True)
    owned.write_bytes(b"owned")

    report = reconcile_feedback_attachments(
        db_session,
        delete_orphans=True,
        output=lambda line: None,
    )

    assert report.orphan_file_keys == ()
    assert report.deleted_orphan_keys == ()
    assert owned.exists()
