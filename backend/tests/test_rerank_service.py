from __future__ import annotations

import json

import pytest

from app.core.config import settings
from app.domains.ai.providers.errors import ProviderTimeoutError
from app.domains.ai.providers.protocols import ChatCompletionRequest, ChatCompletionResponse
from app.domains.chat.services.rerank_service import (
    RerankCandidate,
    RerankService,
    RerankSettings,
)


class _FakeRerankProvider:
    def __init__(self, responses: list[str | Exception]) -> None:
        self._responses = list(responses)
        self.calls: list[ChatCompletionRequest] = []

    async def complete(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        self.calls.append(request)
        if not self._responses:
            raise AssertionError("unexpected rerank provider call")
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return ChatCompletionResponse(
            content=response,
            model=request.model or settings.openai_llm_model,
            prompt_tokens=18,
            completion_tokens=6,
            total_tokens=24,
            latency_ms=4,
        )


class _FakeProviderFactory:
    def __init__(self, provider: _FakeRerankProvider) -> None:
        self.provider = provider
        self.requested_keys: list[str | None] = []

    def get_chat_provider(self, provider_key: str | None = None) -> _FakeRerankProvider:
        self.requested_keys.append(provider_key)
        return self.provider


def _candidate(
    key: str,
    *,
    similarity_score: float,
    original_rank: int,
) -> RerankCandidate:
    return RerankCandidate(
        key=key,
        text=f"{key} text",
        similarity_score=similarity_score,
        original_rank=original_rank,
    )


@pytest.mark.asyncio
async def test_rerank_disabled_returns_original_order_without_scores() -> None:
    service = RerankService(default_provider_key="rerank-provider")
    candidates = [
        _candidate("a", similarity_score=0.91, original_rank=1),
        _candidate("b", similarity_score=0.82, original_rank=2),
        _candidate("c", similarity_score=0.77, original_rank=3),
    ]

    result = await service.rerank(
        query="What is the annual leave policy?",
        candidates=candidates,
        enabled=False,
        final_top_k=2,
    )

    assert [item.key for item in result.candidates] == ["a", "b"]
    assert [item.final_rank for item in result.candidates] == [1, 2]
    assert all(item.rerank_score is None for item in result.candidates)
    assert all(item.rerank_rank is None for item in result.candidates)
    assert result.diagnostics.enabled is False
    assert result.diagnostics.fallback_used is False
    assert result.diagnostics.batch_count == 0


@pytest.mark.asyncio
async def test_rerank_provider_reorders_chunks_and_records_diagnostics() -> None:
    provider = _FakeRerankProvider(
        responses=[
            json.dumps(
                {
                    "scores": [
                        {"key": "b", "score": 0.91},
                        {"key": "c", "score": 0.85},
                    ]
                }
            ),
            json.dumps({"scores": [{"key": "a", "score": 0.32}]}),
        ]
    )
    service = RerankService(provider_factory=_FakeProviderFactory(provider))
    candidates = [
        _candidate("a", similarity_score=0.41, original_rank=1),
        _candidate("b", similarity_score=0.93, original_rank=2),
        _candidate("c", similarity_score=0.62, original_rank=3),
    ]

    result = await service.rerank(
        query="Which chunk answers the question best?",
        candidates=candidates,
        enabled=True,
        final_top_k=3,
        settings_override=RerankSettings(
            enabled=True,
            provider_key="rerank-provider",
            model_name="rerank-model",
            batch_size=2,
            max_input_candidates=3,
            max_candidate_chars=256,
        ),
    )

    assert [item.key for item in result.candidates] == ["b", "c", "a"]
    assert [item.rerank_rank for item in result.candidates] == [1, 2, 3]
    assert [item.final_rank for item in result.candidates] == [1, 2, 3]
    assert [item.original_rank for item in result.candidates] == [2, 3, 1]
    assert [item.rerank_score for item in result.candidates] == pytest.approx(
        [0.91, 0.85, 0.32]
    )
    assert result.diagnostics.enabled is True
    assert result.diagnostics.provider_key == "rerank-provider"
    assert result.diagnostics.model_name == "rerank-model"
    assert result.diagnostics.batch_count == 2
    assert result.diagnostics.requested_count == 3
    assert result.diagnostics.reranked_count == 3
    assert result.diagnostics.selected_count == 3
    assert result.diagnostics.prompt_tokens == 36
    assert result.diagnostics.completion_tokens == 12
    assert result.diagnostics.total_tokens == 48
    assert result.diagnostics.fallback_used is False
    assert provider.calls[0].model == "rerank-model"
    assert provider.calls[0].json_mode is True
    assert provider.calls[0].system_message


@pytest.mark.asyncio
async def test_rerank_falls_back_when_provider_times_out() -> None:
    provider = _FakeRerankProvider(responses=[ProviderTimeoutError("timed out")])
    service = RerankService(provider_factory=_FakeProviderFactory(provider))
    candidates = [
        _candidate("a", similarity_score=0.91, original_rank=1),
        _candidate("b", similarity_score=0.82, original_rank=2),
        _candidate("c", similarity_score=0.77, original_rank=3),
    ]

    result = await service.rerank(
        query="What is the annual leave policy?",
        candidates=candidates,
        enabled=True,
        final_top_k=2,
        settings_override=RerankSettings(
            enabled=True,
            provider_key="rerank-provider",
            model_name="rerank-model",
            batch_size=2,
            max_input_candidates=3,
            max_candidate_chars=256,
        ),
    )

    assert [item.key for item in result.candidates] == ["a", "b"]
    assert all(item.rerank_score is None for item in result.candidates)
    assert all(item.rerank_rank is None for item in result.candidates)
    assert result.diagnostics.fallback_used is True
    assert result.diagnostics.fallback_reason == "ProviderTimeoutError"
    assert result.diagnostics.batch_count == 1
    assert result.diagnostics.selected_count == 2
    assert provider.calls[0].prompt.startswith("You are reranking retrieved document chunks")
