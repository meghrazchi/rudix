"""Tests for F345 — concurrent retrieval and tool execution optimizer."""

from __future__ import annotations

import asyncio
import os
from time import perf_counter
from unittest.mock import AsyncMock
from uuid import uuid4

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

from app.domains.chat.services.graph_retrieval_service import (
    GraphRetrievalResult,
    GraphRetrievedChunk,
)
from app.domains.chat.services.keyword_retrieval_service import (
    KeywordRetrievalResult,
    KeywordRetrievedCandidate,
)
from app.domains.chat.services.parallel_retrieval_optimizer import (
    ParallelRetrievalBudget,
    ParallelRetrievalOptimizer,
)
from app.domains.chat.services.query_retrieval_service import RetrievedCandidate


class _FakeQueryRetrievalService:
    def __init__(self, *, delay_seconds: float = 0.1) -> None:
        self.embedding_model = "test-embedding"
        self.delay_seconds = delay_seconds
        self.embed_calls: list[str] = []
        self.retrieve_calls: list[tuple[list[float], list[object] | None]] = []

    async def embed_query(self, *, question: str) -> tuple[list[float], int]:
        self.embed_calls.append(question)
        await asyncio.sleep(self.delay_seconds)
        return [1.0, 2.0, 3.0], 8

    def retrieve_candidates(
        self,
        *,
        query_vector: list[float],
        organization_id,
        document_ids,
        initial_top_k: int,
        qdrant_client=None,
    ) -> list[RetrievedCandidate]:
        del organization_id, qdrant_client, initial_top_k
        self.retrieve_calls.append((query_vector, document_ids))
        doc_id = document_ids[0] if document_ids else uuid4()
        return [
            RetrievedCandidate(
                document_id=doc_id,
                chunk_id=uuid4(),
                filename="vector.pdf",
                page_number=1,
                text="vector result",
                similarity_score=0.9,
            )
        ]


class _FakeKeywordRetrievalService:
    def __init__(self, *, delay_seconds: float = 0.1) -> None:
        self.delay_seconds = delay_seconds
        self.calls: list[tuple[str, list[object] | None]] = []

    async def search_chunks(
        self,
        *,
        session,
        query: str,
        organization_id,
        document_ids,
        top_k: int,
        exact_match_boost: float = 1.5,
    ) -> KeywordRetrievalResult:
        del session, organization_id, top_k, exact_match_boost
        self.calls.append((query, document_ids))
        await asyncio.sleep(self.delay_seconds)
        doc_id = document_ids[0] if document_ids else uuid4()
        candidate = KeywordRetrievedCandidate(
            document_id=doc_id,
            chunk_id=uuid4(),
            filename="keyword.pdf",
            page_number=1,
            text=f"keyword result for {query}",
            section_path=None,
            keyword_score=0.8,
            exact_match_hit=True,
        )
        return KeywordRetrievalResult(
            candidates=[candidate],
            query_tokens=query.split(),
            exact_match_tokens=["TEST"],
        )


class _FakeGraphRetrievalService:
    def __init__(self, *, delay_seconds: float = 0.1) -> None:
        self.delay_seconds = delay_seconds
        self.calls: list[tuple[str, list[object] | None]] = []

    async def expand(
        self,
        *,
        session,
        organization_id,
        question: str,
        allowed_document_ids,
        graph_enabled: bool,
    ) -> GraphRetrievalResult:
        del session, organization_id
        self.calls.append((question, allowed_document_ids))
        if not graph_enabled:
            return GraphRetrievalResult(
                graph_context_enabled=False,
                graph_context_used=False,
                graph_context_reason="disabled",
            )
        await asyncio.sleep(self.delay_seconds)
        doc_id = uuid4()
        return GraphRetrievalResult(
            chunks=[
                GraphRetrievedChunk(
                    document_id=doc_id,
                    chunk_id=uuid4(),
                    filename="graph.pdf",
                    page_number=1,
                    text="graph result",
                    similarity_score=0.75,
                    graph_score=0.75,
                )
            ],
            graph_context_enabled=True,
            graph_context_used=True,
            graph_chunk_count=1,
        )


@pytest.mark.asyncio
async def test_parallel_retrieval_optimizer_runs_branches_concurrently() -> None:
    optimizer = ParallelRetrievalOptimizer()
    query_service = _FakeQueryRetrievalService(delay_seconds=0.12)
    keyword_service = _FakeKeywordRetrievalService(delay_seconds=0.12)
    graph_service = _FakeGraphRetrievalService(delay_seconds=0.12)
    organization_id = uuid4()
    document_ids = [uuid4()]

    started = perf_counter()
    result = await optimizer.execute(
        session=AsyncMock(),
        organization_id=organization_id,
        document_ids=document_ids,
        queries=["alpha", "beta"],
        query_retrieval_service=query_service,
        keyword_retrieval_service=keyword_service,
        graph_retrieval_service=graph_service,
        graph_enabled=True,
        keyword_enabled=True,
        qdrant_client=None,
        top_k=3,
        exact_match_boost=1.5,
        budget=ParallelRetrievalBudget(max_parallel_calls=4, timeout_ms=1000, max_retry_attempts=0),
    )
    elapsed = perf_counter() - started

    assert elapsed < 0.45
    assert result.plan.admitted_queries == ["alpha", "beta"]
    assert len(result.query_records) == 2
    assert len(result.branch_records) >= 5
    assert all(record.succeeded for record in result.branch_records)
    assert result.total_embedding_prompt_tokens == 16
    assert result.graph_result.graph_context_used is True
    assert query_service.retrieve_calls[0][1] == document_ids
    assert keyword_service.calls[0][1] == document_ids


@pytest.mark.asyncio
async def test_parallel_retrieval_optimizer_degrades_on_timeout() -> None:
    optimizer = ParallelRetrievalOptimizer()
    query_service = _FakeQueryRetrievalService(delay_seconds=0.01)
    keyword_service = _FakeKeywordRetrievalService(delay_seconds=0.2)
    graph_service = _FakeGraphRetrievalService(delay_seconds=0.01)

    result = await optimizer.execute(
        session=AsyncMock(),
        organization_id=uuid4(),
        document_ids=None,
        queries=["alpha"],
        query_retrieval_service=query_service,
        keyword_retrieval_service=keyword_service,
        graph_retrieval_service=graph_service,
        graph_enabled=True,
        keyword_enabled=True,
        qdrant_client=None,
        top_k=3,
        exact_match_boost=1.5,
        budget=ParallelRetrievalBudget(max_parallel_calls=2, timeout_ms=50, max_retry_attempts=0),
    )

    assert any(record.error_code == "timeout" for record in result.branch_records)
    assert any(
        record.branch_name == "vector_search" and record.succeeded
        for record in result.branch_records
    )
    assert result.graph_result.graph_context_used is True
