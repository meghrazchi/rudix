import hashlib

import pytest

from app.services.upload_validation import validate_upload


def test_validate_upload_accepts_pdf() -> None:
    content = b"%PDF-1.7\nsample"
    result = validate_upload(
        filename="sample.pdf",
        content_type="application/pdf",
        content=content,
        max_size_bytes=1024,
    )

    assert result.extension == "pdf"
    assert result.content_type == "application/pdf"
    assert result.file_size_bytes == len(content)
    assert result.checksum_sha256 == hashlib.sha256(content).hexdigest()


def test_validate_upload_normalizes_mime_parameters() -> None:
    result = validate_upload(
        filename="sample.txt",
        content_type="text/plain; charset=utf-8",
        content=b"hello",
        max_size_bytes=1024,
    )

    assert result.content_type == "text/plain"


@pytest.mark.parametrize(
    ("filename", "content_type", "error_message"),
    [
        ("sample.exe", "application/x-msdownload", "unsupported file extension"),
        ("sample.pdf", "text/plain", "unsupported mime type"),
        ("", "application/pdf", "filename is required"),
        ("folder/sample.pdf", "application/pdf", "filename must not contain path separators"),
    ],
)
def test_validate_upload_rejects_invalid_metadata(
    filename: str,
    content_type: str,
    error_message: str,
) -> None:
    with pytest.raises(ValueError, match=error_message):
        validate_upload(
            filename=filename,
            content_type=content_type,
            content=b"content",
            max_size_bytes=1024,
        )


def test_validate_upload_rejects_empty_file() -> None:
    with pytest.raises(ValueError, match="empty file"):
        validate_upload(
            filename="sample.txt",
            content_type="text/plain",
            content=b"",
            max_size_bytes=1024,
        )


def test_validate_upload_rejects_oversized_file() -> None:
    with pytest.raises(OverflowError, match="file size exceeds configured limit"):
        validate_upload(
            filename="sample.txt",
            content_type="text/plain",
            content=b"a" * 11,
            max_size_bytes=10,
        )
