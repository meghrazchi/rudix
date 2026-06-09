"""Tests for ProviderFactory — F217."""
from __future__ import annotations

import os

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

from app.domains.ai.providers.factory import ProviderFactory, UnknownProviderError
from app.domains.ai.providers.openai.adapter import OpenAIChatProvider, OpenAIEmbeddingProvider


def test_factory_returns_openai_chat_provider() -> None:
    factory = ProviderFactory()
    provider = factory.get_chat_provider("openai")
    assert isinstance(provider, OpenAIChatProvider)


def test_factory_returns_openai_embedding_provider() -> None:
    factory = ProviderFactory()
    provider = factory.get_embedding_provider("openai")
    assert isinstance(provider, OpenAIEmbeddingProvider)


def test_factory_caches_chat_provider() -> None:
    factory = ProviderFactory()
    p1 = factory.get_chat_provider("openai")
    p2 = factory.get_chat_provider("openai")
    assert p1 is p2


def test_factory_caches_embedding_provider() -> None:
    factory = ProviderFactory()
    p1 = factory.get_embedding_provider("openai")
    p2 = factory.get_embedding_provider("openai")
    assert p1 is p2


def test_factory_raises_for_unknown_chat_provider() -> None:
    factory = ProviderFactory()
    with pytest.raises(UnknownProviderError, match="no-such-provider"):
        factory.get_chat_provider("no-such-provider")


def test_factory_raises_for_unknown_embedding_provider() -> None:
    factory = ProviderFactory()
    with pytest.raises(UnknownProviderError, match="no-such-provider"):
        factory.get_embedding_provider("no-such-provider")


def test_factory_uses_default_provider_from_settings() -> None:
    factory = ProviderFactory()
    provider = factory.get_chat_provider()
    assert isinstance(provider, OpenAIChatProvider)


def test_factory_embedding_uses_default_from_settings() -> None:
    factory = ProviderFactory()
    provider = factory.get_embedding_provider()
    assert isinstance(provider, OpenAIEmbeddingProvider)
