"""Parent-context expansion service — F300.

When a child chunk (chunk_level=1) is retrieved, substitute its text with the
parent section text inside the LLM prompt so the model receives richer surrounding
context.  Citations stay linked to the precise child chunk; expansion is purely
a prompt-construction step.

Permission safety: parent text is sourced from the same document as its child
chunk.  All documents are already org-scoped before reaching this service, so no
additional permission check is required.

Token-budget enforcement: each parent text is truncated (at a word boundary) to
``max_tokens_per_chunk`` estimated tokens before insertion into the context map.
"""

from __future__ import annotations

from dataclasses import dataclass

_CHARS_PER_TOKEN = 4  # cheap approximation; avoids a tokenizer dependency


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // _CHARS_PER_TOKEN)


def _truncate_to_budget(text: str, max_tokens: int) -> str:
    char_budget = max_tokens * _CHARS_PER_TOKEN
    if len(text) <= char_budget:
        return text
    truncated = text[:char_budget].rsplit(" ", 1)[0]
    return truncated if truncated else text[:char_budget]


@dataclass(frozen=True)
class ParentExpansionResult:
    """Diagnostic data from a single expansion pass."""

    context_map: dict[str, str]
    """Mapping of str(chunk_id) → expanded text to use in the LLM prompt."""
    expanded_count: int
    """Number of child chunks whose context was replaced with parent text."""
    child_hit_count: int
    """Total child chunks (chunk_level=1) present in the input set."""
    tokens_used: int
    """Estimated token count of all inserted parent texts (post-truncation)."""


class ParentContextExpansionService:
    """Expands retrieved child chunks to their parent section text for the LLM prompt."""

    def expand(
        self,
        *,
        chunks: list,
        enabled: bool = True,
        max_tokens_per_chunk: int = 512,
    ) -> ParentExpansionResult:
        """Build a context map substituting parent text for qualifying child chunks.

        Args:
            chunks: List of ``RetrievedChunk`` objects (must have ``chunk_level``,
                ``parent_text``, and ``chunk_id`` attributes).
            enabled: When ``False``, returns an empty result with no expansion.
            max_tokens_per_chunk: Hard cap on parent-text tokens per chunk. Parent
                texts that exceed this limit are truncated at a word boundary.

        Returns:
            A :class:`ParentExpansionResult` with the context map and diagnostics.
            The caller should pass ``result.context_map`` to the prompt builder so
            that child chunk text is replaced with parent text in the LLM context.
        """
        child_hit_count = sum(
            1
            for c in chunks
            if getattr(c, "chunk_level", 0) == 1 and getattr(c, "parent_text", None)
        )

        if not enabled or child_hit_count == 0:
            return ParentExpansionResult(
                context_map={},
                expanded_count=0,
                child_hit_count=child_hit_count,
                tokens_used=0,
            )

        context_map: dict[str, str] = {}
        total_tokens = 0

        for chunk in chunks:
            parent_text = getattr(chunk, "parent_text", None)
            if getattr(chunk, "chunk_level", 0) != 1 or not parent_text:
                continue

            expanded = _truncate_to_budget(parent_text.strip(), max_tokens_per_chunk)
            if not expanded:
                continue

            context_map[str(chunk.chunk_id)] = expanded
            total_tokens += _estimate_tokens(expanded)

        return ParentExpansionResult(
            context_map=context_map,
            expanded_count=len(context_map),
            child_hit_count=child_hit_count,
            tokens_used=total_tokens,
        )
