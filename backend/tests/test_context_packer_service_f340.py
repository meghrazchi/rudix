"""Unit tests for the strict context packing service — F340.

Coverage:
- Pack score computation (similarity, rerank blend, type bonuses, graph hop discount)
- Relevance ranking: highest-scored chunks selected first
- Rejection rules: low_relevance, weak_ocr, stale_superseded, token_budget (hard/soft)
- Strategy presets: strict floor raises min_relevance; permissive disables all rejections
- Token budget: hard mode stops on first overrun; soft mode skips large chunks
- Permission safety: unauthorized chunks are already filtered upstream; packer preserves order
- not_found_min_chunks: controls when grounded answer is attempted
- Disabled packer: returns all chunks unchanged
- Empty input: safe no-op
- Diagnostics: rejection reason counts are accurate
"""

from __future__ import annotations

import os
from uuid import UUID, uuid4

import pytest

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("API_BASE_URL", "http://localhost:8000")
os.environ.setdefault("FRONTEND_BASE_URL", "http://localhost:3000")
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/rag_app"
)
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_COLLECTION", "documents")
os.environ.setdefault("MINIO_ENDPOINT", "http://localhost:9000")
os.environ.setdefault("MINIO_ACCESS_KEY", "minioadmin")
os.environ.setdefault("MINIO_SECRET_KEY", "minioadmin")
os.environ.setdefault("MINIO_BUCKET", "documents")
os.environ.setdefault("RABBITMQ_URL", "amqp://admin:admin123@localhost:5672//")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("OPENAI_API_KEY", "sk-test")
os.environ.setdefault("AUTH_PROVIDER", "app")
os.environ.setdefault("APP_AUTH_SECRET", "test-secret")

from app.domains.chat.services.context_packer_service import (
    ContextPackerConfig,
    ContextPackerService,
    _compute_pack_score,
    _estimate_tokens,
    _is_stale_superseded,
    _is_weak_ocr,
)

# ---------------------------------------------------------------------------
# Mock chunk — minimal duck-typed stand-in for RetrievedChunk
# ---------------------------------------------------------------------------


class _Chunk:
    def __init__(
        self,
        *,
        chunk_id: UUID | None = None,
        document_id: UUID | None = None,
        text: str = "example chunk text about something",
        similarity_score: float = 0.75,
        rerank_score: float | None = None,
        chunk_type: str = "text",
        retrieval_source: str = "vector",
        graph_score: float | None = None,
        graph_hops: int = 0,
        chunk_level: int = 0,
    ) -> None:
        self.chunk_id = chunk_id or uuid4()
        self.document_id = document_id or uuid4()
        self.text = text
        self.similarity_score = similarity_score
        self.rerank_score = rerank_score
        self.chunk_type = chunk_type
        self.retrieval_source = retrieval_source
        self.graph_score = graph_score
        self.graph_hops = graph_hops
        self.chunk_level = chunk_level


def _svc() -> ContextPackerService:
    return ContextPackerService()


def _cfg(**overrides) -> ContextPackerConfig:
    defaults: dict = dict(
        enabled=True,
        strategy="balanced",
        budget_max_tokens=None,
        min_relevance_score=0.0,
        reject_weak_ocr=True,
        reject_stale_superseded=False,
        require_citations=True,
        not_found_min_chunks=1,
    )
    defaults.update(overrides)
    return ContextPackerConfig(**defaults)


# ---------------------------------------------------------------------------
# _estimate_tokens
# ---------------------------------------------------------------------------


class TestEstimateTokens:
    def test_empty_string_returns_one(self) -> None:
        assert _estimate_tokens("") == 1

    def test_short_text(self) -> None:
        assert _estimate_tokens("abcd") == 1

    def test_longer_text(self) -> None:
        text = "word " * 100  # 500 chars → 125 tokens
        assert _estimate_tokens(text) == 125


# ---------------------------------------------------------------------------
# _is_weak_ocr / _is_stale_superseded helpers
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_weak_ocr_failed(self) -> None:
        assert _is_weak_ocr("failed") is True

    def test_weak_ocr_low_confidence(self) -> None:
        assert _is_weak_ocr("low_confidence") is True

    def test_weak_ocr_low(self) -> None:
        assert _is_weak_ocr("low") is True

    def test_weak_ocr_good(self) -> None:
        assert _is_weak_ocr("good") is False

    def test_weak_ocr_none(self) -> None:
        assert _is_weak_ocr(None) is False

    def test_stale_superseded_deprecated(self) -> None:
        assert _is_stale_superseded("deprecated") is True

    def test_stale_superseded_expired(self) -> None:
        assert _is_stale_superseded("expired") is True

    def test_stale_superseded_current(self) -> None:
        assert _is_stale_superseded("current") is False

    def test_stale_superseded_none(self) -> None:
        assert _is_stale_superseded(None) is False

    def test_stale_superseded_stale(self) -> None:
        # "stale" is demoted but not lifecycle-terminated → not rejected by stale rule
        assert _is_stale_superseded("stale") is False


