"""Tests for F219: local embedding provider adapter and vector-dimension safety."""

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
    ProviderInternalError,
    ProviderUnavailableError,
)
from app.domains.ai.providers.local.embedding_adapter import OpenAICompatibleEmbeddingProvider
from app.domains.ai.providers.protocols import EmbeddingRequest, EmbeddingResponse
from app.domains.documents.services.embedding_service import (
    EmbeddingService,
    TransientEmbeddingError,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FakeChunk:
    id: UUID
    text: str
    token_count: int


class _FakeEmbeddingsEndpoint:
    def __init__(self, responses: list[object]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, object]] = []

    async def create(self, *, model: str, input: list[str]) -> object:
        self.calls.append({"model": model, "input": input})
        if not self._responses:
            raise RuntimeError("No fake response available")
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class _FakeEmbeddingClient:
    def __init__(self, responses: list[object]) -> None:
        self.embeddings = _FakeEmbeddingsEndpoint(responses)


@dataclass
class _EmbeddingDataItem:
    index: int
    embedding: list[float]


@dataclass
class _EmbeddingUsage:
    prompt_tokens: int
    total_tokens: int


@dataclass
class _EmbeddingApiResponse:
    data: list[_EmbeddingDataItem]
    usage: _EmbeddingUsage | None = None


def _make_api_response(
    vectors: list[list[float]],
    prompt_tokens: int | None = 10,
    total_tokens: int | None = 10,
) -> _EmbeddingApiResponse:
    items = [_EmbeddingDataItem(index=i, embedding=v) for i, v in enumerate(vectors)]
    usage = (
        _EmbeddingUsage(prompt_tokens=prompt_tokens, total_tokens=total_tokens)
        if prompt_tokens is not None
        else None
    )
    return _EmbeddingApiResponse(data=items, usage=usage)


# ---------------------------------------------------------------------------
# OpenAICompatibleEmbeddingProvider unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_local_embedding_normalizes_response() -> None:
    """Successful response with usage tokens is returned correctly."""
    vectors = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    client = _FakeEmbeddingClient([_make_api_response(vectors, prompt_tokens=20, total_tokens=20)])
    provider = OpenAICompatibleEmbeddingProvider(client=client, model_name="nomic-embed-text")

    resp = await provider.embed(
        EmbeddingRequest(texts=["hello", "world"], model="nomic-embed-text")
    )

    assert resp.vectors == vectors
    assert resp.model == "nomic-embed-text"
    assert resp.prompt_tokens == 20
    assert resp.total_tokens == 20
    assert resp.latency_ms >= 0


@pytest.mark.asyncio
async def test_local_embedding_handles_missing_usage_tokens() -> None:
    """When the local endpoint omits usage, prompt_tokens and total_tokens default to 0."""
    vectors = [[1.0, 2.0]]
    client = _FakeEmbeddingClient([_make_api_response(vectors, prompt_tokens=None)])
    provider = OpenAICompatibleEmbeddingProvider(client=client, model_name="all-minilm")

    resp = await provider.embed(EmbeddingRequest(texts=["test"]))

    assert resp.vectors == vectors
    assert resp.prompt_tokens == 0
    assert resp.total_tokens == 0


@pytest.mark.asyncio
async def test_local_embedding_uses_request_model_over_default() -> None:
    """model from EmbeddingRequest takes precedence over provider default."""
    vectors = [[0.9]]
    client = _FakeEmbeddingClient([_make_api_response(vectors)])
    provider = OpenAICompatibleEmbeddingProvider(client=client, model_name="default-model")

    await provider.embed(EmbeddingRequest(texts=["x"], model="override-model"))

    assert client.embeddings.calls[0]["model"] == "override-model"


@pytest.mark.asyncio
async def test_local_embedding_maps_unavailable_error() -> None:
    """APIConnectionError surfaces as ProviderUnavailableError."""
    from openai import APIConnectionError

    client = _FakeEmbeddingClient([APIConnectionError(request=None)])
    provider = OpenAICompatibleEmbeddingProvider(client=client, model_name="model")

    with pytest.raises(ProviderUnavailableError):
        await provider.embed(EmbeddingRequest(texts=["x"]))


@pytest.mark.asyncio
async def test_local_embedding_maps_internal_error() -> None:
    """Unexpected errors surface as ProviderInternalError."""
    client = _FakeEmbeddingClient([RuntimeError("kaboom")])
    provider = OpenAICompatibleEmbeddingProvider(client=client, model_name="model")

    with pytest.raises(ProviderInternalError):
        await provider.embed(EmbeddingRequest(texts=["x"]))


