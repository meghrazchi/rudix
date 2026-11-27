"""Streaming chat providers and the chat provider proxy (R05-03)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import aclosing
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from openai import APITimeoutError, BadRequestError, RateLimitError

from app.application.chat.pipeline.provider_proxies import _ChatCompletionProviderProxy
from app.domains.ai.providers.errors import (
    ProviderQuotaExceededError,
    ProviderTimeoutError,
    UnsupportedCapabilityError,
)
from app.domains.ai.providers.local.adapter import OpenAICompatibleChatProvider
from app.domains.ai.providers.openai.adapter import OpenAIChatProvider
from app.domains.ai.providers.openai.streaming import close_stream, parse_stream_chunk
from app.domains.ai.providers.protocols import (
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatCompletionResponse,
    StreamingChatCompletionProvider,
)

pytestmark = [pytest.mark.asyncio]


def _chunk(content: str | None = None, *, finish: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content=content), finish_reason=finish)],
        usage=None,
        model="gpt-stream",
    )


def _usage_chunk(prompt: int, completion: int, cached: int | None = None) -> SimpleNamespace:
    details = SimpleNamespace(cached_tokens=cached) if cached is not None else None
    return SimpleNamespace(
        choices=[],
        usage=SimpleNamespace(
            prompt_tokens=prompt, completion_tokens=completion, prompt_tokens_details=details
        ),
        model="gpt-stream",
    )


class _FakeStream:
    def __init__(self, events: list[Any], *, fail_at: int | None = None) -> None:
        self._events = events
        self._fail_at = fail_at
        self.closed = False

    def __aiter__(self) -> _FakeStream:
        self._index = 0
        return self

    async def __anext__(self) -> Any:
        if self._fail_at is not None and self._index == self._fail_at:
            raise APITimeoutError(request=httpx.Request("POST", "http://local/v1"))
        if self._index >= len(self._events):
            raise StopAsyncIteration
        event = self._events[self._index]
        self._index += 1
        return event

    async def close(self) -> None:
        self.closed = True


class _FakeEndpoint:
    def __init__(self, results: list[Any]) -> None:
        self._results = results
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        item = self._results.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class _FakeClient:
    def __init__(self, results: list[Any]) -> None:
        self.completions = _FakeEndpoint(results)
        self.chat = self


def _bad_request(message: str) -> BadRequestError:
    request = httpx.Request("POST", "http://local/v1/chat/completions")
    return BadRequestError(message, response=httpx.Response(400, request=request), body=None)


def _rate_limited() -> RateLimitError:
    request = httpx.Request("POST", "http://local/v1/chat/completions")
    return RateLimitError("slow down", response=httpx.Response(429, request=request), body=None)


async def _collect(iterator: AsyncIterator[ChatCompletionChunk]) -> list[ChatCompletionChunk]:
    return [chunk async for chunk in iterator]


@pytest.mark.parametrize("provider_cls", [OpenAIChatProvider, OpenAICompatibleChatProvider])
async def test_stream_yields_text_then_usage_and_closes(provider_cls: Any) -> None:
    stream = _FakeStream(
        [_chunk(""), _chunk('{"answer"'), _chunk(': "x"}', finish="stop"), _usage_chunk(9, 4, 2)]
    )
    client = _FakeClient([stream])
    provider = provider_cls(client=client, model_name="m")
    assert isinstance(provider, StreamingChatCompletionProvider)

    chunks = await _collect(provider.stream(ChatCompletionRequest(prompt="q")))

    assert "".join(c.text_delta for c in chunks) == '{"answer": "x"}'
    assert chunks[2].finish_reason == "stop"
    assert (chunks[-1].prompt_tokens, chunks[-1].completion_tokens) == (9, 4)
    assert chunks[-1].cached_prompt_tokens == 2 and chunks[-1].text_delta == ""
    call = client.completions.calls[0]
    assert call["stream"] is True and call["stream_options"] == {"include_usage": True}
    assert call["model"] == "m" and call["response_format"] == {"type": "json_object"}
    assert stream.closed


@pytest.mark.parametrize("provider_cls", [OpenAIChatProvider, OpenAICompatibleChatProvider])
async def test_closing_the_iterator_early_closes_the_provider_stream(provider_cls: Any) -> None:
    stream = _FakeStream([_chunk("a"), _chunk("b"), _chunk("c")])
    provider = provider_cls(client=_FakeClient([stream]), model_name="m")
    async with aclosing(provider.stream(ChatCompletionRequest(prompt="q"))) as chunks:
        async for chunk in chunks:
            assert chunk.text_delta == "a"
            break
    assert stream.closed


@pytest.mark.parametrize("provider_cls", [OpenAIChatProvider, OpenAICompatibleChatProvider])
async def test_errors_are_mapped_at_create_and_mid_stream(provider_cls: Any) -> None:
    provider = provider_cls(client=_FakeClient([_rate_limited()]), model_name="m")
    with pytest.raises(ProviderQuotaExceededError):
        await _collect(provider.stream(ChatCompletionRequest(prompt="q")))

    stream = _FakeStream([_chunk("a")], fail_at=1)
    provider = provider_cls(client=_FakeClient([stream]), model_name="m")
    with pytest.raises(ProviderTimeoutError):
        await _collect(provider.stream(ChatCompletionRequest(prompt="q")))
    assert stream.closed


async def test_local_provider_retries_once_without_stream_options() -> None:
    stream = _FakeStream([_chunk("ok")])
    client = _FakeClient([_bad_request("Unrecognized request argument: stream_options"), stream])
    provider = OpenAICompatibleChatProvider(client=client, model_name="m")

    chunks = await _collect(provider.stream(ChatCompletionRequest(prompt="q")))

    assert [c.text_delta for c in chunks] == ["ok"]
    assert "stream_options" in client.completions.calls[0]
    assert "stream_options" not in client.completions.calls[1]
    assert client.completions.calls[1]["stream"] is True


async def test_local_provider_does_not_retry_a_response_format_rejection() -> None:
    client = _FakeClient([_bad_request("response_format json_object is not supported")])
    provider = OpenAICompatibleChatProvider(client=client, model_name="m")
    with pytest.raises(UnsupportedCapabilityError):
        await _collect(provider.stream(ChatCompletionRequest(prompt="q")))
    assert len(client.completions.calls) == 1


async def test_local_provider_maps_a_failing_retry() -> None:
    client = _FakeClient([_bad_request("stream_options unknown"), _rate_limited()])
    provider = OpenAICompatibleChatProvider(client=client, model_name="m")
    with pytest.raises(ProviderQuotaExceededError):
        await _collect(provider.stream(ChatCompletionRequest(prompt="q")))


async def test_local_provider_honours_disabled_json_mode() -> None:
    client = _FakeClient([_FakeStream([_chunk("x")])])
    provider = OpenAICompatibleChatProvider(client=client, model_name="m", json_mode_enabled=False)
    await _collect(provider.stream(ChatCompletionRequest(prompt="q")))
    assert "response_format" not in client.completions.calls[0]


def test_parse_stream_chunk_tolerates_missing_fields() -> None:
    assert parse_stream_chunk(SimpleNamespace()) == ChatCompletionChunk()
    odd = SimpleNamespace(
        choices=[SimpleNamespace(delta=None, finish_reason=None)],
        usage=SimpleNamespace(prompt_tokens=True, completion_tokens=2.0),
        model=None,
    )
    assert parse_stream_chunk(odd) == ChatCompletionChunk(completion_tokens=2)


async def test_close_stream_handles_sync_async_and_missing_closers() -> None:
    closed: list[str] = []

    class _Sync:
        def close(self) -> None:
            closed.append("sync")

    class _Async:
        async def aclose(self) -> None:
            closed.append("async")

    await close_stream(_Sync())
    await close_stream(_Async())
    await close_stream(object())
    assert closed == ["sync", "async"]


# -- provider proxy (injected client or provider factory) ------------------------------


def _completion(content: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=3, completion_tokens=2, total_tokens=5),
        model="fake",
    )


async def test_proxy_streams_through_a_client_that_supports_stream() -> None:
    stream = _FakeStream([_chunk("he"), _chunk("llo"), _usage_chunk(5, 2)])
    client = _FakeClient([stream])
    proxy = _ChatCompletionProviderProxy(lambda: client)

    chunks = await _collect(proxy.stream(ChatCompletionRequest(prompt="q", model="m")))

    assert "".join(c.text_delta for c in chunks) == "hello"
    assert chunks[-1].prompt_tokens == 5
    call = client.completions.calls[0]
    assert call["stream"] is True and call["messages"][0]["role"] == "system"
    assert stream.closed


async def test_proxy_falls_back_when_the_client_ignores_stream() -> None:
    client = _FakeClient([_completion('{"answer": "a"}')])
    proxy = _ChatCompletionProviderProxy(lambda: client)

    chunks = await _collect(proxy.stream(ChatCompletionRequest(prompt="q", model="m")))

    assert len(chunks) == 1
    assert chunks[0].text_delta == '{"answer": "a"}'
    assert (chunks[0].prompt_tokens, chunks[0].completion_tokens) == (3, 2)


class _FactoryComplete:
    async def complete(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        return ChatCompletionResponse(
            content="whole",
            model="f",
            prompt_tokens=1,
            completion_tokens=1,
            total_tokens=2,
            latency_ms=0,
        )


class _FactoryStream(_FactoryComplete):
    async def stream(self, request: ChatCompletionRequest) -> AsyncIterator[ChatCompletionChunk]:
        yield ChatCompletionChunk(text_delta="pi")
        yield ChatCompletionChunk(text_delta="ece")


@pytest.mark.parametrize(
    ("factory_provider", "expected"),
    [(_FactoryStream(), ["pi", "ece"]), (_FactoryComplete(), ["whole"])],
)
async def test_proxy_without_client_uses_the_provider_factory(
    monkeypatch: pytest.MonkeyPatch, factory_provider: Any, expected: list[str]
) -> None:
    from app.application.chat.pipeline import provider_proxies

    monkeypatch.setattr(
        provider_proxies.default_provider_factory,
        "get_chat_provider",
        lambda _key: factory_provider,
    )
    proxy = _ChatCompletionProviderProxy(lambda: None)
    chunks = await _collect(proxy.stream(ChatCompletionRequest(prompt="q")))
    assert [c.text_delta for c in chunks] == expected


def _status_error(cls: type[Exception], code: int) -> Exception:
    request = httpx.Request("POST", "http://local/v1/chat/completions")
    return cls("boom key=sk-secret", response=httpx.Response(code, request=request), body=None)  # type: ignore[call-arg]


def _sdk_errors() -> list[tuple[Exception, type[Exception]]]:
    from openai import (
        APIConnectionError,
        AuthenticationError,
        InternalServerError,
        PermissionDeniedError,
    )

    from app.domains.ai.providers.errors import (
        InvalidProviderResponseError,
        ProviderInternalError,
        ProviderPolicyBlockedError,
        ProviderUnavailableError,
    )

    request = httpx.Request("POST", "http://local/v1/chat/completions")
    return [
        (_rate_limited(), ProviderQuotaExceededError),
        (APITimeoutError(request=request), ProviderTimeoutError),
        (APIConnectionError(request=request), ProviderUnavailableError),
        (_status_error(AuthenticationError, 401), ProviderPolicyBlockedError),
        (_status_error(PermissionDeniedError, 403), ProviderPolicyBlockedError),
        (_bad_request("response_format is not supported"), UnsupportedCapabilityError),
        (_bad_request("bad prompt"), InvalidProviderResponseError),
        (_status_error(InternalServerError, 500), ProviderInternalError),
        (OSError("reset"), ProviderUnavailableError),
        (ValueError("odd"), ProviderInternalError),
    ]


@pytest.mark.parametrize("module", ["openai", "local"])
def test_sdk_errors_map_to_provider_errors_without_secrets(module: str) -> None:
    from app.domains.ai.providers.local import adapter as local_adapter
    from app.domains.ai.providers.openai import adapter as openai_adapter

    translate = (openai_adapter if module == "openai" else local_adapter)._translate_chat_error
    for error, expected in _sdk_errors():
        mapped = translate(error)
        assert type(mapped) is expected, (error, mapped)
        assert "sk-secret" not in str(mapped)
