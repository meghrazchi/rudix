"""Concurrent rerank batches (R05-04): bounded by RERANK_MAX_CONCURRENT_BATCHES, merged in
batch order, output equal to a sequential run. Counted with asyncio events, no timing."""

from __future__ import annotations

import asyncio
import json
import re

import pytest

from app.core.config import settings
from app.domains.ai.providers.protocols import ChatCompletionRequest, ChatCompletionResponse
from app.domains.chat.services.rerank_service import RerankCandidate, RerankService, RerankSettings

pytestmark = [pytest.mark.asyncio]

_KEY_RE = re.compile(r"^key: (\S+)$", re.MULTILINE)


def _score(key: str) -> float:
    # Deterministic and order-independent: reverses the retrieval order.
    return round(1.0 - int(key.removeprefix("k")) / 100, 4)


class _GatedProvider:
    """Holds every call until ``limit`` calls are in flight (or all calls have started)."""

    def __init__(self, *, limit: int, total_batches: int, fail_key: str | None = None) -> None:
        self.limit = limit
        self.total_batches = total_batches
        self.fail_key = fail_key
        self.in_flight = 0
        self.max_in_flight = 0
        self.started = 0
        self.release = asyncio.Event()

    async def complete(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        keys = _KEY_RE.findall(request.prompt)
        self.in_flight += 1
        self.started += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        if self.in_flight >= self.limit or self.started >= self.total_batches:
            self.release.set()
        try:
            await self.release.wait()
            await asyncio.sleep(0)
            if self.fail_key is not None and self.fail_key in keys:
                raise ValueError("scripted rerank failure")
            content = json.dumps({"scores": [{"key": k, "score": _score(k)} for k in keys]})
        finally:
            self.in_flight -= 1
        return ChatCompletionResponse(
            content=content,
            model="rerank-model",
            prompt_tokens=10,
            completion_tokens=2,
            total_tokens=12,
            latency_ms=1,
        )


class _Factory:
    def __init__(self, provider: _GatedProvider) -> None:
        self.provider = provider

    def get_chat_provider(self, provider_key: str | None = None) -> _GatedProvider:
        del provider_key
        return self.provider


def _candidates(count: int) -> list[RerankCandidate]:
    return [
        RerankCandidate(
            key=f"k{index}", text=f"text {index}", similarity_score=0.9, original_rank=index
        )
        for index in range(1, count + 1)
    ]


async def _rerank(provider: _GatedProvider, count: int) -> object:
    service = RerankService(provider_factory=_Factory(provider))
    return await service.rerank(
        query="q",
        candidates=_candidates(count),
        enabled=True,
        final_top_k=count,
        settings_override=RerankSettings(
            enabled=True,
            provider_key="p",
            model_name="rerank-model",
            batch_size=2,
            max_input_candidates=count,
        ),
    )


@pytest.mark.parametrize("limit", [1, 2, 3])
async def test_max_in_flight_batches_equals_the_setting(
    monkeypatch: pytest.MonkeyPatch, limit: int
) -> None:
    monkeypatch.setattr(settings, "rerank_max_concurrent_batches", limit)
    provider = _GatedProvider(limit=limit, total_batches=6)

    result = await _rerank(provider, 12)

    assert provider.max_in_flight == limit
    assert result.diagnostics.batch_count == 6  # type: ignore[attr-defined]


async def test_concurrent_output_equals_sequential(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "rerank_max_concurrent_batches", 1)
    sequential = await _rerank(_GatedProvider(limit=1, total_batches=5), 10)
    monkeypatch.setattr(settings, "rerank_max_concurrent_batches", 4)
    concurrent = await _rerank(_GatedProvider(limit=4, total_batches=5), 10)

    def view(result: object) -> list[tuple[str, float | None, int | None, int]]:
        return [
            (c.key, c.rerank_score, c.rerank_rank, c.final_rank)
            for c in result.candidates  # type: ignore[attr-defined]
        ]

    assert view(concurrent) == view(sequential)
    assert [c[0] for c in view(concurrent)] == [f"k{i}" for i in range(1, 11)]
    seq_diag, con_diag = sequential.diagnostics, concurrent.diagnostics  # type: ignore[attr-defined]
    assert (con_diag.batch_count, con_diag.prompt_tokens, con_diag.completion_tokens) == (
        seq_diag.batch_count,
        seq_diag.prompt_tokens,
        seq_diag.completion_tokens,
    )
    assert len(con_diag.batch_usages) == 5


async def test_a_failed_batch_falls_back_to_the_original_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "rerank_max_concurrent_batches", 2)
    provider = _GatedProvider(limit=2, total_batches=3, fail_key="k3")

    result = await _rerank(provider, 6)

    diagnostics = result.diagnostics  # type: ignore[attr-defined]
    assert diagnostics.fallback_used is True and diagnostics.fallback_reason == "ValueError"
    assert [c.key for c in result.candidates] == ["k1", "k2", "k3", "k4", "k5", "k6"]  # type: ignore[attr-defined]
    # Tokens count the batches that were scored; the failed one is not among them.
    assert diagnostics.prompt_tokens == 10 * (diagnostics.batch_count - 1)


@pytest.mark.parametrize(
    ("error", "reason"),
    [(TimeoutError(), "timeout"), (RuntimeError("provider bug"), "RuntimeError")],
)
async def test_timeout_and_unexpected_errors_fall_back_with_counted_batches(
    monkeypatch: pytest.MonkeyPatch, error: Exception, reason: str
) -> None:
    monkeypatch.setattr(settings, "rerank_max_concurrent_batches", 2)

    class _Raising(_GatedProvider):
        async def complete(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
            if "key: k1\n" in request.prompt:
                raise error
            return await super().complete(request)

    result = await _rerank(_Raising(limit=1, total_batches=2), 4)

    diagnostics = result.diagnostics  # type: ignore[attr-defined]
    assert diagnostics.fallback_used is True and diagnostics.fallback_reason == reason
    assert 1 <= diagnostics.batch_count <= 2
    assert diagnostics.prompt_tokens == 10 * (diagnostics.batch_count - 1)
