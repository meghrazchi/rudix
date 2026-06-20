"""Tests for OpenAIChatProvider and OpenAIEmbeddingProvider — F217."""

from __future__ import annotations

import os
from types import SimpleNamespace

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

from openai import (
    APITimeoutError,
    RateLimitError,
)

from app.domains.ai.providers.errors import (
    InvalidProviderResponseError,
    ProviderQuotaExceededError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    UnsupportedCapabilityError,
)
from app.domains.ai.providers.openai.adapter import OpenAIChatProvider, OpenAIEmbeddingProvider
from app.domains.ai.providers.protocols import ChatCompletionRequest, EmbeddingRequest

# ── Fake OpenAI clients ──────────────────────────────────────────────────────


class FakeChatEndpoint:
    def __init__(self, responses: list) -> None:
        self._responses = responses
        self.calls: list[dict] = []

    async def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        if not self._responses:
            raise RuntimeError("No fake response")
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeChatClient:
    def __init__(self, responses: list) -> None:
        self.completions = FakeChatEndpoint(responses)

    @property
    def chat(self) -> FakeChatClient:
        return self


class FakeEmbeddingsEndpoint:
    def __init__(self, responses: list) -> None:
        self._responses = responses
        self.calls: list[dict] = []

    async def create(self, *, model: str, input: list[str]) -> object:
        self.calls.append({"model": model, "input": input})
        if not self._responses:
            raise RuntimeError("No fake response")
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeEmbeddingClient:
    def __init__(self, responses: list) -> None:
        self.embeddings = FakeEmbeddingsEndpoint(responses)


def _chat_response(content: str, model: str = "gpt-test") -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        model=model,
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )


def _embed_response(vectors: list[list[float]]) -> SimpleNamespace:
    return SimpleNamespace(
        data=[SimpleNamespace(index=i, embedding=v) for i, v in enumerate(vectors)],
        usage=SimpleNamespace(prompt_tokens=20, total_tokens=20),
    )


# ── Chat provider tests ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_chat_provider_returns_parsed_response() -> None:
    client = FakeChatClient([_chat_response('{"answer": "hello"}', model="gpt-test")])
    provider = OpenAIChatProvider(client=client, model_name="gpt-test")  # type: ignore[arg-type]
    response = await provider.complete(ChatCompletionRequest(prompt="say hello", model="gpt-test"))
    assert response.content == '{"answer": "hello"}'
    assert response.model == "gpt-test"
    assert response.prompt_tokens == 10
    assert response.completion_tokens == 5
    assert response.total_tokens == 15
    assert response.latency_ms >= 0


@pytest.mark.asyncio
async def test_chat_provider_uses_default_model_when_request_model_is_empty() -> None:
    client = FakeChatClient([_chat_response("ok")])
    provider = OpenAIChatProvider(client=client, model_name="default-model")  # type: ignore[arg-type]
    await provider.complete(ChatCompletionRequest(prompt="hi"))
    assert client.completions.calls[0]["model"] == "default-model"


