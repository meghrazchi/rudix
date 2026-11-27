"""Token ledger of a chat run (R05-01, contract 4.2.5)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from test_chat_query_api import (
    FakeQdrantClient,
    FakeQdrantResult,
    _inject_providers,
    _seed_document_with_chunk,
    _seed_principal,
    chat_query_client,  # noqa: F401  (pytest fixture re-export)
)

from app.application.chat.pipeline.deps import default_deps
from app.application.chat.pipeline.events import CollectingEmitter
from app.application.chat.pipeline.ledger import LedgerTotals, TokenLedger
from app.application.chat.pipeline.pipeline import ChatPipeline
from app.application.chat.pipeline.sessions import SingleSessionScope
from app.auth.models import AuthenticatedPrincipal
from app.clients import qdrant_client as qdrant_module
from app.domains.chat.schemas.chat import ChatQueryRequest
from app.models.usage import UsageEvent

ANSWER = (
    '{"answer":"Employees receive twenty days of annual leave.","not_found":false,"citations":[]}'
)


def test_empty_ledger_totals_are_zero_without_cost() -> None:
    totals = TokenLedger().totals()
    assert totals == LedgerTotals(
        prompt_tokens=0, completion_tokens=0, cached_tokens=0, cost_usd=None, estimated=False
    )
    assert totals.total_tokens == 0


def test_record_sums_tokens_and_costs_and_groups_by_stage() -> None:
    ledger = TokenLedger()
    ledger.record("retrieve", None, "embed-model", 7, 0)
    ledger.record(
        "generate", "openai", "chat-model", 31, 17, cached_tokens=4, cost_usd=Decimal("0.002")
    )
    ledger.record(
        "generate", "openai", "chat-model", 5, 1, cost_usd=Decimal("0.001"), estimated=True
    )

    totals = ledger.totals()
    assert totals.prompt_tokens == 43
    assert totals.completion_tokens == 18
    assert totals.cached_tokens == 4
    assert totals.total_tokens == 61
    assert totals.cost_usd == Decimal("0.003")
    assert totals.estimated is True

    by_stage = ledger.by_stage()
    assert set(by_stage) == {"retrieve", "generate"}
    assert by_stage["retrieve"].prompt_tokens == 7
    assert by_stage["retrieve"].cost_usd is None
    assert by_stage["generate"].completion_tokens == 18


def test_record_clamps_negative_token_counts() -> None:
    ledger = TokenLedger()
    entry = ledger.record("generate", None, None, -3, -1, cached_tokens=-2)
    assert (entry.prompt_tokens, entry.completion_tokens, entry.cached_tokens) == (0, 0, 0)


@pytest.mark.asyncio
async def test_ledger_totals_equal_the_usage_event(
    chat_query_client: AsyncClient,  # noqa: F811
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, organization, _ = await _seed_principal(db_session)
    document, chunk = await _seed_document_with_chunk(
        db_session,
        organization=organization,
        uploader=user,
        filename="policy.pdf",
        text="Employees receive twenty days of annual leave.",
    )
    qdrant_module.qdrant_client = FakeQdrantClient(
        [
            FakeQdrantResult(
                score=0.92,
                payload={
                    "organization_id": str(organization.id),
                    "document_id": str(document.id),  # type: ignore[attr-defined]
                    "chunk_id": str(chunk.id),
                    "filename": "policy.pdf",
                    "page_number": 1,
                    "text": "Employees receive twenty days of annual leave.",
                },
            )
        ]
    )
    _inject_providers(monkeypatch, answer=ANSWER)
    principal = AuthenticatedPrincipal(
        user_id=str(user.id),
        organization_id=str(organization.id),
        email=user.email,
        roles=["member"],
        auth_provider="app",
    )
    organization_id = organization.id

    ctx = await ChatPipeline(default_deps).run(
        ChatQueryRequest(question="How much annual leave is provided?", top_k=3, rerank=False),
        principal,
        "http",
        CollectingEmitter(),
        SingleSessionScope(db_session),
        "ledger-test",
    )

    event = (
        await db_session.execute(
            select(UsageEvent).where(UsageEvent.organization_id == organization_id)
        )
    ).scalar_one()
    totals = ctx.ledger.totals()
    assert [entry.stage for entry in ctx.ledger.entries] == ["retrieve", "generate"]
    assert totals.prompt_tokens == event.input_tokens == 38
    assert totals.completion_tokens == event.output_tokens == 17
    assert totals.cost_usd is not None and event.cost_usd is not None
    assert float(totals.cost_usd) == pytest.approx(float(event.cost_usd))
