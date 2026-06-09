from __future__ import annotations

import os
from dataclasses import dataclass
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

from app.domains.ai.providers.errors import (
    InvalidProviderResponseError,
    ProviderUnavailableError,
)
from app.domains.ai.providers.protocols import EmbeddingRequest, EmbeddingResponse
from app.domains.documents.services.embedding_service import (
    EmbeddingService,
    PermanentEmbeddingError,
    TransientEmbeddingError,
)


@dataclass(frozen=True)
class FakeChunk:
    id: UUID
    text: str
    token_count: int


class FakeEmbeddingProvider:
    """Fake EmbeddingProvider for unit tests."""

    def __init__(self, responses: list[EmbeddingResponse | Exception]) -> None:
        self._responses = responses
        self.calls: list[EmbeddingRequest] = []

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        self.calls.append(request)
        if not self._responses:
            raise RuntimeError("No fake response available")
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _response(vectors: list[list[float]], prompt_tokens: int = 100, total_tokens: int = 100) -> EmbeddingResponse:
    return EmbeddingResponse(
        vectors=vectors,
        model="text-embedding-3-small",
        prompt_tokens=prompt_tokens,
        total_tokens=total_tokens,
        latency_ms=5,
    )


@pytest.mark.asyncio
async def test_embed_chunks_batches_and_tracks_usage() -> None:
    chunks = [FakeChunk(id=uuid4(), text=f"chunk-{i}", token_count=50) for i in range(5)]

    provider = FakeEmbeddingProvider(
        responses=[
            _response([[0.1, 0.2], [0.3, 0.4]], prompt_tokens=100, total_tokens=100),
            _response([[0.5, 0.6], [0.7, 0.8]], prompt_tokens=100, total_tokens=100),
            _response([[0.9, 1.0]], prompt_tokens=50, total_tokens=50),
        ]
    )

    service = EmbeddingService(
        batch_max_items=2,
        batch_max_tokens=1000,
        retry_max_attempts=2,
        cost_per_million_tokens_usd=1.0,
        provider=provider,
        model_name="text-embedding-3-small",
        index_version="v-test",
    )

    result = await service.embed_chunks(chunks=chunks)

    assert len(provider.calls) == 3
    assert [len(call.texts) for call in provider.calls] == [2, 2, 1]
    assert result.batch_count == 3
    assert result.retry_count == 0
    assert result.input_tokens == 250
    assert result.total_tokens == 250
    assert float(result.approximate_cost_usd) == pytest.approx(0.00025)
    assert list(result.vectors_by_chunk_id.keys()) == [chunk.id for chunk in chunks]


@pytest.mark.asyncio
async def test_embed_chunks_respects_token_batch_budget() -> None:
    chunks = [
        FakeChunk(id=uuid4(), text="a", token_count=100),
        FakeChunk(id=uuid4(), text="b", token_count=140),
        FakeChunk(id=uuid4(), text="c", token_count=40),
    ]

    provider = FakeEmbeddingProvider(
        responses=[
            _response([[0.1], [0.2]], prompt_tokens=240, total_tokens=240),
            _response([[0.3]], prompt_tokens=40, total_tokens=40),
        ]
    )

    service = EmbeddingService(
        batch_max_items=100,
        batch_max_tokens=250,
        provider=provider,
        model_name="text-embedding-3-small",
    )

    result = await service.embed_chunks(chunks=chunks)

    assert len(provider.calls) == 2
    assert [len(call.texts) for call in provider.calls] == [2, 1]
    assert result.batch_count == 2


@pytest.mark.asyncio
async def test_embed_chunks_retries_transient_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    chunks = [FakeChunk(id=uuid4(), text="chunk", token_count=10)]

    provider = FakeEmbeddingProvider(
        responses=[
            ProviderUnavailableError("temporary network failure"),
            _response([[0.1, 0.2, 0.3]]),
        ]
    )

    sleep_calls: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    monkeypatch.setattr(
        "app.domains.documents.services.embedding_service.asyncio.sleep", _fake_sleep
    )

    service = EmbeddingService(
        retry_max_attempts=3,
        retry_base_seconds=0.1,
        retry_max_seconds=1.0,
        provider=provider,
    )

    result = await service.embed_chunks(chunks=chunks)

    assert len(provider.calls) == 2
    assert sleep_calls == [0.1]
    assert result.retry_count == 1


@pytest.mark.asyncio
async def test_embed_chunks_raises_transient_after_retry_exhaustion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chunks = [FakeChunk(id=uuid4(), text="chunk", token_count=10)]

    provider = FakeEmbeddingProvider(
        responses=[
            ProviderUnavailableError("network failure"),
            ProviderUnavailableError("network failure"),
            ProviderUnavailableError("network failure"),
        ]
    )

    sleep_calls: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    monkeypatch.setattr(
        "app.domains.documents.services.embedding_service.asyncio.sleep", _fake_sleep
    )

    service = EmbeddingService(
        retry_max_attempts=3,
        retry_base_seconds=0.2,
        retry_max_seconds=0.5,
        provider=provider,
    )

    with pytest.raises(TransientEmbeddingError, match="failed after retries"):
        await service.embed_chunks(chunks=chunks)

    assert len(provider.calls) == 3
    assert sleep_calls == [0.2, 0.4]


@pytest.mark.asyncio
async def test_embed_chunks_raises_permanent_for_non_transient_error() -> None:
    chunks = [FakeChunk(id=uuid4(), text="chunk", token_count=10)]

    provider = FakeEmbeddingProvider(
        responses=[
            InvalidProviderResponseError("invalid response from provider"),
        ]
    )

    service = EmbeddingService(provider=provider)

    with pytest.raises(PermanentEmbeddingError, match="failed permanently"):
        await service.embed_chunks(chunks=chunks)

    assert len(provider.calls) == 1
