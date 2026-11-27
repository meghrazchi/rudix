"""Shared setup for the auxiliary-stage routing and token-ledger tests (R05-07, R05-08).

Every auxiliary stage is switched on: query rewriting (with decomposition), rerank, conflict
detection, grounded verification (standard mode), the planner-critic-refiner in ``always``
mode, and tree search. One non-high-risk question exercises rewrite, rerank, conflict,
answer, verifier, and refiner; one high-risk question exercises tree search.
"""

from __future__ import annotations

from typing import Any

import pytest
from chat_golden_providers import RecordingChatProvider
from chat_golden_support import GoldenWorld, SeedDoc, seed_documents
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from test_chat_golden_transcripts import (
    HIGH_RISK_QUESTION,
    TEXT_A,
    TEXT_B,
    _answer_with_extra_claim,
    _decompose,
    _verifier_partial,
)
from test_chat_query_api import _auth_headers, _FakeEmbeddingProvider, _seed_principal

from app.auth.token_codec import create_app_access_token
from app.core.config import settings
from app.domains.ai.providers.factory import default_provider_factory
from app.interfaces.http import chat as chat_api
from app.models.enums import OrganizationRole

AUX_QUESTION = "How much leave do employees and contractors get?"
AUX_RESPONDERS: dict[str, Any] = {
    "rewrite": _decompose,
    "answer": _answer_with_extra_claim,
    "verifier": _verifier_partial,
}


def enable_all_aux_stages(monkeypatch: pytest.MonkeyPatch) -> None:
    for flag in (
        "feature_enable_query_rewriting",
        "feature_enable_conflict_detection",
        "feature_enable_grounded_answer_verification",
        "feature_enable_planner_critic_refiner",
        "feature_enable_tree_search_reasoning",
    ):
        monkeypatch.setattr(settings, flag, True)
    monkeypatch.setattr(settings, "planner_critic_refiner_mode", "always")


def install_chat_provider(
    monkeypatch: pytest.MonkeyPatch, provider: RecordingChatProvider, *, provider_key: str
) -> _FakeEmbeddingProvider:
    """Register ``provider`` under ``provider_key`` only (no entry for other keys)."""
    embed_provider = _FakeEmbeddingProvider()
    monkeypatch.setattr(default_provider_factory, "_chat_providers", {provider_key: provider})
    monkeypatch.setattr(chat_api._llm_service, "_provider", provider)
    monkeypatch.setattr(chat_api._query_retrieval_service, "_embedding_provider", embed_provider)
    return embed_provider


async def ask_aux_questions(
    *,
    client: AsyncClient,
    db_session: AsyncSession,
    provider: RecordingChatProvider,
    docs: list[SeedDoc] | None = None,
) -> tuple[list[dict[str, Any]], str]:
    """Seed two documents and ask the two questions; return the payloads and the org id."""
    user, organization, _ = await _seed_principal(db_session)
    world = GoldenWorld(
        user=user,
        organization=organization,
        role=OrganizationRole.member,
        provider=provider,
        payload={},
    )
    await seed_documents(
        db_session, world, docs or [SeedDoc("a", TEXT_A, 0.92), SeedDoc("b", TEXT_B, 0.88)]
    )
    await db_session.commit()
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(organization.id),
        expires_in_seconds=600,
    )
    payloads: list[dict[str, Any]] = []
    for question in (AUX_QUESTION, HIGH_RISK_QUESTION):
        response = await client.post(
            "/api/v1/chat",
            headers=_auth_headers(token=token, organization_id=str(organization.id)),
            json={"question": question, "top_k": 3, "rerank": True},
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        # Number of provider calls recorded once this request finished.
        payload["_provider_call_mark"] = len(provider.calls)
        payloads.append(payload)
    return payloads, str(organization.id)


EXPECTED_AUX_KINDS = frozenset(
    {"rewrite", "rerank", "conflict", "answer", "verifier", "refiner", "tree_search"}
)
