"""R05-02: SQL statement budget of one grounded HTTP chat question on the pipeline.

The baseline below was measured on this branch (SQLite, one indexed chunk, default flags,
prompt templates already seeded) and is an upper bound: a change that adds statements to
the chat path has to raise it deliberately. Every statement before the final write is a
read; the chat session row is only written by stage 10.
"""

from __future__ import annotations

import pytest
from chat_golden_providers import RecordingChatProvider, install_providers
from chat_golden_support import SeedDoc, seed_documents
from httpx import AsyncClient
from query_count import count_queries
from sqlalchemy.ext.asyncio import AsyncSession
from test_chat_golden_transcripts import QUESTION, TEXT_A, GoldenWorld
from test_chat_query_api import (
    _auth_headers,
    _seed_principal,
    chat_query_client,  # noqa: F401  (pytest fixture re-export)
)

from app.auth.token_codec import create_app_access_token
from app.core.config import settings
from app.domains.prompt_templates.services.prompt_template_service import PromptTemplateService
from app.models.enums import OrganizationRole

pytestmark = [pytest.mark.asyncio]

# Measured on this branch: 46 statements for one grounded question, authentication included
# (the legacy body sent the same number). Raise it deliberately, never silently.
# R05-07 (B1): +4 for the token-quota increment (QuotaType.tokens) in stage 10: the quota
# policy and usage reads, the upsert, and the returned row. Measured: 50.
GROUNDED_HTTP_QUESTION_STATEMENT_BASELINE = 50
_WRITE_PREFIXES = ("INSERT", "UPDATE", "DELETE")


async def test_grounded_http_question_statement_count_and_read_only_until_persist(
    chat_query_client: AsyncClient,  # noqa: F811
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "chat_pipeline_v2", True)
    provider = RecordingChatProvider()
    install_providers(monkeypatch, provider)
    user, organization, _ = await _seed_principal(db_session)
    world = GoldenWorld(
        user=user,
        organization=organization,
        role=OrganizationRole.member,
        provider=provider,
        payload={"question": QUESTION, "top_k": 3, "rerank": False},
    )
    await seed_documents(db_session, world, [SeedDoc("a", TEXT_A, 0.92)])
    # The answer template is seeded lazily on an organisation's first question.
    await PromptTemplateService().ensure_default_templates(
        db_session, organization_id=organization.id
    )
    await db_session.commit()
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(organization.id),
        expires_in_seconds=600,
    )

    async with count_queries(db_session) as counter:
        response = await chat_query_client.post(
            "/api/v1/chat",
            headers=_auth_headers(token=token, organization_id=str(organization.id)),
            json=world.payload,
        )

    assert response.status_code == 200, response.text
    assert response.json()["not_found"] is False
    statements = [s.lstrip().upper() for s in counter.statements]
    first_write = next(
        index for index, statement in enumerate(statements) if statement.startswith("INSERT")
    )
    assert "CHAT_SESSIONS" in statements[first_write]
    before_persist = statements[:first_write]
    assert not [s for s in before_persist if s.startswith(_WRITE_PREFIXES)]
    assert counter.count <= GROUNDED_HTTP_QUESTION_STATEMENT_BASELINE, counter.statements
