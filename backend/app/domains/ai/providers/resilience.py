"""Provider resilience: circuit breaker, stream idle timeout, organisation slots (R05-06).

``ResilientChatProvider(inner, provider_key)`` wraps ``complete()`` and ``stream()`` of a
chat provider:

1. The circuit breaker of ``(provider_key, model)`` must admit the call. An open breaker
   raises ``BreakerOpenError`` (a transient ``ProviderUnavailableError``) without calling
   the provider; ``LLMService`` then skips its retries and goes straight to the fallback.
2. The call holds one of the organisation's LLM call slots (``org_call_slot``).
3. While streaming, a gap longer than ``LLM_STREAM_IDLE_TIMEOUT_SECONDS`` between two chunks
   raises ``ProviderStreamIdleTimeoutError`` (a ``ProviderTimeoutError``).

Breaker states: closed (0) -> open (2) after ``LLM_BREAKER_FAILURE_THRESHOLD`` failures
within ``LLM_BREAKER_WINDOW_SECONDS``; open -> half-open (1) after
``LLM_BREAKER_OPEN_SECONDS``, where at most ``LLM_BREAKER_HALF_OPEN_PROBES`` calls run at
once; a probe that succeeds closes the breaker, a probe that fails reopens it. Only
transient provider failures count (unreachable, 5xx, timeouts, idle timeouts), never
validation errors, rate limits, or other 4xx answers.

Breakers live in one process-wide registry; each replica keeps its own state. Settings are
read at call time.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractContextManager, aclosing
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

from opentelemetry.trace import Span

from app.core.config import settings
from app.core.logging import get_logger
from app.core.metrics import (
    LLM_BREAKER_STATE,
    LLM_BREAKER_TRANSITIONS_TOTAL,
    LLM_CACHED_PROMPT_TOKENS_TOTAL,
)
from app.core.tracing_context import operation_span
from app.domains.ai.providers.errors import (
    ProviderInternalError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from app.domains.ai.providers.protocols import (
    ChatCompletionChunk,
    ChatCompletionProvider,
    ChatCompletionRequest,
    ChatCompletionResponse,
)
from app.rate_limit.concurrency import org_call_slot

logger = get_logger("ai.providers.resilience")


class BreakerOpenError(ProviderUnavailableError):
    """The circuit breaker of the provider and model is open; the provider was not called."""


class ProviderStreamIdleTimeoutError(ProviderTimeoutError):
    """The provider stream sent no chunk within ``LLM_STREAM_IDLE_TIMEOUT_SECONDS``."""


# Failures that count towards opening a breaker.
_COUNTED_ERRORS: tuple[type[BaseException], ...] = (
    ProviderTimeoutError,
    ProviderUnavailableError,
    ProviderInternalError,
    TimeoutError,
)


def counts_as_failure(exc: BaseException) -> bool:
    return isinstance(exc, _COUNTED_ERRORS) and not isinstance(exc, BreakerOpenError)


class BreakerState(IntEnum):
    closed = 0
    half_open = 1
    open = 2


@dataclass
class CircuitBreaker:
    provider_key: str
    model: str
    clock: Callable[[], float] = time.monotonic
    state: BreakerState = BreakerState.closed
    failures: deque[float] = field(default_factory=deque)
    opened_at: float = 0.0
    probes_in_flight: int = 0

    def __post_init__(self) -> None:
        LLM_BREAKER_STATE.labels(provider=self.provider_key, model=self.model).set(int(self.state))

    def _transition(self, state: BreakerState) -> None:
        if state == self.state:
            return
        previous = self.state
        self.state = state
        labels = {"provider": self.provider_key, "model": self.model}
        LLM_BREAKER_STATE.labels(**labels).set(int(state))
        LLM_BREAKER_TRANSITIONS_TOTAL.labels(**labels, state=state.name).inc()
        logger.warning(
            "llm.breaker.transition",
            provider=self.provider_key,
            model=self.model,
            from_state=previous.name,
            to_state=state.name,
        )

    def before_call(self) -> bool:
        """Admit a call or raise ``BreakerOpenError``; True when the call is a probe."""
        if not settings.llm_breaker_enabled:
            return False
        if self.state == BreakerState.open:
            if self.clock() - self.opened_at < settings.llm_breaker_open_seconds:
                raise BreakerOpenError(
                    f"Circuit breaker open for provider {self.provider_key} model {self.model}"
                )
            self.probes_in_flight = 0
            self._transition(BreakerState.half_open)
        if self.state == BreakerState.half_open:
            if self.probes_in_flight >= settings.llm_breaker_half_open_probes:
                raise BreakerOpenError(
                    f"Circuit breaker half-open for provider {self.provider_key} model {self.model}"
                )
            self.probes_in_flight += 1
            return True
        return False

    def _end_probe(self, probe: bool) -> None:
        if probe and self.probes_in_flight > 0:
            self.probes_in_flight -= 1

    def record_success(self, probe: bool) -> None:
        self._end_probe(probe)
        if probe and self.state == BreakerState.half_open:
            self.failures.clear()
            self._transition(BreakerState.closed)

    def record_error(self, exc: BaseException, probe: bool) -> None:
        """Count a transient failure; other errors (and cancellation) only end a probe."""
        self._end_probe(probe)
        if not settings.llm_breaker_enabled or not counts_as_failure(exc):
            return
        now = self.clock()
        if probe or self.state == BreakerState.half_open:
            self._open(now)
            return
        self.failures.append(now)
        window = settings.llm_breaker_window_seconds
        while self.failures and now - self.failures[0] > window:
            self.failures.popleft()
        if len(self.failures) >= settings.llm_breaker_failure_threshold:
            self._open(now)

    def _open(self, now: float) -> None:
        self.opened_at = now
        self.failures.clear()
        self.probes_in_flight = 0
        self._transition(BreakerState.open)


class BreakerRegistry:
    """One breaker per ``(provider_key, model)``; ``reset()`` is for tests."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self._breakers: dict[tuple[str, str], CircuitBreaker] = {}

    def get(self, provider_key: str, model: str) -> CircuitBreaker:
        key = (provider_key, model)
        breaker = self._breakers.get(key)
        if breaker is None:
            breaker = CircuitBreaker(provider_key=provider_key, model=model, clock=self.clock)
            self._breakers[key] = breaker
        return breaker

    def reset(self) -> None:
        for breaker in self._breakers.values():
            LLM_BREAKER_STATE.labels(provider=breaker.provider_key, model=breaker.model).set(0)
        self._breakers.clear()


