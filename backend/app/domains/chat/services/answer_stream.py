"""Incremental answer extraction and streamed completions (R05-03).

The answer model replies with a JSON object (``answer``, ``not_found``, ``citations``).
``AnswerFieldStreamExtractor`` is fed the raw JSON text as it arrives and returns the decoded
characters of the top-level ``"answer"`` string as soon as they are complete: escapes
(``\\n``, ``\\"``, ``\\\\``, ``\\uXXXX`` and surrogate pairs) may be split across chunks,
keys may come in any order, and nothing is returned after the closing quote or for output
that is not a JSON object. Only the answer text is streamed; citations never are.

``collect_stream`` runs one provider call: it streams when the provider has ``stream()``
(else one chunk from ``complete()``), forwards answer increments, records progress for
partial usage, and closes the provider stream when the caller is cancelled.
"""

from __future__ import annotations

import math
from collections.abc import Awaitable, Callable
from contextlib import aclosing
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any

from app.domains.ai.providers.protocols import (
    ChatCompletionRequest,
    ChatCompletionResponse,
)

TextCallback = Callable[[str], Awaitable[None]]

# Rough chars-per-token ratio for usage estimates when the provider reports none.
CHARS_PER_TOKEN = 4

_SIMPLE_ESCAPES = {
    '"': '"',
    "\\": "\\",
    "/": "/",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
}
_WHITESPACE = " \t\r\n"
_REPLACEMENT = "�"

# Parser states.
_START, _KEY_WAIT, _KEY, _COLON, _VALUE, _SKIP, _ANSWER, _DONE, _DEAD = range(9)


class AnswerFieldStreamExtractor:
    """Streams the decoded top-level ``answer`` string out of raw JSON text chunks."""

    def __init__(self, field_name: str = "answer") -> None:
        self._field = field_name
        self._buf = ""
        self._state = _START
        self._key: list[str] = []
        self._skip_depth = 0
        self._skip_in_string = False
        self._skip_escape = False

    @property
    def done(self) -> bool:
        """The answer string was closed, or the output is not a JSON object."""
        return self._state in (_DONE, _DEAD)

    @property
    def failed(self) -> bool:
        return self._state == _DEAD

    def feed(self, chunk: str) -> str:
        if self.done or not chunk:
            return ""
        self._buf += chunk
        out: list[str] = []
        pos = self._run(out)
        self._buf = self._buf[pos:]
        return "".join(out)

    def _run(self, out: list[str]) -> int:
        buf = self._buf
        pos = 0
        n = len(buf)
        while pos < n and not self.done:
            state = self._state
            char = buf[pos]
            if state == _START:
                if char in _WHITESPACE:
                    pos += 1
                elif char == "{":
                    self._state = _KEY_WAIT
                    pos += 1
                else:
                    self._state = _DEAD
            elif state == _KEY_WAIT:
                if char in _WHITESPACE or char == ",":
                    pos += 1
                elif char == '"':
                    self._key = []
                    self._state = _KEY
                    pos += 1
                elif char == "}":
                    self._state = _DONE
                else:
                    self._state = _DEAD
            elif state in (_KEY, _ANSWER):
                consumed = self._read_string_char(buf, pos, self._key if state == _KEY else out)
                if consumed == 0:
                    break  # an escape is split across chunks: wait for more text
                pos += consumed
            elif state == _COLON:
                if char in _WHITESPACE:
                    pos += 1
                elif char == ":":
                    self._state = _VALUE
                    pos += 1
                else:
                    self._state = _DEAD
            elif state == _VALUE:
                if char in _WHITESPACE:
                    pos += 1
                elif char == '"' and "".join(self._key) == self._field:
                    self._state = _ANSWER
                    pos += 1
                else:
                    self._skip_depth = 0
                    self._skip_in_string = False
                    self._skip_escape = False
                    self._state = _SKIP
            else:  # _SKIP
                pos += self._skip_char(char)
        return pos

    def _read_string_char(self, buf: str, pos: int, sink: list[str]) -> int:
        """Decode one character (or escape) of a string; 0 means wait for more input."""
        char = buf[pos]
        if char == '"':
            self._state = _COLON if self._state == _KEY else _DONE
            return 1
        if char != "\\":
            sink.append(char)
            return 1
        if pos + 1 >= len(buf):
            return 0
        code = buf[pos + 1]
        if code in _SIMPLE_ESCAPES:
            sink.append(_SIMPLE_ESCAPES[code])
            return 2
        if code != "u":
            sink.append(code)  # invalid escape: keep the character, as lenient parsers do
            return 2
        high = _hex4(buf, pos + 2)
        if high is None:
            return 0 if len(buf) < pos + 6 else self._bad_escape(sink)
        if 0xD800 <= high <= 0xDBFF:
            if len(buf) < pos + 12:
                # Wait for the low surrogate unless the text after the escape cannot be one.
                tail = buf[pos + 6 : pos + 8]
                if "\\u".startswith(tail) or tail.startswith("\\u"):
                    return 0
                sink.append(_REPLACEMENT)
                return 6
            low = _hex4(buf, pos + 8) if buf[pos + 6 : pos + 8] == "\\u" else None
            if low is not None and 0xDC00 <= low <= 0xDFFF:
                sink.append(chr(0x10000 + ((high - 0xD800) << 10) + (low - 0xDC00)))
                return 12
            sink.append(_REPLACEMENT)
            return 6
        if 0xDC00 <= high <= 0xDFFF:
            sink.append(_REPLACEMENT)
            return 6
        sink.append(chr(high))
        return 6

    def _bad_escape(self, sink: list[str]) -> int:
        sink.append(_REPLACEMENT)
        return 2

    def _skip_char(self, char: str) -> int:
        """Skip one character of a value that is not the answer string."""
        if self._skip_in_string:
            if self._skip_escape:
                self._skip_escape = False
            elif char == "\\":
                self._skip_escape = True
            elif char == '"':
                self._skip_in_string = False
                if self._skip_depth == 0:
                    self._state = _KEY_WAIT
            return 1
        if char == '"':
            self._skip_in_string = True
        elif char in "{[":
            self._skip_depth += 1
        elif char in "}]":
            if self._skip_depth == 0:
                self._state = _DONE  # end of the top-level object
                return 0
            self._skip_depth -= 1
            if self._skip_depth == 0:
                self._state = _KEY_WAIT
        elif char == "," and self._skip_depth == 0:
            self._state = _KEY_WAIT
        return 1


