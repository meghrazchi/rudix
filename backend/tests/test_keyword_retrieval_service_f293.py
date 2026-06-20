"""Unit tests for KeywordRetrievalService — F293 hybrid retrieval."""

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

from app.domains.chat.services.keyword_retrieval_service import (
    KeywordRetrievalService,
    _extract_exact_match_tokens,
    _has_exact_match,
)

# ---------------------------------------------------------------------------
# Exact-match token detection
# ---------------------------------------------------------------------------


class TestExtractExactMatchTokens:
    def test_uppercase_acronyms(self) -> None:
        tokens = _extract_exact_match_tokens("What does GDPR say about data retention?")
        assert "GDPR" in tokens

    def test_policy_id_with_hyphen(self) -> None:
        tokens = _extract_exact_match_tokens("Find POLICY-001 requirements")
        assert "POLICY-001" in tokens

    def test_jira_ticket_key(self) -> None:
        tokens = _extract_exact_match_tokens("Status of PROJ-1234 please")
        assert "PROJ-1234" in tokens

    def test_iso_date(self) -> None:
        tokens = _extract_exact_match_tokens("Effective since 2024-01-15")
        assert "2024-01-15" in tokens

    def test_alphanumeric_id(self) -> None:
        tokens = _extract_exact_match_tokens("See section SOC2 controls")
        assert "SOC2" in tokens

    def test_no_match_for_regular_query(self) -> None:
        tokens = _extract_exact_match_tokens("what is the vacation policy?")
        assert tokens == []

    def test_multiple_tokens(self) -> None:
        tokens = _extract_exact_match_tokens("GDPR and HIPAA compliance for SOC-2")
        assert "GDPR" in tokens
        assert "HIPAA" in tokens

    def test_deduplication(self) -> None:
        tokens = _extract_exact_match_tokens("GDPR GDPR compliance")
        assert tokens.count("GDPR") == 1


class TestHasExactMatch:
    def test_token_in_chunk_text(self) -> None:
        assert _has_exact_match("This document covers GDPR requirements.", None, ["GDPR"])

    def test_token_in_section_path(self) -> None:
        assert _has_exact_match("Some text here.", "Section > POLICY-001 > Details", ["POLICY-001"])

    def test_case_insensitive(self) -> None:
        assert _has_exact_match("This covers gdpr requirements.", None, ["GDPR"])

    def test_no_match(self) -> None:
        assert not _has_exact_match("General data protection rules apply.", None, ["SOC-2"])

    def test_empty_tokens(self) -> None:
        assert not _has_exact_match("GDPR compliance text", None, [])


# ---------------------------------------------------------------------------
# KeywordRetrievalService
# ---------------------------------------------------------------------------


def _make_row(
    *,
    chunk_id: UUID | None = None,
    document_id: UUID | None = None,
    text: str = "Sample chunk text",
    page_number: int | None = 1,
    section_path: str | None = None,
    filename: str = "policy.pdf",
    rank_score: float = 0.5,
    chunk_level: int = 0,
    parent_chunk_id: UUID | None = None,
    parent_text: str | None = None,
) -> dict:
    return {
        "chunk_id": chunk_id or uuid4(),
        "document_id": document_id or uuid4(),
        "text": text,
        "page_number": page_number,
        "section_path": section_path,
        "filename": filename,
        "rank_score": rank_score,
        # Parent-child fields (F300).
        "chunk_level": chunk_level,
        "parent_chunk_id": parent_chunk_id,
        "parent_text": parent_text,
    }


def _make_session(rows: list[dict]) -> AsyncMock:
    """Return a mock AsyncSession whose execute() returns dict-like rows via .mappings().all()."""

    async def _execute(stmt):
        result = MagicMock()
        result.mappings.return_value.all.return_value = rows
        return result

    session = AsyncMock()
    session.execute = _execute
    return session


