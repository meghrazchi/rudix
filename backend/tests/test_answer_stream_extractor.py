"""AnswerFieldStreamExtractor and collect_stream (R05-03).

The property test splits sample model outputs at every index (and into single characters)
and checks the concatenated increments equal ``json.loads(output)["answer"]``.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import pytest

from app.domains.ai.providers.protocols import (
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatCompletionResponse,
)
from app.domains.chat.services.answer_stream import (
    AnswerFieldStreamExtractor,
    StreamAttempt,
    StreamProgress,
    collect_stream,
    estimate_tokens,
)

_SAMPLES: list[str] = [
    json.dumps({"answer": "Twenty days of leave.", "not_found": False, "citations": []}),
    # Escapes of every kind, including a surrogate pair written as two \u escapes.
    json.dumps(
        {
            "answer": 'Line one\nLine "two"\t\\ back / slash é \U0001f600 end\r\b\f',
            "not_found": False,
            "citations": [],
        }
    ),
    # Raw (non-ASCII) characters, not escaped.
    json.dumps(
        {"answer": "Grüße — 日本語 \U0001f680", "not_found": False, "citations": []},
        ensure_ascii=False,
    ),
    # The answer is not the first key; earlier values contain braces, quotes, and arrays.
    json.dumps(
        {
            "not_found": False,
            "citations": [
                {"document_id": "d", "chunk_id": "c", "text_snippet": 'a "q" {x} [y] \\'}
            ],
            "meta": {"answer": "nested, not top level", "n": [1, 2, {"k": None}]},
            "answer": "The real answer.",
        }
    ),
    # Whitespace around tokens and an empty answer.
    '  {\n  "answer" :  "",\n  "not_found": true, "citations": [] }\n',
    # A top-level string value (with escapes) before the answer.
    '{"id": "x\\"y\\\\", "answer": "after a string"}',
    # Numbers and literals before the answer.
    '{"score": -1.5e3, "ok": true, "none": null, "answer": "after literals"}',
]


def _expected(output: str) -> str:
    return str(json.loads(output)["answer"])


def _run(chunks: list[str]) -> str:
    extractor = AnswerFieldStreamExtractor()
    return "".join(extractor.feed(chunk) for chunk in chunks)


@pytest.mark.parametrize("output", _SAMPLES)
def test_every_split_point_yields_the_decoded_answer(output: str) -> None:
    expected = _expected(output)
    assert _run([output]) == expected
    assert _run(list(output)) == expected
    for index in range(len(output) + 1):
        assert _run([output[:index], output[index:]]) == expected, index


@pytest.mark.parametrize("output", _SAMPLES)
def test_every_pair_of_split_points_yields_the_decoded_answer(output: str) -> None:
    expected = _expected(output)
    step = max(1, len(output) // 40)
    for first in range(0, len(output) + 1, step):
        for second in range(first, len(output) + 1, step):
            parts = [output[:first], output[first:second], output[second:]]
            assert _run(parts) == expected, (first, second)


def test_increments_arrive_before_the_answer_closes() -> None:
    extractor = AnswerFieldStreamExtractor()
    assert extractor.feed('{"answer": "Hel') == "Hel"
    assert extractor.feed("lo wor") == "lo wor"
    assert not extractor.done
    assert extractor.feed('ld", "not_found": false, "answer": "ignored"}') == "ld"
    assert extractor.done and not extractor.failed
    assert extractor.feed("more") == ""


def test_escape_split_across_chunks_waits_for_the_rest() -> None:
    extractor = AnswerFieldStreamExtractor()
    assert extractor.feed('{"answer": "a\\') == "a"
    assert extractor.feed("u00") == ""
    assert extractor.feed("e9b") == "éb"
    assert extractor.feed("\\ud83d") == ""  # high surrogate: wait for the low half
    assert extractor.feed("\\ude00") == "\U0001f600"
    assert extractor.feed('"}') == ""


@pytest.mark.parametrize(
    "output",
    [
        "I could not find this in the documents.",
        '```json\n{"answer": "fenced"}\n```',
        "",
        "[1, 2]",
        '{"not_found": true, "citations": []}',
        '{"answer": null, "not_found": true}',
        '{"answer": 42}',
        '{answer: "unquoted key"}',
    ],
)
def test_non_json_or_missing_answer_emits_nothing(output: str) -> None:
    assert _run([output]) == ""
    assert _run(list(output)) == ""


def test_invalid_json_after_the_object_starts_stops_streaming() -> None:
    extractor = AnswerFieldStreamExtractor()
    assert extractor.feed('{"a" 1, "answer": "x"}') == ""
    assert extractor.failed


def test_lone_surrogates_and_bad_escapes_become_replacement_characters() -> None:
    assert _run(['{"answer": "x\\ud83dy"}']) == "x�y"
    assert _run(['{"answer": "x\\ud83d', '\\u0041"}']) == "x�A"
    assert _run(['{"answer": "\\ude00"}']) == "�"
    assert _run(['{"answer": "\\uZZZZ!"}']) == "�ZZZZ!"
    assert _run(['{"answer": "\\q"}']) == "q"


def test_attempt_usage_prefers_reported_tokens() -> None:
    reported = StreamAttempt(provider_key="p", model="m", prompt_chars=400, completion_chars=40)
    reported.prompt_tokens, reported.completion_tokens, reported.cached_prompt_tokens = 9, 3, 2
    assert reported.usage() == (9, 3, 2, False)
    estimated = StreamAttempt(provider_key="p", model="m", prompt_chars=401, completion_chars=8)
    assert estimated.usage() == (101, 2, 0, True)
    assert estimate_tokens(0) == 0 and estimate_tokens(-3) == 0


class _CompleteOnly:
    async def complete(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        return ChatCompletionResponse(
            content='{"answer": "whole", "not_found": false, "citations": []}',
            model="m",
            prompt_tokens=5,
            completion_tokens=4,
            total_tokens=9,
            latency_ms=1,
        )


class _Streaming:
    def __init__(self, chunks: list[ChatCompletionChunk]) -> None:
        self._chunks = chunks
        self.closed = False

    async def stream(self, request: ChatCompletionRequest) -> AsyncIterator[ChatCompletionChunk]:
        try:
            for chunk in self._chunks:
                yield chunk
        finally:
            self.closed = True


async def test_collect_stream_falls_back_to_one_chunk_from_complete() -> None:
    texts: list[str] = []

    async def on_text(text: str) -> None:
        texts.append(text)

    attempt = StreamProgress().begin("p", "m", 10)
    response = await collect_stream(
        _CompleteOnly(), ChatCompletionRequest(prompt="q"), on_text=on_text, attempt=attempt
    )
    assert texts == ["whole"]
    assert response.prompt_tokens == 5 and not response.usage_estimated
    assert attempt.usage() == (5, 4, 0, False)


async def test_collect_stream_uses_usage_from_the_last_chunk() -> None:
    provider = _Streaming(
        [
            ChatCompletionChunk(text_delta=' {"answer": "a', model="m-1"),
            ChatCompletionChunk(text_delta='b"} '),
            ChatCompletionChunk(finish_reason="stop"),
            ChatCompletionChunk(prompt_tokens=11, completion_tokens=6, cached_prompt_tokens=4),
        ]
    )
    texts: list[str] = []

    async def on_text(text: str) -> None:
        texts.append(text)

    attempt = StreamProgress().begin("p", "m", 10)
    response = await collect_stream(
        provider, ChatCompletionRequest(prompt="q", model="m"), on_text=on_text, attempt=attempt
    )
    assert texts == ["a", "b"]
    assert response.content == '{"answer": "ab"}'
    assert (response.model, response.prompt_tokens, response.completion_tokens) == ("m-1", 11, 6)
    assert response.total_tokens == 17 and not response.usage_estimated
    assert attempt.usage() == (11, 6, 4, False)
    assert provider.closed


async def test_collect_stream_estimates_usage_when_none_is_reported() -> None:
    provider = _Streaming([ChatCompletionChunk(text_delta='{"answer": "12345678"}')])

    async def on_text(text: str) -> None:
        return None

    attempt = StreamProgress().begin("p", "m", 40)
    response = await collect_stream(
        provider, ChatCompletionRequest(prompt="q", model="m"), on_text=on_text, attempt=attempt
    )
    assert response.usage_estimated
    assert (response.prompt_tokens, response.completion_tokens) == (10, 6)
    assert response.model == "m"
