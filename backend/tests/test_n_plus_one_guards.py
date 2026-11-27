"""R04-03: list endpoints issue a constant number of SQL statements.

Each test measures one request with 2 rows and again with 12 rows; the counts must be equal
and stay under an explicit per-endpoint bound, so a new per-row query fails here.
"""

from __future__ import annotations

import secrets
from collections.abc import Awaitable, Callable
from uuid import uuid4

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.chat.message_citations import persist_answer_citations
from app.auth.dependencies import ensure_document_ids_access
from app.auth.models import AuthenticatedPrincipal
from app.domains.chat.repositories.share import ChatShareRepository
from app.domains.chat.schemas.chat import ChatCitationResponse
from app.models.citation import Citation
from app.models.enums import ChatRole
from tests.list_endpoint_seed import (
    Tenant,
    api_client,
    chat_repository,
    configure_app_auth,
    seed_chat_session,
    seed_collection,
    seed_connection,
    seed_document,
    seed_evaluation_set,
    seed_tenant,
    seed_turns,
)
from tests.query_count import count_queries

pytestmark = [pytest.mark.asyncio, pytest.mark.both_dialects]


@pytest.fixture(autouse=True)
def _app_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_app_auth(monkeypatch)


# Upper bounds per request, including authentication. They are deliberately loose enough to
# absorb unrelated auth changes but far below what a per-row query at 12 rows would cost.
MAX_MESSAGES_LIST = 16
MAX_SHARED_SESSION = 18
MAX_DOCUMENTS_LIST = 16
MAX_COLLECTIONS_LIST = 14
MAX_CONNECTIONS_LIST = 14
MAX_EVALUATION_SETS_LIST = 14
MAX_ENSURE_DOCUMENT_IDS = 2
MAX_CITATION_PERSIST = 1


async def _count_get(
    client: AsyncClient, db_session: AsyncSession, url: str, tenant: Tenant
) -> tuple[int, dict]:
    async with count_queries(db_session) as counter:
        response = await client.get(url, headers=tenant.headers)
    assert response.status_code == 200, response.text
    return counter.count, response.json()


async def _assert_constant(
    measure: Callable[[], Awaitable[int]],
    grow: Callable[[], Awaitable[None]],
    bound: int,
) -> None:
    small = await measure()
    await grow()
    large = await measure()
    assert small == large, f"statement count grew with rows: {small} -> {large}"
    assert large <= bound, f"{large} statements exceeds the bound {bound}"


async def test_count_queries_ignores_session_context_marker(db_session: AsyncSession) -> None:
    from sqlalchemy import text

    async with count_queries(db_session) as counter:
        await db_session.execute(text("/* rudix:session-context */ SELECT 1"))
        await db_session.execute(text("SELECT 2"))
    assert counter.count == 1
    assert counter.matching("select 2")


