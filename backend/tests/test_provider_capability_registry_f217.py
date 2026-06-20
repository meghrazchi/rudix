"""Tests for ModelCapabilityRegistry — F217."""

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

from app.domains.ai.providers.capability_registry import (
    ModelCapabilityRegistry,
    UnknownModelError,
)
from app.domains.ai.providers.errors import UnsupportedCapabilityError
from app.domains.ai.providers.schemas import CostBehavior, ModelCapability


def _chat_model(
    provider: str = "openai",
    model_name: str = "gpt-test",
    supports_json_mode: bool = True,
    supports_tool_calling: bool = True,
) -> ModelCapability:
    return ModelCapability(
        provider=provider,
        model_name=model_name,
        context_window=128000,
        max_input_tokens=128000,
        is_chat_model=True,
        is_embedding_model=False,
        supports_json_mode=supports_json_mode,
        supports_streaming=True,
        supports_tool_calling=supports_tool_calling,
    )


def _embedding_model(
    provider: str = "openai",
    model_name: str = "text-embedding-test",
    embedding_dimension: int = 1536,
) -> ModelCapability:
    return ModelCapability(
        provider=provider,
        model_name=model_name,
        context_window=8191,
        max_input_tokens=8191,
        is_chat_model=False,
        is_embedding_model=True,
        embedding_dimension=embedding_dimension,
        supports_json_mode=False,
        supports_streaming=False,
        supports_tool_calling=False,
        cost_behavior=CostBehavior.per_token,
    )


def test_register_and_get_capability() -> None:
    registry = ModelCapabilityRegistry()
    cap = _chat_model()
    registry.register(cap)
    assert registry.get("openai", "gpt-test") is cap


def test_get_unknown_returns_none() -> None:
    registry = ModelCapabilityRegistry()
    assert registry.get("openai", "no-such-model") is None


def test_require_unknown_raises_unknown_model_error() -> None:
    registry = ModelCapabilityRegistry()
    with pytest.raises(UnknownModelError, match="no-such-model"):
        registry.require("openai", "no-such-model")


def test_assert_supports_json_mode_passes_when_supported() -> None:
    registry = ModelCapabilityRegistry()
    registry.register(_chat_model(supports_json_mode=True))
    registry.assert_supports_json_mode("openai", "gpt-test")  # must not raise


def test_assert_supports_json_mode_raises_when_unsupported() -> None:
    registry = ModelCapabilityRegistry()
    registry.register(_chat_model(supports_json_mode=False))
    with pytest.raises(UnsupportedCapabilityError, match="JSON output mode"):
        registry.assert_supports_json_mode("openai", "gpt-test")


def test_assert_supports_json_mode_skips_unknown_model() -> None:
    registry = ModelCapabilityRegistry()
    registry.assert_supports_json_mode("openai", "unknown-model")  # must not raise


def test_assert_supports_tool_calling_raises_when_unsupported() -> None:
    registry = ModelCapabilityRegistry()
    registry.register(_chat_model(supports_tool_calling=False))
    with pytest.raises(UnsupportedCapabilityError, match="tool calling"):
        registry.assert_supports_tool_calling("openai", "gpt-test")


def test_assert_is_embedding_model_raises_for_chat_model() -> None:
    registry = ModelCapabilityRegistry()
    registry.register(_chat_model())
    with pytest.raises(UnsupportedCapabilityError, match="embedding model"):
        registry.assert_is_embedding_model("openai", "gpt-test")


def test_assert_is_chat_model_raises_for_embedding_model() -> None:
    registry = ModelCapabilityRegistry()
    registry.register(_embedding_model())
    with pytest.raises(UnsupportedCapabilityError, match="chat model"):
        registry.assert_is_chat_model("openai", "text-embedding-test")


def test_assert_embedding_dimension_passes_when_match() -> None:
    registry = ModelCapabilityRegistry()
    registry.register(_embedding_model(embedding_dimension=1536))
    registry.assert_embedding_dimension("openai", "text-embedding-test", 1536)  # must not raise


def test_assert_embedding_dimension_raises_on_mismatch() -> None:
    registry = ModelCapabilityRegistry()
    registry.register(_embedding_model(embedding_dimension=1536))
    with pytest.raises(UnsupportedCapabilityError, match=r"1536.*3072"):
        registry.assert_embedding_dimension("openai", "text-embedding-test", 3072)


def test_assert_embedding_dimension_skips_unknown_model() -> None:
    registry = ModelCapabilityRegistry()
    registry.assert_embedding_dimension("openai", "unknown", 9999)  # must not raise


def test_default_registry_has_openai_models() -> None:
    from app.domains.ai.providers import default_capability_registry

    assert default_capability_registry.get("openai", "gpt-5.4-mini") is not None
    assert default_capability_registry.get("openai", "text-embedding-3-small") is not None
    assert default_capability_registry.get("openai", "text-embedding-3-large") is not None
