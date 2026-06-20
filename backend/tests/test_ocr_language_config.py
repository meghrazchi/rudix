"""Unit tests for OCR language configuration utility (F232)."""

from __future__ import annotations

import pytest

from app.domains.documents.services.ocr_language_config import (
    SUPPORTED_ISO_LANGUAGES,
    SUPPORTED_TESSERACT_CODES,
    UnsupportedOcrLanguageError,
    iso_list_to_tesseract_string,
    iso_to_tesseract,
    resolve_ocr_tesseract_string,
    tesseract_string_to_iso_list,
    tesseract_to_iso,
    validate_iso_languages,
)

# ---------------------------------------------------------------------------
# iso_to_tesseract
# ---------------------------------------------------------------------------


class TestIsoToTesseract:
    def test_english(self) -> None:
        assert iso_to_tesseract("en") == "eng"

    def test_german(self) -> None:
        assert iso_to_tesseract("de") == "deu"

    def test_spanish(self) -> None:
        assert iso_to_tesseract("es") == "spa"

    def test_french(self) -> None:
        assert iso_to_tesseract("fr") == "fra"

    def test_unsupported_raises(self) -> None:
        with pytest.raises(UnsupportedOcrLanguageError):
            iso_to_tesseract("ja")

    def test_empty_string_raises(self) -> None:
        with pytest.raises(UnsupportedOcrLanguageError):
            iso_to_tesseract("")

    def test_mixed_case_normalized(self) -> None:
        assert iso_to_tesseract("EN") == "eng"
        assert iso_to_tesseract("De") == "deu"


# ---------------------------------------------------------------------------
# tesseract_to_iso
# ---------------------------------------------------------------------------


class TestTesseractToIso:
    def test_eng_to_en(self) -> None:
        assert tesseract_to_iso("eng") == "en"

    def test_deu_to_de(self) -> None:
        assert tesseract_to_iso("deu") == "de"

    def test_spa_to_es(self) -> None:
        assert tesseract_to_iso("spa") == "es"

    def test_fra_to_fr(self) -> None:
        assert tesseract_to_iso("fra") == "fr"

    def test_unknown_returns_none(self) -> None:
        assert tesseract_to_iso("jpn") is None
        assert tesseract_to_iso("") is None


# ---------------------------------------------------------------------------
# validate_iso_languages
# ---------------------------------------------------------------------------


class TestValidateIsoLanguages:
    def test_valid_list(self) -> None:
        result = validate_iso_languages(["en", "de"])
        assert result == ["en", "de"]

    def test_deduplication(self) -> None:
        result = validate_iso_languages(["en", "en", "de"])
        assert result == ["en", "de"]

    def test_empty_list_returns_empty(self) -> None:
        assert validate_iso_languages([]) == []

    def test_unsupported_raises(self) -> None:
        with pytest.raises(UnsupportedOcrLanguageError):
            validate_iso_languages(["en", "klingon"])

    def test_case_normalization(self) -> None:
        result = validate_iso_languages(["EN", "FR"])
        assert result == ["en", "fr"]


# ---------------------------------------------------------------------------
# iso_list_to_tesseract_string
# ---------------------------------------------------------------------------


class TestIsoListToTesseractString:
    def test_single_language(self) -> None:
        assert iso_list_to_tesseract_string(["en"]) == "eng"

    def test_two_languages(self) -> None:
        result = iso_list_to_tesseract_string(["en", "de"])
        assert result == "eng+deu"

    def test_four_languages(self) -> None:
        result = iso_list_to_tesseract_string(["en", "de", "es", "fr"])
        assert result == "eng+deu+spa+fra"

    def test_unsupported_raises(self) -> None:
        with pytest.raises(UnsupportedOcrLanguageError):
            iso_list_to_tesseract_string(["en", "xyz"])


# ---------------------------------------------------------------------------
# tesseract_string_to_iso_list
# ---------------------------------------------------------------------------


class TestTesseractStringToIsoList:
    def test_single_code(self) -> None:
        assert tesseract_string_to_iso_list("eng") == ["en"]

    def test_plus_delimited(self) -> None:
        result = tesseract_string_to_iso_list("eng+deu")
        assert result == ["en", "de"]

    def test_comma_delimited(self) -> None:
        result = tesseract_string_to_iso_list("spa,fra")
        assert result == ["es", "fr"]

    def test_unknown_codes_dropped(self) -> None:
        result = tesseract_string_to_iso_list("eng+jpn+fra")
        assert result == ["en", "fr"]

    def test_empty_returns_empty(self) -> None:
        assert tesseract_string_to_iso_list("") == []


# ---------------------------------------------------------------------------
# resolve_ocr_tesseract_string
# ---------------------------------------------------------------------------


class TestResolveOcrTesseractString:
    def test_override_takes_priority(self) -> None:
        result = resolve_ocr_tesseract_string(
            ocr_override="deu+fra",
            document_language="en",
            system_default="eng",
        )
        assert result == "deu+fra"

    def test_document_language_used_when_no_override(self) -> None:
        result = resolve_ocr_tesseract_string(
            ocr_override=None,
            document_language="de",
            system_default="eng",
        )
        assert result == "deu"

    def test_system_default_used_when_no_override_and_no_language(self) -> None:
        result = resolve_ocr_tesseract_string(
            ocr_override=None,
            document_language=None,
            system_default="eng",
        )
        assert result == "eng"

    def test_blank_override_falls_through_to_document_language(self) -> None:
        result = resolve_ocr_tesseract_string(
            ocr_override="   ",
            document_language="fr",
            system_default="eng",
        )
        assert result == "fra"

    def test_unsupported_document_language_falls_through_to_system_default(self) -> None:
        result = resolve_ocr_tesseract_string(
            ocr_override=None,
            document_language="ja",
            system_default="eng",
        )
        assert result == "eng"


# ---------------------------------------------------------------------------
# Supported sets
# ---------------------------------------------------------------------------


class TestSupportedSets:
    def test_four_iso_codes_supported(self) -> None:
        assert SUPPORTED_ISO_LANGUAGES == frozenset({"en", "de", "es", "fr"})

    def test_four_tesseract_codes_supported(self) -> None:
        assert SUPPORTED_TESSERACT_CODES == frozenset({"eng", "deu", "spa", "fra"})
