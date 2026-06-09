"""Tests for OpenAICompatibleChatProvider and local LLM factory support — F218."""
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

from openai import APIConnectionError, APITimeoutError, RateLimitError

from app.domains.ai.providers.errors import (
    InvalidProviderResponseError,
    ProviderInternalError,
    ProviderPolicyBlockedError,
    ProviderQuotaExceededError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    UnsupportedCapabilityError,
)
from app.domains.ai.providers.local.adapter import OpenAICompatibleChatProvider
from app.domains.ai.providers.protocols import ChatCompletionRequest


# ── Fake client infrastructure ───────────────────────────────────────────────


class FakeChatEndpoint:
    def __init__(self, responses: list) -> None:
        self._responses = responses
        self.calls: list[dict] = []

    async def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        if not self._responses:
            raise RuntimeError("No fake response queued")
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeChatClient:
    def __init__(self, responses: list) -> None:
        self.completions = FakeChatEndpoint(responses)

    @property
    def chat(self) -> "FakeChatClient":
        return self


def _response(
    content: str,
    model: str = "local-model",
    prompt_tokens: int = 10,
    completion_tokens: int = 5,
    total_tokens: int = 15,
    include_usage: bool = True,
) -> SimpleNamespace:
    usage = (
        SimpleNamespace(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )
        if include_usage
        else None
    )
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        model=model,
        usage=usage,
    )


# ── Provider-likeness tests ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ollama_like_success_response_with_usage() -> None:
    """Ollama returns standard usage fields and echoes the model name."""
    client = FakeChatClient([_response('{"answer": "hello"}', model="llama3:8b")])
    provider = OpenAICompatibleChatProvider(client=client, model_name="llama3:8b")  # type: ignore[arg-type]
    result = await provider.complete(ChatCompletionRequest(prompt="hi"))
    assert result.content == '{"answer": "hello"}'
    assert result.model == "llama3:8b"
    assert result.prompt_tokens == 10
    assert result.completion_tokens == 5
    assert result.total_tokens == 15
    assert result.latency_ms >= 0


@pytest.mark.asyncio
async def test_vllm_like_success_response_with_usage() -> None:
    """vLLM returns standard OpenAI-compatible usage with full token counts."""
    client = FakeChatClient(
        [_response('{"answer": "vllm answer"}', model="mistralai/Mistral-7B-v0.1", total_tokens=22)]
    )
    provider = OpenAICompatibleChatProvider(
        client=client, model_name="mistralai/Mistral-7B-v0.1"  # type: ignore[arg-type]
    )
    result = await provider.complete(ChatCompletionRequest(prompt="test"))
    assert result.content == '{"answer": "vllm answer"}'
    assert result.model == "mistralai/Mistral-7B-v0.1"
    assert result.total_tokens == 22


@pytest.mark.asyncio
async def test_localai_like_success_response_without_usage() -> None:
    """LocalAI may omit the usage field; tokens should default to zero."""
    client = FakeChatClient(
        [_response('{"answer": "localai answer"}', model="gpt-4", include_usage=False)]
    )
    provider = OpenAICompatibleChatProvider(client=client, model_name="gpt-4")  # type: ignore[arg-type]
    result = await provider.complete(ChatCompletionRequest(prompt="test"))
    assert result.content == '{"answer": "localai answer"}'
    assert result.prompt_tokens == 0
    assert result.completion_tokens == 0
    assert result.total_tokens == 0


@pytest.mark.asyncio
async def test_litellm_like_success_response_proxied_model_name() -> None:
    """LiteLLM proxy may return a different resolved model name in the response."""
    client = FakeChatClient(
        [_response('{"answer": "ok"}', model="openai/gpt-4o-mini")]
    )
    provider = OpenAICompatibleChatProvider(
        client=client, model_name="gpt-4o-mini"  # type: ignore[arg-type]
    )
    result = await provider.complete(ChatCompletionRequest(prompt="test"))
    assert result.model == "openai/gpt-4o-mini"


