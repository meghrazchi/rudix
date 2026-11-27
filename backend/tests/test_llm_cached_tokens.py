"""Cached prompt tokens (R05-06): read from the OpenAI usage, counted per provider and
model, and recorded on the answer result and in the token ledger."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from test_llm_breaker import ANSWER, ScriptedProvider, _cached

from app.application.chat.pipeline.ledger import TokenLedger
from app.application.chat.pipeline.stages._ledger import record_llm_results
from app.core.config import settings
from app.domains.ai.providers.openai.adapter import OpenAIChatProvider
from app.domains.ai.providers.openai.streaming import cached_prompt_tokens, parse_stream_chunk
from app.domains.ai.providers.protocols import ChatCompletionRequest
from app.domains.chat.services.llm_service import LLMService

pytestmark = pytest.mark.asyncio


async def test_openai_adapter_reads_cached_prompt_tokens() -> None:
    usage = SimpleNamespace(
        prompt_tokens=100,
        completion_tokens=5,
        total_tokens=105,
        prompt_tokens_details=SimpleNamespace(cached_tokens=64),
    )
    completion = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=ANSWER % "a"))],
        model="gpt",
        usage=usage,
    )

    async def create(**_kwargs: object) -> Any:
        return completion

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    provider = OpenAIChatProvider(client=client, model_name="gpt")
    response = await provider.complete(ChatCompletionRequest(prompt="q"))
    assert response.cached_prompt_tokens == 64

    assert cached_prompt_tokens(None) == 0
    assert cached_prompt_tokens(SimpleNamespace(prompt_tokens=1)) == 0
    chunk = parse_stream_chunk(SimpleNamespace(choices=[], usage=usage, model="gpt"))
    assert chunk.cached_prompt_tokens == 64


async def test_cached_tokens_reach_the_answer_result_and_the_ledger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = ScriptedProvider("x", cached=12)
    service = LLMService(provider=provider)  # type: ignore[arg-type]
    before = _cached(settings.llm_default_provider, service.model_name)
    result = await service.generate_answer(prompt="q")
    assert result.cached_prompt_tokens == 12
    assert _cached(settings.llm_default_provider, service.model_name) == before + 12

    streamed = await service.stream_answer(prompt="q", on_text=_ignore)
    assert streamed.cached_prompt_tokens == 12

    ctx = SimpleNamespace(ledger=TokenLedger())
    record_llm_results(ctx, [result])  # type: ignore[arg-type]
    assert ctx.ledger.totals().cached_tokens == 12


async def _ignore(_text: str) -> None:
    return None
