from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services.llm_service import (
    LLMService,
    ParsedCitation,
    PermanentLLMServiceError,
    TransientLLMServiceError,
)


@dataclass(frozen=True)
class FakeUsage:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


@dataclass(frozen=True)
class FakeResponse:
    content: str
    model: str = "gpt-5.4-mini"
    usage: FakeUsage = FakeUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0)


class FakeChatCompletionsEndpoint:
    def __init__(self, responses: list[FakeResponse | Exception]) -> None:
        self._responses = responses
        self.calls: list[dict[str, object]] = []

    async def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        if not self._responses:
            raise RuntimeError("No fake response available")
        next_response = self._responses.pop(0)
        if isinstance(next_response, Exception):
            raise next_response
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=next_response.content))],
            usage=next_response.usage,
            model=next_response.model,
        )


class FakeOpenAIClient:
    def __init__(self, responses: list[FakeResponse | Exception]) -> None:
        self.chat = SimpleNamespace(completions=FakeChatCompletionsEndpoint(responses))


@pytest.mark.asyncio
async def test_generate_answer_parses_structured_output_and_metadata() -> None:
    client = FakeOpenAIClient(
        responses=[
            FakeResponse(
                content=(
                    '{"answer":"Employees receive 20 days of leave.",'
                    '"not_found":false,'
                    '"citations":[{"document_id":"doc-1","chunk_id":"chunk-1","filename":"policy.pdf","page_number":4}]}'
                ),
                usage=FakeUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150),
            )
        ]
    )
    service = LLMService(
        model_name="gpt-5.4-mini",
        retry_max_attempts=2,
        input_cost_per_million_tokens_usd=2.0,
        output_cost_per_million_tokens_usd=4.0,
    )

    result = await service.generate_answer(
        prompt="test prompt",
        openai_client=client,
    )

    assert result.answer == "Employees receive 20 days of leave."
    assert result.not_found is False
    assert result.citations == [
        ParsedCitation(
            document_id="doc-1",
            chunk_id="chunk-1",
            filename="policy.pdf",
            page_number=4,
        )
    ]
    assert result.model_name == "gpt-5.4-mini"
    assert result.prompt_tokens == 100
    assert result.completion_tokens == 50
    assert result.total_tokens == 150
    assert result.approximate_cost_usd == Decimal("0.0004")
    assert result.latency_ms >= 0
    assert result.retry_count == 0
    assert result.used_fallback_parser is False


@pytest.mark.asyncio
async def test_generate_answer_retries_invalid_json_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeOpenAIClient(
        responses=[
            FakeResponse(
                content="not-json",
                usage=FakeUsage(prompt_tokens=10, completion_tokens=10, total_tokens=20),
            ),
            FakeResponse(
                content='{"answer":"Valid answer","not_found":false,"citations":[]}',
                usage=FakeUsage(prompt_tokens=11, completion_tokens=9, total_tokens=20),
            ),
        ]
    )
    sleep_calls: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    monkeypatch.setattr("app.services.llm_service.asyncio.sleep", _fake_sleep)

    service = LLMService(retry_max_attempts=2, retry_base_seconds=0.1, retry_max_seconds=1.0)

    result = await service.generate_answer(
        prompt="test prompt",
        openai_client=client,
    )

    assert result.answer == "Valid answer"
    assert result.retry_count == 1
    assert sleep_calls == [0.1]


@pytest.mark.asyncio
async def test_generate_answer_disables_response_format_when_unsupported_even_with_single_retry_budget() -> None:
    class ResponseFormatUnsupportedError(Exception):
        status_code = 400

    client = FakeOpenAIClient(
        responses=[
            ResponseFormatUnsupportedError("response_format is not supported"),
            FakeResponse(
                content='{"answer":"Fallback request worked","not_found":false,"citations":[]}',
                usage=FakeUsage(prompt_tokens=15, completion_tokens=5, total_tokens=20),
            ),
        ]
    )
    service = LLMService(retry_max_attempts=1)

    result = await service.generate_answer(
        prompt="test prompt",
        openai_client=client,
    )

    calls = client.chat.completions.calls
    assert len(calls) == 2
    assert calls[0]["response_format"] == {"type": "json_object"}
    assert "response_format" not in calls[1]
    assert result.answer == "Fallback request worked"
    assert result.retry_count == 0


@pytest.mark.asyncio
async def test_generate_answer_uses_fallback_parser_on_final_attempt() -> None:
    client = FakeOpenAIClient(
        responses=[
            FakeResponse(
                content='prefix {"answer":"Recovered","not_found":false,"citations":[]} suffix',
                usage=FakeUsage(prompt_tokens=20, completion_tokens=5, total_tokens=25),
            )
        ]
    )
    service = LLMService(retry_max_attempts=1)

    result = await service.generate_answer(
        prompt="test prompt",
        openai_client=client,
    )

    assert result.answer == "Recovered"
    assert result.not_found is False
    assert result.used_fallback_parser is True


@pytest.mark.asyncio
async def test_generate_answer_retries_transient_provider_error(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeOpenAIClient(
        responses=[
            OSError("temporary network failure"),
            FakeResponse(
                content='{"answer":"Recovered after retry","not_found":false,"citations":[]}',
                usage=FakeUsage(prompt_tokens=12, completion_tokens=8, total_tokens=20),
            ),
        ]
    )
    sleep_calls: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    monkeypatch.setattr("app.services.llm_service.asyncio.sleep", _fake_sleep)
    service = LLMService(retry_max_attempts=2, retry_base_seconds=0.2, retry_max_seconds=1.0)

    result = await service.generate_answer(
        prompt="test prompt",
        openai_client=client,
    )

    assert result.answer == "Recovered after retry"
    assert result.retry_count == 1
    assert sleep_calls == [0.2]


@pytest.mark.asyncio
async def test_generate_answer_raises_permanent_error_without_retry() -> None:
    class InvalidRequestError(Exception):
        status_code = 400
        code = "invalid_request_error"

    client = FakeOpenAIClient(
        responses=[
            InvalidRequestError("invalid input"),
        ]
    )
    service = LLMService(retry_max_attempts=3)

    with pytest.raises(PermanentLLMServiceError):
        await service.generate_answer(prompt="test prompt", openai_client=client)

    assert len(client.chat.completions.calls) == 1


@pytest.mark.asyncio
async def test_generate_answer_raises_after_transient_retry_exhaustion(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeOpenAIClient(
        responses=[
            OSError("temporary network failure"),
            OSError("temporary network failure"),
        ]
    )
    sleep_calls: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    monkeypatch.setattr("app.services.llm_service.asyncio.sleep", _fake_sleep)
    service = LLMService(retry_max_attempts=2, retry_base_seconds=0.3, retry_max_seconds=1.0)

    with pytest.raises(TransientLLMServiceError):
        await service.generate_answer(prompt="test prompt", openai_client=client)

    assert sleep_calls == [0.3]
