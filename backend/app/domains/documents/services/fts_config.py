"""PostgreSQL text search configuration for a document or question language (R06-09).

One mapping serves the chunk writer (``fts_config`` and ``fts_vector`` on new chunks), the
tenant backfill (rendered into its ``UPDATE`` as a ``CASE``), and keyword search (the
question's configuration). Languages come from F230 detection (ISO 639-1 codes such as
``de``; a region suffix such as ``de-AT`` is ignored). Anything else, or no language, maps
to ``simple``: lower-casing without stemming or stop words, which never drops a token.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import cast, func
from sqlalchemy.dialects.postgresql import REGCONFIG

FTS_CONFIG_FALLBACK = "simple"

# ISO 639-1 language code -> built-in PostgreSQL text search configuration.
FTS_CONFIG_BY_LANGUAGE: dict[str, str] = {
    "en": "english",
    "de": "german",
    "es": "spanish",
    "fr": "french",
}

ALLOWED_FTS_CONFIGS: frozenset[str] = frozenset(
    {*FTS_CONFIG_BY_LANGUAGE.values(), FTS_CONFIG_FALLBACK}
)


def _language_code(language: str | None) -> str:
    if not language:
        return ""
    return language.strip().lower().replace("_", "-").split("-", 1)[0]


def fts_config_for_language(language: str | None) -> str:
    """Return the text search configuration for ``language`` (``simple`` when unknown)."""
    return FTS_CONFIG_BY_LANGUAGE.get(_language_code(language), FTS_CONFIG_FALLBACK)


def fts_vector_expression(config: str, text: Any) -> Any:
    """``to_tsvector(config::regconfig, text)``; ``config`` must be an allowed name."""
    if config not in ALLOWED_FTS_CONFIGS:
        raise ValueError(f"unsupported text search configuration: {config!r}")
    return func.to_tsvector(cast(config, REGCONFIG), text)


def fts_config_case_sql(language_column: str) -> str:
    """A SQL ``CASE`` over ``language_column`` returning the configuration name.

    Built only from the constant mapping above (no input reaches it), for the backfill's
    set-based ``UPDATE``. Applies the same normalisation as ``fts_config_for_language``.
    """
    code = f"split_part(replace(lower(btrim({language_column})), '_', '-'), '-', 1)"
    branches = " ".join(
        f"WHEN '{language}' THEN '{config}'"
        for language, config in sorted(FTS_CONFIG_BY_LANGUAGE.items())
    )
    return f"CASE {code} {branches} ELSE '{FTS_CONFIG_FALLBACK}' END"


def chunk_search_fields(document: Any) -> dict[str, Any]:
    """Tenant and full-text fields of a new chunk row for ``document`` (chunk stage)."""
    return {
        "organization_id": getattr(document, "organization_id", None),
        "fts_config": fts_config_for_language(getattr(document, "language", None)),
    }
