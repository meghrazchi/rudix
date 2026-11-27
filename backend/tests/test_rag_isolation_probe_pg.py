"""F144 cross-organisation retrieval and chat cases under the RLS probe role (0.5.0, S3).

The F144 suite runs as the superuser test role, which bypasses row-level security, so it
proves the application filters only. Here the same cases run with the session switched to
the non-owner probe role (``SET LOCAL ROLE``, as ``test_rls_enforcement_pg.py`` does) and
``RLS_ENFORCEMENT=strict``: the chat request binds its tenant like production, and the
database policy is a second wall. Each test also reads the strict tables directly as the
probe and asserts that no row of the other organisation is visible.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.factory import get_auth_provider
from app.auth.token_codec import create_app_access_token
from app.clients import qdrant_client as qdrant_module
from app.core.config import AuthProvider, RlsEnforcement, settings
from app.db.session import get_db_session
from app.interfaces.http import chat as chat_api
from app.main import app
from tests.conftest import RLS_PROBE_ROLE, RlsProbe
from tests.test_rag_isolation_f144 import (
    FakeOpenAIClient,
    FakeQdrantClient,
    FakeQdrantResult,
    _auth_headers,
    _make_document_with_chunk,
    _make_org_and_user,
    _qdrant_payload,
)

pytestmark = [pytest.mark.requires_postgres, pytest.mark.isolation]

FOREIGN_TEXT = "F144_PROBE_FOREIGN_SECRET"
STRICT_TABLES_CHECKED = ("documents", "chat_sessions", "usage_events", "audit_logs")


@pytest_asyncio.fixture
async def probe_client(
    monkeypatch: pytest.MonkeyPatch, rls_probe_session: RlsProbe
) -> AsyncIterator[AsyncClient]:
    monkeypatch.setattr(settings, "auth_provider", AuthProvider.app)
    monkeypatch.setattr(settings, "app_auth_secret", SecretStr("test-secret"))
    monkeypatch.setattr(settings, "app_auth_issuer", "rudix-test")
    monkeypatch.setattr(settings, "app_auth_audience", "rudix-test-audience")
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    monkeypatch.setattr(settings, "feature_enable_embeddings", True)
    monkeypatch.setattr(settings, "feature_enable_llm", True)
    monkeypatch.setattr(settings, "rls_enforcement", RlsEnforcement.strict)
    get_auth_provider.cache_clear()
    session = rls_probe_session.session

    async def _override_db() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_db_session] = _override_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
        yield c
    app.dependency_overrides.clear()
    qdrant_module.qdrant_client = None
    chat_api._openai_client = None
    get_auth_provider.cache_clear()


async def _seed(probe: RlsProbe) -> dict[str, object]:
    """Two organisations, each with an indexed document; org B's text is the secret."""
    session = probe.session
    own_org, own_user = await _make_org_and_user(session, slug_prefix="probe-own")
    foreign_org, foreign_user = await _make_org_and_user(session, slug_prefix="probe-fgn")
    own_doc, own_chunk = await _make_document_with_chunk(
        session, org=own_org, user=own_user, filename="hr.pdf", text="HR policy content."
    )
    foreign_doc, foreign_chunk = await _make_document_with_chunk(
        session, org=foreign_org, user=foreign_user, filename="secret.pdf", text=FOREIGN_TEXT
    )
    # The chat path writes sessions, messages, citations, usage and quota rows as the probe.
    await session.execute(
        text(f"GRANT UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {RLS_PROBE_ROLE}")
    )
    await session.execute(
        text(f"GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO {RLS_PROBE_ROLE}")
    )
    await probe.become_probe(organization_id=None, mode="strict")
    await session.commit()
    token = create_app_access_token(
        subject=own_user.external_auth_id,
        organization_id=str(own_org.id),
        expires_in_seconds=600,
    )
    return {
        "own_org": own_org.id,
        "foreign_org": foreign_org.id,
        "own_doc": own_doc.id,
        "own_chunk": own_chunk.id,
        "foreign_doc": foreign_doc.id,
        "foreign_chunk": foreign_chunk.id,
        "headers": _auth_headers(token, str(own_org.id)),
    }


async def _assert_probe_sees_only(probe: RlsProbe, organization_id: object) -> None:
    session = probe.session
    current = (
        await session.execute(text("SELECT current_user, current_setting('app.rls_mode', true)"))
    ).one()
    assert tuple(current) == (RLS_PROBE_ROLE, "strict"), "the request must run as the probe"
    for table in STRICT_TABLES_CHECKED:
        rows = await session.execute(text(f"SELECT DISTINCT organization_id FROM {table}"))
        assert {row[0] for row in rows} <= {organization_id}, table


async def _assert_owner_rows_belong_to(probe: RlsProbe, organization_id: UUID) -> None:
    """As the owner again: every chat row the request wrote is in the caller's org."""
    session = probe.session
    await probe.become_owner()
    for table in ("chat_sessions", "usage_events"):
        rows = await session.execute(
            text(f"SELECT DISTINCT organization_id FROM {table} WHERE organization_id <> :org"),
            {"org": organization_id},
        )
        assert rows.all() == [], table


