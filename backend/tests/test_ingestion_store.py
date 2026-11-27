"""Stage store: leases, stage rows, artifacts, cleanup, deletion (R06-01)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from ingestion_golden_support import (
    FakeEmbeddings,  # noqa: F401  (sets the strict-settings environment first)
)
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.models.document import Document
from app.models.document_processing import DocumentProcessingStage, DocumentStageArtifact
from app.models.organization import Organization
from app.models.user import User
from app.workers.ingestion.errors import DocumentPipelinePermanentError
from app.workers.ingestion.store import (
    COMPLETED,
    FAILED,
    PENDING,
    RUNNING,
    DbStageStore,
    MemoryStageStore,
    checked_artifact,
    decode_artifact,
    encode_artifact,
)

pytestmark = pytest.mark.both_dialects


async def _seed_document(session: AsyncSession) -> tuple[UUID, UUID]:
    suffix = uuid4().hex[:10]
    org = Organization(name=f"Store {suffix}", slug=f"store-{suffix}")
    session.add(org)
    await session.flush()
    user = User(
        organization_id=org.id,
        external_auth_id=f"store-{suffix}",
        email=f"store-{suffix}@example.com",
    )
    session.add(user)
    await session.flush()
    document = Document(
        organization_id=org.id,
        uploaded_by_user_id=user.id,
        filename="store.txt",
        file_type="txt",
        storage_bucket="documents",
        storage_object_key=f"uploads/{org.id}/{uuid4()}.txt",
        status="processing",
    )
    session.add(document)
    await session.commit()
    return org.id, document.id


def _factory(db_session: AsyncSession) -> Any:
    if db_session.bind.dialect.name == "sqlite":
        return async_sessionmaker(bind=db_session.bind, expire_on_commit=False)
    # PostgreSQL: join the test's outer transaction (rolled back at teardown).
    return async_sessionmaker(
        bind=db_session.bind, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )


async def _store(db_session: AsyncSession, run_id: str = "run-a") -> DbStageStore:
    org_id, document_id = await _seed_document(db_session)
    return DbStageStore(
        _factory(db_session), organization_id=org_id, document_id=document_id, run_id=run_id
    )


async def test_lease_is_exclusive_until_owner_or_stale_heartbeat(db_session: AsyncSession) -> None:
    store = await _store(db_session)
    first = await store.lease("embed", owner="task-1")
    assert first is not None and first.status == RUNNING and first.attempt == 1
    assert await store.lease("embed", owner="task-2") is None
    again = await store.lease("embed", owner="task-1")
    assert again is not None and again.attempt == 2

    stale = datetime.now(UTC) - timedelta(seconds=settings.ingest_stage_lease_seconds + 5)
    async with _factory(db_session)() as session:
        await session.execute(
            update(DocumentProcessingStage)
            .where(DocumentProcessingStage.document_id == store.document_id)
            .values(heartbeat_at=stale)
        )
        await session.commit()
    taken = await store.lease("embed", owner="task-2")
    assert taken is not None and taken.owner_task_id == "task-2" and taken.attempt == 3


async def test_completed_failed_and_reset_transitions(db_session: AsyncSession) -> None:
    store = await _store(db_session)
    assert await store.lease("chunk", owner="t") is not None
    await store.mark_failed("chunk", error_code="EMPTY_CHUNK_SET")
    records = await store.load()
    assert records["chunk"].status == FAILED
    assert records["chunk"].error_code == "EMPTY_CHUNK_SET"
    assert await store.lease("chunk", owner="other") is not None  # failed is leasable

    await store.heartbeat("chunk")
    await store.mark_completed("chunk", metrics={"chunk_count": 3}, artifact_ref="db")
    records = await store.load()
    assert records["chunk"].status == COMPLETED
    assert records["chunk"].metrics == {"chunk_count": 3}
    assert await store.lease("chunk", owner="other") is None  # completed is final

    await store.reset("chunk")
    assert (await store.load())["chunk"].status == PENDING
    assert await store.lease("chunk", owner="other") is not None


async def test_artifacts_round_trip_in_part_order(db_session: AsyncSession) -> None:
    store = await _store(db_session)
    parts = {index: {"page_number": index + 1, "text": f"page {index}"} for index in range(20)}
    await store.write_artifacts("extract", parts, replace_stage=True)
    assert await store.artifact_parts("extract") == set(range(20))
    read = [item async for item in store.iter_artifacts("extract")]
    assert [item["page_number"] for item in read] == list(range(1, 21))

    await store.write_artifacts("embed", {1: {"batch": 1}}, replace_stage=False)
    await store.write_artifacts("embed", {1: {"batch": "again"}}, replace_stage=False)
    assert [item async for item in store.iter_artifacts("embed")] == [{"batch": "again"}]

    await store.write_artifacts("extract", {0: {"page_number": 1}}, replace_stage=True)
    assert await store.artifact_parts("extract") == {0}

    await store.delete_run_artifacts()
    assert await store.artifact_parts("extract") == set()
    assert await store.artifact_parts("embed") == set()


async def test_purge_other_runs_keeps_this_run_and_other_documents(
    db_session: AsyncSession,
) -> None:
    store = await _store(db_session, run_id="run-new")
    factory = _factory(db_session)
    old = DbStageStore(
        factory,
        organization_id=store.organization_id,
        document_id=store.document_id,
        run_id="run-old",
    )
    other = await _store(db_session, run_id="run-old")
    for target in (store, old, other):
        await target.lease("extract", owner="t")
        await target.write_artifacts("extract", {0: {"text": "x"}}, replace_stage=True)

    await store.purge_other_runs()
    assert set(await store.load()) == {"extract"}
    assert await old.load() == {}
    assert await old.artifact_parts("extract") == set()
    assert set(await other.load()) == {"extract"}
    assert await other.artifact_parts("extract") == {0}


def test_artifact_codec_and_size_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"text": "Grüße — 漢字", "n": [1, 2]}
    assert decode_artifact(encode_artifact(payload)) == payload
    monkeypatch.setattr(settings, "ingest_artifact_max_part_bytes", 16)
    with pytest.raises(DocumentPipelinePermanentError) as raised:
        checked_artifact("extract", {"text": "x" * 1000 + str(uuid4())})
    assert raised.value.error_details["code"] == "STAGE_ARTIFACT_TOO_LARGE"


def test_memory_store_matches_the_contract() -> None:
    async def _run() -> None:
        store = MemoryStageStore(run_id="eval")
        assert await store.lease("extract", owner="a") is not None
        assert await store.lease("extract", owner="b") is None
        await store.heartbeat("extract")
        await store.mark_failed("extract", error_code="X")
        assert (await store.load())["extract"].status == FAILED
        assert await store.lease("extract", owner="b") is not None
        await store.mark_completed("extract", metrics={"page_count": 1})
        assert await store.lease("extract", owner="b") is None
        await store.reset("extract")
        assert (await store.load())["extract"].status == PENDING
        await store.reset("missing")
        await store.write_artifacts("extract", {1: {"p": 2}, 0: {"p": 1}}, replace_stage=True)
        assert [item async for item in store.iter_artifacts("extract")] == [{"p": 1}, {"p": 2}]
        assert await store.artifact_parts("extract") == {0, 1}
        await store.purge_other_runs()
        await store.delete_run_artifacts()
        assert await store.artifact_parts("extract") == set()

    asyncio.run(_run())


async def test_document_deletion_removes_stage_state_of_that_document_only(
    db_session: AsyncSession,
) -> None:
    from app.workers.ingestion.deletion import delete_stage_state

    store = await _store(db_session)
    other = await _store(db_session)
    for target in (store, other):
        await target.lease("embed", owner="t")
        await target.write_artifacts("embed", {0: {"batch": 0}}, replace_stage=False)

    async with _factory(db_session)() as session:
        await delete_stage_state(
            session, organization_id=store.organization_id, document_id=store.document_id
        )
        await session.commit()

    async def _count(model: Any, document_id: UUID) -> int:
        async with _factory(db_session)() as session:
            stmt = select(func.count()).where(model.document_id == document_id)
            return int((await session.execute(stmt)).scalar_one())

    assert await _count(DocumentStageArtifact, store.document_id) == 0
    assert await _count(DocumentProcessingStage, store.document_id) == 0
    assert await _count(DocumentStageArtifact, other.document_id) == 1
    assert await _count(DocumentProcessingStage, other.document_id) == 1

    # Deleting a document row cascades to whatever stage state is left.
    async with _factory(db_session)() as session:
        await session.execute(delete(Document).where(Document.id == other.document_id))
        await session.commit()
    if db_session.bind.dialect.name == "postgresql":
        assert await _count(DocumentStageArtifact, other.document_id) == 0
        assert await _count(DocumentProcessingStage, other.document_id) == 0
