"""Unit tests for TableRetrievalService — F298."""

from __future__ import annotations

import os
from dataclasses import dataclass
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

from app.domains.chat.services.table_retrieval_service import (
    TableRetrievalService,
    is_table_query,
)


# ---------------------------------------------------------------------------
# Fake chunk for testing
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FakeChunk:
    chunk_id: object
    similarity_score: float
    chunk_type: str = "text"
    text: str = "sample text"


# ---------------------------------------------------------------------------
# is_table_query
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "query",
    [
        "What are the prices in the table?",
        "Show me the revenue breakdown by quarter",
        "Compare the values for Q1 vs Q2",
        "How many rows are in the spreadsheet?",
        "What is the total cost?",
        "List of all products",
        "What is the average revenue?",
        "How much did we spend in 2024?",
        "What is the maximum value?",
        "Show me a summary of metrics",
    ],
)
def test_is_table_query_positive(query: str):
    assert is_table_query(query) is True


@pytest.mark.parametrize(
    "query",
    [
        "What is our privacy policy?",
        "When was the company founded?",
        "Describe the onboarding process",
    ],
)
def test_is_table_query_negative(query: str):
    assert is_table_query(query) is False


# ---------------------------------------------------------------------------
# apply_table_boost — basic cases
# ---------------------------------------------------------------------------


def test_apply_table_boost_boosts_table_chunks():
    svc = TableRetrievalService()
    chunks = [
        FakeChunk(chunk_id=uuid4(), similarity_score=0.8, chunk_type="table"),
        FakeChunk(chunk_id=uuid4(), similarity_score=0.7, chunk_type="text"),
    ]
    result_chunks, meta = svc.apply_table_boost(
        chunks=chunks,
        query="What are the total revenue values in the table?",
        boost_multiplier=1.25,
        enabled=True,
    )
    scores = {c.chunk_type: c.similarity_score for c in result_chunks}
    assert scores["table"] == pytest.approx(0.8 * 1.25)
    assert scores["text"] == pytest.approx(0.7)
    assert meta.boost_applied is True
    assert meta.boosted_count == 1
    assert meta.table_chunk_count == 1


def test_apply_table_boost_disabled_skips_boost():
    svc = TableRetrievalService()
    chunks = [FakeChunk(chunk_id=uuid4(), similarity_score=0.8, chunk_type="table")]
    result_chunks, meta = svc.apply_table_boost(
        chunks=chunks,
        query="What are the totals in the table?",
        boost_multiplier=1.25,
        enabled=False,
    )
    assert result_chunks[0].similarity_score == pytest.approx(0.8)
    assert meta.boost_applied is False


def test_apply_table_boost_no_boost_when_not_table_query():
    svc = TableRetrievalService()
    chunks = [FakeChunk(chunk_id=uuid4(), similarity_score=0.8, chunk_type="table")]
    result_chunks, meta = svc.apply_table_boost(
        chunks=chunks,
        query="What is the general privacy policy?",
        boost_multiplier=1.25,
        enabled=True,
    )
    assert result_chunks[0].similarity_score == pytest.approx(0.8)
    assert meta.boost_applied is False
    assert meta.table_chunk_count == 1


def test_apply_table_boost_no_table_chunks_skips():
    svc = TableRetrievalService()
    chunks = [
        FakeChunk(chunk_id=uuid4(), similarity_score=0.8, chunk_type="text"),
        FakeChunk(chunk_id=uuid4(), similarity_score=0.7, chunk_type="text"),
    ]
    result_chunks, meta = svc.apply_table_boost(
        chunks=chunks,
        query="What are the total revenue values?",
        boost_multiplier=1.25,
        enabled=True,
    )
    for chunk in result_chunks:
        assert chunk.similarity_score in (0.8, 0.7)
    assert meta.boost_applied is False
    assert meta.table_chunk_count == 0


def test_apply_table_boost_multiplier_one_is_noop():
    svc = TableRetrievalService()
    chunks = [FakeChunk(chunk_id=uuid4(), similarity_score=0.8, chunk_type="table")]
    result_chunks, meta = svc.apply_table_boost(
        chunks=chunks,
        query="Show me the table breakdown",
        boost_multiplier=1.0,
        enabled=True,
    )
    assert result_chunks[0].similarity_score == pytest.approx(0.8)
    assert meta.boost_applied is False


def test_apply_table_boost_multiple_table_chunks():
    svc = TableRetrievalService()
    chunks = [
        FakeChunk(chunk_id=uuid4(), similarity_score=0.5, chunk_type="table"),
        FakeChunk(chunk_id=uuid4(), similarity_score=0.6, chunk_type="table"),
        FakeChunk(chunk_id=uuid4(), similarity_score=0.9, chunk_type="text"),
    ]
    result_chunks, meta = svc.apply_table_boost(
        chunks=chunks,
        query="What is the breakdown by column?",
        boost_multiplier=1.5,
        enabled=True,
    )
    table_chunks = [c for c in result_chunks if c.chunk_type == "table"]
    text_chunks = [c for c in result_chunks if c.chunk_type == "text"]

    assert all(c.similarity_score > 0.5 for c in table_chunks)
    assert text_chunks[0].similarity_score == pytest.approx(0.9)
    assert meta.boosted_count == 2
    assert meta.table_chunk_count == 2


def test_apply_table_boost_empty_chunks():
    svc = TableRetrievalService()
    result_chunks, meta = svc.apply_table_boost(
        chunks=[],
        query="What are the totals in the table?",
        boost_multiplier=1.25,
        enabled=True,
    )
    assert result_chunks == []
    assert meta.boost_applied is False


def test_apply_table_boost_result_count_unchanged():
    svc = TableRetrievalService()
    chunks = [
        FakeChunk(chunk_id=uuid4(), similarity_score=0.8, chunk_type="table"),
        FakeChunk(chunk_id=uuid4(), similarity_score=0.7, chunk_type="text"),
        FakeChunk(chunk_id=uuid4(), similarity_score=0.6, chunk_type="table"),
    ]
    result_chunks, meta = svc.apply_table_boost(
        chunks=chunks,
        query="Show me the comparison table",
        boost_multiplier=1.25,
        enabled=True,
    )
    assert len(result_chunks) == 3


# ---------------------------------------------------------------------------
# Boost preserves other chunk fields
# ---------------------------------------------------------------------------


def test_apply_table_boost_preserves_chunk_type():
    svc = TableRetrievalService()
    chunks = [FakeChunk(chunk_id=uuid4(), similarity_score=0.8, chunk_type="table")]
    result_chunks, _ = svc.apply_table_boost(
        chunks=chunks,
        query="What is the total in the table?",
        boost_multiplier=1.25,
        enabled=True,
    )
    assert result_chunks[0].chunk_type == "table"


def test_apply_table_boost_table_chunk_count_matches():
    svc = TableRetrievalService()
    chunks = [
        FakeChunk(chunk_id=uuid4(), similarity_score=0.5, chunk_type="table"),
        FakeChunk(chunk_id=uuid4(), similarity_score=0.6, chunk_type="table"),
        FakeChunk(chunk_id=uuid4(), similarity_score=0.9, chunk_type="text"),
    ]
    _, meta = svc.apply_table_boost(
        chunks=chunks,
        query="What are the column values?",
        boost_multiplier=1.25,
        enabled=True,
    )
    assert meta.table_chunk_count == 2
