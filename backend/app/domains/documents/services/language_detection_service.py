from __future__ import annotations

from dataclasses import dataclass

_SUPPORTED_LANGUAGES: frozenset[str] = frozenset({"en", "de", "es", "fr"})

# Minimum sample length for reliable detection.
_MIN_SAMPLE_LENGTH = 20

# Characters strongly associated with each language.
_DE_CHARS: frozenset[str] = frozenset("äöüÄÖÜß")
_ES_CHARS: frozenset[str] = frozenset("ñÑ¿¡")
# French accented vowels and ligatures. Overlap with other Romance languages is
# resolved by ES taking priority (¿/¡/ñ are unambiguous).
_FR_CHARS: frozenset[str] = frozenset("àâçéèêëîïôùûüœæÀÂÇÉÈÊËÎÏÔÙÛÜŒÆ")

# Confidence is calibrated as: density of diagnostic characters relative to text length.
# DE and ES markers are highly distinctive; FR markers are more common across Romance langs.
_DE_CONFIDENCE_SCALE = 8.0
_ES_CONFIDENCE_SCALE = 12.0
_FR_CONFIDENCE_SCALE = 5.0
_CONFIDENCE_CAP = 1.0


@dataclass(frozen=True)
class LanguageDetectionResult:
    language_code: str | None
    confidence: float
    source: str = "auto_detected"


def detect_language_from_text(
    text: str,
    *,
    supported_languages: frozenset[str] | None = None,
) -> LanguageDetectionResult:
    """Detect the primary language of *text* from the supported set.

    Returns a :class:`LanguageDetectionResult` with ``language_code=None``
    and ``confidence=0.0`` when the sample is too short or no language signal
    is found.  Detection is heuristic-only (character frequency) — deterministic,
    cheap, and dependency-free.
    """
    effective_supported = (
        supported_languages if supported_languages is not None else _SUPPORTED_LANGUAGES
    )

    if not text or not text.strip():
        return LanguageDetectionResult(language_code=None, confidence=0.0)

    # Sample up to 4 000 characters for speed; language signal is dense at document start.
    sample = text.strip()[:4000]
    length = len(sample)
    if length < _MIN_SAMPLE_LENGTH:
        return LanguageDetectionResult(language_code=None, confidence=0.0)

    de_count = sum(1 for ch in sample if ch in _DE_CHARS)
    es_count = sum(1 for ch in sample if ch in _ES_CHARS)
    fr_count = sum(1 for ch in sample if ch in _FR_CHARS)

    # Density per 100 characters.
    de_density = de_count / length * 100
    es_density = es_count / length * 100
    fr_density = fr_count / length * 100

    # Spanish markers are unambiguous (¿/¡/ñ have no false-positive overlap).
    if "es" in effective_supported and es_density > 0:
        confidence = min(_CONFIDENCE_CAP, es_density * _ES_CONFIDENCE_SCALE / 100)
        return LanguageDetectionResult(language_code="es", confidence=round(confidence, 3))

    # German markers (ä/ö/ü/ß) are distinctive within Latin-script languages.
    if "de" in effective_supported and de_density > 0:
        confidence = min(_CONFIDENCE_CAP, de_density * _DE_CONFIDENCE_SCALE / 100)
        return LanguageDetectionResult(language_code="de", confidence=round(confidence, 3))

    # French accented vowels — only checked when ES and DE signals are absent.
    if "fr" in effective_supported and fr_density > 0:
        confidence = min(_CONFIDENCE_CAP, fr_density * _FR_CONFIDENCE_SCALE / 100)
        return LanguageDetectionResult(language_code="fr", confidence=round(confidence, 3))

    # Fall back to English for ASCII-dominant text.
    ascii_count = sum(1 for ch in sample if ord(ch) < 128)
    ascii_ratio = ascii_count / length
    if "en" in effective_supported and ascii_ratio >= 0.92:
        confidence = round(0.4 + ascii_ratio * 0.5, 3)
        return LanguageDetectionResult(
            language_code="en", confidence=min(_CONFIDENCE_CAP, confidence)
        )

    return LanguageDetectionResult(language_code=None, confidence=0.0)


def confidence_bucket(confidence: float) -> str:
    """Map a detection confidence value to a human-readable bucket."""
    if confidence >= 0.7:
        return "high"
    if confidence >= 0.3:
        return "medium"
    return "low"
