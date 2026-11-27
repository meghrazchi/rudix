"""R05-07: the chat usage event and the token quota carry every provider call of a run.

All auxiliary stages are on and the stub provider returns known usage per prompt kind, so
the stored usage equals the sum of the stubbed calls, and ``QuotaType.tokens`` usage equals
the total.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest
from chat_aux_support import (
    AUX_RESPONDERS,
    EXPECTED_AUX_KINDS,
    ask_aux_questions,
    enable_all_aux_stages,
    install_chat_provider,
)
from chat_golden_providers import _KIND_TOKENS, RecordingChatProvider
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from test_chat_query_api import chat_query_client  # noqa: F401  (pytest fixture re-export)

from app.application.chat.pipeline.ledger import TokenLedger
from app.application.chat.pipeline.stages._ledger import ledger_metadata
from app.core import metrics
from app.core.config import settings
from app.models.quotas import OrgQuotaUsage
from app.models.usage import UsageEvent

EMBEDDING_TOKENS_PER_CALL = 7  # _FakeEmbeddingProvider


@pytest.mark.asyncio
async def test_usage_event_equals_sum_of_stubbed_calls_with_all_stages_on(
    chat_query_client: AsyncClient,  # noqa: F811
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enable_all_aux_stages(monkeypatch)
    provider = RecordingChatProvider(responders=AUX_RESPONDERS)
    embed = install_chat_provider(monkeypatch, provider, provider_key=settings.llm_default_provider)
    recorded: list[tuple[str, str, int]] = []
    monkeypatch.setattr(metrics, "is_metrics_enabled", lambda: True)
    original = metrics.CHAT_TOKENS_TOTAL.labels

    def _labels(**labels: str) -> object:
        counter = original(**labels)

        class _Spy:
            def inc(self, amount: float = 1) -> None:
                recorded.append((labels["stage"], labels["kind"], int(amount)))
                counter.inc(amount)

        return _Spy()

    monkeypatch.setattr(metrics.CHAT_TOKENS_TOTAL, "labels", _labels)

    _payloads, organization_id = await ask_aux_questions(
        client=chat_query_client, db_session=db_session, provider=provider
    )

    kinds = [kind for kind, _ in provider.calls]
    assert EXPECTED_AUX_KINDS <= set(kinds), kinds
    expected_prompt = sum(_KIND_TOKENS[k][0] for k in kinds)
    expected_prompt += EMBEDDING_TOKENS_PER_CALL * len(embed.calls)
    expected_completion = sum(_KIND_TOKENS[k][1] for k in kinds)
    assert len(embed.calls) > 2  # sub-queries from decomposition are embedded too

    events = list(
        (
            await db_session.execute(
                select(UsageEvent).where(UsageEvent.event_type == "chat.completion")
            )
        )
        .scalars()
        .all()
    )
    assert len(events) == 2
    assert sum(e.input_tokens for e in events) == expected_prompt
    assert sum(e.output_tokens for e in events) == expected_completion

    stages: set[str] = set()
    for event in events:
        ledger = event.metadata_json["token_ledger"]
        assert sum(entry["prompt_tokens"] for entry in ledger) == event.input_tokens
        assert sum(entry["completion_tokens"] for entry in ledger) == event.output_tokens
        costs = [Decimal(str(e["cost_usd"])) for e in ledger if e["cost_usd"] is not None]
        assert event.cost_usd is not None
        assert Decimal(str(event.cost_usd)) == pytest.approx(sum(costs, Decimal("0")))
        stages.update(entry["stage"] for entry in ledger)
        for entry in ledger:
            assert set(entry) == {
                "stage",
                "provider",
                "model",
                "prompt_tokens",
                "completion_tokens",
                "cached_tokens",
                "cost_usd",
                "estimated",
            }
    assert {"rewrite", "retrieve", "rerank", "conflict", "generate", "verifier", "refiner"} <= (
        stages
    )

    usage = (
        await db_session.execute(
            select(OrgQuotaUsage).where(
                OrgQuotaUsage.organization_id == UUID(organization_id),
                OrgQuotaUsage.quota_type == "tokens",
            )
        )
    ).scalar_one()
    assert usage.current_value == expected_prompt + expected_completion

    prompt_metric = sum(a for _, kind, a in recorded if kind == "prompt")
    completion_metric = sum(a for _, kind, a in recorded if kind == "completion")
    assert (prompt_metric, completion_metric) == (expected_prompt, expected_completion)


def test_ledger_metadata_lists_each_entry_without_text() -> None:
    ledger = TokenLedger()
    ledger.record("rerank", "openai", "m", 3, 2, cached_tokens=1, cost_usd=Decimal("0.5"))
    ledger.record("retrieve", None, "e", 4, 0)
    assert ledger_metadata(ledger) == [
        {
            "stage": "rerank",
            "provider": "openai",
            "model": "m",
            "prompt_tokens": 3,
            "completion_tokens": 2,
            "cached_tokens": 1,
            "cost_usd": 0.5,
            "estimated": False,
        },
        {
            "stage": "retrieve",
            "provider": None,
            "model": "e",
            "prompt_tokens": 4,
            "completion_tokens": 0,
            "cached_tokens": 0,
            "cost_usd": None,
            "estimated": False,
        },
    ]


def test_chat_token_metric_ignores_zero_and_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(metrics, "is_metrics_enabled", lambda: True)
    before = metrics.CHAT_TOKENS_TOTAL.labels(stage="unit", kind="prompt")._value.get()
    metrics.record_chat_tokens("unit", "prompt", 0)
    metrics.record_chat_tokens("unit", "prompt", 5)
    after = metrics.CHAT_TOKENS_TOTAL.labels(stage="unit", kind="prompt")._value.get()
    assert after - before == 5
    monkeypatch.setattr(metrics, "is_metrics_enabled", lambda: False)
    metrics.record_chat_tokens("unit", "prompt", 5)
    assert metrics.CHAT_TOKENS_TOTAL.labels(stage="unit", kind="prompt")._value.get() == after
