"""Vector index build and dual writes on PostgreSQL under strict RLS (R06-08).

``vector_index_generation_documents`` and ``usage_events`` have strict tenant policies, so
the build must bind each document's tenant before it writes, and its cross-tenant reads
(the document walk and progress counts) must go through ``maintenance_session()``. The
worker sessions here use the unprivileged ``rudix_rls_probe`` role (no BYPASSRLS).
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from ingestion_golden_support import (
    IngestionEnv,
    ingestion_env_pg,  # noqa: F401  (fixture)
)
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from test_ingestion_chain_pg import _grant_probe, _probe_is_unprivileged, _revoke_probe
from vector_index_support import NEW_MODEL, VectorIndexEnv, make_vector_index_env

from app.core.config import RlsEnforcement, settings
from app.db import session as db_session_module
from app.domains.vector_index.services import lifecycle_service
from app.workers import document_tasks, status_tracking
from tests.conftest import RLS_PROBE_ROLE

pytestmark = pytest.mark.requires_postgres


@pytest.fixture
def vi_pg(
    ingestion_env_pg: IngestionEnv,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[VectorIndexEnv]:
    yield from make_vector_index_env(ingestion_env_pg, monkeypatch)


def _use_probe(vi: VectorIndexEnv) -> async_sessionmaker[AsyncSession]:
    env = vi.env
    env.run_async(_grant_probe(env))
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"], poolclass=NullPool)

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
    vi.__dict__["probe_engine"] = engine
    return factory


def _release_probe(vi: VectorIndexEnv) -> None:
    vi.env.run_async(vi.__dict__["probe_engine"].dispose())
    vi.env.run_async(_revoke_probe(vi.env))


def test_build_and_dual_write_under_strict_rls(vi_pg: VectorIndexEnv) -> None:
    vi = vi_pg
    docs = [vi.seed_indexed(f"pg-doc-{i}") for i in range(2)]
    gen = vi.adopt_and_register()
    factory = _use_probe(vi)
    try:
        assert vi.run(_probe_is_unprivileged(factory))
        progress = vi.build()
        assert progress.finished and progress.documents_written == 2
        assert progress.verify is not None and progress.verify.passed
        rows = vi.generation_documents(gen.id)
        assert set(rows) == {doc.document_id for doc in docs}

        # A document ingested while the generation is verifying is dual-written.
        fresh = vi.seed_indexed("pg-during-verify")
        assert vi.generation_documents(gen.id)[fresh.document_id] == vi.chunk_count(fresh)
        models = {p.payload["embedding_model"] for p in vi.points(gen.collection_name).values()}
        assert models == {NEW_MODEL}
        events = [
            e
            for e in vi.usage_events()
            if (e.metadata_json or {}).get("reason", "").startswith("vector_reindex")
        ]
        assert {e.organization_id for e in events} == {d.organization_id for d in (*docs, fresh)}

        result = vi.run(lifecycle_service.swap(dry_run=False))
        assert result.applied
        assert vi.generations()[gen.generation].state == "active"
    finally:
        _release_probe(vi)