# ---------------------------------------------------------------------------
# _compute_pack_score
# ---------------------------------------------------------------------------


class TestComputePackScore:
    def test_similarity_only(self) -> None:
        chunk = _Chunk(similarity_score=0.8)
        score = _compute_pack_score(chunk)
        assert score == pytest.approx(0.8, abs=1e-4)

    def test_rerank_blend(self) -> None:
        chunk = _Chunk(similarity_score=0.6, rerank_score=1.0)
        score = _compute_pack_score(chunk)
        # 0.55 * 0.6 + 0.45 * 1.0 = 0.33 + 0.45 = 0.78
        assert score == pytest.approx(0.78, abs=1e-4)

    def test_table_chunk_bonus(self) -> None:
        base_chunk = _Chunk(similarity_score=0.8, chunk_type="text")
        table_chunk = _Chunk(similarity_score=0.8, chunk_type="table")
        assert _compute_pack_score(table_chunk) > _compute_pack_score(base_chunk)

    def test_graph_chunk_bonus(self) -> None:
        base_chunk = _Chunk(similarity_score=0.8)
        graph_chunk = _Chunk(similarity_score=0.8, retrieval_source="graph", graph_score=0.8)
        assert _compute_pack_score(graph_chunk) > _compute_pack_score(base_chunk)

    def test_graph_hop_discount_applied(self) -> None:
        direct = _Chunk(similarity_score=0.8, retrieval_source="graph", graph_score=0.8, graph_hops=0)
        multi_hop = _Chunk(similarity_score=0.8, retrieval_source="graph", graph_score=0.8, graph_hops=5)
        assert _compute_pack_score(direct) > _compute_pack_score(multi_hop)

    def test_zero_similarity_gives_zero_score(self) -> None:
        chunk = _Chunk(similarity_score=0.0)
        assert _compute_pack_score(chunk) == 0.0

    def test_score_rounded(self) -> None:
        chunk = _Chunk(similarity_score=0.333333)
        score = _compute_pack_score(chunk)
        assert len(str(score).split(".")[-1]) <= 6


# ---------------------------------------------------------------------------
# ContextPackerService.pack — disabled
# ---------------------------------------------------------------------------


class TestPackerDisabled:
    def test_disabled_returns_all_chunks_unchanged(self) -> None:
        svc = _svc()
        chunks = [_Chunk(similarity_score=0.9), _Chunk(similarity_score=0.5)]
        result = svc.pack(chunks=chunks, config=_cfg(enabled=False))
        assert result.selected is chunks  # exact same list reference
        assert result.rejected == []

    def test_disabled_with_empty_chunks(self) -> None:
        svc = _svc()
        result = svc.pack(chunks=[], config=_cfg(enabled=False))
        assert result.selected == []
        assert result.rejected == []

    def test_disabled_budget_not_applied(self) -> None:
        svc = _svc()
        chunks = [_Chunk(text="x" * 10_000)]
        result = svc.pack(chunks=chunks, config=_cfg(enabled=False))
        assert result.budget_applied is False


# ---------------------------------------------------------------------------
# ContextPackerService.pack — empty input
# ---------------------------------------------------------------------------


class TestPackerEmptyInput:
    def test_enabled_empty_returns_empty(self) -> None:
        svc = _svc()
        result = svc.pack(chunks=[], config=_cfg(enabled=True))
        assert result.selected == []
        assert result.rejected == []
        assert result.total_estimated_tokens == 0

    def test_citation_metadata_returned_on_empty(self) -> None:
        svc = _svc()
        result = svc.pack(chunks=[], config=_cfg(enabled=True, require_citations=True))
        assert result.require_citations is True


# ---------------------------------------------------------------------------
# Relevance ranking
# ---------------------------------------------------------------------------


