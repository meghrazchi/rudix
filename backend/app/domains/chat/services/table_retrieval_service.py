"""Table-aware retrieval boost service — F298.

Detects queries that are likely asking about tabular data and applies a
configurable score multiplier to table chunks so they rank higher before
reranking.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

# ---------------------------------------------------------------------------
# Table-query heuristics
# ---------------------------------------------------------------------------

# Patterns that suggest the user wants tabular information.
_TABLE_QUERY_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(table|chart|matrix|grid|spreadsheet|rows?|columns?|cell)\b", re.IGNORECASE),
    re.compile(r"\b(compare|comparison|versus|vs\.?|side[- ]by[- ]side)\b", re.IGNORECASE),
    re.compile(
        r"\b(breakdown|summary|overview|list of|summary of|breakdown of)\b", re.IGNORECASE
    ),
    re.compile(r"\b(how much|how many|what (is|are) the (value|amount|number|count|total|rate|price|cost|fee|percentage|ratio))\b", re.IGNORECASE),
    re.compile(r"\b(highest|lowest|maximum|minimum|average|total|sum)\b", re.IGNORECASE),
    re.compile(r"\b(between \w+ and \w+|in (q[1-4]|\d{4}|january|february|march|april|may|june|july|august|september|october|november|december))\b", re.IGNORECASE),
]

# Minimum number of pattern matches to classify as a table query.
_TABLE_QUERY_MIN_MATCHES = 1


def is_table_query(query: str) -> bool:
    """Return True when the query looks like it's asking for tabular information."""
    match_count = sum(1 for p in _TABLE_QUERY_PATTERNS if p.search(query))
    return match_count >= _TABLE_QUERY_MIN_MATCHES


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TableBoostResult:
    boosted_count: int
    table_chunk_count: int
    boost_applied: bool


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class TableRetrievalService:
    """Applies table-chunk score boosts when the query suggests tabular data."""

    def apply_table_boost(
        self,
        *,
        chunks: list,
        query: str,
        boost_multiplier: float,
        enabled: bool = True,
    ) -> tuple[list, TableBoostResult]:
        """Boost similarity scores of table chunks when the query is table-like.

        Args:
            chunks: List of RetrievedChunk (or any object with .chunk_type and
                    .similarity_score fields).
            query: The user's question.
            boost_multiplier: Multiplier applied to table chunk scores (e.g. 1.25).
            enabled: When False, returns chunks unchanged with no boost applied.

        Returns:
            (updated_chunks, result_metadata)
        """
        table_chunk_count = sum(1 for c in chunks if getattr(c, "chunk_type", "text") == "table")

        if not enabled or boost_multiplier <= 1.0 or not is_table_query(query) or table_chunk_count == 0:
            return chunks, TableBoostResult(
                boosted_count=0,
                table_chunk_count=table_chunk_count,
                boost_applied=False,
            )

        boosted_count = 0
        updated: list = []
        for chunk in chunks:
            if getattr(chunk, "chunk_type", "text") == "table":
                new_score = chunk.similarity_score * boost_multiplier
                from dataclasses import replace as _replace
                try:
                    updated.append(_replace(chunk, similarity_score=new_score))
                except TypeError:
                    updated.append(chunk)
                    continue
                boosted_count += 1
            else:
                updated.append(chunk)

        return updated, TableBoostResult(
            boosted_count=boosted_count,
            table_chunk_count=table_chunk_count,
            boost_applied=boosted_count > 0,
        )
