"""R07-06: ``chunk_id`` filter on ``GET /documents/{document_id}/chunks``."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.domains.documents.repositories.documents import DocumentRepository
from tests.list_endpoint_seed import api_client, seed_document, seed_tenant

document_repository = DocumentRepository()


@pytest.mark.asyncio
async def test_chunk_id_filter_returns_only_that_chunk(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    async with api_client(monkeypatch, db_session) as client:
        tenant = await seed_tenant(db_session)
        document, chunks = await seed_document(db_session, tenant, chunks=4)
        wanted = chunks[2]

        response = await client.get(
            f"/api/v1/documents/{document.id}/chunks",
            headers=tenant.headers,
            params={"chunk_id": str(wanted.id), "include_full_text": "true"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert [item["chunk_id"] for item in payload["items"]] == [str(wanted.id)]
    assert payload["items"][0]["chunk_index"] == wanted.chunk_index
    assert payload["items"][0]["text"] == wanted.text


@pytest.mark.asyncio
async def test_chunk_id_of_another_document_returns_empty_page(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    async with api_client(monkeypatch, db_session) as client:
        tenant = await seed_tenant(db_session)
        document, _ = await seed_document(db_session, tenant, chunks=2)
        _, other_chunks = await seed_document(db_session, tenant, chunks=1)

        response = await client.get(
            f"/api/v1/documents/{document.id}/chunks",
            headers=tenant.headers,
            params={"chunk_id": str(other_chunks[0].id)},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["items"] == []
    assert payload["total"] == 0


@pytest.mark.asyncio
async def test_chunk_id_filter_keeps_cross_organisation_404(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    async with api_client(monkeypatch, db_session) as client:
        tenant = await seed_tenant(db_session)
        foreign = await seed_tenant(db_session)
        foreign_document, foreign_chunks = await seed_document(db_session, foreign, chunks=1)

        response = await client.get(
            f"/api/v1/documents/{foreign_document.id}/chunks",
            headers=tenant.headers,
            params={"chunk_id": str(foreign_chunks[0].id)},
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "Document not found"


@pytest.mark.asyncio
async def test_invalid_chunk_id_is_rejected(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    async with api_client(monkeypatch, db_session) as client:
        tenant = await seed_tenant(db_session)
        document, _ = await seed_document(db_session, tenant, chunks=1)

        response = await client.get(
            f"/api/v1/documents/{document.id}/chunks",
            headers=tenant.headers,
            params={"chunk_id": "not-a-uuid"},
        )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_without_chunk_id_listing_is_unchanged(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    async with api_client(monkeypatch, db_session) as client:
        tenant = await seed_tenant(db_session)
        document, chunks = await seed_document(db_session, tenant, chunks=3)

        response = await client.get(
            f"/api/v1/documents/{document.id}/chunks",
            headers=tenant.headers,
            params={"limit": 2, "offset": 1},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 3
    assert [item["chunk_id"] for item in payload["items"]] == [
        str(chunks[1].id),
        str(chunks[2].id),
    ]


@pytest.mark.asyncio
async def test_repository_chunk_id_filter_stays_within_document_and_index_version(
    db_session: AsyncSession,
) -> None:
    tenant = await seed_tenant(db_session)
    document, chunks = await seed_document(db_session, tenant, chunks=2)

    found = await document_repository.list_document_chunks_paginated(
        db_session,
        document_id=document.id,
        index_version=settings.document_index_version,
        chunk_id=chunks[1].id,
    )
    assert [chunk.id for chunk in found] == [chunks[1].id]

    stale_version = await document_repository.count_document_chunks(
        db_session,
        document_id=document.id,
        index_version=f"{settings.document_index_version}-other",
        chunk_id=chunks[1].id,
    )
    assert stale_version == 0

    unknown = await document_repository.count_document_chunks(
        db_session,
        document_id=document.id,
        index_version=settings.document_index_version,
        chunk_id=uuid4(),
    )
    assert unknown == 0