@pytest.mark.asyncio
async def test_local_embedding_raises_on_out_of_range_index() -> None:
    """Out-of-range embedding index raises InvalidProviderResponseError."""
    from app.domains.ai.providers.errors import InvalidProviderResponseError

    bad_data = [_EmbeddingDataItem(index=99, embedding=[0.1, 0.2])]
    bad_response = _EmbeddingApiResponse(data=bad_data)
    client = _FakeEmbeddingClient([bad_response])
    provider = OpenAICompatibleEmbeddingProvider(client=client, model_name="model")

    with pytest.raises(InvalidProviderResponseError, match="out of range"):
        await provider.embed(EmbeddingRequest(texts=["only one text"]))


# ---------------------------------------------------------------------------
# EmbeddingService: provider_type / is_local / vector_dimension metadata
# ---------------------------------------------------------------------------


class _FakeEmbeddingProvider:
    def __init__(self, responses: list[EmbeddingResponse | Exception]) -> None:
        self._responses = list(responses)

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        if not self._responses:
            raise RuntimeError("No fake response available")
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _resp(vectors: list[list[float]]) -> EmbeddingResponse:
    return EmbeddingResponse(
        vectors=vectors,
        model="nomic-embed-text",
        prompt_tokens=0,
        total_tokens=0,
        latency_ms=1,
    )


@pytest.mark.asyncio
async def test_embedding_result_records_local_provider_metadata() -> None:
    """EmbeddingResult.provider_type is 'local' and is_local is True when configured."""
    chunks = [FakeChunk(id=uuid4(), text="hello local", token_count=3)]
    provider = _FakeEmbeddingProvider([_resp([[0.1, 0.2, 0.3, 0.4]])])

    svc = EmbeddingService(
        provider_type="local",
        model_name="nomic-embed-text",
        provider=provider,
    )
    result = await svc.embed_chunks(chunks=chunks)

    assert result.provider_type == "local"
    assert result.is_local is True
    assert result.vector_dimension == 4


@pytest.mark.asyncio
async def test_embedding_result_records_openai_provider_metadata() -> None:
    """EmbeddingResult.provider_type is 'openai' and is_local is False for OpenAI."""
    chunks = [FakeChunk(id=uuid4(), text="hello openai", token_count=3)]
    provider = _FakeEmbeddingProvider([_resp([[0.1] * 1536])])

    svc = EmbeddingService(
        provider_type="openai",
        model_name="text-embedding-3-small",
        provider=provider,
    )
    result = await svc.embed_chunks(chunks=chunks)

    assert result.provider_type == "openai"
    assert result.is_local is False
    assert result.vector_dimension == 1536


@pytest.mark.asyncio
async def test_embedding_result_vector_dimension_zero_for_empty_chunks() -> None:
    """vector_dimension is 0 when there are no chunks to embed."""
    svc = EmbeddingService(provider_type="local")
    result = await svc.embed_chunks(chunks=[])

    assert result.vector_dimension == 0
    assert result.is_local is True
    assert result.vectors_by_chunk_id == {}


# ---------------------------------------------------------------------------
# Vector dimension mismatch guard (QdrantService)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_qdrant_upsert_blocks_on_dimension_mismatch() -> None:
    """upsert_chunks raises ValueError when embedding dimension != qdrant_vector_size."""
    import os

    os.environ.setdefault("QDRANT_VECTOR_SIZE", "1536")

    from app.clients import qdrant_client as qdrant_module
    from app.core.config import settings
    from app.domains.documents.services.qdrant_service import QdrantService

    @dataclass
    class _Chunk:
        id: UUID
        document_id: UUID
        page_number: int | None
        chunk_index: int
        text: str
        token_count: int
        qdrant_point_id: str | None
        embedding_model: str
        index_version: str
        chunk_hash: str | None = None
        section_path: str | None = None
        language: str | None = None
        chunk_level: int | None = None
        parent_chunk_id: UUID | None = None
        child_count: int | None = None

    class _FakeClient:
        def upsert(self, **_kwargs: object) -> None:
            pass

        def get_collections(self) -> object:
            return object()

    qdrant_module.qdrant_client = _FakeClient()  # type: ignore[assignment]

    def _fake_ensure() -> None:
        pass

    qdrant_module.ensure_qdrant_collection = _fake_ensure  # type: ignore[method-assign]

    svc = QdrantService()
    doc_id = uuid4()
    chunk_id = uuid4()
    chunk = _Chunk(
        id=chunk_id,
        document_id=doc_id,
        page_number=1,
        chunk_index=0,
        text="test",
        token_count=1,
        qdrant_point_id=None,
        embedding_model="nomic-embed-text",
        index_version="v1",
    )
    wrong_dim = 768
    assert wrong_dim != settings.qdrant_vector_size, (
        "Test requires QDRANT_VECTOR_SIZE != 768; adjust if needed"
    )

    with pytest.raises(ValueError, match="embedding dimension mismatch"):
        await svc.upsert_chunks(
            organization_id=uuid4(),
            user_id=uuid4(),
            document_id=doc_id,
            filename="test.pdf",
            file_type="pdf",
            chunks=[chunk],
            vectors_by_chunk_id={chunk_id: [0.1] * wrong_dim},
        )


