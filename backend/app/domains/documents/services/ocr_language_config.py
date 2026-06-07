from __future__ import annotations

# ISO 639-1 → Tesseract language code mapping for F232-supported languages.
# Tesseract codes follow ISO 639-2/T (three-letter) conventions.
_ISO_TO_TESSERACT: dict[str, str] = {
    "en": "eng",
    "de": "deu",
    "es": "spa",
    "fr": "fra",
}

# Reverse mapping: Tesseract → ISO 639-1
_TESSERACT_TO_ISO: dict[str, str] = {v: k for k, v in _ISO_TO_TESSERACT.items()}

# Supported ISO 639-1 codes for OCR language configuration.
SUPPORTED_ISO_LANGUAGES: frozenset[str] = frozenset(_ISO_TO_TESSERACT.keys())

# Supported Tesseract codes for validation.
SUPPORTED_TESSERACT_CODES: frozenset[str] = frozenset(_ISO_TO_TESSERACT.values())


class UnsupportedOcrLanguageError(ValueError):
    """Raised when an unsupported OCR language code is requested."""


def iso_to_tesseract(iso_code: str) -> str:
    """Convert an ISO 639-1 code to a Tesseract language code.

    Raises :class:`UnsupportedOcrLanguageError` for unknown codes.
    """
    code = iso_code.strip().lower()
    if code in _ISO_TO_TESSERACT:
        return _ISO_TO_TESSERACT[code]
    raise UnsupportedOcrLanguageError(
        f"Unsupported OCR language: {iso_code!r}. Supported: {sorted(SUPPORTED_ISO_LANGUAGES)}"
    )


def tesseract_to_iso(tesseract_code: str) -> str | None:
    """Convert a Tesseract code back to its ISO 639-1 equivalent, or None."""
    return _TESSERACT_TO_ISO.get(tesseract_code.strip().lower())


def validate_iso_languages(iso_codes: list[str]) -> list[str]:
    """Validate a list of ISO 639-1 codes and return them normalised.

    Raises :class:`UnsupportedOcrLanguageError` on the first unsupported code.
    """
    seen: set[str] = set()
    normalised: list[str] = []
    for code in iso_codes:
        lower = code.strip().lower()
        if not lower:
            continue
        if lower not in SUPPORTED_ISO_LANGUAGES:
            raise UnsupportedOcrLanguageError(
                f"Unsupported OCR language: {code!r}. Supported: {sorted(SUPPORTED_ISO_LANGUAGES)}"
            )
        if lower not in seen:
            seen.add(lower)
            normalised.append(lower)
    return normalised


def iso_list_to_tesseract_string(iso_codes: list[str]) -> str:
    """Convert a list of ISO 639-1 codes to a Tesseract '+'-delimited language string.

    Example: ["en", "de"] → "eng+deu"
    """
    validated = validate_iso_languages(iso_codes)
    return "+".join(iso_to_tesseract(c) for c in validated)


def tesseract_string_to_iso_list(tesseract_str: str) -> list[str]:
    """Convert a Tesseract '+'/','  language string to ISO 639-1 codes.

    Unknown codes are silently dropped.
    """
    codes = [c.strip() for c in tesseract_str.replace("+", ",").split(",") if c.strip()]
    return [iso for tess in codes for iso in [tesseract_to_iso(tess)] if iso]


def resolve_ocr_tesseract_string(
    *,
    ocr_override: str | None,
    document_language: str | None,
    system_default: str,
) -> str:
    """Resolve the effective Tesseract language string for OCR.

    Priority:
    1. Per-document ``ocr_override`` (comma-separated Tesseract codes stored on Document).
    2. ``document_language`` (ISO 639-1, from F230 detection) mapped to Tesseract.
    3. ``system_default`` Tesseract string from config.
    """
    if ocr_override and ocr_override.strip():
        return ocr_override.strip()

    if document_language:
        lower = document_language.strip().lower()
        if lower in _ISO_TO_TESSERACT:
            return _ISO_TO_TESSERACT[lower]

    return system_default
