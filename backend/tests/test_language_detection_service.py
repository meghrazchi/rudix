"""Unit tests for the document language detection service (F230)."""
from __future__ import annotations

import pytest

from app.domains.documents.services.language_detection_service import (
    LanguageDetectionResult,
    confidence_bucket,
    detect_language_from_text,
)


# ---------------------------------------------------------------------------
# detect_language_from_text
# ---------------------------------------------------------------------------


class TestDetectLanguageFromText:
    def test_empty_string_returns_none(self) -> None:
        result = detect_language_from_text("")
        assert result.language_code is None
        assert result.confidence == 0.0

    def test_whitespace_only_returns_none(self) -> None:
        result = detect_language_from_text("   \n\t  ")
        assert result.language_code is None
        assert result.confidence == 0.0

    def test_too_short_returns_none(self) -> None:
        result = detect_language_from_text("ok")
        assert result.language_code is None

    # --- English ---

    def test_plain_ascii_returns_english(self) -> None:
        text = (
            "The quick brown fox jumps over the lazy dog. "
            "This document describes the company annual report and financial results."
        )
        result = detect_language_from_text(text)
        assert result.language_code == "en"
        assert result.confidence > 0.0

    def test_english_with_high_ascii_ratio(self) -> None:
        text = "Revenue grew by fifteen percent in the third quarter. " * 10
        result = detect_language_from_text(text)
        assert result.language_code == "en"

    # --- German ---

    def test_detects_german_with_umlaut(self) -> None:
        text = (
            "Das Unternehmen hat im vergangenen Geschäftsjahr erhebliche "
            "Fortschritte erzielt. Die Mitarbeiter sind sehr zufrieden. "
            "Über die Strategie für die nächsten Jahre wird ausführlich diskutiert."
        )
        result = detect_language_from_text(text)
        assert result.language_code == "de"
        assert result.confidence > 0.0

    def test_detects_german_sharp_s(self) -> None:
        text = "Das ist die größte Straße in der ganzen Stadt. " * 5
        result = detect_language_from_text(text)
        assert result.language_code == "de"

    # --- Spanish ---

    def test_detects_spanish_with_question_mark(self) -> None:
        text = "¿Cómo estás? ¿Qué tal el trabajo? ¡Excelente! " * 5
        result = detect_language_from_text(text)
        assert result.language_code == "es"
        assert result.confidence > 0.0

    def test_detects_spanish_with_tilde_n(self) -> None:
        text = "El señor González trabaja en la oficina central de España. " * 5
        result = detect_language_from_text(text)
        assert result.language_code == "es"

    # --- French ---

    def test_detects_french_with_accents(self) -> None:
        text = (
            "La société française a publié son rapport annuel. "
            "Les résultats sont très encourageants pour l'avenir. "
            "L'équipe est très motivée et prête à relever de nouveaux défis." * 3
        )
        result = detect_language_from_text(text)
        assert result.language_code == "fr"
        assert result.confidence > 0.0

    def test_detects_french_cedilla(self) -> None:
        text = "La façade du bâtiment a été rénovée récemment. " * 5
        result = detect_language_from_text(text)
        assert result.language_code == "fr"

    # --- Spanish takes priority over French ---

    def test_spanish_priority_over_french(self) -> None:
        # ¿/¡ markers should always win over French accents
        text = "¿Es posible que cette chose soit correcte? ¡Oui! " * 5
        result = detect_language_from_text(text)
        assert result.language_code == "es"

    # --- Unsupported language subset ---

    def test_custom_supported_set_excludes_english(self) -> None:
        text = "The quick brown fox jumps over the lazy dog." * 5
        result = detect_language_from_text(text, supported_languages=frozenset({"de", "es", "fr"}))
        # ASCII text won't match DE/ES/FR → should return None
        assert result.language_code is None

    def test_custom_supported_set_detects_only_german(self) -> None:
        text = "Das Unternehmen wächst über die Grenzen hinaus. " * 5
        result = detect_language_from_text(text, supported_languages=frozenset({"de"}))
        assert result.language_code == "de"

    # --- Confidence bounds ---

    def test_confidence_between_zero_and_one(self) -> None:
        texts = [
            "The quick brown fox." * 10,
            "Das Unternehmen ist groß. " * 10,
            "¿Cómo estás? " * 10,
            "La façade du château. " * 10,
        ]
        for text in texts:
            result = detect_language_from_text(text)
            if result.language_code is not None:
                assert 0.0 <= result.confidence <= 1.0

    def test_source_is_auto_detected(self) -> None:
        result = detect_language_from_text("The quick brown fox jumps." * 5)
        assert result.source == "auto_detected"

    def test_returns_language_detection_result_type(self) -> None:
        result = detect_language_from_text("Hello world, this is a test sentence." * 3)
        assert isinstance(result, LanguageDetectionResult)


# ---------------------------------------------------------------------------
# confidence_bucket
# ---------------------------------------------------------------------------


class TestConfidenceBucket:
    def test_high_confidence(self) -> None:
        assert confidence_bucket(0.9) == "high"

    def test_medium_confidence(self) -> None:
        assert confidence_bucket(0.5) == "medium"

    def test_low_confidence(self) -> None:
        assert confidence_bucket(0.1) == "low"

    def test_zero_confidence(self) -> None:
        assert confidence_bucket(0.0) == "low"

    def test_exact_boundaries(self) -> None:
        assert confidence_bucket(0.7) == "high"
        assert confidence_bucket(0.3) == "medium"
        assert confidence_bucket(0.29) == "low"