@pytest.mark.asyncio
async def test_chat_provider_sends_json_mode_when_enabled() -> None:
    client = FakeChatClient([_chat_response("ok")])
    provider = OpenAIChatProvider(client=client, model_name="m")  # type: ignore[arg-type]
    await provider.complete(ChatCompletionRequest(prompt="hi", json_mode=True))
    assert client.completions.calls[0]["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_chat_provider_omits_response_format_when_json_mode_false() -> None:
    client = FakeChatClient([_chat_response("ok")])
    provider = OpenAIChatProvider(client=client, model_name="m")  # type: ignore[arg-type]
    await provider.complete(ChatCompletionRequest(prompt="hi", json_mode=False))
    assert "response_format" not in client.completions.calls[0]


@pytest.mark.asyncio
async def test_chat_provider_maps_rate_limit_error() -> None:
    exc = RateLimitError.__new__(RateLimitError)
    exc.args = ("rate limit",)
    exc.status_code = 429
    client = FakeChatClient([exc])
    provider = OpenAIChatProvider(client=client, model_name="m")  # type: ignore[arg-type]
    with pytest.raises(ProviderQuotaExceededError):
        await provider.complete(ChatCompletionRequest(prompt="hi"))


@pytest.mark.asyncio
async def test_chat_provider_maps_timeout_error() -> None:
    exc = APITimeoutError.__new__(APITimeoutError)
    exc.args = ("timeout",)
    client = FakeChatClient([exc])
    provider = OpenAIChatProvider(client=client, model_name="m")  # type: ignore[arg-type]
    with pytest.raises(ProviderTimeoutError):
        await provider.complete(ChatCompletionRequest(prompt="hi"))


@pytest.mark.asyncio
async def test_chat_provider_maps_oserror_to_unavailable() -> None:
    client = FakeChatClient([OSError("connection refused")])
    provider = OpenAIChatProvider(client=client, model_name="m")  # type: ignore[arg-type]
    with pytest.raises(ProviderUnavailableError):
        await provider.complete(ChatCompletionRequest(prompt="hi"))


@pytest.mark.asyncio
async def test_chat_provider_maps_response_format_bad_request_to_unsupported_capability() -> None:
    from openai import BadRequestError

    exc = BadRequestError.__new__(BadRequestError)
    exc.args = ("response_format is not supported by this model",)
    exc.status_code = 400
    client = FakeChatClient([exc])
    provider = OpenAIChatProvider(client=client, model_name="m")  # type: ignore[arg-type]
    with pytest.raises(UnsupportedCapabilityError, match="response_format"):
        await provider.complete(ChatCompletionRequest(prompt="hi"))


@pytest.mark.asyncio
async def test_chat_provider_raises_invalid_response_when_no_choices() -> None:
    no_choices = SimpleNamespace(choices=[], model="m", usage=None)
    client = FakeChatClient([no_choices])
    provider = OpenAIChatProvider(client=client, model_name="m")  # type: ignore[arg-type]
    with pytest.raises(InvalidProviderResponseError, match="no choices"):
        await provider.complete(ChatCompletionRequest(prompt="hi"))


# ── Embedding provider tests ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_embedding_provider_returns_vectors_in_order() -> None:
    vectors = [[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]]
    client = FakeEmbeddingClient([_embed_response(vectors)])
    provider = OpenAIEmbeddingProvider(client=client, model_name="text-embedding-test")  # type: ignore[arg-type]
    response = await provider.embed(
        EmbeddingRequest(texts=["a", "b", "c"], model="text-embedding-test")
    )
    assert response.vectors == vectors
    assert response.prompt_tokens == 20
    assert response.total_tokens == 20
    assert response.latency_ms >= 0


@pytest.mark.asyncio
async def test_embedding_provider_uses_default_model() -> None:
    client = FakeEmbeddingClient([_embed_response([[0.1]])])
    provider = OpenAIEmbeddingProvider(client=client, model_name="default-embed")  # type: ignore[arg-type]
    await provider.embed(EmbeddingRequest(texts=["x"]))
    assert client.embeddings.calls[0]["model"] == "default-embed"


@pytest.mark.asyncio
async def test_embedding_provider_maps_rate_limit_error() -> None:
    exc = RateLimitError.__new__(RateLimitError)
    exc.args = ("rate limit",)
    exc.status_code = 429
    client = FakeEmbeddingClient([exc])
    provider = OpenAIEmbeddingProvider(client=client, model_name="m")  # type: ignore[arg-type]
    with pytest.raises(ProviderQuotaExceededError):
        await provider.embed(EmbeddingRequest(texts=["x"]))


@pytest.mark.asyncio
async def test_embedding_provider_maps_oserror_to_unavailable() -> None:
    client = FakeEmbeddingClient([OSError("network error")])
    provider = OpenAIEmbeddingProvider(client=client, model_name="m")  # type: ignore[arg-type]
    with pytest.raises(ProviderUnavailableError):
        await provider.embed(EmbeddingRequest(texts=["x"]))


@pytest.mark.asyncio
async def test_embedding_provider_raises_on_index_out_of_range() -> None:
    bad_response = SimpleNamespace(
        data=[SimpleNamespace(index=5, embedding=[0.1])],
        usage=SimpleNamespace(prompt_tokens=5, total_tokens=5),
    )
    client = FakeEmbeddingClient([bad_response])
    provider = OpenAIEmbeddingProvider(client=client, model_name="m")  # type: ignore[arg-type]
    with pytest.raises(InvalidProviderResponseError, match="out of range"):
        await provider.embed(EmbeddingRequest(texts=["x"]))


@pytest.mark.asyncio
async def test_embedding_provider_redacts_credentials_from_errors() -> None:
    exc = OSError("sk-supersecret key is bad")
    client = FakeEmbeddingClient([exc])
    provider = OpenAIEmbeddingProvider(client=client, model_name="m")  # type: ignore[arg-type]
    with pytest.raises(ProviderUnavailableError) as exc_info:
        await provider.embed(EmbeddingRequest(texts=["x"]))
    assert "sk-supersecret" not in str(exc_info.value)
    assert "[REDACTED]" in str(exc_info.value)