async def test_probe_foreign_document_id_returns_404(
    probe_client: AsyncClient, rls_probe_session: RlsProbe
) -> None:
    seed = await _seed(rls_probe_session)
    response = await probe_client.post(
        "/api/v1/chat",
        headers=seed["headers"],
        json={"question": "What is in it?", "document_ids": [str(seed["foreign_doc"])]},
    )
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "document_not_found"
    await _assert_probe_sees_only(rls_probe_session, seed["own_org"])


async def test_probe_cross_org_vector_hit_yields_no_citation(
    probe_client: AsyncClient, rls_probe_session: RlsProbe, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed = await _seed(rls_probe_session)
    qdrant_module.qdrant_client = FakeQdrantClient(
        [
            FakeQdrantResult(
                score=0.99,
                payload=_qdrant_payload(
                    org_id=seed["foreign_org"],  # type: ignore[arg-type]
                    doc_id=seed["foreign_doc"],  # type: ignore[arg-type]
                    chunk_id=seed["foreign_chunk"],  # type: ignore[arg-type]
                    filename="secret.pdf",
                    text=FOREIGN_TEXT,
                ),
            )
        ]
    )
    fake_openai = FakeOpenAIClient(answer="Should not be called")
    monkeypatch.setattr(chat_api, "_openai_client", fake_openai)

    response = await probe_client.post(
        "/api/v1/chat",
        headers=seed["headers"],
        json={"question": "Any secret?", "top_k": 5, "rerank": False},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["citations"] == []
    assert FOREIGN_TEXT not in response.text
    assert str(seed["foreign_doc"]) not in response.text
    assert fake_openai.chat.completions.calls == []
    await _assert_probe_sees_only(rls_probe_session, seed["own_org"])
    await _assert_owner_rows_belong_to(rls_probe_session, seed["own_org"])  # type: ignore[arg-type]


async def test_probe_grounded_answer_cites_only_own_chunk(
    probe_client: AsyncClient, rls_probe_session: RlsProbe, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A model citation that points at a foreign chunk is dropped; the own chunk is kept."""
    seed = await _seed(rls_probe_session)
    qdrant_module.qdrant_client = FakeQdrantClient(
        [
            FakeQdrantResult(
                score=0.9,
                payload=_qdrant_payload(
                    org_id=seed["own_org"],  # type: ignore[arg-type]
                    doc_id=seed["own_doc"],  # type: ignore[arg-type]
                    chunk_id=seed["own_chunk"],  # type: ignore[arg-type]
                    filename="hr.pdf",
                    text="HR policy content.",
                ),
            ),
            FakeQdrantResult(
                score=0.95,
                payload=_qdrant_payload(
                    org_id=seed["foreign_org"],  # type: ignore[arg-type]
                    doc_id=seed["foreign_doc"],  # type: ignore[arg-type]
                    chunk_id=seed["foreign_chunk"],  # type: ignore[arg-type]
                    filename="secret.pdf",
                    text=FOREIGN_TEXT,
                ),
            ),
        ]
    )
    answer = (
        '{"answer":"HR policy content.","not_found":false,"citations":['
        f'{{"document_id":"{seed["foreign_doc"]}","chunk_id":"{seed["foreign_chunk"]}",'
        '"filename":"secret.pdf","page_number":1,"text_snippet":"secret"}]}'
    )
    fake_openai = FakeOpenAIClient(answer=answer)
    monkeypatch.setattr(chat_api, "_openai_client", fake_openai)

    response = await probe_client.post(
        "/api/v1/chat",
        headers=seed["headers"],
        json={"question": "What is the HR policy?", "top_k": 5, "rerank": False},
    )

    assert response.status_code == 200
    payload = response.json()
    cited = {citation["chunk_id"] for citation in payload["citations"]}
    assert str(seed["foreign_chunk"]) not in cited
    assert cited <= {str(seed["own_chunk"])}
    assert FOREIGN_TEXT not in response.text
    prompts = " ".join(str(call) for call in fake_openai.chat.completions.calls)
    assert FOREIGN_TEXT not in prompts, "a foreign chunk must never reach the prompt"
    await _assert_probe_sees_only(rls_probe_session, seed["own_org"])
    await _assert_owner_rows_belong_to(rls_probe_session, seed["own_org"])  # type: ignore[arg-type]


async def test_probe_unbound_strict_session_sees_no_tenant_rows(
    rls_probe_session: RlsProbe,
) -> None:
    """Control: with no tenant bound, strict hides both organisations' documents."""
    await _seed(rls_probe_session)
    count = await rls_probe_session.session.execute(text("SELECT count(*) FROM documents"))
    assert count.scalar_one() == 0
    own = uuid4()
    await rls_probe_session.become_probe(organization_id=own, mode="strict")
    count = await rls_probe_session.session.execute(text("SELECT count(*) FROM documents"))
    assert count.scalar_one() == 0
