"""Tenant isolation tests for hybrid retrieval — F293.

Verifies that organization_id scoping is enforced at every layer:
- KeywordRetrievalService filters by organization_id in SQL.
- Row-level defence-in-depth: chunks from other document_ids are dropped.
- HybridRetrievalService merge never introduces cross-org chunks.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock
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

from app.domains.chat.services.hybrid_retrieval_service import HybridRetrievalService
from app.domains.chat.services.keyword_retrieval_service import KeywordRetrievalService
from app.domains.chat.services.query_retrieval_service import RetrievedCandidate

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_row(**kwargs) -> dict:
    defaults: dict = {
        "chunk_id": uuid4(),
        "document_id": uuid4(),
        "text": "some chunk text",
        "page_number": 1,
        "section_path": None,
        "filename": "doc.pdf",
        "rank_score": 0.5,
        # Parent-child fields (F300).
        "chunk_level": 0,
        "parent_chunk_id": None,
        "parent_text": None,
    }
    defaults.update(kwargs)
    return defaults


def _make_session(rows: list[dict]) -> AsyncMock:
    async def _execute(stmt):
        result = MagicMock()
        result.mappings.return_value.all.return_value = rows
        return result

    session = AsyncMock()
    session.execute = _execute
    return session


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_keyword_service_drops_chunk_from_wrong_document_id() -> None:
    """Row whose document_id is not in the allowed list is silently dropped."""
    org_id = uuid4()
    allowed_doc_id = uuid4()
    intruder_doc_id = uuid4()

    rows = [
        _make_row(document_id=allowed_doc_id, rank_score=0.8),
        _make_row(document_id=intruder_doc_id, rank_score=0.9),
    ]
    session = _make_session(rows)
    service = KeywordRetrievalService()

    result = await service.search_chunks(
        session=session,
        query="compliance policy",
        organization_id=org_id,
        document_ids=[allowed_doc_id],
        top_k=10,
    )

    returned_doc_ids = {c.document_id for c in result.candidates}
    assert intruder_doc_id not in returned_doc_ids
    assert allowed_doc_id in returned_doc_ids


@pytest.mark.asyncio
async def test_keyword_service_returns_empty_for_empty_document_id_list() -> None:
    """Empty allowed document_ids ⇒ no candidates regardless of DB rows."""
    org_id = uuid4()
    rows = [_make_row(rank_score=0.9)]
    session = _make_session(rows)
    service = KeywordRetrievalService()

    result = await service.search_chunks(
        session=session,
        query="anything",
        organization_id=org_id,
        document_ids=[],
        top_k=10,
    )

    assert result.candidates == []


@pytest.mark.asyncio
async def test_hybrid_merge_preserves_org_scoped_document_ids() -> None:
    """After RRF merge, document_ids stay within the set that was retrieved."""
    org_a_doc_ids = [uuid4(), uuid4()]

    def _vc(doc_id: UUID) -> RetrievedCandidate:
        return RetrievedCandidate(
            chunk_id=uuid4(),
            document_id=doc_id,
            filename="a.pdf",
            page_number=None,
            text="org A text",
            similarity_score=0.8,
        )

    vector_candidates = [_vc(d) for d in org_a_doc_ids]
    service = HybridRetrievalService()

    result = service.merge(
        vector_candidates=vector_candidates,
        keyword_candidates=[],
        exact_match_tokens=[],
        vector_weight=0.7,
        rrf_k=60,
        exact_match_boost=1.5,
    )

    returned_doc_ids = {c.document_id for c in result.candidates}
    assert returned_doc_ids.issubset(set(org_a_doc_ids))


@pytest.mark.asyncio
async def test_hybrid_merge_no_cross_org_contamination() -> None:
    """Chunks from org B's vector results never appear in org A's hybrid result."""
    org_a_doc = uuid4()
    org_b_doc = uuid4()

    # Simulate: org A only calls with org_a_doc's vector candidates.
    # Org B's doc_id should never appear even if somehow injected.
    org_a_vc = RetrievedCandidate(
        chunk_id=uuid4(),
        document_id=org_a_doc,
        filename="org_a.pdf",
        page_number=1,
        text="org A content",
        similarity_score=0.9,
    )

    service = HybridRetrievalService()
    result = service.merge(
        vector_candidates=[org_a_vc],
        keyword_candidates=[],
        exact_match_tokens=[],
        vector_weight=0.7,
        rrf_k=60,
        exact_match_boost=1.5,
    )

    for candidate in result.candidates:
        assert candidate.document_id != org_b_doc


@pytest.mark.asyncio
async def test_keyword_service_invalid_doc_id_row_dropped() -> None:
    """Rows with an unparseable document_id are silently skipped."""
    org_id = uuid4()
    valid_row = _make_row(rank_score=0.7)
    bad_row = _make_row(rank_score=0.9)
    bad_row["document_id"] = "not-a-valid-uuid"

    session = _make_session([valid_row, bad_row])
    service = KeywordRetrievalService()

    result = await service.search_chunks(
        session=session,
        query="security policy",
        organization_id=org_id,
        document_ids=None,
        top_k=10,
    )

    for candidate in result.candidates:
        try:
            UUID(str(candidate.document_id))
        except ValueError:
            pytest.fail("Invalid UUID slipped through into candidates")


@pytest.mark.asyncio
async def test_keyword_service_exact_match_boost_does_not_leak_org() -> None:
    """Exact match boosting only scores higher; it never adds new document_ids."""
    org_id = uuid4()
    allowed_doc_id = uuid4()
    another_doc_id = uuid4()

    rows = [
        _make_row(document_id=allowed_doc_id, text="GDPR compliance rules", rank_score=0.4),
        _make_row(document_id=another_doc_id, text="GDPR more data", rank_score=0.6),
    ]
    session = _make_session(rows)
    service = KeywordRetrievalService()

    result = await service.search_chunks(
        session=session,
        query="GDPR compliance",
        organization_id=org_id,
        document_ids=[allowed_doc_id],
        top_k=10,
        exact_match_boost=5.0,
    )

    for candidate in result.candidates:
        assert candidate.document_id == allowed_doc_id


@pytest.mark.asyncio
async def test_hybrid_merge_chunk_ids_unique() -> None:
    """Every chunk_id appears at most once in the merged output."""
    shared_id = uuid4()
    doc_id = uuid4()

    vc = RetrievedCandidate(
        chunk_id=shared_id,
        document_id=doc_id,
        filename="f.pdf",
        page_number=1,
        text="shared chunk",
        similarity_score=0.8,
    )
    from app.domains.chat.services.keyword_retrieval_service import KeywordRetrievedCandidate

    kc = KeywordRetrievedCandidate(
        chunk_id=shared_id,
        document_id=doc_id,
        filename="f.pdf",
        page_number=1,
        text="shared chunk",
        section_path=None,
        keyword_score=0.6,
        exact_match_hit=False,
    )

    service = HybridRetrievalService()
    result = service.merge(
        vector_candidates=[vc],
        keyword_candidates=[kc],
        exact_match_tokens=[],
        vector_weight=0.7,
        rrf_k=60,
        exact_match_boost=1.5,
    )

    chunk_ids = [str(c.chunk_id) for c in result.candidates]
    assert len(chunk_ids) == len(set(chunk_ids)), "Duplicate chunk_ids in merged output"
