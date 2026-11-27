"""Golden transcripts of chat refusals and rarer branches (R05-01).

Recorded through the legacy ``query_chat`` body and WebSocket pipeline like the core goldens
in test_chat_golden_transcripts.py; the HTTP pipeline (``CHAT_PIPELINE_V2``) must match them.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from chat_golden_providers import cite_first_chunk
from chat_golden_support import GoldenWorld, SeedDoc, assert_matches_golden, seed_documents
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
    _seed_quota_policy,
    chat_query_client,  # noqa: F401  (pytest fixture re-export)
)

from app.clients import qdrant_client as qdrant_module
from app.core.config import settings
from app.domains.ai_response_policy.repositories.ai_response_policy import (
    AiResponsePolicyRepository,
)
from app.interfaces.http import chat as chat_api
from app.models.enums import OrganizationRole
from app.models.rag_profile import RagProfile

pytestmark = [pytest.mark.asyncio]

MISSING_DOCUMENT_ID = "00000000-0000-4000-8000-0000000000dd"
MEMBER = OrganizationRole.member


class _FailingQdrantClient:
    def search(self, **_kwargs: object) -> list[object]:
        raise ConnectionError("vector store unavailable")


async def _policy(db: AsyncSession, world: GoldenWorld, **kwargs: Any) -> None:
    repo = AiResponsePolicyRepository()
    policy = await repo.create(
        db, organization_id=world.organization.id, policy_name="Golden policy", **kwargs
    )
    await repo.activate(db, organization_id=world.organization.id, policy=policy)
    await db.commit()
    world.label(policy.id, "policy")


async def _quota_exhausted(db: AsyncSession, mp: pytest.MonkeyPatch, world: GoldenWorld) -> None:
    await seed_documents(db, world, [SeedDoc("a", TEXT_A, 0.92)])
    await _seed_quota_policy(
        db,
        organization_id=world.organization.id,
        limits={"questions": {"soft_limit": 0, "hard_limit": 0, "reset_window": "per_day"}},
    )


async def _document_not_found(db: AsyncSession, mp: pytest.MonkeyPatch, world: GoldenWorld) -> None:
    await seed_documents(db, world, [SeedDoc("a", TEXT_A, 0.92)])
    world.payload["document_ids"] = [MISSING_DOCUMENT_ID]


async def _malformed_session(db: AsyncSession, mp: pytest.MonkeyPatch, world: GoldenWorld) -> None:
    await seed_documents(db, world, [SeedDoc("a", TEXT_A, 0.92)])
    world.payload["chat_session_id"] = "not-a-session-id"


async def _vector_store_down(db: AsyncSession, mp: pytest.MonkeyPatch, world: GoldenWorld) -> None:
    # The parallel retrieval branches absorb vector-store errors: the answer is not-found.
    await seed_documents(db, world, [SeedDoc("a", TEXT_A, 0.92)])
    qdrant_module.qdrant_client = _FailingQdrantClient()  # type: ignore[assignment]


async def _retrieval_failure(db: AsyncSession, mp: pytest.MonkeyPatch, world: GoldenWorld) -> None:
    # A failure after the branches (provenance filtering) is a retrieval_failed refusal.
    await seed_documents(db, world, [SeedDoc("a", TEXT_A, 0.92)])

    async def _fail(*_args: object, **_kwargs: object) -> list[object]:
        raise RuntimeError("provenance store unavailable")

    mp.setattr(chat_api._source_provenance_service, "filter_active_chunks", _fail)


async def _persistence_failure(
    db: AsyncSession, mp: pytest.MonkeyPatch, world: GoldenWorld
) -> None:
    await seed_documents(db, world, [SeedDoc("a", TEXT_A, 0.92)])

    async def _fail(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("usage store unavailable")

    mp.setattr(chat_api.usage_repository, "create_usage_event", _fail)


async def _guidance_failure(db: AsyncSession, mp: pytest.MonkeyPatch, world: GoldenWorld) -> None:
    mp.setattr(chat_api._llm_service, "retry_base_seconds", 0.0)
    mp.setattr(chat_api._llm_service, "retry_max_seconds", 0.0)
    await seed_documents(db, world, [])
    world.payload.update(
        {"question": "How do I choose a source scope?", "document_ids": [], "scope_mode": "none"}
    )


async def _policy_post_block(db: AsyncSession, mp: pytest.MonkeyPatch, world: GoldenWorld) -> None:
    await seed_documents(db, world, [SeedDoc("a", TEXT_A, 0.92)])
    await _policy(
        db,
        world,
        min_confidence_threshold=0.99,
        no_answer_behavior="refuse",
        refusal_message="Confidence is too low to answer.",
    )


async def _policy_disclaimer(db: AsyncSession, mp: pytest.MonkeyPatch, world: GoldenWorld) -> None:
    await seed_documents(
        db,
        world,
        [SeedDoc("a", TEXT_A, 0.92, trust_status="stale"), SeedDoc("b", TEXT_B, 0.88)],
    )
    await _policy(
        db,
        world,
        stale_source_behavior="warn",
        disclaimer_text="Answers are generated from your documents.",
        disclaimer_position="append",
    )
    world.payload["source_scope"] = {"mode": "all"}


async def _routing_tools(db: AsyncSession, mp: pytest.MonkeyPatch, world: GoldenWorld) -> None:
    mp.setattr(settings, "feature_enable_dynamic_retrieval_routing", True)
    mp.setattr(settings, "feature_enable_chat_tool_orchestration", True)
    mp.setattr(settings, "feature_enable_planner_critic_refiner", True)
    mp.setattr(settings, "feature_enable_parent_context_expansion", True)
    await seed_documents(db, world, [SeedDoc("a", TEXT_A, 0.92), SeedDoc("b", TEXT_B, 0.88)])
    world.payload["question"] = HIGH_RISK_QUESTION


def _model_refuses(_prompt: str) -> str:
    return json.dumps({"answer": "", "not_found": True, "citations": []})


async def _tree_rejected(db: AsyncSession, mp: pytest.MonkeyPatch, world: GoldenWorld) -> None:
    mp.setattr(settings, "feature_enable_planner_critic_refiner", True)
    mp.setattr(settings, "feature_enable_tree_search_reasoning", True)
    mp.setattr(settings, "tree_search_min_selected_score", 0.99)
    await seed_documents(db, world, [SeedDoc("a", TEXT_A, 0.92), SeedDoc("b", TEXT_B, 0.88)])
    world.payload["question"] = HIGH_RISK_QUESTION


def _verifier_conflicting(prompt: str) -> str:
    return json.dumps(
        {
            "verdict": "supported",
            "revised_answer": TEXT_A,
            "removed_claims": [],
            "reason_codes": ["source_conflict"],
            "claim_count": 1,
            "supported_claim_count": 1,
            "partially_supported_claim_count": 0,
            "unsupported_claim_count": 0,
            "unverifiable_claim_count": 0,
            "conflicting_claim_count": 1,
        }
    )


async def _strict_conflicting(db: AsyncSession, mp: pytest.MonkeyPatch, world: GoldenWorld) -> None:
    await seed_documents(db, world, [SeedDoc("a", TEXT_A, 0.93)])
    await _policy(
        db, world, grounded_verification_mode="strict", grounded_verification_threshold=0.1
    )


def _verifier_supported_text(prompt: str) -> str:
    return _verifier_conflicting(prompt).replace('"conflicting_claim_count": 1', '"x": 0')


async def _standard_verified(db: AsyncSession, mp: pytest.MonkeyPatch, world: GoldenWorld) -> None:
    mp.setattr(settings, "feature_enable_grounded_answer_verification", True)
    await seed_documents(db, world, [SeedDoc("a", TEXT_A, 0.93)])


def _refiner_empty(_prompt: str) -> str:
    return json.dumps({"refined_answer": "", "changes_made": [], "unsupported_claims_removed": 2})


def _answer_with_extra_claim(prompt: str) -> str:
    payload = json.loads(cite_first_chunk(prompt))
    payload["answer"] = f"{payload['answer']} Parking is free."
    return json.dumps(payload)


def _verifier_unsupported(prompt: str) -> str:
    return (
        _verifier_conflicting(prompt)
        .replace('"conflicting_claim_count": 1', '"conflicting_claim_count": 0')
        .replace('"unsupported_claim_count": 0', '"unsupported_claim_count": 1')
    )


async def _refiner_removes_all(
    db: AsyncSession, mp: pytest.MonkeyPatch, world: GoldenWorld
) -> None:
    mp.setattr(settings, "feature_enable_planner_critic_refiner", True)
    mp.setattr(settings, "feature_enable_grounded_answer_verification", True)
    await seed_documents(db, world, [SeedDoc("a", TEXT_A, 0.92), SeedDoc("b", TEXT_B, 0.88)])
    world.payload["question"] = HIGH_RISK_QUESTION


def _rewrite_single(_prompt: str) -> str:
    return json.dumps(
        {"strategy": "rewrite", "primary_query": "annual leave days", "sub_queries": []}
    )


async def _rag_profile(db: AsyncSession, mp: pytest.MonkeyPatch, world: GoldenWorld) -> None:
    # An org default RAG profile overrides the settings in every stage that reads it.
    mp.setattr(settings, "feature_enable_query_rewriting", True)
    mp.setattr(settings, "feature_enable_context_packing", True)
    mp.setattr(settings, "feature_enable_parent_context_expansion", True)
    mp.setattr(settings, "feature_enable_dynamic_retrieval_routing", True)
    await seed_documents(
        db,
        world,
        [SeedDoc("a", TEXT_A, 0.92, trust_status="stale"), SeedDoc("b", TEXT_B, 0.88)],
    )
    profile = RagProfile(
        organization_id=world.organization.id,
        name="Golden default",
        is_default=True,
        config={
            "conflict_detection_enabled": True,
            "query_decomposition_enabled": False,
            "grounded_answer_verification_enabled": True,
            "planner_critic_refiner_enabled": True,
            "planner_critic_refiner_mode": "always",
            "stale_threshold_days": 30,
            "table_retrieval_boost_multiplier": 1.5,
            "parent_context_max_tokens_per_chunk": 256,
        },
    )
    db.add(profile)
    await db.commit()
    world.label(profile.id, "rag_profile")
    world.payload["question"] = "How many days of annual leave are listed in the table?"


def _answer_is_not_found_text(_prompt: str) -> str:
    return json.dumps(
        {
            "answer": "I could not find this information in the uploaded documents.",
            "not_found": False,
            "citations": [],
        }
    )


def _verifier_empty(_prompt: str) -> str:
    return _verifier_conflicting(_prompt).replace(
        f'"revised_answer": "{TEXT_A}"', '"revised_answer": ""'
    )


async def _single_doc(db: AsyncSession, mp: pytest.MonkeyPatch, world: GoldenWorld) -> None:
    await seed_documents(db, world, [SeedDoc("a", TEXT_A, 0.92)])


async def _verifier_on(db: AsyncSession, mp: pytest.MonkeyPatch, world: GoldenWorld) -> None:
    mp.setattr(settings, "feature_enable_grounded_answer_verification", True)
    await _single_doc(db, mp, world)


async def _critic_low_risk(db: AsyncSession, mp: pytest.MonkeyPatch, world: GoldenWorld) -> None:
    # Planner runs (high_risk_only) but the question is not high risk: no critic pass.
    mp.setattr(settings, "feature_enable_planner_critic_refiner", True)
    await _single_doc(db, mp, world)


async def _hybrid(db: AsyncSession, mp: pytest.MonkeyPatch, world: GoldenWorld) -> None:
    mp.setattr(settings, "feature_enable_hybrid_retrieval", True)
    await seed_documents(db, world, [SeedDoc("a", TEXT_A, 0.92), SeedDoc("b", TEXT_B, 0.88)])


EDGE_SCENARIOS: dict[str, ScenarioSpec] = {
    "quota_exhausted": (_quota_exhausted, MEMBER, {}, frozenset()),
    "document_not_found": (_document_not_found, MEMBER, {}, frozenset()),
    "malformed_session_id": (_malformed_session, MEMBER, {}, frozenset()),
    "vector_store_down": (_vector_store_down, MEMBER, {}, frozenset()),
    "retrieval_failure": (_retrieval_failure, MEMBER, {}, frozenset()),
    "persistence_failure": (_persistence_failure, MEMBER, {}, frozenset()),
    "guidance_llm_failure": (_guidance_failure, MEMBER, {}, frozenset({"guidance"})),
    "policy_post_generation_block": (_policy_post_block, MEMBER, {}, frozenset()),
    "policy_disclaimer_stale_warning": (_policy_disclaimer, MEMBER, {}, frozenset()),
    "routing_tools_parent_context": (_routing_tools, MEMBER, {}, frozenset()),
    "tree_search_rejected": (
        _tree_rejected,
        MEMBER,
        {"tree_search": _model_refuses},
        frozenset(),
    ),
    "strict_verifier_conflicting_claims": (
        _strict_conflicting,
        MEMBER,
        {"verifier": _verifier_conflicting},
        frozenset(),
    ),
    "standard_verifier_supported": (
        _standard_verified,
        MEMBER,
        {"verifier": _verifier_supported_text},
        frozenset(),
    ),
    "rag_profile_overrides": (
        _rag_profile,
        MEMBER,
        {"rewrite": _rewrite_single},
        frozenset(),
    ),
    "model_answers_not_found_text": (
        _single_doc,
        MEMBER,
        {"answer": _answer_is_not_found_text},
        frozenset(),
    ),
    "verifier_unavailable": (_verifier_on, MEMBER, {}, frozenset({"verifier"})),
    "verifier_removes_everything": (
        _verifier_on,
        MEMBER,
        {"verifier": _verifier_empty},
        frozenset(),
    ),
    "refiner_unavailable": (
        _refiner_removes_all,
        MEMBER,
        {"answer": _answer_with_extra_claim, "verifier": _verifier_unsupported},
        frozenset({"refiner"}),
    ),
    "critic_skipped_low_risk": (_critic_low_risk, MEMBER, {}, frozenset()),
    "hybrid_retrieval": (_hybrid, MEMBER, {}, frozenset()),
    "refiner_removes_everything": (
        _refiner_removes_all,
        MEMBER,
        {
            "answer": _answer_with_extra_claim,
            "verifier": _verifier_unsupported,
            "refiner": _refiner_empty,
        },
        frozenset(),
    ),
}


@pytest.mark.parametrize(("transport", "pipeline_v2"), RUNS)
@pytest.mark.parametrize("scenario", list(EDGE_SCENARIOS))
async def test_chat_golden_edge_transcript(
    scenario: str,
    transport: str,
    pipeline_v2: bool,
    chat_query_client: AsyncClient,  # noqa: F811
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "chat_pipeline_v2", pipeline_v2)
    transcript = await run_golden(
        EDGE_SCENARIOS[scenario],
        transport,
        client=chat_query_client,
        db_session=db_session,
        monkeypatch=monkeypatch,
    )
    fixture_transport = "http" if transport == "http_direct" else transport
    assert_matches_golden(
        scenario,
        fixture_transport,
        transcript,
        allow_update=transport != "http_direct" and not pipeline_v2,
    )