async def test_session_messages_constant(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    tenant = await seed_tenant(db_session)
    document, chunks = await seed_document(db_session, tenant)
    chat_session = await seed_chat_session(db_session, tenant)
    await seed_turns(db_session, chat_session, turns=1, document=document, chunk=chunks[0])
    await db_session.commit()
    url = f"/api/v1/chat/sessions/{chat_session.id}/messages"

    async with api_client(monkeypatch, db_session) as client:

        async def measure() -> int:
            count, body = await _count_get(client, db_session, url, tenant)
            assistant = [item for item in body["items"] if item["role"] == "assistant"]
            assert all(len(item["citations"]) == 2 for item in assistant)
            return count

        async def grow() -> None:
            await seed_turns(db_session, chat_session, turns=5, document=document, chunk=chunks[0])
            await db_session.commit()

        await _assert_constant(measure, grow, MAX_MESSAGES_LIST)


async def test_shared_session_constant(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    tenant = await seed_tenant(db_session)
    document, chunks = await seed_document(db_session, tenant)
    chat_session = await seed_chat_session(db_session, tenant)
    await seed_turns(db_session, chat_session, turns=1, document=document, chunk=chunks[0])
    token = secrets.token_urlsafe(24)
    await ChatShareRepository().create_chat_share(
        db_session,
        chat_session_id=chat_session.id,
        organization_id=tenant.org_id,
        shared_by_user_id=tenant.user.id,
        token=token,
    )
    await db_session.commit()
    url = f"/api/v1/chat/shared/{token}"

    async with api_client(monkeypatch, db_session) as client:

        async def measure() -> int:
            count, body = await _count_get(client, db_session, url, tenant)
            assistant = [item for item in body["messages"] if item["role"] == "assistant"]
            assert assistant and all(len(item["citations"]) == 2 for item in assistant)
            return count

        async def grow() -> None:
            await seed_turns(db_session, chat_session, turns=5, document=document, chunk=chunks[0])
            await db_session.commit()

        await _assert_constant(measure, grow, MAX_SHARED_SESSION)


async def test_documents_list_constant(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    tenant = await seed_tenant(db_session)
    for _ in range(2):
        await seed_document(db_session, tenant, chunks=3)
    await db_session.commit()

    async with api_client(monkeypatch, db_session) as client:

        async def measure() -> int:
            count, body = await _count_get(client, db_session, "/api/v1/documents?limit=50", tenant)
            assert all(item["chunk_count"] == 3 for item in body["items"])
            return count

        async def grow() -> None:
            for _ in range(10):
                await seed_document(db_session, tenant, chunks=3)
            await db_session.commit()

        await _assert_constant(measure, grow, MAX_DOCUMENTS_LIST)


async def test_collections_list_constant(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    tenant = await seed_tenant(db_session)
    indexed, _ = await seed_document(db_session, tenant)
    uploaded, _ = await seed_document(db_session, tenant, status="uploaded")
    for _ in range(2):
        await seed_collection(db_session, tenant, documents=[indexed, uploaded])
    await db_session.commit()

    async with api_client(monkeypatch, db_session) as client:

        async def measure() -> int:
            count, body = await _count_get(
                client, db_session, "/api/v1/collections?limit=50", tenant
            )
            assert all(item["document_count"] == 2 for item in body["items"])
            assert all(item["indexed_count"] == 1 for item in body["items"])
            return count

        async def grow() -> None:
            for _ in range(10):
                await seed_collection(db_session, tenant, documents=[indexed, uploaded])
            await db_session.commit()

        await _assert_constant(measure, grow, MAX_COLLECTIONS_LIST)


async def test_document_collections_constant(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    tenant = await seed_tenant(db_session)
    document, _ = await seed_document(db_session, tenant)
    for _ in range(2):
        await seed_collection(db_session, tenant, documents=[document])
    await db_session.commit()
    url = f"/api/v1/documents/{document.id}/collections"

    async with api_client(monkeypatch, db_session) as client:

        async def measure() -> int:
            count, body = await _count_get(client, db_session, url, tenant)
            assert all(item["indexed_count"] == 1 for item in body["items"])
            return count

        async def grow() -> None:
            for _ in range(10):
                await seed_collection(db_session, tenant, documents=[document])
            await db_session.commit()

        await _assert_constant(measure, grow, MAX_COLLECTIONS_LIST)


async def test_connections_list_constant(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    tenant = await seed_tenant(db_session)
    for _ in range(2):
        await seed_connection(db_session, tenant, indexed_documents=2)
    await db_session.commit()

    async with api_client(monkeypatch, db_session) as client:

        async def measure() -> int:
            count, body = await _count_get(
                client, db_session, "/api/v1/connectors/connections", tenant
            )
            assert all(item["indexed_document_count"] == 2 for item in body["items"])
            return count

        async def grow() -> None:
            for _ in range(10):
                await seed_connection(db_session, tenant, indexed_documents=2)
            await db_session.commit()

        await _assert_constant(measure, grow, MAX_CONNECTIONS_LIST)


async def test_available_connections_constant(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    tenant = await seed_tenant(db_session)
    for _ in range(2):
        await seed_connection(db_session, tenant, indexed_documents=1)
    await db_session.commit()

    async with api_client(monkeypatch, db_session) as client:

        async def measure() -> int:
            count, body = await _count_get(
                client, db_session, "/api/v1/connectors/available", tenant
            )
            assert all(item["indexed_document_count"] == 1 for item in body["items"])
            return count

        async def grow() -> None:
            for _ in range(10):
                await seed_connection(db_session, tenant, indexed_documents=1)
            await db_session.commit()

        await _assert_constant(measure, grow, MAX_CONNECTIONS_LIST)


async def test_evaluation_sets_list_constant(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    tenant = await seed_tenant(db_session)
    for _ in range(2):
        await seed_evaluation_set(db_session, tenant, questions=3)
    await db_session.commit()

    async with api_client(monkeypatch, db_session) as client:

        async def measure() -> int:
            count, body = await _count_get(
                client, db_session, "/api/v1/evaluation-sets?limit=50", tenant
            )
            assert all(item["question_count"] == 3 for item in body["items"])
            return count

        async def grow() -> None:
            for _ in range(10):
                await seed_evaluation_set(db_session, tenant, questions=3)
            await db_session.commit()

        await _assert_constant(measure, grow, MAX_EVALUATION_SETS_LIST)


def _principal(tenant: Tenant) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=str(tenant.user.id),
        organization_id=str(tenant.org_id),
        roles=["owner"],
        auth_provider="app",
    )


async def test_ensure_document_ids_access_constant(db_session: AsyncSession) -> None:
    tenant = await seed_tenant(db_session)
    _, connector_docs = await seed_connection(db_session, tenant, indexed_documents=12)
    plain_docs = [(await seed_document(db_session, tenant, chunks=0))[0] for _ in range(12)]
    await db_session.commit()
    principal = _principal(tenant)

    async def measure(size: int) -> int:
        ids = [str(d.id) for d in plain_docs[:size]] + [str(d.id) for d in connector_docs[:size]]
        async with count_queries(db_session) as counter:
            result = await ensure_document_ids_access(
                document_ids=ids, principal=principal, db_session=db_session
            )
        assert [str(item) for item in result] == ids
        return counter.count

    small, large = await measure(2), await measure(12)
    assert small == large <= MAX_ENSURE_DOCUMENT_IDS


async def test_ensure_document_ids_access_keeps_404_semantics(db_session: AsyncSession) -> None:
    tenant = await seed_tenant(db_session)
    other = await seed_tenant(db_session)
    own, _ = await seed_document(db_session, tenant, chunks=0)
    foreign, _ = await seed_document(db_session, other, chunks=0)
    _, deleted_docs = await seed_connection(db_session, tenant, indexed_documents=1, deleted=True)
    _, paused_docs = await seed_connection(
        db_session, tenant, indexed_documents=1, status="disabled"
    )
    await db_session.commit()
    principal = _principal(tenant)

    # Duplicates collapse and the input order is kept.
    result = await ensure_document_ids_access(
        document_ids=[str(own.id), str(own.id)], principal=principal, db_session=db_session
    )
    assert result == [own.id]
    assert (
        await ensure_document_ids_access(
            document_ids=[], principal=principal, db_session=db_session
        )
        == []
    )
    for bad in (foreign.id, uuid4(), deleted_docs[0].id, paused_docs[0].id):
        with pytest.raises(HTTPException) as exc_info:
            await ensure_document_ids_access(
                document_ids=[str(own.id), str(bad)], principal=principal, db_session=db_session
            )
        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Document not found"


def _citation(document_id: str, chunk_id: str, index: int) -> ChatCitationResponse:
    return ChatCitationResponse(
        citation_id=None,
        document_id=document_id,
        chunk_id=chunk_id,
        filename="seed.pdf",
        page_number=1,
        score=0.9,
        similarity_score=0.9 - index / 100,
        rerank_score=0.5,
        rerank_rank=index,
        text_snippet=f"snippet {index}",
    )


async def test_answer_citations_inserted_in_one_statement(db_session: AsyncSession) -> None:
    tenant = await seed_tenant(db_session)
    document, chunks = await seed_document(db_session, tenant)
    chat_session = await seed_chat_session(db_session, tenant)
    await db_session.commit()

    for size in (2, 12):
        answer = await chat_repository.create_chat_message(
            db_session,
            chat_session_id=chat_session.id,
            role=ChatRole.assistant.value,
            content="answer",
        )
        citations = [_citation(str(document.id), str(chunks[0].id), i) for i in range(size)]
        # A citation with a non-UUID ID is skipped, as before.
        citations.insert(1, _citation("not-a-uuid", str(chunks[0].id), 99))
        async with count_queries(db_session) as counter:
            persisted = await persist_answer_citations(
                db_session,
                chat_message_id=answer.id,
                citations=citations,
                rerank_applied=False,
            )
        assert counter.count <= MAX_CITATION_PERSIST
        assert len(counter.matching("INSERT INTO citations")) == 1
        assert [c.text_snippet for c in persisted] == [f"snippet {i}" for i in range(size)]
        assert all(c.citation_id for c in persisted)
        await db_session.commit()

        loaded = await chat_repository.list_citations_for_messages_with_filename(
            db_session, chat_message_ids=[answer.id]
        )
        # Read back in insertion order, with the IDs the response carried.
        assert [str(c.id) for c, _ in loaded[answer.id]] == [c.citation_id for c in persisted]
        assert all(c.rerank_score is None for c, _ in loaded[answer.id])
        assert all(filename == document.filename for _, filename in loaded[answer.id])

    total = (await db_session.execute(select(func.count(Citation.id)))).scalar_one()
    assert total == 14


async def test_citations_bulk_empty_is_a_no_op(db_session: AsyncSession) -> None:
    async with count_queries(db_session) as counter:
        assert (
            await chat_repository.create_citations_bulk(
                db_session, chat_message_id=uuid4(), rows=[]
            )
            == []
        )
        assert (
            await chat_repository.list_citations_for_messages_with_filename(
                db_session, chat_message_ids=[]
            )
            == {}
        )
    assert counter.count == 0