class TestRelevanceRanking:
    def test_highest_score_selected_first(self) -> None:
        svc = _svc()
        low = _Chunk(similarity_score=0.4)
        mid = _Chunk(similarity_score=0.6)
        high = _Chunk(similarity_score=0.9)
        result = svc.pack(chunks=[low, mid, high], config=_cfg(enabled=True))
        ids = [str(c.chunk_id) for c in result.selected]
        assert ids[0] == str(high.chunk_id)
        assert ids[1] == str(mid.chunk_id)
        assert ids[2] == str(low.chunk_id)

    def test_rerank_score_influences_order(self) -> None:
        svc = _svc()
        # lower similarity but high rerank score should rank higher
        chunk_a = _Chunk(similarity_score=0.9, rerank_score=0.3)
        chunk_b = _Chunk(similarity_score=0.5, rerank_score=0.99)
        result = svc.pack(chunks=[chunk_a, chunk_b], config=_cfg(enabled=True))
        # chunk_b: 0.55*0.5 + 0.45*0.99 = 0.275 + 0.4455 = 0.7205
        # chunk_a: 0.55*0.9 + 0.45*0.3  = 0.495 + 0.135  = 0.63
        assert str(result.selected[0].chunk_id) == str(chunk_b.chunk_id)

    def test_table_chunk_ranked_above_same_score_text_chunk(self) -> None:
        svc = _svc()
        text_chunk = _Chunk(similarity_score=0.8, chunk_type="text")
        table_chunk = _Chunk(similarity_score=0.8, chunk_type="table")
        result = svc.pack(chunks=[text_chunk, table_chunk], config=_cfg(enabled=True))
        assert str(result.selected[0].chunk_id) == str(table_chunk.chunk_id)


# ---------------------------------------------------------------------------
# Rejection: low_relevance
# ---------------------------------------------------------------------------


class TestLowRelevanceRejection:
    def test_chunk_below_floor_rejected(self) -> None:
        svc = _svc()
        low = _Chunk(similarity_score=0.1)
        high = _Chunk(similarity_score=0.9)
        result = svc.pack(
            chunks=[low, high], config=_cfg(enabled=True, min_relevance_score=0.5)
        )
        assert len(result.selected) == 1
        assert str(result.selected[0].chunk_id) == str(high.chunk_id)
        assert result.rejected_low_relevance == 1
        assert result.rejected[0].reason == "low_relevance"

    def test_chunk_exactly_at_floor_accepted(self) -> None:
        svc = _svc()
        chunk = _Chunk(similarity_score=0.5)
        result = svc.pack(chunks=[chunk], config=_cfg(enabled=True, min_relevance_score=0.5))
        assert len(result.selected) == 1
        assert result.rejected_low_relevance == 0

    def test_strategy_strict_raises_floor(self) -> None:
        svc = _svc()
        # strict preset raises floor to 0.4; config says 0.0
        chunk_low = _Chunk(similarity_score=0.3)
        chunk_ok = _Chunk(similarity_score=0.5)
        result = svc.pack(
            chunks=[chunk_low, chunk_ok],
            config=_cfg(enabled=True, strategy="strict", min_relevance_score=0.0),
        )
        assert str(result.selected[0].chunk_id) == str(chunk_ok.chunk_id)
        assert result.rejected_low_relevance == 1

    def test_strategy_permissive_no_relevance_floor(self) -> None:
        svc = _svc()
        chunk = _Chunk(similarity_score=0.0)
        result = svc.pack(
            chunks=[chunk],
            config=_cfg(enabled=True, strategy="permissive", min_relevance_score=0.0),
        )
        assert len(result.selected) == 1
        assert result.rejected_low_relevance == 0


# ---------------------------------------------------------------------------
# Rejection: weak_ocr
# ---------------------------------------------------------------------------