# ── JSON mode tests ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_json_mode_enabled_sends_response_format() -> None:
    client = FakeChatClient([_response("ok")])
    provider = OpenAICompatibleChatProvider(
        client=client, model_name="m", json_mode_enabled=True  # type: ignore[arg-type]
    )
    await provider.complete(ChatCompletionRequest(prompt="hi", json_mode=True))
    assert client.completions.calls[0]["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_json_mode_disabled_at_class_level_omits_response_format() -> None:
    """When the provider is configured with json_mode_enabled=False, response_format is never sent."""
    client = FakeChatClient([_response("ok")])
    provider = OpenAICompatibleChatProvider(
        client=client, model_name="m", json_mode_enabled=False  # type: ignore[arg-type]
    )
    await provider.complete(ChatCompletionRequest(prompt="hi", json_mode=True))
    assert "response_format" not in client.completions.calls[0]


@pytest.mark.asyncio
async def test_json_mode_false_on_request_omits_response_format() -> None:
    client = FakeChatClient([_response("ok")])
    provider = OpenAICompatibleChatProvider(
        client=client, model_name="m", json_mode_enabled=True  # type: ignore[arg-type]
    )
    await provider.complete(ChatCompletionRequest(prompt="hi", json_mode=False))
    assert "response_format" not in client.completions.calls[0]


@pytest.mark.asyncio
async def test_provider_without_json_mode_support_raises_unsupported_capability() -> None:
    """Providers that reject response_format with a 400 trigger UnsupportedCapabilityError."""
    from openai import BadRequestError

    exc = BadRequestError.__new__(BadRequestError)
    exc.args = ("response_format is not supported by this model",)
    exc.status_code = 400
    client = FakeChatClient([exc])
    provider = OpenAICompatibleChatProvider(client=client, model_name="m")  # type: ignore[arg-type]
    with pytest.raises(UnsupportedCapabilityError, match="response_format"):
        await provider.complete(ChatCompletionRequest(prompt="hi"))


# ── Error mapping tests ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_timeout_raises_provider_timeout_error() -> None:
    exc = APITimeoutError.__new__(APITimeoutError)
    exc.args = ("timed out",)
    client = FakeChatClient([exc])
    provider = OpenAICompatibleChatProvider(client=client, model_name="m")  # type: ignore[arg-type]
    with pytest.raises(ProviderTimeoutError):
        await provider.complete(ChatCompletionRequest(prompt="hi"))


@pytest.mark.asyncio
async def test_connection_refused_raises_provider_unavailable_error() -> None:
    exc = APIConnectionError.__new__(APIConnectionError)
    exc.args = ("Connection refused",)
    exc.__cause__ = None
    client = FakeChatClient([exc])
    provider = OpenAICompatibleChatProvider(client=client, model_name="m")  # type: ignore[arg-type]
    with pytest.raises(ProviderUnavailableError):
        await provider.complete(ChatCompletionRequest(prompt="hi"))


@pytest.mark.asyncio
async def test_oserror_raises_provider_unavailable_error() -> None:
    client = FakeChatClient([OSError("connection refused")])
    provider = OpenAICompatibleChatProvider(client=client, model_name="m")  # type: ignore[arg-type]
    with pytest.raises(ProviderUnavailableError):
        await provider.complete(ChatCompletionRequest(prompt="hi"))


@pytest.mark.asyncio
async def test_rate_limit_raises_provider_quota_exceeded_error() -> None:
    exc = RateLimitError.__new__(RateLimitError)
    exc.args = ("rate limit exceeded",)
    exc.status_code = 429
    client = FakeChatClient([exc])
    provider = OpenAICompatibleChatProvider(client=client, model_name="m")  # type: ignore[arg-type]
    with pytest.raises(ProviderQuotaExceededError):
        await provider.complete(ChatCompletionRequest(prompt="hi"))


@pytest.mark.asyncio
async def test_empty_choices_raises_invalid_provider_response_error() -> None:
    no_choices = SimpleNamespace(choices=[], model="m", usage=None)
    client = FakeChatClient([no_choices])
    provider = OpenAICompatibleChatProvider(client=client, model_name="m")  # type: ignore[arg-type]
    with pytest.raises(InvalidProviderResponseError, match="no choices"):
        await provider.complete(ChatCompletionRequest(prompt="hi"))


@pytest.mark.asyncio
async def test_unexpected_exception_raises_provider_internal_error() -> None:
    client = FakeChatClient([ValueError("some unexpected error")])
    provider = OpenAICompatibleChatProvider(client=client, model_name="m")  # type: ignore[arg-type]
    with pytest.raises(ProviderInternalError):
        await provider.complete(ChatCompletionRequest(prompt="hi"))


# ── Security: credential redaction ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_credentials_redacted_from_oserror_messages() -> None:
    client = FakeChatClient([OSError("sk-supersecret token is invalid")])
    provider = OpenAICompatibleChatProvider(client=client, model_name="m")  # type: ignore[arg-type]
    with pytest.raises(ProviderUnavailableError) as exc_info:
        await provider.complete(ChatCompletionRequest(prompt="hi"))
    assert "sk-supersecret" not in str(exc_info.value)
    assert "[REDACTED]" in str(exc_info.value)


@pytest.mark.asyncio
async def test_api_key_redacted_from_auth_error_messages() -> None:
    from openai import AuthenticationError

    exc = AuthenticationError.__new__(AuthenticationError)
    exc.args = ("Bearer sk-local-secret is invalid",)
    exc.status_code = 401
    client = FakeChatClient([exc])
    provider = OpenAICompatibleChatProvider(client=client, model_name="m")  # type: ignore[arg-type]
    with pytest.raises(ProviderPolicyBlockedError) as exc_info:
        await provider.complete(ChatCompletionRequest(prompt="hi"))
    assert "sk-local-secret" not in str(exc_info.value)
    assert "[REDACTED]" in str(exc_info.value)


# ── Model name resolution ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_uses_default_model_when_request_model_is_empty() -> None:
    client = FakeChatClient([_response("ok")])
    provider = OpenAICompatibleChatProvider(client=client, model_name="default-local")  # type: ignore[arg-type]
    await provider.complete(ChatCompletionRequest(prompt="hi"))
    assert client.completions.calls[0]["model"] == "default-local"


@pytest.mark.asyncio
async def test_request_model_overrides_default_model() -> None:
    client = FakeChatClient([_response("ok")])
    provider = OpenAICompatibleChatProvider(client=client, model_name="default-local")  # type: ignore[arg-type]
    await provider.complete(ChatCompletionRequest(prompt="hi", model="override-model"))
    assert client.completions.calls[0]["model"] == "override-model"


# ── Factory integration ───────────────────────────────────────────────────────


def test_factory_raises_when_local_llm_base_url_not_configured() -> None:
    """Factory must raise ProviderUnavailableError when LOCAL_LLM_BASE_URL is unset."""
    from unittest.mock import patch

    from app.domains.ai.providers.factory import ProviderFactory

    factory = ProviderFactory()
    with patch("app.core.config.settings") as mock_settings:
        mock_settings.local_llm_base_url = None
        with pytest.raises(ProviderUnavailableError, match="LOCAL_LLM_BASE_URL"):
            factory._build_local_chat_provider()


def test_factory_builds_local_provider_when_base_url_configured() -> None:
    """Factory returns an OpenAICompatibleChatProvider when LOCAL_LLM_BASE_URL is set."""
    from unittest.mock import MagicMock, patch

    from app.domains.ai.providers.factory import ProviderFactory

    factory = ProviderFactory()
    mock_settings = MagicMock()
    mock_settings.local_llm_base_url = "http://localhost:11434"
    mock_settings.local_llm_api_key = None
    mock_settings.local_llm_model = "llama3"
    mock_settings.local_llm_timeout_seconds = 30.0
    mock_settings.local_llm_json_mode_enabled = True

    # settings is imported locally inside _build_local_chat_provider, so patch at the module level
    with patch("app.core.config.settings", mock_settings):
        with patch("openai.AsyncOpenAI") as mock_openai:
            mock_openai.return_value = MagicMock()
            provider = factory._build_local_chat_provider()

    assert isinstance(provider, OpenAICompatibleChatProvider)
