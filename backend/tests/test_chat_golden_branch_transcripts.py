"""Golden transcripts of the evidence and verification branches of the chat path (R05-01).

Recorded through the legacy ``query_chat`` body and WebSocket pipeline like the core goldens;
the one chat pipeline (S3) must match them. These scenarios make the branches
that the core and edge goldens leave unexercised actually run: effective freshness statuses
(``quality_state``), the all-excluded fallback, OCR downranking, table boosting, parent context,
the hybrid keyword merge, strict-mode verifier refusals, and a refiner that changes the draft.
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any
from uuid import UUID

import pytest
from chat_golden_providers import cite_first_chunk
from chat_golden_support import (
    GoldenWorld,
    SeedDoc,
    assert_matches_golden,
    golden_target,
    seed_documents,
)
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from test_chat_golden_transcripts import (
    HIGH_RISK_QUESTION,
    RUNS,
    TEXT_A,
    TEXT_B,
    ScenarioSpec,
    run_golden,
)
from test_chat_query_api import (
    FakeQdrantClient,
    chat_query_client,  # noqa: F401  (pytest fixture re-export)
)

from app.clients import qdrant_client as qdrant_module
from app.core.config import settings
from app.domains.ai_response_policy.repositories.ai_response_policy import (
    AiResponsePolicyRepository,
)
from app.domains.chat.services.grounded_answer_verifier import GroundedVerifierResult
from app.domains.chat.services.keyword_retrieval_service import (
    KeywordRetrievalResult,
    KeywordRetrievedCandidate,
)
from app.interfaces.http import chat as chat_api
from app.models.document import Document
from app.models.enums import OrganizationRole

pytestmark = [pytest.mark.asyncio]

MEMBER = OrganizationRole.member
PARENT_TEXT = "Leave policy section. Employees receive twenty days of annual leave per year."


async def _set_document_fields(db: AsyncSession, document_id: UUID, **fields: object) -> None:
    document = await db.get(Document, document_id)
    assert document is not None
    for key, value in fields.items():
        setattr(document, key, value)
    db.add(document)
    await db.commit()


def _patch_qdrant_payloads(updates: dict[int, dict[str, object]]) -> None:
    """Add payload fields (chunk_type, chunk_level, parent_text) to the seeded results."""
    client = qdrant_module.qdrant_client
    assert isinstance(client, FakeQdrantClient)
    results = list(client._results)
    for index, extra in updates.items():
        results[index] = replace(results[index], payload={**results[index].payload, **extra})
    qdrant_module.qdrant_client = FakeQdrantClient(results)


async def _freshness_effective(
    db: AsyncSession, mp: pytest.MonkeyPatch, world: GoldenWorld
) -> None:
    # quality_state drives the effective status: a is stale, b is deprecated (excluded).
    seeded = await seed_documents(
        db, world, [SeedDoc("a", TEXT_A, 0.92), SeedDoc("b", TEXT_B, 0.88)]
    )
    await _set_document_fields(db, seeded["a"][0], quality_state="stale")
    await _set_document_fields(db, seeded["b"][0], quality_state="deprecated")


async def _freshness_fallback(db: AsyncSession, mp: pytest.MonkeyPatch, world: GoldenWorld) -> None:
    # Every retrieved source is deprecated: the excluded chunks come back with a warning.
    seeded = await seed_documents(db, world, [SeedDoc("a", TEXT_A, 0.92)])
    await _set_document_fields(db, seeded["a"][0], quality_state="deprecated")


async def _evidence_quality(db: AsyncSession, mp: pytest.MonkeyPatch, world: GoldenWorld) -> None:
    mp.setattr(settings, "feature_enable_ocr_quality_downranking", True)
    mp.setattr(settings, "feature_enable_table_aware_retrieval", True)
    mp.setattr(settings, "feature_enable_parent_context_expansion", True)
    seeded = await seed_documents(
        db, world, [SeedDoc("a", TEXT_A, 0.92), SeedDoc("b", TEXT_B, 0.88)]
    )
    await _set_document_fields(db, seeded["a"][0], ocr_quality_status="low")
    _patch_qdrant_payloads(
        {
            0: {"chunk_level": 1, "parent_text": PARENT_TEXT},
            1: {"chunk_type": "table"},
        }
    )


async def _hybrid_keyword(db: AsyncSession, mp: pytest.MonkeyPatch, world: GoldenWorld) -> None:
    # SQLite has no full-text search, so the keyword branch is scripted; the merge is real.
    mp.setattr(settings, "feature_enable_hybrid_retrieval", True)
    seeded = await seed_documents(
        db, world, [SeedDoc("a", TEXT_A, 0.92), SeedDoc("b", TEXT_B, 0.88)]
    )
    doc_b, chunk_b = seeded["b"]

    async def _search_chunks(**_kwargs: Any) -> KeywordRetrievalResult:
        return KeywordRetrievalResult(
            candidates=[
                KeywordRetrievedCandidate(
                    document_id=doc_b,
                    chunk_id=chunk_b,
                    filename="b.pdf",
                    page_number=1,
                    text=TEXT_B,
                    section_path=None,
                    keyword_score=0.7,
                    exact_match_hit=False,
                )
            ],
            query_tokens=["annual", "leave"],
            exact_match_tokens=[],
        )

    mp.setattr(chat_api._keyword_retrieval_service, "search_chunks", _search_chunks)


def _scripted_verifier(mp: pytest.MonkeyPatch, **overrides: Any) -> None:
    async def _verify(*, answer: str, **_kwargs: Any) -> GroundedVerifierResult:
        fields: dict[str, Any] = {
            "applied": True,
            "verdict": "supported",
            "verification_score": 1.0,
            "claim_count": 1,
            "supported_claim_count": 1,
            "partially_supported_claim_count": 0,
            "unsupported_claim_count": 0,
            "unverifiable_claim_count": 0,
            "aggregate_support_score": 0.9,
            "final_answer": answer,
            "mode": "strict",
            "threshold": 0.8,
            **overrides,
        }
        return GroundedVerifierResult(**fields)

    mp.setattr(chat_api._grounded_verifier, "verify", _verify)


async def _strict_policy(db: AsyncSession, world: GoldenWorld) -> None:
    await seed_documents(db, world, [SeedDoc("a", TEXT_A, 0.93)])
    repo = AiResponsePolicyRepository()
    policy = await repo.create(
        db,
        organization_id=world.organization.id,
        policy_name="Strict verification",
        grounded_verification_mode="strict",
        grounded_verification_threshold=0.8,
    )
    await repo.activate(db, organization_id=world.organization.id, policy=policy)
    await db.commit()
    world.label(policy.id, "policy")


async def _strict_low_score(db: AsyncSession, mp: pytest.MonkeyPatch, world: GoldenWorld) -> None:
    # The verifier keeps the answer but scores it below the strict threshold: refused.
    await _strict_policy(db, world)
    _scripted_verifier(mp, verdict="partially_supported", verification_score=0.4)
    # A source scope with an active policy runs the collection-override lookup.
    world.payload["source_scope"] = {"mode": "all"}


async def _strict_conflict(db: AsyncSession, mp: pytest.MonkeyPatch, world: GoldenWorld) -> None:
    # Above the threshold, but a conflicting claim: strict mode still refuses.
    await _strict_policy(db, world)
    _scripted_verifier(mp, verification_score=0.95, conflicting_claim_count=1)


def _answer_with_extra_claim(prompt: str) -> str:
    payload = json.loads(cite_first_chunk(prompt))
    payload["answer"] = f"{payload['answer']} Parking is free."
    return json.dumps(payload)


def _verifier_unsupported(prompt: str) -> str:
    return json.dumps(
        {
            "verdict": "partially_supported",
            "revised_answer": f"{TEXT_A} Parking is free.",
            "removed_claims": [],
            "reason_codes": ["no_source"],
            "claim_count": 2,
            "supported_claim_count": 1,
            "partially_supported_claim_count": 0,
            "unsupported_claim_count": 1,
            "unverifiable_claim_count": 0,
        }
    )


def _refiner_rewrites(_prompt: str) -> str:
    return json.dumps(
        {
            "refined_answer": "Employees receive twenty days of annual leave each year.",
            "changes_made": ["removed the unsupported parking claim"],
            "unsupported_claims_removed": 1,
        }
    )


async def _refiner_changes(db: AsyncSession, mp: pytest.MonkeyPatch, world: GoldenWorld) -> None:
    mp.setattr(settings, "feature_enable_planner_critic_refiner", True)
    mp.setattr(settings, "feature_enable_grounded_answer_verification", True)
    await seed_documents(db, world, [SeedDoc("a", TEXT_A, 0.92), SeedDoc("b", TEXT_B, 0.88)])
    world.payload["question"] = HIGH_RISK_QUESTION


BRANCH_SCENARIOS: dict[str, ScenarioSpec] = {
    "freshness_effective_statuses": (_freshness_effective, MEMBER, {}, frozenset()),
    "freshness_all_excluded_fallback": (_freshness_fallback, MEMBER, {}, frozenset()),
    "evidence_ocr_table_parent": (_evidence_quality, MEMBER, {}, frozenset()),
    "hybrid_keyword_merge": (_hybrid_keyword, MEMBER, {}, frozenset()),
    "strict_verifier_low_score": (_strict_low_score, MEMBER, {}, frozenset()),
    "strict_verifier_conflict_result": (_strict_conflict, MEMBER, {}, frozenset()),
    "refiner_changes_draft": (
        _refiner_changes,
        MEMBER,
        {
            "answer": _answer_with_extra_claim,
            "verifier": _verifier_unsupported,
            "refiner": _refiner_rewrites,
        },
        frozenset(),
    ),
}


@pytest.mark.parametrize("transport", RUNS)
@pytest.mark.parametrize("scenario", list(BRANCH_SCENARIOS))
async def test_chat_golden_branch_transcript(
    scenario: str,
    transport: str,
    chat_query_client: AsyncClient,  # noqa: F811
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transcript = await run_golden(
        BRANCH_SCENARIOS[scenario],
        transport,
        client=chat_query_client,
        db_session=db_session,
        monkeypatch=monkeypatch,
    )
    fixture_transport, allow_update = golden_target(transport)
    assert_matches_golden(scenario, fixture_transport, transcript, allow_update=allow_update)
