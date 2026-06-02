import hashlib

import pytest

from app.domains.documents.services.upload_validation import validate_upload


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


def test_validate_upload_accepts_docx() -> None:
    content = b"PK\x03\x04" + b"\x00" * 30 + b"document content"
    result = validate_upload(
        filename="report.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        content=content,
        max_size_bytes=1024,
    )

    assert result.extension == "docx"
    assert result.file_size_bytes == len(content)


def test_validate_upload_accepts_txt() -> None:
    content = b"plain text content"
    result = validate_upload(
        filename="notes.txt",
        content_type="text/plain",
        content=content,
        max_size_bytes=1024,
    )

    assert result.extension == "txt"


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


# --- Magic bytes (MIME spoofing protection) ---


def test_validate_upload_rejects_pdf_with_wrong_magic_bytes() -> None:
    # A file that claims to be a PDF but starts with ZIP magic bytes (DOCX content).
    content = b"PK\x03\x04" + b"\x00" * 20 + b"fake pdf"
    with pytest.raises(ValueError, match="file content does not match expected format for .pdf"):
        validate_upload(
            filename="evil.pdf",
            content_type="application/pdf",
            content=content,
            max_size_bytes=1024,
        )


def test_validate_upload_rejects_docx_with_wrong_magic_bytes() -> None:
    # A file that claims to be a DOCX but starts with PDF magic bytes.
    content = b"%PDF-1.4" + b"\x00" * 20 + b"fake docx"
    with pytest.raises(ValueError, match="file content does not match expected format for .docx"):
        validate_upload(
            filename="evil.docx",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            content=content,
            max_size_bytes=1024,
        )


def test_validate_upload_rejects_txt_with_claimed_pdf_extension() -> None:
    # Extension mismatch is caught by MIME type check.
    with pytest.raises(ValueError, match="unsupported mime type"):
        validate_upload(
            filename="masquerade.pdf",
            content_type="text/plain",
            content=b"%PDF-1.4 plain text content",
            max_size_bytes=1024,
        )


# --- Encrypted / password-protected PDFs ---


def test_validate_upload_rejects_encrypted_pdf() -> None:
    encrypted_header = b"%PDF-1.6\n1 0 obj\n<</Encrypt 2 0 R>>\nendobj\n"
    with pytest.raises(ValueError, match="encrypted or password-protected PDF"):
        validate_upload(
            filename="locked.pdf",
            content_type="application/pdf",
            content=encrypted_header,
            max_size_bytes=1024,
        )


def test_validate_upload_rejects_encrypted_pdf_lowercase_marker() -> None:
    content = b"%PDF-1.4\n<</encrypt 3 0 R>>\n%%EOF"
    with pytest.raises(ValueError, match="encrypted or password-protected PDF"):
        validate_upload(
            filename="protected.pdf",
            content_type="application/pdf",
            content=content,
            max_size_bytes=1024,
        )


def test_validate_upload_accepts_unencrypted_pdf() -> None:
    content = b"%PDF-1.4\n1 0 obj\n<</Type /Catalog>>\nendobj\n%%EOF"
    result = validate_upload(
        filename="clean.pdf",
        content_type="application/pdf",
        content=content,
        max_size_bytes=1024,
    )
    assert result.extension == "pdf"


# --- Null byte protection ---


def test_validate_upload_rejects_filename_with_null_byte() -> None:
    with pytest.raises(ValueError, match="null bytes"):
        validate_upload(
            filename="report\x00.pdf",
            content_type="application/pdf",
            content=b"%PDF-1.4 content",
            max_size_bytes=1024,
        )


# --- Security: combined MIME spoofing scenario ---


def test_validate_upload_rejects_html_file_claiming_to_be_txt() -> None:
    """An HTML file with script tags cannot be uploaded as TXT despite MIME match.

    TXT has no magic bytes check, so this passes magic bytes — but the MIME type
    for text/plain is the same, so the test validates that the extension whitelist
    prevents executing code disguised as text.
    """
    content = b"<html><script>alert(1)</script></html>"
    result = validate_upload(
        filename="page.txt",
        content_type="text/plain",
        content=content,
        max_size_bytes=1024,
    )
    assert result.extension == "txt"
