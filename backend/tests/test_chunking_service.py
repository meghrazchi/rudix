from __future__ import annotations

import os
from itertools import pairwise
from uuid import uuid4

import pytest

# Ensure strict settings can be loaded when importing modules in tests.
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

from app.domains.documents.services.chunking_service import ChunkingService
from app.domains.documents.services.text_extraction import ExtractedSection


@pytest.mark.asyncio
async def test_chunking_service_is_deterministic_with_overlap() -> None:
    service = ChunkingService(
        chunk_size_tokens=30,
        chunk_overlap_tokens=10,
        embedding_model="text-embedding-3-small",
        index_version="v-test",
        tiny_chunk_min_tokens=1,
    )
    text = " ".join(f"term{i}" for i in range(180))
    pages = [ExtractedSection(page_number=1, text=text, char_count=len(text))]

    first = await service.chunk(document_id=uuid4(), pages=pages)
    second = await service.chunk(document_id=uuid4(), pages=pages)

    assert len(first) > 1
    assert [chunk.text for chunk in first] == [chunk.text for chunk in second]
    assert [chunk.token_count for chunk in first] == [chunk.token_count for chunk in second]
    assert [chunk.page_number for chunk in first] == [chunk.page_number for chunk in second]
    assert [chunk.chunk_index for chunk in first] == list(range(len(first)))
    assert all(chunk.token_count <= service.chunk_size_tokens for chunk in first)

    for previous, current in pairwise(first):
        previous_terms = set(previous.text.split())
        current_terms = set(current.text.split())
        assert previous_terms & current_terms
        assert current_terms - previous_terms


@pytest.mark.asyncio
async def test_chunking_service_handles_cross_page_chunks() -> None:
    service = ChunkingService(
        chunk_size_tokens=45,
        chunk_overlap_tokens=8,
        embedding_model="text-embedding-3-small",
        index_version="v-test",
        tiny_chunk_min_tokens=1,
    )
    pages = [
        ExtractedSection(page_number=1, text=" ".join(["alpha"] * 90), char_count=90 * 6),
        ExtractedSection(page_number=2, text=" ".join(["beta"] * 90), char_count=90 * 5),
    ]

    chunks = await service.chunk(document_id=uuid4(), pages=pages)

    assert len(chunks) >= 2
    assert any(chunk.page_number == 1 for chunk in chunks)
    assert any(chunk.page_number == 2 for chunk in chunks)

    boundary_chunk = next(
        (chunk for chunk in chunks if "alpha" in chunk.text and "beta" in chunk.text), None
    )
    assert boundary_chunk is not None
    assert boundary_chunk.page_number in {1, 2}


@pytest.mark.asyncio
async def test_chunking_service_keeps_single_small_document_chunk() -> None:
    service = ChunkingService(
        chunk_size_tokens=50,
        chunk_overlap_tokens=10,
        embedding_model="text-embedding-3-small",
        index_version="v-test",
    )

    chunks = await service.chunk(
        document_id=uuid4(),
        pages=[ExtractedSection(page_number=1, text="tiny", char_count=4)],
    )

    assert len(chunks) == 1
    assert chunks[0].chunk_index == 0
    assert chunks[0].page_number == 1
    assert chunks[0].token_count > 0
    assert chunks[0].text == "tiny"
