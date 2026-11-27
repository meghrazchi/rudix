"""Verified-answer shortcut, stage 4 (R05-05).

The shortcut evaluates in shadow mode: a validated exact match is recorded on the context and
in ``rudix_chat_verified_answer_shortcut_total{result}``, but the run still retrieves and
generates, because the response contract requires a numeric ``confidence_score`` and none may
be invented for a verified answer (see ``stages/shortcut.py``).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from chat_b2_support import QUESTION, TEXT, B2World, make_world, run_pipeline
from chat_golden_support import SeedDoc
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.chat.pipeline.stages import shortcut
from app.application.chat.pipeline.stages.shortcut import single_collection_scope
from app.core.config import settings
from app.core.metrics import CHAT_VERIFIED_ANSWER_SHORTCUT_TOTAL
from app.domains.chat.schemas.chat import ChatQueryRequest
from app.domains.verified_answers.services.shortcut_matcher import (
    VerifiedAnswerCandidate,
    find_exact_match,
)
from app.models.document import Document
from app.models.verified_answer import VerifiedAnswer, VerifiedAnswerCitation

pytestmark = [pytest.mark.asyncio]


@pytest.fixture
def shortcut_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "chat_verified_answer_shortcut_enabled", True)


def _metric(result: str) -> float:
    return float(CHAT_VERIFIED_ANSWER_SHORTCUT_TOTAL.labels(result=result)._value.get())


async def _card(
    db_session: AsyncSession,
    world: B2World,
    *,
    question: str = QUESTION,
    citations: list[tuple[UUID, UUID | None]] | None = None,
    requires_citations: bool = True,
    expiry_date: date | None = None,
    collection_id: UUID | None = None,
    organization_id: UUID | None = None,
) -> VerifiedAnswer:
    if citations is None:
        citations = [next(iter(world.seeded.values()))]
    card = VerifiedAnswer(
        organization_id=organization_id or world.organization.id,
        title="Annual leave",
        question=question,
        answer_text="Employees receive twenty days of annual leave.",
        status="published",
        published_at=datetime.now(UTC),
        requires_citations=requires_citations,
        expiry_date=expiry_date,
        collection_id=collection_id,
    )
    db_session.add(card)
    await db_session.flush()
    for order, (document_id, chunk_id) in enumerate(citations):
        db_session.add(
            VerifiedAnswerCitation(
                verified_answer_id=card.id,
                document_id=document_id,
                chunk_id=chunk_id,
                text_snippet="twenty days",
                citation_order=order,
            )
        )
    await db_session.commit()
    return card


def _result(ctx: Any) -> str | None:
    return ctx.verified_answer_match.result if ctx.verified_answer_match is not None else None


async def test_flag_is_off_by_default(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert settings.chat_verified_answer_shortcut_enabled is False
    world = await make_world(db_session, monkeypatch)
    await _card(db_session, world)

    ctx = await run_pipeline(db_session, world.principal)

    assert ctx.verified_answer_match is None
    assert world.calls("answer") == 1


async def test_exact_normalised_match_is_a_hit_without_any_provider_call_in_stage_4(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, shortcut_on: None
) -> None:
    world = await make_world(db_session, monkeypatch)
    card = await _card(db_session, world, question=f"  {QUESTION.upper()}\n")
    hits = _metric("hit")

    ctx = await run_pipeline(db_session, world.principal)

    assert _result(ctx) == "hit"
    assert ctx.verified_answer_match is not None
    assert ctx.verified_answer_match.verified_answer_id == card.id
    assert len(ctx.verified_answer_match.valid_citations) == 1
    assert _metric("hit") == hits + 1
    # Shadow mode: the answer is still generated (exactly one embedding and one answer
    # call, the same as without a card), so stage 4 itself made no provider call.
    assert len(world.embed.calls) == 1 and world.calls("answer") == 1
    assert ctx.generation.not_found is False


async def test_near_miss_wording_falls_through(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, shortcut_on: None
) -> None:
    world = await make_world(db_session, monkeypatch)
    await _card(db_session, world, question="How many days of annual leave do staff receive?")

    ctx = await run_pipeline(db_session, world.principal)

    assert _result(ctx) == "no_match"


async def test_another_organisations_card_never_matches(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, shortcut_on: None
) -> None:
    world = await make_world(db_session, monkeypatch)
    other = await make_world(db_session, monkeypatch, docs=[SeedDoc("b2-va-other", TEXT, 0.9)])
    await _card(db_session, other)

    ctx = await run_pipeline(db_session, world.principal)

    assert _result(ctx) == "no_match"


async def test_citation_to_an_inaccessible_document_falls_through(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, shortcut_on: None
) -> None:
    world = await make_world(db_session, monkeypatch)
    other = await make_world(db_session, monkeypatch, docs=[SeedDoc("b2-va-foreign", TEXT, 0.9)])
    # A card in the user's organisation that cites another organisation's document.
    await _card(db_session, world, citations=[next(iter(other.seeded.values()))])

    ctx = await run_pipeline(db_session, world.principal)

    assert _result(ctx) == "citation_rejected"


async def test_citation_outside_the_document_scope_falls_through(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, shortcut_on: None
) -> None:
    world = await make_world(
        db_session,
        monkeypatch,
        docs=[SeedDoc("b2-va-in", TEXT, 0.92), SeedDoc("b2-va-out", "Other text.", 0.5)],
    )
    in_doc, _ = world.seeded["b2-va-in"]
    await _card(db_session, world, citations=[world.seeded["b2-va-out"]])

    ctx = await run_pipeline(db_session, world.principal, document_ids=[str(in_doc)])

    assert _result(ctx) == "citation_rejected"


async def test_missing_chunk_or_unindexed_document_falls_through(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, shortcut_on: None
) -> None:
    world = await make_world(db_session, monkeypatch)
    document_id, _ = next(iter(world.seeded.values()))
    card = await _card(db_session, world, citations=[(document_id, uuid4())])
    assert _result(await run_pipeline(db_session, world.principal)) == "citation_rejected"

    await db_session.delete(card)
    await _card(db_session, world, citations=[(document_id, None)])
    assert _result(await run_pipeline(db_session, world.principal)) == "citation_rejected"


async def test_deleted_document_falls_through(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, shortcut_on: None
) -> None:
    world = await make_world(
        db_session,
        monkeypatch,
        docs=[SeedDoc("b2-va-live", TEXT, 0.92), SeedDoc("b2-va-gone", TEXT, 0.5)],
    )
    gone_id, _ = world.seeded["b2-va-gone"]
    await _card(db_session, world, citations=[world.seeded["b2-va-gone"]])
    document = await db_session.get(Document, gone_id)
    assert document is not None
    document.status = "delete_requested"
    await db_session.commit()

    ctx = await run_pipeline(db_session, world.principal)

    assert _result(ctx) == "citation_rejected"


async def test_requires_citations_with_none_falls_through_unless_waived(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, shortcut_on: None
) -> None:
    world = await make_world(db_session, monkeypatch)
    card = await _card(db_session, world, citations=[])
    assert _result(await run_pipeline(db_session, world.principal)) == "citation_rejected"

    card.requires_citations = False
    await db_session.commit()
    ctx = await run_pipeline(db_session, world.principal)
    assert _result(ctx) == "hit"
    assert ctx.verified_answer_match is not None
    assert ctx.verified_answer_match.valid_citations == []


async def test_expired_or_other_collection_cards_do_not_match(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, shortcut_on: None
) -> None:
    world = await make_world(db_session, monkeypatch)
    await _card(db_session, world, expiry_date=datetime.now(UTC).date() - timedelta(days=1))

    assert _result(await run_pipeline(db_session, world.principal)) == "no_match"


async def test_over_cap_organisation_never_shortcuts(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, shortcut_on: None
) -> None:
    monkeypatch.setattr(settings, "chat_verified_answer_max_candidates", 1)
    world = await make_world(db_session, monkeypatch)
    await _card(db_session, world)
    await _card(db_session, world, question="Another question?")
    over_cap = _metric("over_cap")

    ctx = await run_pipeline(db_session, world.principal)

    assert _result(ctx) == "over_cap"
    assert _metric("over_cap") == over_cap + 1


async def test_guidance_and_blocked_questions_are_not_evaluated(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, shortcut_on: None
) -> None:
    world = await make_world(db_session, monkeypatch)
    await _card(db_session, world, question="How do I upload a document?")

    ctx = await run_pipeline(db_session, world.principal, question="How do I upload a document?")

    assert ctx.verified_answer_match is None


def _candidate(**overrides: Any) -> VerifiedAnswerCandidate:
    values: dict[str, Any] = {
        "id": uuid4(),
        "normalised_question": "how much leave?",
        "answer_text": "a",
    }
    return VerifiedAnswerCandidate(**{**values, **overrides})


async def test_match_rule_prefers_the_collection_card_and_respects_scope_and_expiry() -> None:
    collection = uuid4()
    today = date(2026, 11, 27)
    unscoped = _candidate()
    scoped = _candidate(collection_id=collection)
    elsewhere = _candidate(collection_id=uuid4())
    expired = _candidate(collection_id=collection, expiry_date=date(2026, 11, 26))
    candidates = [unscoped, scoped, elsewhere, expired]

    match = find_exact_match(
        candidates, question="How much  LEAVE?", collection_id=collection, today=today
    )
    assert match is scoped
    assert (
        find_exact_match(candidates, question="how much leave?", collection_id=None, today=today)
        is unscoped
    )
    assert (
        find_exact_match(candidates, question="how much leave", collection_id=None, today=today)
        is None
    )
    assert find_exact_match(candidates, question="   ", collection_id=None, today=today) is None
    assert (
        find_exact_match(
            [elsewhere], question="how much leave?", collection_id=collection, today=today
        )
        is None
    )


async def test_single_collection_scope_needs_exactly_one_collection() -> None:
    collection = str(uuid4())

    def scope(**source_scope: Any) -> UUID | None:
        return single_collection_scope(
            ChatQueryRequest.model_validate({"question": "q", "source_scope": source_scope})
        )

    assert scope(mode="collections", collection_ids=[collection]) == UUID(collection)
    assert scope(mode="collections", collection_ids=[collection, str(uuid4())]) is None
    assert scope(mode="all") is None
    assert scope(mode="collections", collection_ids=["not-a-uuid"]) is None
    assert single_collection_scope(ChatQueryRequest(question="q")) is None


async def _deny_all(*_args: Any, **_kwargs: Any) -> list[Any]:
    return []


@pytest.mark.parametrize(
    "check", ["_filter_authorized_document_ids_for_chat", "filter_chunks_by_cite_access"]
)
async def test_unreadable_or_uncitable_document_falls_through(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    shortcut_on: None,
    check: str,
) -> None:
    world = await make_world(db_session, monkeypatch)
    await _card(db_session, world)
    # Only the shortcut's own read/cite check denies; retrieval keeps its real checks.
    monkeypatch.setattr(shortcut, check, _deny_all)

    ctx = await run_pipeline(db_session, world.principal)

    assert _result(ctx) == "citation_rejected"


async def test_empty_document_scope_never_shortcuts(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, shortcut_on: None
) -> None:
    world = await make_world(db_session, monkeypatch)
    await _card(db_session, world, requires_citations=False, citations=[])

    ctx = await run_pipeline(
        db_session,
        world.principal,
        source_scope={"mode": "collections", "collection_ids": []},
    )

    assert _result(ctx) == "citation_rejected"
