import hashlib
from io import BytesIO

import pytest

from app.services.product_release_service import (
    RELEASE_ARCHIVE_INSPECTION_CHUNK_SIZE,
    ReleaseArchiveTooLargeError,
    inspect_release_archive,
)


class RecordingBytesIO(BytesIO):
    def __init__(self, content: bytes) -> None:
        super().__init__(content)
        self.read_sizes: list[int | None] = []

    def read(self, size: int | None = -1) -> bytes:
        self.read_sizes.append(size)
        return super().read(size)


class FailingBytesIO(BytesIO):
    def read(self, size: int | None = -1) -> bytes:
        raise OSError("test read failure")


def test_inspect_release_archive_calculates_metadata_in_bounded_chunks() -> None:
    content = b"a" * RELEASE_ARCHIVE_INSPECTION_CHUNK_SIZE + b"tail"
    file_obj = RecordingBytesIO(content)

    metadata = inspect_release_archive(file_obj, max_bytes=len(content))

    assert metadata.file_size == len(content)
    assert metadata.sha256_hash == hashlib.sha256(content).hexdigest()
    assert len(file_obj.read_sizes) >= 3
    assert all(
        read_size is not None and 0 < read_size <= RELEASE_ARCHIVE_INSPECTION_CHUNK_SIZE
        for read_size in file_obj.read_sizes
    )
    assert file_obj.tell() == 0


def test_inspect_release_archive_accepts_exact_boundary() -> None:
    file_obj = BytesIO(b"exact")

    metadata = inspect_release_archive(file_obj, max_bytes=5)

    assert metadata.file_size == 5
    assert file_obj.tell() == 0


def test_inspect_release_archive_rejects_limit_plus_one_and_rewinds() -> None:
    file_obj = RecordingBytesIO(b"oversized")

    with pytest.raises(ReleaseArchiveTooLargeError):
        inspect_release_archive(file_obj, max_bytes=8)

    assert file_obj.read_sizes == [9]
    assert file_obj.tell() == 0


def test_inspect_release_archive_rewinds_after_read_failure() -> None:
    file_obj = FailingBytesIO(b"content")

    with pytest.raises(OSError, match="test read failure"):
        inspect_release_archive(file_obj, max_bytes=10)

    assert file_obj.tell() == 0


@pytest.mark.parametrize("max_bytes", [0, -2])
def test_inspect_release_archive_rejects_non_positive_limit_without_reading(
    max_bytes: int,
) -> None:
    file_obj = RecordingBytesIO(b"content")

    with pytest.raises(ValueError, match="max_bytes must be greater than zero"):
        inspect_release_archive(file_obj, max_bytes=max_bytes)

    assert file_obj.read_sizes == []
    assert file_obj.closed is False