class TestKeywordRetrievalService:
    @pytest.mark.asyncio
    async def test_empty_query_returns_no_results(self) -> None:
        service = KeywordRetrievalService()
        session = AsyncMock()
        result = await service.search_chunks(
            session=session,
            query="",
            organization_id=uuid4(),
            document_ids=None,
            top_k=10,
        )
        assert result.candidates == []
        assert result.query_tokens == []

    @pytest.mark.asyncio
    async def test_empty_document_ids_returns_no_results(self) -> None:
        service = KeywordRetrievalService()
        session = AsyncMock()
        result = await service.search_chunks(
            session=session,
            query="GDPR compliance",
            organization_id=uuid4(),
            document_ids=[],
            top_k=10,
        )
        assert result.candidates == []

    @pytest.mark.asyncio
    async def test_returns_candidates_from_rows(self) -> None:
        org_id = uuid4()
        doc_id = uuid4()
        chunk_id = uuid4()
        rows = [_make_row(chunk_id=chunk_id, document_id=doc_id, rank_score=0.8)]

        service = KeywordRetrievalService()
        session = _make_session(rows)

        result = await service.search_chunks(
            session=session,
            query="policy retention",
            organization_id=org_id,
            document_ids=None,
            top_k=5,
        )

        assert len(result.candidates) == 1
        cand = result.candidates[0]
        assert cand.document_id == doc_id
        assert cand.chunk_id == chunk_id
        assert cand.keyword_score == pytest.approx(0.8, abs=1e-6)
        assert not cand.exact_match_hit

    @pytest.mark.asyncio
    async def test_exact_match_boost_applied(self) -> None:
        org_id = uuid4()
        doc_id = uuid4()
        chunk_id = uuid4()
        rows = [
            _make_row(
                chunk_id=chunk_id,
                document_id=doc_id,
                text="GDPR article 5 applies here",
                rank_score=0.5,
            )
        ]

        service = KeywordRetrievalService()
        session = _make_session(rows)

        result = await service.search_chunks(
            session=session,
            query="GDPR article 5",
            organization_id=org_id,
            document_ids=None,
            top_k=5,
            exact_match_boost=2.0,
        )

        assert len(result.candidates) == 1
        cand = result.candidates[0]
        assert cand.exact_match_hit is True
        assert cand.keyword_score == pytest.approx(1.0, abs=1e-6)  # 0.5 * 2.0

    @pytest.mark.asyncio
    async def test_exact_match_tokens_extracted(self) -> None:
        org_id = uuid4()
        service = KeywordRetrievalService()
        session = _make_session([])

        result = await service.search_chunks(
            session=session,
            query="POLICY-001 compliance requirements",
            organization_id=org_id,
            document_ids=None,
            top_k=5,
        )

        assert "POLICY-001" in result.exact_match_tokens

    @pytest.mark.asyncio
    async def test_query_tokens_split(self) -> None:
        org_id = uuid4()
        service = KeywordRetrievalService()
        session = _make_session([])

        result = await service.search_chunks(
            session=session,
            query="data retention policy",
            organization_id=org_id,
            document_ids=None,
            top_k=5,
        )

        assert result.query_tokens == ["data", "retention", "policy"]

    @pytest.mark.asyncio
    async def test_cross_org_row_skipped(self) -> None:
        """Rows with a document_id not in document_ids are dropped (defence-in-depth)."""
        org_id = uuid4()
        allowed_doc_id = uuid4()
        other_doc_id = uuid4()
        chunk_id = uuid4()
        rows = [_make_row(chunk_id=chunk_id, document_id=other_doc_id, rank_score=0.9)]

        service = KeywordRetrievalService()
        session = _make_session(rows)

        result = await service.search_chunks(
            session=session,
            query="data compliance",
            organization_id=org_id,
            document_ids=[allowed_doc_id],
            top_k=10,
        )

        # The row belongs to other_doc_id which is not in document_ids.
        assert len(result.candidates) == 0

    @pytest.mark.asyncio
    async def test_invalid_chunk_id_skipped(self) -> None:
        org_id = uuid4()
        bad_row = _make_row(rank_score=0.3)
        bad_row["chunk_id"] = "not-a-uuid"

        service = KeywordRetrievalService()
        session = _make_session([bad_row])

        # Should not raise; bad row is silently skipped.
        result = await service.search_chunks(
            session=session,
            query="compliance",
            organization_id=org_id,
            document_ids=None,
            top_k=5,
        )
        assert len(result.candidates) == 0

    @pytest.mark.asyncio
    async def test_page_number_none_for_zero(self) -> None:
        org_id = uuid4()
        rows = [_make_row(page_number=0, rank_score=0.4)]

        service = KeywordRetrievalService()
        session = _make_session(rows)

        result = await service.search_chunks(
            session=session,
            query="policy",
            organization_id=org_id,
            document_ids=None,
            top_k=5,
        )

        assert result.candidates[0].page_number is None
