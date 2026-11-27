"""Distributed ingestion chain on PostgreSQL, including strict row-level security (R06-01).

The strict-RLS tests run every task session as the non-owner probe role of
``tests/test_rls_enforcement_pg.py`` (``rudix_rls_probe``: NOSUPERUSER, NOBYPASSRLS), so the
database policies apply to worker writes. Seeding and assertions use the owner connection;
``maintenance_session()`` stands for the ``BYPASSRLS`` maintenance role.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from ingestion_chain_support import (
    ALL_STAGES,
    PROFILE,
    ChainHarness,
    WorkerKilled,
    chain_pg,  # noqa: F401  (fixture)
    state,
)
from ingestion_golden_support import (
    IngestionEnv,
    ingestion_env_pg,  # noqa: F401  (fixture)
)
from sqlalchemy import event, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import RlsEnforcement, settings
from app.db import session as db_session_module
from app.models.document import Document, DocumentChunk
from app.models.document_processing import DocumentProcessingStage
from app.models.enums import DocumentStatus
from app.models.failed_job import FailedJob
from app.models.usage import AuditLog, UsageEvent
from app.workers import document_tasks, status_tracking
from app.workers.ingestion.stages.base import StageName
from tests.conftest import RLS_PROBE_ROLE

pytestmark = pytest.mark.requires_postgres


def test_kill_during_embed_resumes_at_embed_on_postgres(chain_pg: ChainHarness) -> None:  # noqa: F811
    env = chain_pg.env
    seeded = env.seed()
    armed = {"on": True}

    def _before(call_index: int) -> None:
        if armed["on"] and call_index == 1:
            armed["on"] = False
            raise WorkerKilled("embed")

    env.fakes.embeddings.before_call = _before
    with pytest.raises(WorkerKilled):
        chain_pg.process(seeded, chunking_profile_config=PROFILE)
    killed = chain_pg.last(StageName.embed)
    stages_before = len(chain_pg.messages)
    chain_pg.redeliver(killed)
    # Resumed at embed: the redelivery dispatched only the stages after it.
    assert chain_pg.stages()[stages_before:] == ["index", "finalize", "graph_extract"]
    final = env.run_async(state(env, seeded))
    assert final["status"] == DocumentStatus.indexed.value
    assert final["chunk_count"] == 6 and final["usage"] == 1 and final["audits"] == 1
    assert final["completed"] == ALL_STAGES
    assert env.fakes.minio.reads == 1
    embedded = [cid for batch in env.fakes.embeddings.batches for cid in batch]
    assert len(embedded) == len(set(embedded)) == 6
    assert env.fakes.qdrant.points == final["point_ids"]
    assert final["pipeline_runs"] == 1


def test_duplicate_finalize_after_commit_is_reported_once_on_postgres(
    chain_pg: ChainHarness,  # noqa: F811
) -> None:
    env = chain_pg.env
    seeded = env.seed()
    chain_pg.process(seeded, chunking_profile_config=PROFILE)
    for number, message in enumerate(list(chain_pg.messages)):
        chain_pg.redeliver(message, task_id=f"again-{number}")
    final = env.run_async(state(env, seeded))
    assert final["usage"] == 1 and final["audits"] == 1
    assert final["status"] == DocumentStatus.indexed.value


# ── strict row-level security through the probe role ──────────────────────────────────


@pytest.fixture
def probe_factory(chain_pg: ChainHarness) -> Iterator[async_sessionmaker[AsyncSession]]:  # noqa: F811
    env = chain_pg.env
    url = os.environ["TEST_DATABASE_URL"]
    env.run_async(_grant_probe(env))
    engine = create_async_engine(url, poolclass=NullPool)

    @event.listens_for(engine.sync_engine, "connect")
    def _become_probe(dbapi_connection: Any, _: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute(f"SET ROLE {RLS_PROBE_ROLE}")
        cursor.close()

    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    owner = env.factory

    @asynccontextmanager
    async def _maintenance() -> AsyncIterator[AsyncSession]:
        async with owner() as session:
            session.info["rls_maintenance"] = True
            yield session

    env.monkeypatch.setattr(settings, "rls_enforcement", RlsEnforcement.strict)
    for module in (document_tasks, status_tracking, db_session_module):
        env.monkeypatch.setattr(module, "SessionLocal", factory)
    env.monkeypatch.setattr(db_session_module, "maintenance_session", _maintenance)
    try:
        yield factory
    finally:
        env.run_async(engine.dispose())
        env.run_async(_revoke_probe(env))


async def _grant_probe(env: IngestionEnv) -> None:
    async with env.factory() as session, session.begin():
        await session.execute(
            text(
                "DO $$ BEGIN "
                f"IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{RLS_PROBE_ROLE}') "
                f"THEN CREATE ROLE {RLS_PROBE_ROLE} NOLOGIN NOSUPERUSER NOBYPASSRLS; END IF; "
                "EXCEPTION WHEN duplicate_object THEN NULL; END $$"
            )
        )
        await session.execute(text(f"GRANT USAGE ON SCHEMA public TO {RLS_PROBE_ROLE}"))
        await session.execute(
            text(
                "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public "
                f"TO {RLS_PROBE_ROLE}"
            )
        )
        await session.execute(
            text(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {RLS_PROBE_ROLE}")
        )


async def _revoke_probe(env: IngestionEnv) -> None:
    async with env.factory() as session, session.begin():
        await session.execute(
            text(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {RLS_PROBE_ROLE}")
        )
        await session.execute(
            text(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {RLS_PROBE_ROLE}")
        )
        await session.execute(text(f"REVOKE USAGE ON SCHEMA public FROM {RLS_PROBE_ROLE}"))


async def _probe_is_unprivileged(factory: async_sessionmaker[AsyncSession]) -> bool:
    async with factory() as session:
        row = (
            await session.execute(
                text(
                    "SELECT current_user, r.rolsuper, r.rolbypassrls FROM pg_roles r "
                    "WHERE r.rolname = current_user"
                )
            )
        ).one()
    return row[0] == RLS_PROBE_ROLE and not row[1] and not row[2]


def test_full_chain_succeeds_under_strict_rls_as_the_probe_role(
    chain_pg: ChainHarness,  # noqa: F811
    probe_factory: async_sessionmaker[AsyncSession],
) -> None:
    env = chain_pg.env
    assert env.run_async(_probe_is_unprivileged(probe_factory))
    seeded = env.seed()
    chain_pg.process(seeded, chunking_profile_config=PROFILE)
    final = env.run_async(state(env, seeded))
    assert final["status"] == DocumentStatus.indexed.value
    assert final["completed"] == ALL_STAGES
    assert final["chunk_count"] == 6 and final["usage"] == 1 and final["audits"] == 1
    assert final["failed_jobs"] == []


async def _footprint(env: IngestionEnv, document_id: Any, orgs: list[Any]) -> dict[str, Any]:
    async with env.factory() as session:
        document = (
            await session.execute(select(Document).where(Document.id == document_id))
        ).scalar_one()

        async def _count(model: Any, *where: Any) -> int:
            stmt = select(func.count()).select_from(model).where(*where)
            return int((await session.execute(stmt)).scalar_one())

        return {
            "status": document.status,
            "claim": document.processing_task_id,
            "updated_at": document.updated_at,
            "graph": document.graph_extraction_status,
            "stages": await _count(
                DocumentProcessingStage, DocumentProcessingStage.document_id == document_id
            ),
            "chunks": await _count(DocumentChunk, DocumentChunk.document_id == document_id),
            "failed_jobs": await _count(FailedJob, FailedJob.organization_id.in_(orgs)),
            "audits": await _count(AuditLog, AuditLog.organization_id.in_(orgs)),
            "usage": await _count(UsageEvent, UsageEvent.organization_id.in_(orgs)),
        }


def test_chain_with_a_wrong_organization_writes_nothing(
    chain_pg: ChainHarness,  # noqa: F811
    probe_factory: async_sessionmaker[AsyncSession],
) -> None:
    env = chain_pg.env
    victim = env.seed()
    other = env.seed()
    orgs = [victim.organization_id, other.organization_id]
    before = env.run_async(_footprint(env, victim.document_id, orgs))
    result = document_tasks.process_document.apply(
        args=[str(victim.document_id)],
        kwargs={"organization_id": str(other.organization_id), "user_id": str(other.user_id)},
        task_id="wrong-org",
    )
    assert result.failed()
    assert str(result.result) == "tenant_mismatch"
    # Stage messages naming the wrong organisation stop before any write as well.
    stage = document_tasks.celery_app.tasks["documents.ingest.extract"].apply(
        kwargs={
            "document_id": str(victim.document_id),
            "organization_id": str(other.organization_id),
            "run_id": "forged",
            "claim_token": "forged",
        },
        task_id="forged-stage",
    )
    assert stage.failed()
    after = env.run_async(_footprint(env, victim.document_id, orgs))
    assert after == before
    assert chain_pg.messages == []
    assert env.fakes.minio.reads == 0
