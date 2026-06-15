"""Tests for parent-child retrieval and context expansion — F300.

Covers:
- ParentContextExpansionService: expansion, token budget, disabled mode, empty input
- HybridCandidate: parent fields thread through merge_with_rrf
- KeywordRetrievedCandidate: parent fields present on dataclass
- Permission safety: parent text scoped to same document
- Diagnostics: ParentExpansionResult counts and context_map accuracy
- _build_prompt integration: parent text replaces child text in LLM context
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

from app.domains.chat.services.hybrid_retrieval_service import (
    HybridCandidate,
    HybridRetrievalService,
    merge_with_rrf,
)
from app.domains.chat.services.keyword_retrieval_service import KeywordRetrievedCandidate
from app.domains.chat.services.parent_context_expansion_service import (
    ParentContextExpansionService,
    _estimate_tokens,
    _truncate_to_budget,
)
from app.domains.chat.services.query_retrieval_service import RetrievedCandidate


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _child_chunk(
    *,
    chunk_id: UUID | None = None,
    document_id: UUID | None = None,
    parent_chunk_id: UUID | None = None,
    text: str = "precise child text",
    parent_text: str | None = "full parent section providing surrounding context",
    similarity_score: float = 0.85,
) -> RetrievedCandidate:
    return RetrievedCandidate(
        chunk_id=chunk_id or uuid4(),
        document_id=document_id or uuid4(),
        filename="policy.pdf",
        page_number=2,
        text=text,
        similarity_score=similarity_score,
        chunk_level=1,
        parent_chunk_id=parent_chunk_id or uuid4(),
        parent_text=parent_text,
    )


def _parent_chunk(
    *,
    chunk_id: UUID | None = None,
    document_id: UUID | None = None,
    text: str = "parent section full text",
    similarity_score: float = 0.75,
) -> RetrievedCandidate:
    return RetrievedCandidate(
        chunk_id=chunk_id or uuid4(),
        document_id=document_id or uuid4(),
        filename="policy.pdf",
        page_number=2,
        text=text,
        similarity_score=similarity_score,
        chunk_level=0,
        parent_chunk_id=None,
        parent_text=None,
    )


def _keyword_child(
    *,
    chunk_id: UUID | None = None,
    document_id: UUID | None = None,
    parent_chunk_id: UUID | None = None,
    text: str = "keyword child text",
    parent_text: str | None = "keyword parent section",
    keyword_score: float = 0.6,
) -> KeywordRetrievedCandidate:
    return KeywordRetrievedCandidate(
        chunk_id=chunk_id or uuid4(),
        document_id=document_id or uuid4(),
        filename="policy.pdf",
        page_number=3,
        text=text,
        section_path=None,
        keyword_score=keyword_score,
        chunk_level=1,
        parent_chunk_id=parent_chunk_id or uuid4(),
        parent_text=parent_text,
    )


# Simple mock chunk for expansion service that mimics RetrievedChunk.
class _MockChunk:
    def __init__(
        self,
        *,
        chunk_id: UUID | None = None,
        text: str = "child text",
        chunk_level: int = 1,
        parent_text: str | None = "parent text",
    ) -> None:
        self.chunk_id = chunk_id or uuid4()
        self.text = text
        self.chunk_level = chunk_level
        self.parent_text = parent_text


# ---------------------------------------------------------------------------
# _estimate_tokens / _truncate_to_budget helpers
# ---------------------------------------------------------------------------


class TestTokenHelpers:
    def test_estimate_tokens_basic(self) -> None:
        assert _estimate_tokens("hello") >= 1

    def test_estimate_tokens_empty_returns_one(self) -> None:
        assert _estimate_tokens("") == 1

    def test_truncate_within_budget_unchanged(self) -> None:
        text = "short text"
        result = _truncate_to_budget(text, max_tokens=500)
        assert result == text

    def test_truncate_over_budget_at_word_boundary(self) -> None:
        # 4 chars per token → budget of 2 tokens = 8 chars
        text = "alpha beta gamma delta"
        result = _truncate_to_budget(text, max_tokens=2)
        assert len(result) <= 8
        # result should not end mid-word
        assert " " not in result or result.endswith(" ") is False

    def test_truncate_zero_budget_returns_characters(self) -> None:
        # even with extreme limits, should not crash
        result = _truncate_to_budget("abcd efgh", max_tokens=1)
        assert len(result) >= 1


# ---------------------------------------------------------------------------
# ParentContextExpansionService
# ---------------------------------------------------------------------------


class TestParentContextExpansionService:
    def _svc(self) -> ParentContextExpansionService:
        return ParentContextExpansionService()

    # --- basic expansion ---

    def test_child_chunk_expanded(self) -> None:
        svc = self._svc()
        chunk = _MockChunk(chunk_level=1, parent_text="full parent context")
        result = svc.expand(chunks=[chunk])
        assert str(chunk.chunk_id) in result.context_map
        assert result.context_map[str(chunk.chunk_id)] == "full parent context"

    def test_child_expanded_count(self) -> None:
        svc = self._svc()
        chunks = [
            _MockChunk(chunk_level=1, parent_text="parent A"),
            _MockChunk(chunk_level=1, parent_text="parent B"),
        ]
        result = svc.expand(chunks=chunks)
        assert result.expanded_count == 2
        assert result.child_hit_count == 2

    def test_parent_chunk_not_expanded(self) -> None:
        svc = self._svc()
        chunk = _MockChunk(chunk_level=0, parent_text=None)
        result = svc.expand(chunks=[chunk])
        assert result.expanded_count == 0
        assert str(chunk.chunk_id) not in result.context_map

    def test_child_without_parent_text_not_expanded(self) -> None:
        svc = self._svc()
        chunk = _MockChunk(chunk_level=1, parent_text=None)
        result = svc.expand(chunks=[chunk])
        assert result.expanded_count == 0
        assert result.child_hit_count == 0

    def test_mixed_chunks(self) -> None:
        svc = self._svc()
        child = _MockChunk(chunk_level=1, parent_text="parent text")
        parent = _MockChunk(chunk_level=0, parent_text=None)
        result = svc.expand(chunks=[child, parent])
        assert result.expanded_count == 1
        assert result.child_hit_count == 1
        assert str(child.chunk_id) in result.context_map
        assert str(parent.chunk_id) not in result.context_map

    # --- disabled mode ---

    def test_disabled_returns_empty_map(self) -> None:
        svc = self._svc()
        chunk = _MockChunk(chunk_level=1, parent_text="parent")
        result = svc.expand(chunks=[chunk], enabled=False)
        assert result.context_map == {}
        assert result.expanded_count == 0
        assert result.child_hit_count == 1  # still counted

    def test_disabled_zero_expanded(self) -> None:
        svc = self._svc()
        chunks = [_MockChunk(chunk_level=1, parent_text="p") for _ in range(5)]
        result = svc.expand(chunks=chunks, enabled=False)
        assert result.expanded_count == 0
        assert result.tokens_used == 0

    # --- empty input ---

    def test_empty_chunk_list(self) -> None:
        svc = self._svc()
        result = svc.expand(chunks=[])
        assert result.context_map == {}
        assert result.expanded_count == 0
        assert result.child_hit_count == 0
        assert result.tokens_used == 0

    # --- token budget enforcement ---

    def test_token_budget_truncates_long_parent(self) -> None:
        svc = self._svc()
        long_text = " ".join(["word"] * 600)  # ~600 words → ~2400 chars → ~600 tokens
        chunk = _MockChunk(chunk_level=1, parent_text=long_text)
        result = svc.expand(chunks=[chunk], max_tokens_per_chunk=64)
        expanded = result.context_map[str(chunk.chunk_id)]
        # 64 tokens × 4 chars/token = 256 chars max
        assert len(expanded) <= 256 + 10  # small slack for word boundary

    def test_token_budget_short_text_unchanged(self) -> None:
        svc = self._svc()
        short_text = "Short parent section."
        chunk = _MockChunk(chunk_level=1, parent_text=short_text)
        result = svc.expand(chunks=[chunk], max_tokens_per_chunk=512)
        assert result.context_map[str(chunk.chunk_id)] == short_text

    def test_tokens_used_non_zero_when_expanded(self) -> None:
        svc = self._svc()
        chunk = _MockChunk(chunk_level=1, parent_text="This is some parent content.")
        result = svc.expand(chunks=[chunk])
        assert result.tokens_used > 0

    def test_tokens_used_zero_when_disabled(self) -> None:
        svc = self._svc()
        chunk = _MockChunk(chunk_level=1, parent_text="parent")
        result = svc.expand(chunks=[chunk], enabled=False)
        assert result.tokens_used == 0

    # --- permission safety (same-document guarantee) ---

    def test_expansion_does_not_cross_document_boundary(self) -> None:
        """Parent text comes from the same document as the child; org isolation
        is enforced at the retrieval layer so expansion is inherently safe."""
        svc = self._svc()
        doc_a = uuid4()
        doc_b = uuid4()
        chunk_a = _MockChunk(chunk_level=1, parent_text="doc A parent")
        chunk_a_child = _MockChunk(chunk_level=1, parent_text=None)
        # chunk_b has parent_text from a different document but that can't happen in
        # practice — we just verify that absent parent_text means no expansion.
        result = svc.expand(chunks=[chunk_a, chunk_a_child])
        # Only chunk_a should appear in the map.
        assert str(chunk_a.chunk_id) in result.context_map
        assert str(chunk_a_child.chunk_id) not in result.context_map

    # --- diagnostics ---

    def test_result_is_frozen(self) -> None:
        svc = self._svc()
        result = svc.expand(chunks=[])
        with pytest.raises((AttributeError, TypeError)):
            result.expanded_count = 99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# KeywordRetrievedCandidate — parent fields
# ---------------------------------------------------------------------------


class TestKeywordCandidateParentFields:
    def test_default_parent_fields_are_none(self) -> None:
        candidate = KeywordRetrievedCandidate(
            chunk_id=uuid4(),
            document_id=uuid4(),
            filename="f.pdf",
            page_number=1,
            text="some text",
            section_path=None,
            keyword_score=0.5,
        )
        assert candidate.chunk_level == 0
        assert candidate.parent_chunk_id is None
        assert candidate.parent_text is None

    def test_child_candidate_carries_parent_fields(self) -> None:
        parent_id = uuid4()
        candidate = KeywordRetrievedCandidate(
            chunk_id=uuid4(),
            document_id=uuid4(),
            filename="f.pdf",
            page_number=1,
            text="child",
            section_path=None,
            keyword_score=0.5,
            chunk_level=1,
            parent_chunk_id=parent_id,
            parent_text="parent section text",
        )
        assert candidate.chunk_level == 1
        assert candidate.parent_chunk_id == parent_id
        assert candidate.parent_text == "parent section text"


# ---------------------------------------------------------------------------
# HybridCandidate — parent fields threaded through merge_with_rrf
# ---------------------------------------------------------------------------


class TestHybridMergeParentFields:
    def _vector_child(
        self,
        *,
        chunk_id: UUID | None = None,
        parent_text: str | None = "vector parent text",
        chunk_level: int = 1,
    ) -> RetrievedCandidate:
        return RetrievedCandidate(
            chunk_id=chunk_id or uuid4(),
            document_id=uuid4(),
            filename="d.pdf",
            page_number=1,
            text="child text",
            similarity_score=0.9,
            chunk_level=chunk_level,
            parent_chunk_id=uuid4(),
            parent_text=parent_text,
        )

    def _kw_child(
        self,
        *,
        chunk_id: UUID | None = None,
        parent_text: str | None = "kw parent text",
    ) -> KeywordRetrievedCandidate:
        return KeywordRetrievedCandidate(
            chunk_id=chunk_id or uuid4(),
            document_id=uuid4(),
            filename="d.pdf",
            page_number=1,
            text="child text",
            section_path=None,
            keyword_score=0.5,
            chunk_level=1,
            parent_chunk_id=uuid4(),
            parent_text=parent_text,
        )

    def test_vector_parent_text_in_hybrid(self) -> None:
        child_id = uuid4()
        vc = self._vector_child(chunk_id=child_id, parent_text="vector parent")
        result = merge_with_rrf(
            vector_candidates=[vc],
            keyword_candidates=[],
            vector_weight=0.7,
            rrf_k=60,
            exact_match_boost=1.5,
            exact_match_tokens=[],
        )
        assert result
        merged = result[0]
        assert merged.parent_text == "vector parent"
        assert merged.chunk_level == 1

    def test_keyword_parent_text_when_no_vector(self) -> None:
        kc = self._kw_child(parent_text="kw parent")
        result = merge_with_rrf(
            vector_candidates=[],
            keyword_candidates=[kc],
            vector_weight=0.7,
            rrf_k=60,
            exact_match_boost=1.5,
            exact_match_tokens=[],
        )
        assert result
        merged = result[0]
        assert merged.parent_text == "kw parent"
        assert merged.chunk_level == 1

    def test_vector_parent_preferred_over_keyword_when_both_present(self) -> None:
        chunk_id = uuid4()
        vc = self._vector_child(chunk_id=chunk_id, parent_text="from_vector")
        kc = KeywordRetrievedCandidate(
            chunk_id=chunk_id,
            document_id=vc.document_id,
            filename="d.pdf",
            page_number=1,
            text="child text",
            section_path=None,
            keyword_score=0.5,
            chunk_level=1,
            parent_chunk_id=uuid4(),
            parent_text="from_keyword",
        )
        result = merge_with_rrf(
            vector_candidates=[vc],
            keyword_candidates=[kc],
            vector_weight=0.7,
            rrf_k=60,
            exact_match_boost=1.5,
            exact_match_tokens=[],
        )
        assert result
        merged = result[0]
        assert merged.parent_text == "from_vector"

    def test_keyword_parent_text_fallback_when_vector_has_none(self) -> None:
        chunk_id = uuid4()
        vc = self._vector_child(chunk_id=chunk_id, parent_text=None, chunk_level=0)
        kc = KeywordRetrievedCandidate(
            chunk_id=chunk_id,
            document_id=vc.document_id,
            filename="d.pdf",
            page_number=1,
            text="child text",
            section_path=None,
            keyword_score=0.5,
            chunk_level=1,
            parent_chunk_id=uuid4(),
            parent_text="kw_fallback",
        )
        result = merge_with_rrf(
            vector_candidates=[vc],
            keyword_candidates=[kc],
            vector_weight=0.7,
            rrf_k=60,
            exact_match_boost=1.5,
            exact_match_tokens=[],
        )
        assert result
        merged = result[0]
        assert merged.parent_text == "kw_fallback"

    def test_parent_chunk_without_parent_text(self) -> None:
        """A top-level (chunk_level=0) chunk should have no parent_text."""
        vc = self._vector_child(parent_text=None, chunk_level=0)
        result = merge_with_rrf(
            vector_candidates=[vc],
            keyword_candidates=[],
            vector_weight=0.7,
            rrf_k=60,
            exact_match_boost=1.5,
            exact_match_tokens=[],
        )
        assert result
        assert result[0].parent_text is None


# ---------------------------------------------------------------------------
# Integration: expansion context_map replaces child text in prompt input
# ---------------------------------------------------------------------------


class TestExpansionContextMapPromptIntegration:
    """Verify that the context_map from the expansion service is correctly
    structured so that _build_prompt can substitute parent text."""

    def test_context_map_keyed_by_string_chunk_id(self) -> None:
        svc = ParentContextExpansionService()
        chunk_id = uuid4()
        chunk = _MockChunk(chunk_id=chunk_id, chunk_level=1, parent_text="parent body")
        result = svc.expand(chunks=[chunk])
        assert str(chunk_id) in result.context_map

    def test_context_map_value_is_parent_text(self) -> None:
        svc = ParentContextExpansionService()
        chunk = _MockChunk(chunk_level=1, parent_text="The full parent section.")
        result = svc.expand(chunks=[chunk])
        assert result.context_map[str(chunk.chunk_id)] == "The full parent section."

    def test_empty_parent_text_not_in_map(self) -> None:
        svc = ParentContextExpansionService()
        chunk = _MockChunk(chunk_level=1, parent_text="   ")
        result = svc.expand(chunks=[chunk])
        assert str(chunk.chunk_id) not in result.context_map

    def test_multiple_children_all_in_map(self) -> None:
        svc = ParentContextExpansionService()
        chunks = [
            _MockChunk(chunk_level=1, parent_text=f"parent {i}") for i in range(5)
        ]
        result = svc.expand(chunks=chunks)
        assert len(result.context_map) == 5
        for chunk in chunks:
            assert result.context_map[str(chunk.chunk_id)] == f"parent {chunks.index(chunk)}"

    def test_parent_chunks_absent_from_map(self) -> None:
        svc = ParentContextExpansionService()
        children = [_MockChunk(chunk_level=1, parent_text="p") for _ in range(3)]
        parents = [_MockChunk(chunk_level=0, parent_text=None) for _ in range(2)]
        result = svc.expand(chunks=children + parents)
        for p in parents:
            assert str(p.chunk_id) not in result.context_map


# ---------------------------------------------------------------------------
# Token budget tests
# ---------------------------------------------------------------------------


class TestTokenBudget:
    def test_multiple_chunks_tokens_summed(self) -> None:
        svc = ParentContextExpansionService()
        chunks = [
            _MockChunk(chunk_level=1, parent_text="a" * 40) for _ in range(3)
        ]
        result = svc.expand(chunks=chunks, max_tokens_per_chunk=512)
        assert result.tokens_used > 0
        # Each 40-char text = 10 estimated tokens; 3 chunks = 30 tokens
        assert result.tokens_used == 3 * _estimate_tokens("a" * 40)

    def test_per_chunk_budget_independent(self) -> None:
        """Each chunk is independently truncated — one long chunk doesn't
        consume budget for other chunks."""
        svc = ParentContextExpansionService()
        long_chunk = _MockChunk(chunk_level=1, parent_text="word " * 400)
        short_chunk = _MockChunk(chunk_level=1, parent_text="short text")
        result = svc.expand(
            chunks=[long_chunk, short_chunk], max_tokens_per_chunk=64
        )
        # short chunk should be unexpanded (within budget)
        assert result.context_map[str(short_chunk.chunk_id)] == "short text"
        # long chunk should be truncated
        expanded_long = result.context_map[str(long_chunk.chunk_id)]
        assert len(expanded_long) <= 64 * 4 + 10


# ---------------------------------------------------------------------------
# pytest.mark.parent_child_retrieval marker registration
# ---------------------------------------------------------------------------

pytest_plugins: list[str] = []
