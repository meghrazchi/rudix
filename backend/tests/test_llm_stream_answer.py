"""LLMService.stream_answer (R05-03): same result as generate_answer, reset signals."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import pytest

from app.core.config import settings
from app.domains.ai.profile.schemas import ProfileSource, ResolvedTaskProfile, TaskType
from app.domains.ai.providers.errors import (
    ProviderTimeoutError,
    ProviderUnavailableError,
    UnsupportedCapabilityError,
)
from app.domains.ai.providers.factory import ProviderFactory
from app.domains.ai.providers.protocols import (
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatCompletionResponse,
)
from app.domains.chat.services.answer_stream import StreamProgress
from app.domains.chat.services.llm_service import LLMService, PermanentLLMServiceError

pytestmark = [pytest.mark.asyncio]


class _FailAfter(Exception):
    """Script entry: stream ``text`` then raise ``error`` mid-stream."""

    def __init__(self, text: str, error: Exception) -> None:
        super().__init__("fail after")
        self.text = text
        self.error = error


class _ScriptedStreamProvider:
    def __init__(self, script: list[Any], *, model_name: str = "stub-model") -> None:
        self._script = script
        self._model_name = model_name
        self.requests: list[ChatCompletionRequest] = []

    async def complete(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        raise AssertionError("complete() is not used when stream() exists")

    async def stream(self, request: ChatCompletionRequest) -> AsyncIterator[ChatCompletionChunk]:
        self.requests.append(request)
        item = self._script.pop(0)
        if isinstance(item, Exception) and not isinstance(item, _FailAfter):
            raise item
        text = item.text if isinstance(item, _FailAfter) else str(item)
        for index in range(0, len(text), 4):
            yield ChatCompletionChunk(text_delta=text[index : index + 4])
        if isinstance(item, _FailAfter):
            raise item.error
        yield ChatCompletionChunk(prompt_tokens=20, completion_tokens=10, model=self._model_name)


class _CompleteOnly:
    def __init__(self, content: str) -> None:
        self._content = content

    async def complete(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        return ChatCompletionResponse(
            content=self._content,
            model="stub-model",
            prompt_tokens=20,
            completion_tokens=10,
            total_tokens=30,
            latency_ms=1,
        )


def _answer(text: str, **extra: Any) -> str:
    return json.dumps({"answer": text, "not_found": False, "citations": [], **extra})


async def _no_sleep(_seconds: float) -> None:
    return None


class _Recorder:
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    async def on_text(self, text: str) -> None:
        self.events.append(("text", text))

    async def on_reset(self, reason: str) -> None:
        self.events.append(("reset", reason))

    def text(self) -> str:
        return "".join(value for kind, value in self.events if kind == "text")

    def resets(self) -> list[str]:
        return [value for kind, value in self.events if kind == "reset"]


async def test_stream_answer_matches_generate_answer() -> None:
    content = _answer(
        "  Same answer.  ",
        citations=[{"document_id": "d", "chunk_id": "c", "text_snippet": "s"}],
    )
    recorder = _Recorder()
    streamed = await LLMService(provider=_ScriptedStreamProvider([content])).stream_answer(
        prompt="Question?", on_text=recorder.on_text, on_reset=recorder.on_reset
    )
    generated = await LLMService(provider=_CompleteOnly(content)).generate_answer(
        prompt="Question?"
    )

    assert recorder.text() == "  Same answer.  " and recorder.resets() == []
    for name in (
        "answer",
        "not_found",
        "citations",
        "model_name",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "approximate_cost_usd",
        "retry_count",
        "used_fallback_parser",
        "provider_key",
        "fallback_used",
        "usage_estimated",
    ):
        assert getattr(streamed, name) == getattr(generated, name), name


async def test_provider_without_stream_falls_back_to_one_chunk() -> None:
    recorder = _Recorder()
    result = await LLMService(provider=_CompleteOnly(_answer("Whole."))).stream_answer(
        prompt="Question?", on_text=recorder.on_text
    )
    assert recorder.events == [("text", "Whole.")]
    assert result.answer == "Whole." and result.usage_estimated is False


async def test_parse_retry_after_streamed_text_signals_reset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.domains.chat.services.llm_service.asyncio.sleep", _no_sleep)
    provider = _ScriptedStreamProvider(['{"answer": "broken', _answer("Fixed.")])
    recorder = _Recorder()
    result = await LLMService(provider=provider, retry_max_attempts=2).stream_answer(
        prompt="Question?", on_text=recorder.on_text, on_reset=recorder.on_reset
    )
    assert recorder.events[0] == ("text", "brok")
    assert recorder.resets() == ["retry"]
    after = recorder.events[recorder.events.index(("reset", "retry")) + 1 :]
    assert "".join(value for _, value in after) == "Fixed."
    assert result.answer == "Fixed." and result.retry_count == 1


async def test_no_reset_when_nothing_was_streamed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.domains.chat.services.llm_service.asyncio.sleep", _no_sleep)
    provider = _ScriptedStreamProvider(
        [UnsupportedCapabilityError("no json mode"), ProviderTimeoutError("t"), _answer("Ok.")]
    )
    recorder = _Recorder()
    result = await LLMService(provider=provider, retry_max_attempts=2).stream_answer(
        prompt="Question?", on_text=recorder.on_text, on_reset=recorder.on_reset
    )
    assert recorder.resets() == []
    assert result.answer == "Ok."
    assert [r.json_mode for r in provider.requests] == [True, False, False]


async def test_retry_and_fallback_resets_and_attempt_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.domains.chat.services.llm_service.asyncio.sleep", _no_sleep)
    monkeypatch.setattr(settings, "feature_enable_provider_fallback", True)
    primary = _ScriptedStreamProvider(
        [
            _FailAfter(_answer("first try"), ProviderTimeoutError("cut")),
            _FailAfter(_answer("second"), ProviderUnavailableError("down")),
        ]
    )
    fallback = _ScriptedStreamProvider([_answer("From the fallback.")], model_name="fb")
    factory = ProviderFactory()
    factory._chat_providers["local"] = primary
    factory._chat_providers["openai"] = fallback
    monkeypatch.setattr("app.domains.ai.providers.factory.default_provider_factory", factory)
    service = LLMService(retry_max_attempts=2)
    monkeypatch.setattr(service, "_provider", None)
    profile = ResolvedTaskProfile(
        task_type=TaskType.chat,
        provider_type="local",
        base_model="local-model",
        context_window=None,
        json_mode=True,
        streaming=True,
        fallback_provider_key="openai",
        source=ProfileSource.org_profile,
        version=1,
    )
    recorder = _Recorder()
    progress = StreamProgress()

    result = await service.stream_answer(
        prompt="Question?",
        resolved_profile=profile,
        on_text=recorder.on_text,
        on_reset=recorder.on_reset,
        progress=progress,
    )

    assert recorder.resets() == ["retry", "fallback"]
    after = recorder.events[recorder.events.index(("reset", "fallback")) + 1 :]
    assert "".join(value for _, value in after) == "From the fallback."
    assert result.answer == "From the fallback." and result.fallback_used is True
    assert result.provider_key == "openai" and result.model_name == "fb"
    assert [a.provider_key for a in progress.attempts] == ["local", "local", "openai"]
    assert not progress.attempts[0].usage_reported
    assert progress.attempts[2].usage() == (20, 10, 0, False)


async def test_stream_answer_honours_disabled_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "feature_enable_llm", False)
    recorder = _Recorder()
    with pytest.raises(PermanentLLMServiceError):
        await LLMService(provider=_CompleteOnly(_answer("x"))).stream_answer(
            prompt="Question?", on_text=recorder.on_text
        )
