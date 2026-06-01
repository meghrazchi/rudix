from __future__ import annotations

import os
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

from pydantic import ValidationError

from app.domains.documents.chunking.config import ChunkingProfileConfig
from app.domains.documents.chunking.registry import (
    StrategyRegistry,
    UnknownStrategyError,
    get_registry,
)
from app.domains.documents.chunking.strategies.token_recursive import (
    STRATEGY_NAME,
    STRATEGY_VERSION,
    TokenRecursiveStrategy,
)
from app.domains.documents.services.chunking_service import ChunkingService
from app.domains.documents.services.text_extraction import ExtractedSection

# ---------------------------------------------------------------------------
# ChunkingProfileConfig validation
# ---------------------------------------------------------------------------


def test_profile_defaults_are_valid() -> None:
    profile = ChunkingProfileConfig()
    assert profile.strategy == "token_recursive"
    assert profile.chunk_size_tokens > profile.chunk_overlap_tokens


def test_profile_rejects_overlap_gte_size() -> None:
    with pytest.raises(ValidationError, match="chunk_overlap_tokens must be smaller"):
        ChunkingProfileConfig(chunk_size_tokens=200, chunk_overlap_tokens=200)


def test_profile_rejects_size_below_minimum() -> None:
    with pytest.raises(ValidationError):
        ChunkingProfileConfig(chunk_size_tokens=50)  # ge=100


def test_profile_rejects_blank_strategy_name() -> None:
    with pytest.raises(ValidationError):
        ChunkingProfileConfig(strategy="")


def test_profile_accepts_strategy_options() -> None:
    profile = ChunkingProfileConfig(strategy_options={"heading_level": 2})
    assert profile.strategy_options == {"heading_level": 2}


# ---------------------------------------------------------------------------
# StrategyRegistry
# ---------------------------------------------------------------------------


def test_registry_resolves_token_recursive() -> None:
    registry = get_registry()
    assert "token_recursive" in registry.known_strategies()


def test_registry_resolve_returns_strategy_instance() -> None:
    registry = get_registry()
    profile = ChunkingProfileConfig()
    strategy = registry.resolve(
        profile, embedding_model="text-embedding-3-small", index_version="v1"
    )
    assert isinstance(strategy, TokenRecursiveStrategy)
    assert strategy.name == STRATEGY_NAME
    assert strategy.version == STRATEGY_VERSION


def test_registry_resolve_unknown_strategy_raises() -> None:
    registry = get_registry()
    profile = ChunkingProfileConfig(strategy="nonexistent_strategy")
    with pytest.raises(UnknownStrategyError, match="nonexistent_strategy"):
        registry.resolve(
            profile, embedding_model="text-embedding-3-small", index_version="v1"
        )


def test_registry_register_custom_factory() -> None:
    registry = StrategyRegistry()
    calls: list[str] = []

    class _FakeStrategy:
        name = "fake"
        version = "0.1"
        supported_file_types = None
        supported_languages = None

        async def chunk(self, *, document_id, pages):
            return []

    def _factory(profile, embedding_model, index_version):
        calls.append(profile.strategy)
        return _FakeStrategy()

    registry.register("fake", _factory)
    profile = ChunkingProfileConfig(strategy="fake")
    strategy = registry.resolve(
        profile, embedding_model="model", index_version="v1"
    )
    assert isinstance(strategy, _FakeStrategy)
    assert calls == ["fake"]


def test_unknown_strategy_error_message_lists_known() -> None:
    err = UnknownStrategyError("bogus", ["token_recursive", "semantic"])
    assert "bogus" in str(err)
    assert "token_recursive" in str(err)
    assert "semantic" in str(err)


def test_unknown_strategy_error_message_empty_registry() -> None:
    err = UnknownStrategyError("bogus", [])
    assert "(none registered)" in str(err)


# ---------------------------------------------------------------------------
# TokenRecursiveStrategy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_strategy_metadata_in_chunk_payload() -> None:
    strategy = TokenRecursiveStrategy(
        chunk_size_tokens=40,
        chunk_overlap_tokens=8,
        embedding_model="text-embedding-3-small",
        index_version="v-test",
    )
    text = " ".join(f"word{i}" for i in range(120))
    pages = [ExtractedSection(page_number=1, text=text, char_count=len(text))]
    chunks = await strategy.chunk(document_id=uuid4(), pages=pages)

    assert len(chunks) > 0
    for chunk in chunks:
        assert chunk.strategy_name == STRATEGY_NAME
        assert chunk.strategy_version == STRATEGY_VERSION


@pytest.mark.asyncio
async def test_strategy_from_profile_factory() -> None:
    profile = ChunkingProfileConfig(chunk_size_tokens=500, chunk_overlap_tokens=100)
    strategy = TokenRecursiveStrategy.from_profile(
        profile,
        embedding_model="text-embedding-3-small",
        index_version="v1",
    )
    assert strategy.chunk_size_tokens == 500
    assert strategy.chunk_overlap_tokens == 100
    assert strategy.embedding_model == "text-embedding-3-small"
    assert strategy.index_version == "v1"


def test_strategy_rejects_overlap_gte_size() -> None:
    with pytest.raises(ValueError, match="chunk_overlap_tokens must be smaller"):
        TokenRecursiveStrategy(
            chunk_size_tokens=100,
            chunk_overlap_tokens=100,
            embedding_model="text-embedding-3-small",
            index_version="v1",
        )


# ---------------------------------------------------------------------------
# ChunkingService delegation (backward-compatible)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chunking_service_delegates_to_registry() -> None:
    service = ChunkingService(
        chunk_size_tokens=200,
        chunk_overlap_tokens=40,
        embedding_model="text-embedding-3-small",
        index_version="v-test",
    )
    text = " ".join(f"word{i}" for i in range(1200))
    pages = [ExtractedSection(page_number=1, text=text, char_count=len(text))]
    chunks = await service.chunk(document_id=uuid4(), pages=pages)

    assert len(chunks) > 0
    assert all(chunk.strategy_name == STRATEGY_NAME for chunk in chunks)
    assert all(chunk.strategy_version == STRATEGY_VERSION for chunk in chunks)
    assert all(chunk.embedding_model == "text-embedding-3-small" for chunk in chunks)
    assert all(chunk.index_version == "v-test" for chunk in chunks)


@pytest.mark.asyncio
async def test_chunking_service_empty_pages_returns_empty() -> None:
    service = ChunkingService(
        chunk_size_tokens=100, chunk_overlap_tokens=20, index_version="v1"
    )
    chunks = await service.chunk(document_id=uuid4(), pages=[])
    assert chunks == []


def test_chunking_service_invalid_overlap_fails_fast() -> None:
    with pytest.raises((ValueError, Exception)):
        ChunkingService(chunk_size_tokens=100, chunk_overlap_tokens=100)
