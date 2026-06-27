"""Strict context packing and in-context learning hardening — F340.

After reranking, this service selects the final evidence window sent to the LLM
by applying a composite priority score and hard rejection rules:

Priority signals (higher is better):
  - verified / trusted sources  → similarity_score already boosted by freshness service
  - high reranker score         → weighted blend with similarity_score
  - table chunks on table query → type bonus applied by caller before packing
  - graph evidence              → graph_score bonus; hop discount for multi-hop
  - parent section context      → chunk_level=0 preferred over isolated child fragments

Rejection rules (chunk excluded regardless of score):
  - low_relevance       → pack_score < min_relevance_score
  - weak_ocr            → OCR failed/low-confidence AND reject_weak_ocr=True
  - stale_superseded    → freshness state is "deprecated" AND reject_stale_superseded=True
  - token_budget        → cumulative budget exhausted (strategy="strict") or
                          individual chunk exceeds remaining budget

Answer rules enforced in the returned metadata:
  - require_citations   → signals to the prompt builder that every claim must cite
  - not_found_min_chunks → minimum chunks needed before attempting a grounded answer
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

_CHARS_PER_TOKEN = 4  # matches parent_context_expansion_service approximation

RejectionReason = Literal[
    "low_relevance",
    "weak_ocr",
    "stale_superseded",
    "token_budget",
]

ContextPackingStrategy = Literal["strict", "balanced", "permissive"]

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_STRATEGY_DEFAULTS: dict[str, dict] = {
    "strict": {
        "min_relevance_score": 0.4,
        "reject_weak_ocr": True,
        "reject_stale_superseded": True,
        "budget_mode": "hard",
    },
    "balanced": {
        "min_relevance_score": 0.2,
        "reject_weak_ocr": True,
        "reject_stale_superseded": False,
        "budget_mode": "soft",
    },
    "permissive": {
        "min_relevance_score": 0.0,
        "reject_weak_ocr": False,
        "reject_stale_superseded": False,
        "budget_mode": "none",
    },
}

# OCR status values considered too noisy for grounded answers.
_WEAK_OCR_STATUSES: frozenset[str] = frozenset({"failed", "low_confidence", "low"})

# Freshness states considered lifecycle-terminated for strict packing.
_STALE_SUPERSEDED_STATES: frozenset[str] = frozenset({"deprecated", "expired"})

# Weight blending similarity_score and rerank_score when both are present.
_SIMILARITY_WEIGHT = 0.55
_RERANK_WEIGHT = 0.45

# Type bonuses applied on top of the blended score.
_GRAPH_BONUS = 1.25
_GRAPH_HOP_DISCOUNT = 0.08  # per additional hop beyond 0
_TABLE_BONUS = 1.15


@dataclass(frozen=True)
class ContextPackerConfig:
    """Per-request packing parameters resolved from RagProfileConfig + system settings."""

    enabled: bool = False
    strategy: ContextPackingStrategy = "balanced"
    budget_max_tokens: int | None = None
    min_relevance_score: float = 0.0
    reject_weak_ocr: bool = True
    reject_stale_superseded: bool = False
    require_citations: bool = True
    not_found_min_chunks: int = 1


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RejectedChunk:
    chunk_id: str
    document_id: str
    reason: RejectionReason
    pack_score: float


@dataclass(frozen=True)
class PackedChunk:
    """A chunk selected for the LLM context window, with its computed pack_score."""

    chunk_id: str
    document_id: str
    pack_score: float
    estimated_tokens: int


@dataclass(frozen=True)
class ContextPackResult:
    """Output of a single packing pass."""

    selected: list  # list[RetrievedChunk] — typed as list to avoid circular import
    rejected: list[RejectedChunk]
    total_estimated_tokens: int
    budget_applied: bool
    rejected_low_relevance: int
    rejected_weak_ocr: int
    rejected_stale_superseded: int
    rejected_token_budget: int
    require_citations: bool
    not_found_min_chunks: int


# ---------------------------------------------------------------------------
# Protocol for duck-typed chunk input
# ---------------------------------------------------------------------------


class _ChunkLike(Protocol):
    @property
    def chunk_id(self): ...
    @property
    def document_id(self): ...
    @property
    def text(self) -> str: ...
    @property
    def similarity_score(self) -> float: ...
    @property
    def rerank_score(self) -> float | None: ...
    @property
    def chunk_type(self) -> str: ...
    @property
    def retrieval_source(self) -> str: ...
    @property
    def graph_score(self) -> float | None: ...
    @property
    def graph_hops(self) -> int: ...
    @property
    def chunk_level(self) -> int: ...


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class ContextPackerService:
    """Applies strict context packing rules to a ranked list of retrieved chunks.

    The service is stateless and synchronous.  All inputs are passed explicitly
    so the caller retains full control over which data reaches the service.

    Usage::

        result = ContextPackerService().pack(
            chunks=selected_chunks,
            config=ContextPackerConfig(enabled=True, strategy="strict"),
            ocr_quality_map=_ocr_quality_map,       # {str(document_id): status}
            freshness_state_map=_freshness_state_map, # {str(document_id): FreshnessState}
        )
        selected_chunks = result.selected
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def pack(
        self,
        *,
        chunks: list,
        config: ContextPackerConfig,
        ocr_quality_map: dict[str, str] | None = None,
        freshness_state_map: dict[str, str] | None = None,
    ) -> ContextPackResult:
        """Apply strict packing rules and return the selected + rejected chunks.

        Args:
            chunks:            Pre-ranked ``RetrievedChunk`` objects (after reranking).
            config:            Resolved packing configuration for this request.
            ocr_quality_map:   Optional ``{str(document_id): ocr_status}`` index.
            freshness_state_map: Optional ``{str(document_id): FreshnessState}`` index.

        Returns:
            A :class:`ContextPackResult` containing the selected chunks in
            priority order, rejection details, and budget/citation metadata.
        """
        if not config.enabled or not chunks:
            return ContextPackResult(
                selected=chunks,  # pass-through: same list reference, no copy
                rejected=[],
                total_estimated_tokens=_total_tokens(chunks),
                budget_applied=False,
                rejected_low_relevance=0,
                rejected_weak_ocr=0,
                rejected_stale_superseded=0,
                rejected_token_budget=0,
                require_citations=config.require_citations,
                not_found_min_chunks=config.not_found_min_chunks,
            )

        strategy_defaults = _STRATEGY_DEFAULTS[config.strategy]
        min_relevance = max(config.min_relevance_score, strategy_defaults["min_relevance_score"])
        reject_weak_ocr = config.reject_weak_ocr and strategy_defaults["reject_weak_ocr"]
        reject_stale = (
            config.reject_stale_superseded and strategy_defaults["reject_stale_superseded"]
        )
        budget_mode: str = strategy_defaults["budget_mode"]
        budget_tokens: int | None = config.budget_max_tokens

        _ocr = ocr_quality_map or {}
        _freshness = freshness_state_map or {}

        # --- score and sort ---
        scored: list[tuple[float, object]] = [
            (_compute_pack_score(c), c) for c in chunks
        ]
        scored.sort(key=lambda t: t[0], reverse=True)

        selected: list = []
        rejected: list[RejectedChunk] = []
        total_tokens = 0
        n_low_rel = n_weak_ocr = n_stale = n_budget = 0

        for pack_score, chunk in scored:
            cid = str(chunk.chunk_id)
            did = str(chunk.document_id)

            # Rule 1: relevance floor
            if pack_score < min_relevance:
                rejected.append(RejectedChunk(chunk_id=cid, document_id=did,
                                               reason="low_relevance", pack_score=pack_score))
                n_low_rel += 1
                continue

            # Rule 2: weak OCR rejection
            if reject_weak_ocr and _is_weak_ocr(_ocr.get(did)):
                rejected.append(RejectedChunk(chunk_id=cid, document_id=did,
                                               reason="weak_ocr", pack_score=pack_score))
                n_weak_ocr += 1
                continue

            # Rule 3: stale / superseded rejection
            if reject_stale and _is_stale_superseded(_freshness.get(did)):
                rejected.append(RejectedChunk(chunk_id=cid, document_id=did,
                                               reason="stale_superseded", pack_score=pack_score))
                n_stale += 1
                continue

            # Rule 4: token budget (hard mode stops at first overrun; soft skips large chunks)
            chunk_tokens = _estimate_tokens(chunk.text)
            if budget_tokens is not None and budget_mode != "none":
                remaining = budget_tokens - total_tokens
                if chunk_tokens > remaining:
                    if budget_mode == "hard":
                        # Stop processing; remaining chunks are rejected.
                        rejected.append(
                            RejectedChunk(chunk_id=cid, document_id=did,
                                          reason="token_budget", pack_score=pack_score)
                        )
                        n_budget += 1
                        # mark all remaining as budget-rejected
                        for _, remaining_chunk in scored[scored.index((pack_score, chunk)) + 1:]:
                            rc_id = str(remaining_chunk.chunk_id)
                            rd_id = str(remaining_chunk.document_id)
                            rp = _compute_pack_score(remaining_chunk)
                            rejected.append(
                                RejectedChunk(chunk_id=rc_id, document_id=rd_id,
                                              reason="token_budget", pack_score=rp)
                            )
                            n_budget += 1
                        break
                    else:
                        # soft mode: skip this chunk but continue
                        rejected.append(
                            RejectedChunk(chunk_id=cid, document_id=did,
                                          reason="token_budget", pack_score=pack_score)
                        )
                        n_budget += 1
                        continue

            selected.append(chunk)
            total_tokens += chunk_tokens

        return ContextPackResult(
            selected=selected,
            rejected=rejected,
            total_estimated_tokens=total_tokens,
            budget_applied=budget_tokens is not None and budget_mode != "none",
            rejected_low_relevance=n_low_rel,
            rejected_weak_ocr=n_weak_ocr,
            rejected_stale_superseded=n_stale,
            rejected_token_budget=n_budget,
            require_citations=config.require_citations,
            not_found_min_chunks=config.not_found_min_chunks,
        )

    # ------------------------------------------------------------------
    # Helpers for external access
    # ------------------------------------------------------------------

    def compute_pack_score(self, chunk) -> float:
        """Public proxy for testing and diagnostics."""
        return _compute_pack_score(chunk)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // _CHARS_PER_TOKEN)


