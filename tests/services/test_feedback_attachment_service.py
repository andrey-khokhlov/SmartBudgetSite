import pytest

from app.core.config import settings
from app.services.feedback_attachment_service import (
    UnsafeFeedbackStorageKey,
    feedback_storage_root,
    resolve_feedback_storage_path,
    sanitize_attachment_download_filename,
)


def test_resolve_feedback_storage_path_stays_below_feedback_root():
    resolved = resolve_feedback_storage_path("feedback/abc123.pdf")

    assert resolved == feedback_storage_root() / "abc123.pdf"
    assert resolved.is_relative_to(feedback_storage_root())


@pytest.mark.parametrize(
    "storage_key",
    [
        "C:/uploads/feedback/file.pdf",
        "/uploads/feedback/file.pdf",
        "../feedback/file.pdf",
        "feedback/../file.pdf",
        "feedback/nested/file.pdf",
        r"feedback\file.pdf",
        "other/file.pdf",
        "",
    ],
)
def test_resolve_feedback_storage_path_rejects_unsafe_keys(storage_key):
    with pytest.raises(UnsafeFeedbackStorageKey):
        resolve_feedback_storage_path(storage_key)


def test_sanitize_attachment_download_filename_removes_paths_and_controls():
    assert (
        sanitize_attachment_download_filename(
            'C:\\private\\client\\evil\r\n"name.pdf'
        )
        == "evilname.pdf"
    )
    assert sanitize_attachment_download_filename("...") == "attachment"
