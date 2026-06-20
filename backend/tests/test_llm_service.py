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

from app.domains.ai.providers.errors import (
    ProviderPolicyBlockedError,
    ProviderUnavailableError,
    UnsupportedCapabilityError,
)
from app.domains.ai.providers.protocols import ChatCompletionRequest, ChatCompletionResponse
from app.domains.chat.services.llm_service import (
    LLMService,
    ParsedCitation,
    PermanentLLMServiceError,
    TransientLLMServiceError,
)


class FakeChatProvider:
    """Fake ChatCompletionProvider for unit tests."""

    def __init__(self, responses: list[ChatCompletionResponse | Exception]) -> None:
        self._responses = responses
        self.calls: list[ChatCompletionRequest] = []

    async def complete(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        self.calls.append(request)
        if not self._responses:
            raise RuntimeError("No fake response available")
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _response(
    content: str,
    model: str = "gpt-5.4-mini",
    prompt_tokens: int = 10,
    completion_tokens: int = 5,
    total_tokens: int = 15,
) -> ChatCompletionResponse:
    return ChatCompletionResponse(
        content=content,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        latency_ms=10,
    )


@pytest.mark.asyncio
async def test_generate_answer_parses_structured_output_and_metadata() -> None:
    provider = FakeChatProvider(
        responses=[
            _response(
                content=(
                    '{"answer":"Employees receive 20 days of leave.",'
                    '"not_found":false,'
                    '"citations":[{"document_id":"doc-1","chunk_id":"chunk-1",'
                    '"filename":"policy.pdf","page_number":4}]}'
                ),
                model="gpt-5.4-mini",
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150,
            )
        ]
    )
    service = LLMService(
        model_name="gpt-5.4-mini",
        retry_max_attempts=2,
        input_cost_per_million_tokens_usd=2.0,
        output_cost_per_million_tokens_usd=4.0,
        provider=provider,
    )

    result = await service.generate_answer(prompt="test prompt")

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
async def test_generate_answer_retries_invalid_json_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = FakeChatProvider(
        responses=[
            _response(content="not-json"),
            _response(content='{"answer":"Valid answer","not_found":false,"citations":[]}'),
        ]
    )
    sleep_calls: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    monkeypatch.setattr("app.domains.chat.services.llm_service.asyncio.sleep", _fake_sleep)

    service = LLMService(
        retry_max_attempts=2, retry_base_seconds=0.1, retry_max_seconds=1.0, provider=provider
    )

    result = await service.generate_answer(prompt="test prompt")

    assert result.answer == "Valid answer"
    assert result.retry_count == 1
    assert sleep_calls == [0.1]


@pytest.mark.asyncio
async def test_generate_answer_disables_json_mode_when_unsupported() -> None:
    provider = FakeChatProvider(
        responses=[
            UnsupportedCapabilityError("Model does not support JSON response_format"),
            _response(
                content='{"answer":"Fallback request worked","not_found":false,"citations":[]}'
            ),
        ]
    )
    service = LLMService(retry_max_attempts=1, provider=provider)

    result = await service.generate_answer(prompt="test prompt")

    assert len(provider.calls) == 2
    assert provider.calls[0].json_mode is True
    assert provider.calls[1].json_mode is False
    assert result.answer == "Fallback request worked"
    assert result.retry_count == 0


@pytest.mark.asyncio
async def test_generate_answer_uses_fallback_parser_on_final_attempt() -> None:
    provider = FakeChatProvider(
        responses=[
            _response(
                content='prefix {"answer":"Recovered","not_found":false,"citations":[]} suffix'
            )
        ]
    )
    service = LLMService(retry_max_attempts=1, provider=provider)

    result = await service.generate_answer(prompt="test prompt")

    assert result.answer == "Recovered"
    assert result.not_found is False
    assert result.used_fallback_parser is True


@pytest.mark.asyncio
async def test_generate_answer_retries_transient_provider_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = FakeChatProvider(
        responses=[
            ProviderUnavailableError("temporary network failure"),
            _response(
                content='{"answer":"Recovered after retry","not_found":false,"citations":[]}'
            ),
        ]
    )
    sleep_calls: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    monkeypatch.setattr("app.domains.chat.services.llm_service.asyncio.sleep", _fake_sleep)
    service = LLMService(
        retry_max_attempts=2, retry_base_seconds=0.2, retry_max_seconds=1.0, provider=provider
    )

    result = await service.generate_answer(prompt="test prompt")

    assert result.answer == "Recovered after retry"
    assert result.retry_count == 1
    assert sleep_calls == [0.2]


@pytest.mark.asyncio
async def test_generate_answer_raises_permanent_error_without_retry() -> None:
    provider = FakeChatProvider(
        responses=[
            ProviderPolicyBlockedError("content policy violation"),
        ]
    )
    service = LLMService(retry_max_attempts=3, provider=provider)

    with pytest.raises(PermanentLLMServiceError):
        await service.generate_answer(prompt="test prompt")

    assert len(provider.calls) == 1


@pytest.mark.asyncio
async def test_generate_answer_raises_after_transient_retry_exhaustion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = FakeChatProvider(
        responses=[
            ProviderUnavailableError("network failure"),
            ProviderUnavailableError("network failure"),
        ]
    )
    sleep_calls: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    monkeypatch.setattr("app.domains.chat.services.llm_service.asyncio.sleep", _fake_sleep)
    service = LLMService(
        retry_max_attempts=2, retry_base_seconds=0.3, retry_max_seconds=1.0, provider=provider
    )

    with pytest.raises(TransientLLMServiceError):
        await service.generate_answer(prompt="test prompt")

    assert sleep_calls == [0.3]
