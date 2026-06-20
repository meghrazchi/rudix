from __future__ import annotations

import re

_SUPPORTED_LANGUAGES: frozenset[str] = frozenset({"en", "de", "es", "fr"})

_LANGUAGE_NAMES: dict[str, str] = {
    "en": "English",
    "de": "German",
    "es": "Spanish",
    "fr": "French",
}

# Character sets strongly associated with specific languages.
_DE_CHARS: frozenset[str] = frozenset("äöüÄÖÜß")
_ES_CHARS: frozenset[str] = frozenset("ñÑ¿¡")
_FR_CHARS: frozenset[str] = frozenset("àâçéèêëîïôùûüœæÀÂÇÉÈÊËÎÏÔÙÛÜŒÆ")
_DE_MARKER_WORDS: frozenset[str] = frozenset(
    {
        "der",
        "die",
        "das",
        "ist",
        "und",
        "von",
        "mit",
        "nicht",
        "war",
        "was",
        "für",
        "den",
        "dem",
        "wie",
        "gibt",
        "es",
        "laut",
        "richtlinien",
        "urlaub",
        "urlaubstage",
        "tage",
        "bitte",
        "kann",
        "können",
        "sind",
        "sein",
        "zum",
        "zur",
        "dass",
    }
)


def detect_language(text: str) -> str | None:
    """Detect the language of *text* from EN/DE/ES/FR.

    Returns an ISO-639-1 code or None when confidence is too low.
    Detection is heuristic-only (character frequency); it is intentionally
    simple to remain dependency-free.
    """
    if not text or not text.strip():
        return None

    normalized = text.strip()
    length = len(normalized)
    if length < 4:
        return None

    de_count = sum(1 for ch in normalized if ch in _DE_CHARS)
    es_count = sum(1 for ch in normalized if ch in _ES_CHARS)
    fr_count = sum(1 for ch in normalized if ch in _FR_CHARS)
    words = {word.lower() for word in re.findall(r"[A-Za-zÀ-ÿ]+", normalized)}
    de_word_count = sum(1 for word in words if word in _DE_MARKER_WORDS)

    threshold = max(1, length * 0.01)

    # Spanish markers are unambiguous (¿/¡/ñ)
    if es_count >= threshold:
        return "es"

    # German markers are distinctive (ä/ö/ü/ß)
    if de_count >= threshold or de_word_count >= 2:
        return "de"

    # French markers (accented vowels)
    if fr_count >= threshold:
        return "fr"

    # Default to English for Latin-script text when no other signal is found.
    if normalized.isascii():
        return "en"

    return None


def resolve_answer_language(
    *,
    mode: str | None,
    detected_language: str | None,
    workspace_default: str,
) -> str | None:
    """Resolve the answer language mode to a concrete ISO-639-1 code.

    Returns None when no language instruction should be injected (auto mode).
    """
    if mode is None or mode == "auto":
        return None

    if mode == "same_as_question":
        if detected_language and detected_language in _SUPPORTED_LANGUAGES:
            return detected_language
        return workspace_default

    if mode == "workspace_default":
        return workspace_default

    if mode in _SUPPORTED_LANGUAGES:
        return mode

    return None


def language_display_name(code: str) -> str:
    """Return the English display name for an ISO-639-1 language code."""
    return _LANGUAGE_NAMES.get(code, code.upper())
