"""Shared helpers for streamed OpenAI-wire chat completions (R05-03).

Used by ``OpenAIChatProvider`` and ``OpenAICompatibleChatProvider``: build the request
payload, turn one ``chat.completion.chunk`` into a ``ChatCompletionChunk``, and close the
provider stream when the consumer stops early (cancellation).
"""

from __future__ import annotations

from typing import Any

from app.domains.ai.providers.protocols import ChatCompletionChunk, ChatCompletionRequest


def build_chat_payload(
    request: ChatCompletionRequest, *, model: str, json_mode: bool
) -> dict[str, object]:
    payload: dict[str, object] = {
        "model": model,
        "messages": [
            {"role": "system", "content": request.system_message},
            {"role": "user", "content": request.prompt},
        ],
        "temperature": request.temperature,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    if request.max_tokens is not None:
        payload["max_tokens"] = request.max_tokens
    return payload


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return int(value)


def _cached_tokens(usage: Any) -> int | None:
    details = getattr(usage, "prompt_tokens_details", None)
    if details is None:
        return None
    return _optional_int(getattr(details, "cached_tokens", None))


def cached_prompt_tokens(usage: Any) -> int:
    """``usage.prompt_tokens_details.cached_tokens`` of a completion; 0 when absent."""
    if usage is None:
        return 0
    return max(0, _cached_tokens(usage) or 0)


def parse_stream_chunk(event: Any) -> ChatCompletionChunk:
    """One wire chunk as a ``ChatCompletionChunk``; a usage-only chunk has no choices."""
    text = ""
    finish_reason: str | None = None
    choices = getattr(event, "choices", None) or []
    if choices:
        choice = choices[0]
        delta = getattr(choice, "delta", None)
        content = getattr(delta, "content", None) if delta is not None else None
        if isinstance(content, str):
            text = content
        reason = getattr(choice, "finish_reason", None)
        finish_reason = str(reason) if reason else None
    usage = getattr(event, "usage", None)
    prompt_tokens = completion_tokens = cached = None
    if usage is not None:
        prompt_tokens = _optional_int(getattr(usage, "prompt_tokens", None))
        completion_tokens = _optional_int(getattr(usage, "completion_tokens", None))
        cached = _cached_tokens(usage)
    model = getattr(event, "model", None)
    return ChatCompletionChunk(
        text_delta=text,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cached_prompt_tokens=cached,
        model=str(model) if model else None,
        finish_reason=finish_reason,
    )


async def close_stream(stream: Any) -> None:
    """Close an SDK stream (``AsyncStream.close``) or an async generator (``aclose``)."""
    closer = getattr(stream, "close", None) or getattr(stream, "aclose", None)
    if closer is None:
        return
    result = closer()
    if hasattr(result, "__await__"):
        await result
