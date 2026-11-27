"""Circuit breaker, stream idle timeout, and cached-token accounting (R05-06).

The fault-injection tests run ``LLMService`` against a provider factory with a failing
primary and a healthy fallback: the breaker opens after N failures, the next call skips the
primary without retry backoff and the fallback answers, and a half-open probe closes it.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest

from app.application.chat.pipeline.ledger import TokenLedger
from app.application.chat.pipeline.stages._ledger import record_llm_results
from app.core.config import settings
from app.core.metrics import (
    LLM_BREAKER_STATE,
    LLM_BREAKER_TRANSITIONS_TOTAL,
    LLM_CACHED_PROMPT_TOKENS_TOTAL,
)
from app.domains.ai.profile.schemas import ProfileSource, ResolvedTaskProfile, TaskType
from app.domains.ai.providers.errors import (
    InvalidProviderResponseError,
    ProviderInternalError,
    ProviderQuotaExceededError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from app.domains.ai.providers.factory import ProviderFactory
from app.domains.ai.providers.openai.adapter import OpenAIChatProvider
from app.domains.ai.providers.openai.streaming import cached_prompt_tokens, parse_stream_chunk
from app.domains.ai.providers.protocols import (
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatCompletionResponse,
)
from app.domains.ai.providers.resilience import (
    BreakerOpenError,
    BreakerRegistry,
    BreakerState,
    ProviderStreamIdleTimeoutError,
    ResilientChatProvider,
    as_resilient,
    breaker_registry,
    counts_as_failure,
    unwrap,
)
from app.domains.chat.services.llm_service import LLMService, TransientLLMServiceError

pytestmark = pytest.mark.asyncio

ANSWER = '{"answer":"%s","not_found":false,"citations":[]}'


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _response(text: str, *, model: str = "m", cached: int = 0) -> ChatCompletionResponse:
    return ChatCompletionResponse(
        content=ANSWER % text,
        model=model,
        prompt_tokens=20,
        completion_tokens=10,
        total_tokens=30,
        latency_ms=1,
        cached_prompt_tokens=cached,
    )


class ScriptedProvider:
    """``complete()`` raises ``fail_with`` while ``failing`` is set, else answers."""

    def __init__(self, text: str, *, model_name: str = "m", cached: int = 0) -> None:
        self.text = text
        self._model_name = model_name
        self.cached = cached
        self.failing = False
        self.fail_with: Exception = ProviderUnavailableError("down")
        self.calls = 0

    async def complete(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        self.calls += 1
        if self.failing:
            raise self.fail_with
        return _response(self.text, model=request.model or self._model_name, cached=self.cached)


def _gauge(provider: str, model: str) -> float:
    for metric in LLM_BREAKER_STATE.collect():
        for sample in metric.samples:
            if sample.labels == {"provider": provider, "model": model}:
                return float(sample.value)
    return -1.0


def _transitions(provider: str, model: str, state: str) -> float:
    for metric in LLM_BREAKER_TRANSITIONS_TOTAL.collect():
        for sample in metric.samples:
            if sample.name.endswith("_total") and sample.labels == {
                "provider": provider,
                "model": model,
                "state": state,
            }:
                return float(sample.value)
    return 0.0


def _profile(provider: str, model: str, fallback: str | None) -> ResolvedTaskProfile:
    return ResolvedTaskProfile(
        task_type=TaskType.chat,
        provider_type=provider,
        base_model=model,
        context_window=None,
        json_mode=True,
        streaming=False,
        fallback_provider_key=fallback,
        source=ProfileSource.org_profile,
        version=1,
    )


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    fake = FakeClock()
    monkeypatch.setattr(breaker_registry, "clock", fake)
    return fake


@pytest.fixture
def breaker_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "llm_breaker_enabled", True)
    monkeypatch.setattr(settings, "llm_breaker_failure_threshold", 3)
    monkeypatch.setattr(settings, "llm_breaker_window_seconds", 30.0)
    monkeypatch.setattr(settings, "llm_breaker_open_seconds", 30.0)
    monkeypatch.setattr(settings, "llm_breaker_half_open_probes", 1)
    monkeypatch.setattr(settings, "feature_enable_provider_fallback", True)


@pytest.fixture
def sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    recorded: list[float] = []

    async def _sleep(seconds: float) -> None:
        recorded.append(seconds)

    monkeypatch.setattr("app.domains.chat.services.llm_service.asyncio.sleep", _sleep)
    return recorded


def _factory(monkeypatch: pytest.MonkeyPatch, **providers: Any) -> ProviderFactory:
    factory = ProviderFactory()
    for key, provider in providers.items():
        factory._chat_providers[key] = provider
    monkeypatch.setattr("app.domains.ai.providers.factory.default_provider_factory", factory)
    return factory


# -- fault injection ------------------------------------------------------------------------


@pytest.mark.usefixtures("breaker_settings")
async def test_breaker_opens_and_the_fallback_answers_without_backoff(
    monkeypatch: pytest.MonkeyPatch, clock: FakeClock, sleeps: list[float]
) -> None:
    primary = ScriptedProvider("primary answer", model_name="primary-model")
    fallback = ScriptedProvider("fallback answer", model_name="fallback-model")
    _factory(monkeypatch, local=primary, openai=fallback)
    service = LLMService(retry_max_attempts=2, provider=None)
    profile = _profile("local", "primary-model", "openai")
    opened_before = _transitions("local", "primary-model", "open")

    primary.failing = True
    # Two calls x two attempts = four failures: the third opens the breaker, so the fourth
    # attempt of the second call is already refused without calling the provider.
    for _ in range(2):
        result = await service.generate_answer(prompt="q", resolved_profile=profile)
        assert result.answer == "fallback answer" and result.fallback_used is True
    assert primary.calls == 3
    assert breaker_registry.get("local", "primary-model").state == BreakerState.open
    assert _gauge("local", "primary-model") == 2.0
    assert _transitions("local", "primary-model", "open") == opened_before + 1

    # Open: the primary is skipped at once (no retry backoff) and the fallback answers.
    sleeps.clear()
    result = await service.generate_answer(prompt="q", resolved_profile=profile)
    assert primary.calls == 3
    assert sleeps == []
    assert result.answer == "fallback answer"
    assert result.fallback_from == "local" and result.fallback_to == "openai"
    assert result.fallback_reason == "BreakerOpenError"
    assert result.model_name == "fallback-model"

    # After the open period one probe goes through; its success closes the breaker.
    primary.failing = False
    clock.advance(31)
    result = await service.generate_answer(prompt="q", resolved_profile=profile)
    assert result.answer == "primary answer" and result.fallback_used is False
    assert primary.calls == 4
    assert breaker_registry.get("local", "primary-model").state == BreakerState.closed
    assert _gauge("local", "primary-model") == 0.0
    assert _transitions("local", "primary-model", "half_open") >= 1
    assert _transitions("local", "primary-model", "closed") >= 1


@pytest.mark.usefixtures("breaker_settings")
async def test_open_breaker_without_fallback_fails_fast(
    monkeypatch: pytest.MonkeyPatch, clock: FakeClock, sleeps: list[float]
) -> None:
    primary = ScriptedProvider("primary answer")
    primary.failing = True
    _factory(monkeypatch, local=primary)
    service = LLMService(retry_max_attempts=1, provider=None)
    profile = _profile("local", "m", None)
    for _ in range(3):
        with pytest.raises(TransientLLMServiceError):
            await service.generate_answer(prompt="q", resolved_profile=profile)
    sleeps.clear()
    with pytest.raises(TransientLLMServiceError) as excinfo:
        await service.generate_answer(prompt="q", resolved_profile=profile)
    assert isinstance(excinfo.value.__cause__, BreakerOpenError)
    assert primary.calls == 3 and sleeps == []


@pytest.mark.usefixtures("breaker_settings")
async def test_failed_half_open_probe_reopens(clock: FakeClock) -> None:
    provider = ScriptedProvider("x")
    wrapped = ResilientChatProvider(provider, "local")
    provider.failing = True
    request = ChatCompletionRequest(prompt="q", model="m")
    for _ in range(3):
        with pytest.raises(ProviderUnavailableError):
            await wrapped.complete(request)
    clock.advance(31)
    with pytest.raises(ProviderUnavailableError) as excinfo:
        await wrapped.complete(request)  # the probe reaches the provider and fails
    assert not isinstance(excinfo.value, BreakerOpenError)
    assert provider.calls == 4
    assert breaker_registry.get("local", "m").state == BreakerState.open
    with pytest.raises(BreakerOpenError):
        await wrapped.complete(request)
    assert provider.calls == 4


@pytest.mark.usefixtures("breaker_settings")
async def test_half_open_admits_only_the_configured_probes(clock: FakeClock) -> None:
    breaker = breaker_registry.get("p", "m")
    for _ in range(3):
        breaker.record_error(ProviderTimeoutError("t"), probe=False)
    clock.advance(31)
    assert breaker.before_call() is True
    assert breaker.state == BreakerState.half_open
    assert _gauge("p", "m") == 1.0
    with pytest.raises(BreakerOpenError):
        breaker.before_call()
    breaker.record_error(InvalidProviderResponseError("bad"), probe=True)  # not counted
    assert breaker.state == BreakerState.half_open
    assert breaker.before_call() is True  # the slot was released
    breaker.record_success(probe=True)
    assert breaker.state == BreakerState.closed


@pytest.mark.usefixtures("breaker_settings")
async def test_only_transient_failures_count_and_old_failures_expire(clock: FakeClock) -> None:
    breaker = breaker_registry.get("p", "m")
    for _ in range(5):
        breaker.record_error(InvalidProviderResponseError("4xx"), probe=False)
        breaker.record_error(ProviderQuotaExceededError("429"), probe=False)
    assert breaker.state == BreakerState.closed
    breaker.record_error(ProviderInternalError("5xx"), probe=False)
    breaker.record_error(ProviderTimeoutError("t"), probe=False)
    clock.advance(31)  # both fall out of the window
    breaker.record_error(ProviderUnavailableError("u"), probe=False)
    assert breaker.state == BreakerState.closed
    breaker.record_error(ProviderStreamIdleTimeoutError("idle"), probe=False)
    breaker.record_error(TimeoutError(), probe=False)
    assert breaker.state == BreakerState.open
    assert counts_as_failure(BreakerOpenError("open")) is False
    assert counts_as_failure(asyncio.CancelledError()) is False


async def test_disabled_breaker_never_opens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "llm_breaker_enabled", False)
    provider = ScriptedProvider("x")
    provider.failing = True
    wrapped = ResilientChatProvider(provider, "local", registry=BreakerRegistry())
    for _ in range(10):
        with pytest.raises(ProviderUnavailableError):
            await wrapped.complete(ChatCompletionRequest(prompt="q", model="m"))
    assert provider.calls == 10


# -- streaming ------------------------------------------------------------------------------


class StreamingProvider:
    def __init__(self, pieces: list[str], *, gap_at: int | None = None, gap: float = 0.0):
        self.pieces = pieces
        self.gap_at = gap_at
        self.gap = gap
        self._model_name = "m"
        self.closed = 0

    async def complete(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        raise AssertionError("stream() is used")

    async def stream(self, request: ChatCompletionRequest) -> AsyncIterator[ChatCompletionChunk]:
        try:
            for index, piece in enumerate(self.pieces):
                if index == self.gap_at:
                    # Stalls until the idle timeout cancels the wait (an Event, not
                    # asyncio.sleep, which some tests patch).
                    try:
                        await asyncio.wait_for(asyncio.Event().wait(), self.gap)
                    except TimeoutError:
                        pass
                yield ChatCompletionChunk(text_delta=piece, model="m")
            yield ChatCompletionChunk(prompt_tokens=3, completion_tokens=4, cached_prompt_tokens=2)
        finally:
            self.closed += 1


@pytest.mark.usefixtures("breaker_settings")
async def test_stream_idle_timeout_counts_and_the_fallback_replaces_streamed_text(
    monkeypatch: pytest.MonkeyPatch, clock: FakeClock
) -> None:
    monkeypatch.setattr(settings, "llm_stream_idle_timeout_seconds", 0.05)
    text = ANSWER % "streamed primary"
    stalling = StreamingProvider([text[:14], text[14:]], gap_at=1, gap=1.0)
    fallback = ScriptedProvider("fallback answer")
    _factory(monkeypatch, local=stalling, openai=fallback)
    service = LLMService(retry_max_attempts=1, provider=None)
    streamed: list[str] = []
    resets: list[str] = []

    async def on_text(piece: str) -> None:
        streamed.append(piece)

    async def on_reset(reason: str) -> None:
        resets.append(reason)

    result = await service.stream_answer(
        prompt="q",
        resolved_profile=_profile("local", "m", "openai"),
        on_text=on_text,
        on_reset=on_reset,
    )
    assert result.answer == "fallback answer" and result.fallback_used is True
    assert result.fallback_reason == "ProviderStreamIdleTimeoutError"
    assert streamed[0] == "str" and resets == ["fallback"]
    assert stalling.closed == 1
    assert len(breaker_registry.get("local", "m").failures) == 1


async def test_stream_passes_chunks_and_counts_cached_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "llm_stream_idle_timeout_seconds", 5.0)
    provider = StreamingProvider(["a", "b"], gap_at=1, gap=0.01)
    wrapped = ResilientChatProvider(provider, "openai")
    before = _cached("openai", "m")
    chunks = [c async for c in wrapped.stream(ChatCompletionRequest(prompt="q", model="m"))]
    assert [c.text_delta for c in chunks] == ["a", "b", ""]
    assert _cached("openai", "m") == before + 2


async def test_stream_of_a_provider_without_stream_is_one_chunk() -> None:
    provider = ScriptedProvider("whole", cached=7)
    wrapped = ResilientChatProvider(provider, "local")
    chunks = [c async for c in wrapped.stream(ChatCompletionRequest(prompt="q", model="m"))]
    assert len(chunks) == 1 and chunks[0].cached_prompt_tokens == 7
    assert chunks[0].prompt_tokens == 20 and chunks[0].finish_reason == "stop"


async def test_stream_closed_early_counts_no_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "llm_breaker_half_open_probes", 1)
    provider = StreamingProvider(["a", "b", "c"])
    wrapped = ResilientChatProvider(provider, "local")
    stream = wrapped.stream(ChatCompletionRequest(prompt="q", model="m"))
    assert (await stream.__anext__()).text_delta == "a"
    await stream.aclose()  # type: ignore[attr-defined]
    assert provider.closed == 1
    assert len(breaker_registry.get("local", "m").failures) == 0


# -- wrapping -------------------------------------------------------------------------------


async def test_wrapping_is_idempotent_and_the_factory_caches_the_wrapper() -> None:
    provider = ScriptedProvider("x", model_name="named")
    wrapped = as_resilient(provider, "local")
    assert as_resilient(wrapped, "other") is wrapped
    assert unwrap(wrapped) is provider and unwrap(provider) is provider
    assert wrapped._model_name == "named"

    factory = ProviderFactory()
    factory._chat_providers["local"] = provider
    first = factory.get_chat_provider("local")
    assert isinstance(first, ResilientChatProvider) and first.inner is provider
    assert factory.get_chat_provider("local") is first
    replacement = ScriptedProvider("y")
    factory._chat_providers["local"] = replacement
    second = factory.get_chat_provider("local")
    assert isinstance(second, ResilientChatProvider) and second.inner is replacement
    factory._chat_providers["pre"] = wrapped  # type: ignore[assignment]
    assert factory.get_chat_provider("pre") is wrapped


async def test_injected_provider_is_wrapped_once() -> None:
    provider = ScriptedProvider("x")
    service = LLMService(provider=provider)  # type: ignore[arg-type]
    resolved = service._resolve_provider("local")
    assert isinstance(resolved, ResilientChatProvider)
    assert resolved.inner is provider and resolved.provider_key == "local"
    result = await service.generate_answer(prompt="q")
    assert result.answer == "x" and provider.calls == 1


async def test_chat_proxy_routes_to_the_unwrapped_factory_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.application.chat.pipeline import provider_proxies

    provider = ScriptedProvider("x")
    factory = ProviderFactory()
    factory._chat_providers[settings.llm_default_provider] = provider
    monkeypatch.setattr(provider_proxies, "default_provider_factory", factory)
    assert provider_proxies._factory_chat_provider() is provider


# -- cached prompt tokens -------------------------------------------------------------------


def _cached(provider: str, model: str) -> float:
    for metric in LLM_CACHED_PROMPT_TOKENS_TOTAL.collect():
        for sample in metric.samples:
            if sample.name.endswith("_total") and sample.labels == {
                "provider": provider,
                "model": model,
            }:
                return float(sample.value)
    return 0.0


async def test_openai_adapter_reads_cached_prompt_tokens() -> None:
    usage = SimpleNamespace(
        prompt_tokens=100,
        completion_tokens=5,
        total_tokens=105,
        prompt_tokens_details=SimpleNamespace(cached_tokens=64),
    )
    completion = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=ANSWER % "a"))],
        model="gpt",
        usage=usage,
    )

    async def create(**_kwargs: object) -> Any:
        return completion

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    provider = OpenAIChatProvider(client=client, model_name="gpt")
    response = await provider.complete(ChatCompletionRequest(prompt="q"))
    assert response.cached_prompt_tokens == 64

    assert cached_prompt_tokens(None) == 0
    assert cached_prompt_tokens(SimpleNamespace(prompt_tokens=1)) == 0
    chunk = parse_stream_chunk(SimpleNamespace(choices=[], usage=usage, model="gpt"))
    assert chunk.cached_prompt_tokens == 64


async def test_cached_tokens_reach_the_answer_result_and_the_ledger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = ScriptedProvider("x", cached=12)
    service = LLMService(provider=provider)  # type: ignore[arg-type]
    before = _cached(settings.llm_default_provider, service.model_name)
    result = await service.generate_answer(prompt="q")
    assert result.cached_prompt_tokens == 12
    assert _cached(settings.llm_default_provider, service.model_name) == before + 12

    streamed = await service.stream_answer(prompt="q", on_text=_ignore)
    assert streamed.cached_prompt_tokens == 12

    ctx = SimpleNamespace(ledger=TokenLedger())
    record_llm_results(ctx, [result])  # type: ignore[arg-type]
    assert ctx.ledger.totals().cached_tokens == 12


async def _ignore(_text: str) -> None:
    return None


class _RaisingStream(StreamingProvider):
    async def stream(self, request: ChatCompletionRequest) -> AsyncIterator[ChatCompletionChunk]:
        yield ChatCompletionChunk(text_delta="a")
        raise TimeoutError("provider read timeout")


async def test_provider_timeout_inside_a_stream_is_not_an_idle_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "llm_stream_idle_timeout_seconds", 5.0)
    wrapped = ResilientChatProvider(_RaisingStream([]), "local")
    with pytest.raises(TimeoutError) as excinfo:
        _ = [c async for c in wrapped.stream(ChatCompletionRequest(prompt="q", model="m"))]
    assert not isinstance(excinfo.value, ProviderStreamIdleTimeoutError)
    assert len(breaker_registry.get("local", "m").failures) == 1
