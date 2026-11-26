"""Unit tests for app.application.chat.citation_access (R02-01)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from app.application.chat import citation_access
from app.auth.models import AuthenticatedPrincipal

pytestmark = pytest.mark.asyncio

ORG_ID = uuid4()
USER_ID = uuid4()


@dataclass(frozen=True)
class _Chunk:
    document_id: UUID | str
    label: str


@dataclass(frozen=True)
class _Doc:
    id: UUID


@dataclass(frozen=True)
class _Ctx:
    resource_id: str


def _principal(role: str) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=str(USER_ID),
        organization_id=str(ORG_ID),
        email="member@example.com",
        roles=[role],
        auth_provider="app",
    )


def _install_fakes(
    monkeypatch: pytest.MonkeyPatch,
    *,
    documents: list[_Doc],
    allowed_ids: set[str],
) -> dict[str, AsyncMock]:
    get_documents = AsyncMock(return_value=documents)
    collection_ids = AsyncMock(return_value=["col-1"])
    contexts = AsyncMock(side_effect=lambda *_a, **kw: [_Ctx(str(d.id)) for d in kw["documents"]])

    async def _filter(_principal: Any, _action: Any, ctxs: list[_Ctx], _db: Any) -> list[_Ctx]:
        return [c for c in ctxs if c.resource_id in allowed_ids]

    filter_mock = AsyncMock(side_effect=_filter)
    monkeypatch.setattr(citation_access._document_repository, "get_documents_by_ids", get_documents)
    monkeypatch.setattr(citation_access, "get_subject_accessible_collection_ids", collection_ids)
    monkeypatch.setattr(citation_access, "build_document_resource_contexts_batch", contexts)
    monkeypatch.setattr(
        citation_access._authorization_service, "filter_accessible_resources", filter_mock
    )
    return {"get_documents": get_documents, "filter": filter_mock, "contexts": contexts}


async def _run(principal_role: str, chunks: list[_Chunk]) -> list[_Chunk]:
    return await citation_access.filter_chunks_by_cite_access(
        AsyncMock(),
        principal=_principal(principal_role),
        organization_id=ORG_ID,
        user_id=USER_ID,
        user_roles=[principal_role],
        chunks=chunks,
    )


async def test_one_repository_call_for_many_chunks_and_order_preserved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    doc_a, doc_b = uuid4(), uuid4()
    chunks = [
        _Chunk(doc_b, "b1"),
        _Chunk(doc_a, "a1"),
        _Chunk(str(doc_b), "b2"),
        _Chunk(doc_a, "a2"),
        _Chunk(doc_a, "a3"),
    ]
    fakes = _install_fakes(
        monkeypatch, documents=[_Doc(doc_a), _Doc(doc_b)], allowed_ids={str(doc_a)}
    )

    kept = await _run("member", chunks)

    assert [c.label for c in kept] == ["a1", "a2", "a3"]
    fakes["get_documents"].assert_awaited_once()
    kwargs = fakes["get_documents"].await_args.kwargs
    assert kwargs["document_ids"] == [doc_b, doc_a]
    assert kwargs["organization_id"] == ORG_ID
    fakes["filter"].assert_awaited_once()


async def test_all_allowed_keeps_every_chunk_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    doc_a, doc_b = uuid4(), uuid4()
    chunks = [_Chunk(doc_b, "b1"), _Chunk(doc_a, "a1")]
    _install_fakes(
        monkeypatch,
        documents=[_Doc(doc_a), _Doc(doc_b)],
        allowed_ids={str(doc_a), str(doc_b)},
    )

    kept = await _run("viewer", chunks)

    assert [c.label for c in kept] == ["b1", "a1"]


@pytest.mark.parametrize("role", ["owner", "admin"])
async def test_owner_and_admin_short_circuit(monkeypatch: pytest.MonkeyPatch, role: str) -> None:
    chunks = [_Chunk(uuid4(), "x"), _Chunk(uuid4(), "y")]
    fakes = _install_fakes(monkeypatch, documents=[], allowed_ids=set())

    kept = await _run(role, chunks)

    assert [c.label for c in kept] == ["x", "y"]
    fakes["get_documents"].assert_not_awaited()


async def test_empty_input_short_circuits(monkeypatch: pytest.MonkeyPatch) -> None:
    fakes = _install_fakes(monkeypatch, documents=[], allowed_ids=set())

    assert await _run("member", []) == []
    fakes["get_documents"].assert_not_awaited()


async def test_missing_document_is_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    doc_a, missing = uuid4(), uuid4()
    chunks = [_Chunk(missing, "gone"), _Chunk(doc_a, "a1")]
    _install_fakes(monkeypatch, documents=[_Doc(doc_a)], allowed_ids={str(doc_a)})

    kept = await _run("member", chunks)

    assert [c.label for c in kept] == ["a1"]


async def test_no_documents_found_drops_everything_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chunks = [_Chunk(uuid4(), "x"), _Chunk(uuid4(), "y")]
    fakes = _install_fakes(monkeypatch, documents=[], allowed_ids=set())

    kept = await _run("member", chunks)

    assert kept == []
    fakes["filter"].assert_not_awaited()


async def test_malformed_document_id_is_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    doc_a = uuid4()
    chunks = [_Chunk("not-a-uuid", "bad"), _Chunk(doc_a, "a1")]
    fakes = _install_fakes(monkeypatch, documents=[_Doc(doc_a)], allowed_ids={str(doc_a)})

    kept = await _run("member", chunks)

    assert [c.label for c in kept] == ["a1"]
    assert fakes["get_documents"].await_args.kwargs["document_ids"] == [doc_a]


async def test_get_documents_by_ids_is_org_scoped(db_session: Any) -> None:
    from test_chat_query_api import _seed_document_with_chunk, _seed_principal

    from app.domains.documents.repositories.documents import DocumentRepository

    user, organization, other_org = await _seed_principal(db_session)
    document, _chunk = await _seed_document_with_chunk(
        db_session, organization=organization, uploader=user, filename="a.pdf", text="alpha"
    )
    repository = DocumentRepository()
    doc_id = document.id  # type: ignore[attr-defined]

    found = await repository.get_documents_by_ids(
        db_session, document_ids=[doc_id, uuid4()], organization_id=organization.id
    )
    other = await repository.get_documents_by_ids(
        db_session, document_ids=[doc_id], organization_id=other_org.id
    )
    trust = await repository.get_documents_by_ids_for_trust(
        db_session, document_ids=[doc_id], organization_id=organization.id
    )
    empty = await repository.get_documents_by_ids(
        db_session, document_ids=[], organization_id=organization.id
    )

    assert [d.id for d in found] == [doc_id]
    assert other == []
    assert [d.id for d in trust] == [doc_id]
    assert empty == []