class TestWeakOcrRejection:
    def test_failed_ocr_chunk_rejected(self) -> None:
        svc = _svc()
        doc_id = uuid4()
        chunk = _Chunk(document_id=doc_id, similarity_score=0.9)
        result = svc.pack(
            chunks=[chunk],
            config=_cfg(enabled=True, reject_weak_ocr=True),
            ocr_quality_map={str(doc_id): "failed"},
        )
        assert len(result.selected) == 0
        assert result.rejected_weak_ocr == 1
        assert result.rejected[0].reason == "weak_ocr"

    def test_low_confidence_ocr_chunk_rejected(self) -> None:
        svc = _svc()
        doc_id = uuid4()
        chunk = _Chunk(document_id=doc_id)
        result = svc.pack(
            chunks=[chunk],
            config=_cfg(enabled=True, reject_weak_ocr=True),
            ocr_quality_map={str(doc_id): "low_confidence"},
        )
        assert result.rejected_weak_ocr == 1

    def test_good_ocr_chunk_kept(self) -> None:
        svc = _svc()
        doc_id = uuid4()
        chunk = _Chunk(document_id=doc_id)
        result = svc.pack(
            chunks=[chunk],
            config=_cfg(enabled=True, reject_weak_ocr=True),
            ocr_quality_map={str(doc_id): "good"},
        )
        assert len(result.selected) == 1

    def test_reject_weak_ocr_false_keeps_failed_chunk(self) -> None:
        svc = _svc()
        doc_id = uuid4()
        chunk = _Chunk(document_id=doc_id)
        result = svc.pack(
            chunks=[chunk],
            config=_cfg(enabled=True, reject_weak_ocr=False),
            ocr_quality_map={str(doc_id): "failed"},
        )
        assert len(result.selected) == 1
        assert result.rejected_weak_ocr == 0

    def test_permissive_strategy_ignores_ocr(self) -> None:
        svc = _svc()
        doc_id = uuid4()
        chunk = _Chunk(document_id=doc_id)
        result = svc.pack(
            chunks=[chunk],
            config=_cfg(enabled=True, strategy="permissive", reject_weak_ocr=True),
            ocr_quality_map={str(doc_id): "failed"},
        )
        # permissive preset disables weak-OCR rejection regardless of config
        assert len(result.selected) == 1

    def test_missing_from_ocr_map_not_rejected(self) -> None:
        svc = _svc()
        chunk = _Chunk()
        result = svc.pack(
            chunks=[chunk],
            config=_cfg(enabled=True, reject_weak_ocr=True),
            ocr_quality_map={},
        )
        assert len(result.selected) == 1


# ---------------------------------------------------------------------------
# Rejection: stale_superseded
# ---------------------------------------------------------------------------


class TestStaleSuperseededRejection:
    def test_deprecated_chunk_rejected_when_enabled(self) -> None:
        svc = _svc()
        doc_id = uuid4()
        chunk = _Chunk(document_id=doc_id)
        result = svc.pack(
            chunks=[chunk],
            config=_cfg(enabled=True, strategy="strict", reject_stale_superseded=True),
            freshness_state_map={str(doc_id): "deprecated"},
        )
        assert len(result.selected) == 0
        assert result.rejected_stale_superseded == 1
        assert result.rejected[0].reason == "stale_superseded"

    def test_expired_chunk_rejected(self) -> None:
        svc = _svc()
        doc_id = uuid4()
        chunk = _Chunk(document_id=doc_id)
        result = svc.pack(
            chunks=[chunk],
            config=_cfg(enabled=True, strategy="strict", reject_stale_superseded=True),
            freshness_state_map={str(doc_id): "expired"},
        )
        assert result.rejected_stale_superseded == 1

    def test_stale_chunk_not_rejected_by_stale_rule(self) -> None:
        """'stale' is demoted in scoring but not lifecycle-terminated — keep it."""
        svc = _svc()
        doc_id = uuid4()
        chunk = _Chunk(document_id=doc_id, similarity_score=0.8)
        result = svc.pack(
            chunks=[chunk],
            config=_cfg(enabled=True, strategy="strict", reject_stale_superseded=True),
            freshness_state_map={str(doc_id): "stale"},
        )
        assert len(result.selected) == 1

    def test_current_chunk_kept(self) -> None:
        svc = _svc()
        doc_id = uuid4()
        chunk = _Chunk(document_id=doc_id)
        result = svc.pack(
            chunks=[chunk],
            config=_cfg(enabled=True, reject_stale_superseded=True),
            freshness_state_map={str(doc_id): "current"},
        )
        assert len(result.selected) == 1

    def test_flag_disabled_keeps_deprecated(self) -> None:
        svc = _svc()
        doc_id = uuid4()
        chunk = _Chunk(document_id=doc_id, similarity_score=0.8)
        result = svc.pack(
            chunks=[chunk],
            config=_cfg(enabled=True, reject_stale_superseded=False),
            freshness_state_map={str(doc_id): "deprecated"},
        )
        assert len(result.selected) == 1

    def test_missing_from_freshness_map_not_rejected(self) -> None:
        svc = _svc()
        chunk = _Chunk()
        result = svc.pack(
            chunks=[chunk],
            config=_cfg(enabled=True, reject_stale_superseded=True),
            freshness_state_map={},
        )
        assert len(result.selected) == 1


# ---------------------------------------------------------------------------
# Token budget — hard mode
# ---------------------------------------------------------------------------