breaker_registry = BreakerRegistry()


def _count_cached(provider_key: str, model: str, cached: int | None) -> None:
    if cached:
        LLM_CACHED_PROMPT_TOKENS_TOTAL.labels(provider=provider_key, model=model).inc(cached)


class ResilientChatProvider:
    """Breaker, organisation slot, and stream idle timeout around one chat provider."""

    def __init__(
        self,
        inner: ChatCompletionProvider,
        provider_key: str,
        *,
        registry: BreakerRegistry | None = None,
    ) -> None:
        self.inner = inner
        self.provider_key = provider_key
        self._registry = registry

    @property
    def _model_name(self) -> str | None:
        # LLMService reads the fallback provider's configured model from this attribute.
        value = getattr(self.inner, "_model_name", None)
        return value if isinstance(value, str) else None

    def _breaker(self, request: ChatCompletionRequest) -> CircuitBreaker:
        model = request.model or self._model_name or "default"
        return (self._registry or breaker_registry).get(self.provider_key, model)

    def _span(
        self, breaker: CircuitBreaker, *, current: bool
    ) -> AbstractContextManager[Span | None]:
        """R08-10: provider and model only; never the prompt or the answer."""
        return operation_span(
            "rudix.llm.call",
            current=current,
            attributes={
                "rudix.llm.provider": self.provider_key,
                "rudix.llm.model": breaker.model,
            },
        )

    async def complete(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        breaker = self._breaker(request)
        probe = breaker.before_call()
        try:
            with self._span(breaker, current=True):
                async with org_call_slot(self.provider_key):
                    response = await self.inner.complete(request)
        except BaseException as exc:
            breaker.record_error(exc, probe)
            raise
        breaker.record_success(probe)
        _count_cached(self.provider_key, breaker.model, response.cached_prompt_tokens)
        return response

    async def stream(self, request: ChatCompletionRequest) -> AsyncIterator[ChatCompletionChunk]:
        breaker = self._breaker(request)
        probe = breaker.before_call()
        finished = False
        try:
            # Not the current span: the generator yields across the consumer's tasks.
            with self._span(breaker, current=False):
                async with org_call_slot(self.provider_key):
                    stream_fn = getattr(self.inner, "stream", None)
                    if not callable(stream_fn):
                        response = await self.inner.complete(request)
                        _count_cached(
                            self.provider_key, breaker.model, response.cached_prompt_tokens
                        )
                        finished = True
                        yield _single_chunk(response)
                        return
                    async with aclosing(stream_fn(request)) as chunks:
                        async for chunk in _with_idle_timeout(chunks):
                            _count_cached(
                                self.provider_key, breaker.model, chunk.cached_prompt_tokens
                            )
                            yield chunk
                    finished = True
        except GeneratorExit:
            # The consumer closed the stream early: the call neither failed nor succeeded.
            if finished:
                breaker.record_success(probe)
            else:
                breaker.record_error(asyncio.CancelledError(), probe)
            raise
        except BaseException as exc:
            breaker.record_error(exc, probe)
            raise
        if finished:
            breaker.record_success(probe)


def _single_chunk(response: ChatCompletionResponse) -> ChatCompletionChunk:
    return ChatCompletionChunk(
        text_delta=response.content,
        prompt_tokens=response.prompt_tokens,
        completion_tokens=response.completion_tokens,
        cached_prompt_tokens=response.cached_prompt_tokens,
        model=response.model,
        finish_reason="stop",
    )


async def _with_idle_timeout(
    chunks: AsyncIterator[ChatCompletionChunk],
) -> AsyncIterator[ChatCompletionChunk]:
    """Yield ``chunks``; after the first one, a gap above the idle timeout raises."""
    iterator = chunks.__aiter__()
    first = True
    while True:
        timeout = settings.llm_stream_idle_timeout_seconds
        idle = asyncio.timeout(timeout if not first and timeout > 0 else None)
        try:
            async with idle:
                chunk = await iterator.__anext__()
        except StopAsyncIteration:
            return
        except TimeoutError:
            if not idle.expired():
                raise  # the provider's own timeout
            raise ProviderStreamIdleTimeoutError(
                f"Provider stream idle for more than {timeout:g} seconds"
            ) from None
        first = False
        yield chunk


def as_resilient(provider: Any, provider_key: str) -> Any:
    """``provider`` wrapped once: an already resilient provider is returned as is."""
    if isinstance(provider, ResilientChatProvider):
        return provider
    return ResilientChatProvider(provider, provider_key)


def unwrap(provider: Any) -> Any:
    """The provider inside a ``ResilientChatProvider`` (anything else as is)."""
    return provider.inner if isinstance(provider, ResilientChatProvider) else provider
