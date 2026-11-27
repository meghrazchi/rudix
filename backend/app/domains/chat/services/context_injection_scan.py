"""Prompt-injection scan of retrieved chunks before they reach a prompt (R05-09).

Chunks whose text matches the prompt-injection patterns are flagged, down-ranked (their
scores multiplied by a configured factor and the list re-ordered), or dropped. The result
carries chunk ids and counts only, never chunk text.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Literal, cast

from app.core.safety_guardrails import PromptInjectionGuard
from app.domains.chat.services.retrieved_chunk import RetrievedChunk

ContextInjectionAction = Literal["flag", "downrank", "drop"]
_ACTIONS: frozenset[str] = frozenset({"flag", "downrank", "drop"})


@dataclass(frozen=True)
class ContextInjectionScanResult:
    action: ContextInjectionAction
    chunks: list[RetrievedChunk]
    flagged_chunk_ids: list[str] = field(default_factory=list)

    @property
    def flagged_count(self) -> int:
        return len(self.flagged_chunk_ids)


def _ranking_score(chunk: RetrievedChunk) -> float:
    return chunk.rerank_score if chunk.rerank_score is not None else chunk.similarity_score


def _downranked(chunk: RetrievedChunk, multiplier: float) -> RetrievedChunk:
    return replace(
        chunk,
        similarity_score=chunk.similarity_score * multiplier,
        rerank_score=chunk.rerank_score * multiplier if chunk.rerank_score is not None else None,
    )


def scan_retrieved_chunks(
    chunks: list[RetrievedChunk],
    *,
    action: str,
    downrank_multiplier: float,
    guard: PromptInjectionGuard | None = None,
) -> ContextInjectionScanResult:
    """Scan ``chunks`` and apply ``action`` to the flagged ones.

    ``flag`` keeps the list unchanged; ``downrank`` multiplies the flagged chunks' scores
    and re-orders the list by score (stable, ``final_rank`` renumbered); ``drop`` removes
    the flagged chunks. An unknown action behaves as ``flag``.
    """
    effective = cast(ContextInjectionAction, action if action in _ACTIONS else "flag")
    scanner = guard or PromptInjectionGuard()
    flagged_ids: list[str] = []
    flagged_keys: set[int] = set()
    for index, chunk in enumerate(chunks):
        # The parent section (F300) may replace the child text in the prompt: scan both.
        if (
            scanner.scan_context(chunk.text).flagged
            or scanner.scan_context(chunk.parent_text).flagged
        ):
            flagged_ids.append(str(chunk.chunk_id))
            flagged_keys.add(index)
    if not flagged_ids or effective == "flag":
        return ContextInjectionScanResult(
            action=effective, chunks=list(chunks), flagged_chunk_ids=flagged_ids
        )
    if effective == "drop":
        kept = [chunk for index, chunk in enumerate(chunks) if index not in flagged_keys]
        return ContextInjectionScanResult(
            action=effective, chunks=kept, flagged_chunk_ids=flagged_ids
        )
    adjusted = [
        _downranked(chunk, downrank_multiplier) if index in flagged_keys else chunk
        for index, chunk in enumerate(chunks)
    ]
    ordered = sorted(adjusted, key=_ranking_score, reverse=True)
    renumbered = [replace(chunk, final_rank=rank) for rank, chunk in enumerate(ordered, start=1)]
    return ContextInjectionScanResult(
        action=effective, chunks=renumbered, flagged_chunk_ids=flagged_ids
    )