def _total_tokens(chunks: list) -> int:
    return sum(_estimate_tokens(getattr(c, "text", "")) for c in chunks)


def _compute_pack_score(chunk) -> float:
    """Compute a composite priority score for context packing ordering.

    The score blends similarity and rerank signals, then applies type bonuses
    for table and graph evidence.  The result is unit-free and only meaningful
    in comparison to other chunks in the same pack pass.
    """
    sim = float(getattr(chunk, "similarity_score", 0.0))
    rerank = getattr(chunk, "rerank_score", None)

    if rerank is not None:
        base = _SIMILARITY_WEIGHT * sim + _RERANK_WEIGHT * float(rerank)
    else:
        base = sim

    retrieval_source = getattr(chunk, "retrieval_source", "vector")
    chunk_type = getattr(chunk, "chunk_type", "text")
    graph_hops = int(getattr(chunk, "graph_hops", 0))
    graph_score = getattr(chunk, "graph_score", None)

    if retrieval_source == "graph" or graph_score is not None:
        hop_discount = max(0.0, 1.0 - graph_hops * _GRAPH_HOP_DISCOUNT)
        base = base * _GRAPH_BONUS * hop_discount

    if chunk_type == "table":
        base = base * _TABLE_BONUS

    return round(base, 6)


def _is_weak_ocr(ocr_status: str | None) -> bool:
    if not ocr_status:
        return False
    return ocr_status.lower() in _WEAK_OCR_STATUSES


def _is_stale_superseded(freshness_state: str | None) -> bool:
    if not freshness_state:
        return False
    return freshness_state.lower() in _STALE_SUPERSEDED_STATES
