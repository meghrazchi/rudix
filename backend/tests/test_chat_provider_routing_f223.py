"""F223 — Provider routing, fallback, and context-window protection tests."""

from __future__ import annotations

import os
from decimal import Decimal

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

from app.domains.ai.profile.schemas import ProfileSource, ResolvedTaskProfile, TaskType
from app.domains.ai.providers.errors import ProviderUnavailableError
from app.domains.ai.providers.protocols import ChatCompletionRequest, ChatCompletionResponse
from app.domains.chat.services.llm_service import (
    LLMService,
    PermanentLLMServiceError,
    TransientLLMServiceError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeChatProvider:
    """Deterministic fake provider for unit tests."""

    def __init__(
        self,
        responses: list[ChatCompletionResponse | Exception],
        *,
        model_name: str = "local-model",
    ) -> None:
        self._responses = responses
        self._model_name = model_name
        self.calls: list[ChatCompletionRequest] = []

    async def complete(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        self.calls.append(request)
        if not self._responses:
            raise RuntimeError("No fake response available")
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _ok_response(
    answer: str = "Answer text.",
    model: str = "local-model",
) -> ChatCompletionResponse:
    payload = (
        f'{{"answer":"{answer}","not_found":false,"citations":[]}}'
    )
    return ChatCompletionResponse(
        content=payload,
        model=model,
        prompt_tokens=20,
        completion_tokens=10,
        total_tokens=30,
        latency_ms=5,
    )


def _make_profile(
    *,
    provider_type: str = "local",
    base_model: str = "local-model",
    context_window: int | None = None,
    fallback_provider_key: str | None = None,
) -> ResolvedTaskProfile:
    return ResolvedTaskProfile(
        task_type=TaskType.chat,
        provider_type=provider_type,
        base_model=base_model,
        context_window=context_window,
        json_mode=False,
        streaming=False,
        fallback_provider_key=fallback_provider_key,
        source=ProfileSource.org_profile,
        version=1,
    )


# ---------------------------------------------------------------------------
# 1. Profile-based provider routing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_profile_routes_to_local_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    local_provider = FakeChatProvider([_ok_response("Local answer.", model="local-model")])

    service = LLMService(retry_max_attempts=1)
    monkeypatch.setattr(service, "_provider", None)

    from app.domains.ai.providers.factory import ProviderFactory
    factory = ProviderFactory()
    factory._chat_providers["local"] = local_provider
    monkeypatch.setattr(
        "app.domains.ai.providers.factory.default_provider_factory", factory
    )

    profile = _make_profile(provider_type="local", base_model="local-model")
    result = await service.generate_answer(prompt="What is the policy?", resolved_profile=profile)

    assert result.answer == "Local answer."
    assert result.provider_key == "local"
    assert result.fallback_used is False
    assert len(local_provider.calls) == 1
    assert local_provider.calls[0].model == "local-model"


@pytest.mark.asyncio
async def test_profile_passes_base_model_to_request(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = FakeChatProvider([_ok_response(model="custom-llama-3")])
    service = LLMService(retry_max_attempts=1)
    monkeypatch.setattr(service, "_provider", None)

    from app.domains.ai.providers.factory import ProviderFactory
    factory = ProviderFactory()
    factory._chat_providers["local"] = provider
    monkeypatch.setattr(
        "app.domains.ai.providers.factory.default_provider_factory", factory
    )

    profile = _make_profile(provider_type="local", base_model="custom-llama-3")
    await service.generate_answer(prompt="Question?", resolved_profile=profile)

    assert provider.calls[0].model == "custom-llama-3"


# ---------------------------------------------------------------------------
# 2. Fallback disabled: local outage returns TransientLLMServiceError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fallback_disabled_local_outage_raises_transient_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import settings

    local_provider = FakeChatProvider([ProviderUnavailableError("local model is down")])
    monkeypatch.setattr(settings, "feature_enable_provider_fallback", False)

    async def _no_sleep(seconds: float) -> None:
        pass

    monkeypatch.setattr("app.domains.chat.services.llm_service.asyncio.sleep", _no_sleep)

    service = LLMService(retry_max_attempts=1)
    monkeypatch.setattr(service, "_provider", None)

    from app.domains.ai.providers.factory import ProviderFactory
    factory = ProviderFactory()
    factory._chat_providers["local"] = local_provider
    monkeypatch.setattr(
        "app.domains.ai.providers.factory.default_provider_factory", factory
    )

    # Profile has fallback configured but feature flag is off.
    profile = _make_profile(
        provider_type="local",
        fallback_provider_key="openai",
    )

    with pytest.raises(TransientLLMServiceError):
        await service.generate_answer(prompt="Question?", resolved_profile=profile)

    # Fallback provider was never called.
    assert "openai" not in factory._chat_providers


# ---------------------------------------------------------------------------
# 3. Fallback enabled: local outage routes to fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fallback_enabled_local_outage_routes_to_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import settings

    local_provider = FakeChatProvider([ProviderUnavailableError("local down")])
    cloud_provider = FakeChatProvider(
        [_ok_response("Cloud fallback answer.", model="gpt-4o")],
        model_name="gpt-4o",
    )
    monkeypatch.setattr(settings, "feature_enable_provider_fallback", True)

    async def _no_sleep(seconds: float) -> None:
        pass

    monkeypatch.setattr("app.domains.chat.services.llm_service.asyncio.sleep", _no_sleep)

    service = LLMService(retry_max_attempts=1)
    monkeypatch.setattr(service, "_provider", None)

    from app.domains.ai.providers.factory import ProviderFactory
    factory = ProviderFactory()
    factory._chat_providers["local"] = local_provider
    factory._chat_providers["openai"] = cloud_provider
    monkeypatch.setattr(
        "app.domains.ai.providers.factory.default_provider_factory", factory
    )

    profile = _make_profile(
        provider_type="local",
        fallback_provider_key="openai",
    )

    result = await service.generate_answer(prompt="Question?", resolved_profile=profile)

    assert result.answer == "Cloud fallback answer."
    assert result.fallback_used is True
    assert result.fallback_from == "local"
    assert result.fallback_to == "openai"
    assert result.fallback_reason is not None
    assert result.provider_key == "openai"


@pytest.mark.asyncio
async def test_fallback_records_sanitised_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "feature_enable_provider_fallback", True)

    async def _no_sleep(_: float) -> None:
        pass

    monkeypatch.setattr("app.domains.chat.services.llm_service.asyncio.sleep", _no_sleep)

    local_provider = FakeChatProvider([ProviderUnavailableError("timeout")])
    cloud_provider = FakeChatProvider([_ok_response("Fallback ok.", model="gpt-4o")])

    service = LLMService(retry_max_attempts=1)
    monkeypatch.setattr(service, "_provider", None)

    from app.domains.ai.providers.factory import ProviderFactory
    factory = ProviderFactory()
    factory._chat_providers["local"] = local_provider
    factory._chat_providers["openai"] = cloud_provider
    monkeypatch.setattr(
        "app.domains.ai.providers.factory.default_provider_factory", factory
    )

    profile = _make_profile(provider_type="local", fallback_provider_key="openai")
    result = await service.generate_answer(prompt="Question?", resolved_profile=profile)

    # Fallback metadata must not leak prompt or context text.
    assert result.fallback_reason is not None
    assert "timeout" not in (result.fallback_reason or "")  # no raw error message
    assert "Question?" not in (result.fallback_reason or "")
    assert result.fallback_from == "local"
    assert result.fallback_to == "openai"


@pytest.mark.asyncio
async def test_fallback_and_primary_both_fail_raises_transient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "feature_enable_provider_fallback", True)

    async def _no_sleep(_: float) -> None:
        pass

    monkeypatch.setattr("app.domains.chat.services.llm_service.asyncio.sleep", _no_sleep)

    local_provider = FakeChatProvider([ProviderUnavailableError("local down")])
    cloud_provider = FakeChatProvider([ProviderUnavailableError("cloud also down")])

    service = LLMService(retry_max_attempts=1)
    monkeypatch.setattr(service, "_provider", None)

    from app.domains.ai.providers.factory import ProviderFactory
    factory = ProviderFactory()
    factory._chat_providers["local"] = local_provider
    factory._chat_providers["openai"] = cloud_provider
    monkeypatch.setattr(
        "app.domains.ai.providers.factory.default_provider_factory", factory
    )

    profile = _make_profile(provider_type="local", fallback_provider_key="openai")

    with pytest.raises(TransientLLMServiceError):
        await service.generate_answer(prompt="Question?", resolved_profile=profile)


# ---------------------------------------------------------------------------
# 4. Context-window protection
# ---------------------------------------------------------------------------


def test_apply_context_window_truncates_over_budget() -> None:
    service = LLMService()
    # context_window=100 tokens → budget = 85 tokens → max 340 chars
    long_prompt = "x" * 400
    result = LLMService._apply_context_window(long_prompt, context_window=100)
    assert len(result) == 340
    assert result == "x" * 340


def test_apply_context_window_no_op_when_within_budget() -> None:
    service = LLMService()
    prompt = "Short prompt that fits."
    result = LLMService._apply_context_window(prompt, context_window=10000)
    assert result == prompt


def test_apply_context_window_no_op_when_none() -> None:
    prompt = "x" * 10_000
    result = LLMService._apply_context_window(prompt, context_window=None)
    assert result == prompt


@pytest.mark.asyncio
async def test_profile_with_small_context_window_truncates_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provider receives a truncated prompt when model context window is small."""
    provider = FakeChatProvider([_ok_response("Truncated answer.")])

    service = LLMService(retry_max_attempts=1)
    monkeypatch.setattr(service, "_provider", None)

    from app.domains.ai.providers.factory import ProviderFactory
    factory = ProviderFactory()
    factory._chat_providers["local"] = provider
    monkeypatch.setattr(
        "app.domains.ai.providers.factory.default_provider_factory", factory
    )

    # context_window=50 → budget = 42 tokens → 170 chars max
    profile = _make_profile(provider_type="local", context_window=50)
    long_prompt = "A" * 500

    result = await service.generate_answer(prompt=long_prompt, resolved_profile=profile)

    assert result.answer == "Truncated answer."
    sent_prompt = provider.calls[0].prompt
    assert len(sent_prompt) <= 170


# ---------------------------------------------------------------------------
# 5. Profile resolution: env default used when no DB profile
# ---------------------------------------------------------------------------


def test_env_default_profile_has_no_context_window() -> None:
    from app.domains.ai.profile.service import _env_default_for_task

    profile = _env_default_for_task(TaskType.chat)
    assert profile.context_window is None
    assert profile.task_type == TaskType.chat


def test_resolved_task_profile_carries_context_window() -> None:
    profile = ResolvedTaskProfile(
        task_type=TaskType.chat,
        provider_type="local",
        base_model="llama-3",
        context_window=4096,
        json_mode=False,
        streaming=False,
        source=ProfileSource.org_profile,
        version=1,
    )
    assert profile.context_window == 4096


# ---------------------------------------------------------------------------
# 6. No profile → instance defaults preserved (backwards compat)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_profile_uses_instance_defaults() -> None:
    provider = FakeChatProvider([_ok_response(model="gpt-4o")])
    service = LLMService(model_name="gpt-4o", retry_max_attempts=1, provider=provider)

    result = await service.generate_answer(prompt="Hello?")

    assert result.model_name == "gpt-4o"
    assert result.fallback_used is False
    assert provider.calls[0].model == "gpt-4o"