# ---------------------------------------------------------------------------
# EmbeddingService retry behaviour with local provider
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_local_embedding_retries_transient_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Transient provider errors trigger exponential backoff and succeed on retry."""
    chunks = [FakeChunk(id=uuid4(), text="retry me", token_count=3)]
    provider = _FakeEmbeddingProvider(
        [
            ProviderUnavailableError("local endpoint temporarily down"),
            _resp([[0.5, 0.5, 0.5]]),
        ]
    )

    sleep_calls: list[float] = []

    async def _fake_sleep(s: float) -> None:
        sleep_calls.append(s)

    monkeypatch.setattr(
        "app.domains.documents.services.embedding_service.asyncio.sleep", _fake_sleep
    )

    svc = EmbeddingService(
        provider_type="local",
        retry_max_attempts=3,
        retry_base_seconds=0.1,
        retry_max_seconds=1.0,
        provider=provider,
    )
    result = await svc.embed_chunks(chunks=chunks)

    assert result.retry_count == 1
    assert len(sleep_calls) == 1
    assert result.is_local is True


@pytest.mark.asyncio
async def test_local_embedding_raises_transient_after_exhaustion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All retry attempts exhausted raises TransientEmbeddingError."""
    chunks = [FakeChunk(id=uuid4(), text="always fails", token_count=2)]
    provider = _FakeEmbeddingProvider(
        [
            ProviderUnavailableError("down"),
            ProviderUnavailableError("still down"),
            ProviderUnavailableError("still down"),
        ]
    )

    async def _fake_sleep(_: float) -> None:
        pass

    monkeypatch.setattr(
        "app.domains.documents.services.embedding_service.asyncio.sleep", _fake_sleep
    )

    svc = EmbeddingService(
        provider_type="local",
        retry_max_attempts=3,
        provider=provider,
    )
    with pytest.raises(TransientEmbeddingError):
        await svc.embed_chunks(chunks=chunks)


# ---------------------------------------------------------------------------
# Re-index requirement: provider/model/index_version change detection
# ---------------------------------------------------------------------------


def test_reindex_required_when_provider_changes() -> None:
    """Changing provider_type while index_version stays the same signals re-index risk.

    This test validates the convention that mismatched (provider_type, index_version)
    combinations recorded on a Document indicate stale embeddings from a prior provider.
    The rule: if document.embedding_provider_type != current_provider_type AND
    document.index_version == current_index_version, a re-index is needed.
    """
    current_provider = "local"
    current_index_version = "v1"

    # Simulate a document indexed with openai at v1
    doc_embedding_provider = "openai"
    doc_index_version = "v1"

    provider_changed = doc_embedding_provider != current_provider
    index_version_bumped = doc_index_version != current_index_version

    assert provider_changed, "provider should differ"
    assert not index_version_bumped, "index_version not yet bumped"

    # The safe path: bump DOCUMENT_INDEX_VERSION when changing provider
    bumped_index_version = "v2"
    safe_after_bump = doc_index_version != bumped_index_version
    assert safe_after_bump, "new index_version separates old and new vectors"


def test_reindex_not_required_when_same_provider_and_version() -> None:
    """No re-index needed when provider and index version both match current config."""
    current_provider = "openai"
    current_index_version = "v1"

    doc_embedding_provider = "openai"
    doc_index_version = "v1"

    requires_reindex = (
        doc_embedding_provider != current_provider or doc_index_version != current_index_version
    )
    assert not requires_reindex