class TestTokenBudgetHard:
    def test_budget_stops_at_overrun(self) -> None:
        svc = _svc()
        # Each chunk ~25 tokens (100 chars / 4).  Budget = 40 → fits 1 fully.
        chunk_a = _Chunk(text="a" * 100, similarity_score=0.9)
        chunk_b = _Chunk(text="b" * 100, similarity_score=0.8)
        result = svc.pack(
            chunks=[chunk_a, chunk_b],
            config=_cfg(enabled=True, strategy="strict", budget_max_tokens=40),
        )
        assert len(result.selected) == 1
        assert str(result.selected[0].chunk_id) == str(chunk_a.chunk_id)
        assert result.rejected_token_budget >= 1

    def test_all_chunks_fit_in_budget(self) -> None:
        svc = _svc()
        chunks = [_Chunk(text="word " * 10) for _ in range(3)]  # ~12 tokens each
        result = svc.pack(
            chunks=chunks,
            config=_cfg(enabled=True, strategy="strict", budget_max_tokens=200),
        )
        assert len(result.selected) == 3
        assert result.rejected_token_budget == 0

    def test_budget_applied_flag_true_when_budget_set(self) -> None:
        svc = _svc()
        chunk = _Chunk(text="short")
        result = svc.pack(
            chunks=[chunk],
            config=_cfg(enabled=True, strategy="strict", budget_max_tokens=1000),
        )
        assert result.budget_applied is True

    def test_no_budget_flag_false(self) -> None:
        svc = _svc()
        chunk = _Chunk()
        result = svc.pack(
            chunks=[chunk],
            config=_cfg(enabled=True, budget_max_tokens=None),
        )
        assert result.budget_applied is False

    def test_tokens_accumulate_correctly(self) -> None:
        svc = _svc()
        chunks = [_Chunk(text="a" * 40) for _ in range(4)]  # 10 tokens each
        result = svc.pack(
            chunks=chunks,
            config=_cfg(enabled=True, strategy="strict", budget_max_tokens=1000),
        )
        assert result.total_estimated_tokens == 4 * _estimate_tokens("a" * 40)


# ---------------------------------------------------------------------------
# Token budget — soft mode
# ---------------------------------------------------------------------------


class TestTokenBudgetSoft:
    def test_soft_mode_skips_large_chunk_but_continues(self) -> None:
        svc = _svc()
        large = _Chunk(text="a" * 400, similarity_score=0.9)   # 100 tokens
        small = _Chunk(text="b" * 40, similarity_score=0.8)    # 10 tokens
        # Budget = 50 tokens → large overruns, small fits
        result = svc.pack(
            chunks=[large, small],
            config=_cfg(enabled=True, strategy="balanced", budget_max_tokens=50),
        )
        assert len(result.selected) == 1
        assert str(result.selected[0].chunk_id) == str(small.chunk_id)
        assert result.rejected_token_budget == 1

    def test_permissive_ignores_budget(self) -> None:
        svc = _svc()
        chunks = [_Chunk(text="a" * 10_000) for _ in range(5)]
        result = svc.pack(
            chunks=chunks,
            config=_cfg(enabled=True, strategy="permissive", budget_max_tokens=10),
        )
        assert len(result.selected) == 5
        assert result.rejected_token_budget == 0


# ---------------------------------------------------------------------------
# Rejection priority: relevance checked before OCR and stale
# ---------------------------------------------------------------------------


class TestRejectionPriority:
    def test_low_relevance_takes_priority_over_ocr(self) -> None:
        svc = _svc()
        doc_id = uuid4()
        # chunk fails both low_relevance and weak_ocr; should be rejected for low_relevance
        chunk = _Chunk(document_id=doc_id, similarity_score=0.05)
        result = svc.pack(
            chunks=[chunk],
            config=_cfg(enabled=True, min_relevance_score=0.5, reject_weak_ocr=True),
            ocr_quality_map={str(doc_id): "failed"},
        )
        assert result.rejected[0].reason == "low_relevance"
        assert result.rejected_low_relevance == 1
        assert result.rejected_weak_ocr == 0


# ---------------------------------------------------------------------------
# Citation and not_found_min_chunks metadata
# ---------------------------------------------------------------------------


