"""PostgreSQL: concurrent stage leases and RLS on the stage tables (R06-01)."""

from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest
from ingestion_golden_support import (
    FakeEmbeddings,  # noqa: F401  (sets the strict-settings environment first)
)
from sqlalchemy import delete, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.document import Document
from app.models.document_processing import DocumentProcessingStage, DocumentStageArtifact
from app.models.organization import Organization
from app.models.user import User
from app.workers.ingestion.store import DbStageStore, encode_artifact
from tests.conftest import RlsProbe

pytestmark = pytest.mark.requires_postgres


async def _seed(session: AsyncSession) -> tuple[UUID, UUID]:
    suffix = uuid4().hex[:10]
    org = Organization(name=f"Lease {suffix}", slug=f"lease-{suffix}")
    session.add(org)
    await session.flush()
    user = User(
        organization_id=org.id,
        external_auth_id=f"lease-{suffix}",
        email=f"lease-{suffix}@example.com",
    )
    session.add(user)
    await session.flush()
    document = Document(
        organization_id=org.id,
        uploaded_by_user_id=user.id,
        filename="lease.txt",
        file_type="txt",
        storage_bucket="documents",
        storage_object_key=f"uploads/{org.id}/{uuid4()}.txt",
        status="processing",
    )
    session.add(document)
    await session.flush()
    return org.id, document.id


@pytest.mark.parametrize("contenders", [2, 12])
async def test_concurrent_leases_have_exactly_one_winner(
    pg_session_factory: async_sessionmaker[AsyncSession], contenders: int
) -> None:
    async with pg_session_factory() as session:
        org_id, document_id = await _seed(session)
        await session.commit()
    try:
        stores = [
            DbStageStore(
                pg_session_factory, organization_id=org_id, document_id=document_id, run_id="r"
            )
            for _ in range(contenders)
        ]
        results = await asyncio.gather(
            *(store.lease("embed", owner=f"task-{i}") for i, store in enumerate(stores))
        )
        winners = [result for result in results if result is not None]
        assert len(winners) == 1
        records = await stores[0].load()
        assert records["embed"].owner_task_id == winners[0].owner_task_id
        assert records["embed"].attempt == 1
    finally:
        async with pg_session_factory() as session:
            await session.execute(delete(Organization).where(Organization.id == org_id))
            await session.commit()


async def _insert_rows(session: AsyncSession, org_id: UUID, document_id: UUID) -> None:
    session.add(
        DocumentProcessingStage(
            organization_id=org_id, document_id=document_id, run_id="r", stage="extract"
        )
    )
    content = encode_artifact({"page_number": 1, "text": "private"})
    session.add(
        DocumentStageArtifact(
            organization_id=org_id,
            document_id=document_id,
            run_id="r",
            stage="extract",
            part=0,
            content=content,
            content_bytes=len(content),
        )
    )
    await session.flush()


@pytest.mark.parametrize("table", ["document_processing_stages", "document_stage_artifacts"])
async def test_strict_rls_isolates_stage_tables(rls_probe_session: RlsProbe, table: str) -> None:
    session = rls_probe_session.session
    org_a, doc_a = await _seed(session)
    org_b, doc_b = await _seed(session)
    await _insert_rows(session, org_a, doc_a)
    await _insert_rows(session, org_b, doc_b)

    await rls_probe_session.become_probe(organization_id=org_a, mode="strict")
    rows = await session.execute(text(f"SELECT DISTINCT organization_id FROM {table}"))
    assert {row[0] for row in rows} == {org_a}

    with pytest.raises(DBAPIError, match="row-level security"):
        async with session.begin_nested():
            await session.execute(
                text(
                    "INSERT INTO document_processing_stages "
                    "(id, organization_id, document_id, run_id, stage, status, attempt, metrics,"
                    " created_at, updated_at) VALUES (:id, :org, :doc, 'x', 'chunk', 'pending',"
                    " 0, '{}', now(), now())"
                ),
                {"id": uuid4(), "org": org_b, "doc": doc_b},
            )

    await rls_probe_session.become_probe(organization_id=None, mode="strict")
    count = await session.execute(text(f"SELECT count(*) FROM {table}"))
    assert int(count.scalar_one()) == 0