def _hex4(buf: str, start: int) -> int | None:
    digits = buf[start : start + 4]
    if len(digits) < 4:
        return None
    try:
        return int(digits, 16)
    except ValueError:
        return None


def estimate_tokens(chars: int) -> int:
    return math.ceil(max(0, chars) / CHARS_PER_TOKEN)


@dataclass
class StreamAttempt:
    """One provider call of a (streamed) answer generation."""

    provider_key: str | None
    model: str | None
    prompt_chars: int
    completion_chars: int = 0
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cached_prompt_tokens: int | None = None

    @property
    def usage_reported(self) -> bool:
        return self.prompt_tokens is not None and self.completion_tokens is not None

    def usage(self) -> tuple[int, int, int, bool]:
        """``(prompt, completion, cached, estimated)``; estimates use chars / 4."""
        if self.usage_reported:
            assert self.prompt_tokens is not None and self.completion_tokens is not None
            return (
                self.prompt_tokens,
                self.completion_tokens,
                self.cached_prompt_tokens or 0,
                False,
            )
        return (
            estimate_tokens(self.prompt_chars),
            estimate_tokens(self.completion_chars),
            0,
            True,
        )


@dataclass
class StreamProgress:
    """Every provider call of one generation, for partial usage on cancellation."""

    attempts: list[StreamAttempt] = field(default_factory=list)

    def begin(
        self, provider_key: str | None, model: str | None, prompt_chars: int
    ) -> StreamAttempt:
        attempt = StreamAttempt(provider_key=provider_key, model=model, prompt_chars=prompt_chars)
        self.attempts.append(attempt)
        return attempt


async def collect_stream(
    provider: Any,
    request: ChatCompletionRequest,
    *,
    on_text: TextCallback,
    attempt: StreamAttempt,
) -> ChatCompletionResponse:
    """Run one call, forwarding answer increments; returns the same response shape as
    ``complete()`` (content stripped). Usage the stream does not report is estimated."""
    extractor = AnswerFieldStreamExtractor()
    stream_fn = getattr(provider, "stream", None)
    if not callable(stream_fn):
        response: ChatCompletionResponse = await provider.complete(request)
        attempt.completion_chars += len(response.content)
        attempt.prompt_tokens = response.prompt_tokens
        attempt.completion_tokens = response.completion_tokens
        increment = extractor.feed(response.content)
        if increment:
            await on_text(increment)
        return response

    started = perf_counter()
    parts: list[str] = []
    model: str | None = None
    async with aclosing(stream_fn(request)) as chunks:
        async for chunk in chunks:
            if chunk.model:
                model = chunk.model
            if chunk.prompt_tokens is not None:
                attempt.prompt_tokens = chunk.prompt_tokens
            if chunk.completion_tokens is not None:
                attempt.completion_tokens = chunk.completion_tokens
            if chunk.cached_prompt_tokens is not None:
                attempt.cached_prompt_tokens = chunk.cached_prompt_tokens
            if not chunk.text_delta:
                continue
            parts.append(chunk.text_delta)
            attempt.completion_chars += len(chunk.text_delta)
            increment = extractor.feed(chunk.text_delta)
            if increment:
                await on_text(increment)
    prompt_tokens, completion_tokens, _, estimated = attempt.usage()
    return ChatCompletionResponse(
        content="".join(parts).strip(),
        model=model or request.model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
        latency_ms=int((perf_counter() - started) * 1000),
        usage_estimated=estimated,
    )
