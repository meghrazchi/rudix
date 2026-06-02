from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

_ALLOWED_MIME_BY_EXTENSION: dict[str, set[str]] = {
    "pdf": {"application/pdf"},
    "txt": {"text/plain"},
    "docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
}

# Magic bytes per extension: (offset, expected_bytes)
_MAGIC_BYTES: dict[str, tuple[int, bytes]] = {
    "pdf": (0, b"%PDF"),
    "docx": (0, b"PK\x03\x04"),
}

# Encrypted PDF marker — presence of /Encrypt dictionary in PDF structure.
_PDF_ENCRYPT_MARKER = b"/Encrypt"
_PDF_HEADER_SCAN_BYTES = 8192


@dataclass(frozen=True)
class UploadValidationResult:
    normalized_filename: str
    extension: str
    content_type: str
    file_size_bytes: int
    checksum_sha256: str


def _normalize_filename(filename: str) -> str:
    cleaned = filename.strip()
    if not cleaned:
        raise ValueError("filename is required")
    if "/" in cleaned or "\\" in cleaned:
        raise ValueError("filename must not contain path separators")
    if "\x00" in cleaned:
        raise ValueError("filename must not contain null bytes")
    return cleaned


def _extract_extension(filename: str) -> str:
    suffix = Path(filename).suffix.lower().lstrip(".")
    if not suffix:
        raise ValueError("file extension is required")
    if suffix not in _ALLOWED_MIME_BY_EXTENSION:
        raise ValueError("unsupported file extension")
    return suffix


def _normalize_content_type(content_type: str | None) -> str:
    normalized = (content_type or "").strip().lower()
    if not normalized:
        raise ValueError("content type is required")
    normalized = normalized.split(";", maxsplit=1)[0].strip()
    return normalized


def _check_magic_bytes(*, extension: str, content: bytes) -> None:
    """Verify file content starts with the expected magic bytes (MIME spoofing guard)."""
    if extension not in _MAGIC_BYTES:
        return
    offset, expected = _MAGIC_BYTES[extension]
    if len(content) < offset + len(expected) or content[offset : offset + len(expected)] != expected:
        raise ValueError(f"file content does not match expected format for .{extension}")


def _check_encrypted_pdf(*, extension: str, content: bytes) -> None:
    """Reject password-protected PDFs by detecting the /Encrypt dictionary."""
    if extension != "pdf":
        return
    header = content[:_PDF_HEADER_SCAN_BYTES]
    if _PDF_ENCRYPT_MARKER in header or _PDF_ENCRYPT_MARKER.lower() in header.lower():
        raise ValueError("encrypted or password-protected PDF files are not supported")


def validate_upload(
    *,
    filename: str,
    content_type: str | None,
    content: bytes,
    max_size_bytes: int,
) -> UploadValidationResult:
    normalized_filename = _normalize_filename(filename)
    extension = _extract_extension(normalized_filename)
    normalized_content_type = _normalize_content_type(content_type)

    allowed_mime_types = _ALLOWED_MIME_BY_EXTENSION[extension]
    if normalized_content_type not in allowed_mime_types:
        raise ValueError("unsupported mime type")

    file_size_bytes = len(content)
    if file_size_bytes == 0:
        raise ValueError("empty file")
    if file_size_bytes > max_size_bytes:
        raise OverflowError("file size exceeds configured limit")

    _check_magic_bytes(extension=extension, content=content)
    _check_encrypted_pdf(extension=extension, content=content)

    checksum_sha256 = hashlib.sha256(content).hexdigest()
    return UploadValidationResult(
        normalized_filename=normalized_filename,
        extension=extension,
        content_type=normalized_content_type,
        file_size_bytes=file_size_bytes,
        checksum_sha256=checksum_sha256,
    )