class TestAnswerRules:
    def test_require_citations_true_by_default(self) -> None:
        svc = _svc()
        result = svc.pack(chunks=[], config=_cfg(enabled=True))
        assert result.require_citations is True

    def test_require_citations_false_propagated(self) -> None:
        svc = _svc()
        result = svc.pack(chunks=[], config=_cfg(enabled=True, require_citations=False))
        assert result.require_citations is False

    def test_not_found_min_chunks_default(self) -> None:
        svc = _svc()
        result = svc.pack(chunks=[], config=_cfg(enabled=True))
        assert result.not_found_min_chunks == 1

    def test_not_found_min_chunks_custom(self) -> None:
        svc = _svc()
        result = svc.pack(chunks=[], config=_cfg(enabled=True, not_found_min_chunks=3))
        assert result.not_found_min_chunks == 3


# ---------------------------------------------------------------------------
# Diagnostic counts
# ---------------------------------------------------------------------------


class TestDiagnosticCounts:
    def test_multiple_rejection_types_counted_separately(self) -> None:
        svc = _svc()
        doc_ocr = uuid4()
        doc_dep = uuid4()

        chunk_irrelevant = _Chunk(similarity_score=0.05)
        chunk_bad_ocr = _Chunk(document_id=doc_ocr, similarity_score=0.8)
        chunk_deprecated = _Chunk(document_id=doc_dep, similarity_score=0.7)
        chunk_ok = _Chunk(similarity_score=0.9)

        result = svc.pack(
            chunks=[chunk_irrelevant, chunk_bad_ocr, chunk_deprecated, chunk_ok],
            config=_cfg(
                enabled=True,
                strategy="strict",
                min_relevance_score=0.2,
                reject_weak_ocr=True,
                reject_stale_superseded=True,
            ),
            ocr_quality_map={str(doc_ocr): "failed"},
            freshness_state_map={str(doc_dep): "deprecated"},
        )
        assert len(result.selected) == 1
        assert str(result.selected[0].chunk_id) == str(chunk_ok.chunk_id)
        assert result.rejected_low_relevance == 1
        assert result.rejected_weak_ocr == 1
        assert result.rejected_stale_superseded == 1
        assert result.rejected_token_budget == 0

    def test_total_rejected_equals_sum_of_reasons(self) -> None:
        svc = _svc()
        doc_id = uuid4()
        chunks = [
            _Chunk(similarity_score=0.1),       # low_relevance
            _Chunk(document_id=doc_id, similarity_score=0.8),  # weak_ocr
            _Chunk(similarity_score=0.9),       # selected
        ]
        result = svc.pack(
            chunks=chunks,
            config=_cfg(enabled=True, min_relevance_score=0.3, reject_weak_ocr=True),
            ocr_quality_map={str(doc_id): "failed"},
        )
        total = (
            result.rejected_low_relevance
            + result.rejected_weak_ocr
            + result.rejected_stale_superseded
            + result.rejected_token_budget
        )
        assert total == len(result.rejected)


# ---------------------------------------------------------------------------
# Permission safety: order preserved after upstream filtering
# ---------------------------------------------------------------------------


class TestPermissionSafety:
    def test_packer_respects_upstream_filtered_list(self) -> None:
        """Unauthorized chunks are removed upstream by the authorization service.
        The packer receives only the allowed set and should not add any back."""
        svc = _svc()
        allowed_a = _Chunk(similarity_score=0.9)
        allowed_b = _Chunk(similarity_score=0.7)
        result = svc.pack(
            chunks=[allowed_a, allowed_b],
            config=_cfg(enabled=True),
        )
        ids = {str(c.chunk_id) for c in result.selected}
        assert str(allowed_a.chunk_id) in ids
        assert str(allowed_b.chunk_id) in ids
        assert len(result.selected) == 2


# ---------------------------------------------------------------------------
# Public proxy: compute_pack_score
# ---------------------------------------------------------------------------


class TestPublicProxy:
    def test_compute_pack_score_matches_internal(self) -> None:
        svc = _svc()
        chunk = _Chunk(similarity_score=0.7, rerank_score=0.9)
        assert svc.compute_pack_score(chunk) == _compute_pack_score(chunk)


# ---------------------------------------------------------------------------
# ContextPackerConfig — strategy validation
# ---------------------------------------------------------------------------


class TestContextPackerConfig:
    def test_default_strategy_is_balanced(self) -> None:
        cfg = ContextPackerConfig()
        assert cfg.strategy == "balanced"

    def test_strict_strategy_accepted(self) -> None:
        cfg = ContextPackerConfig(strategy="strict")
        assert cfg.strategy == "strict"

    def test_permissive_strategy_accepted(self) -> None:
        cfg = ContextPackerConfig(strategy="permissive")
        assert cfg.strategy == "permissive"
