"""No database connection or transaction is held across provider calls in ingestion (R06-01).

While the fake object store, embedder, Qdrant (cleanup and upsert), and entity extractor
run, the engine has zero checked-out connections and no session opened by the pipeline is
in a transaction. Runs on PostgreSQL with real connections (``PoolProbe`` pattern of
``tests/chat_pipeline_probe.py``).
"""

from __future__ import annotations

from typing import Any

import pytest
from chat_pipeline_probe import PoolProbe
from ingestion_golden_support import (
    IngestionEnv,
    ingestion_env_pg,  # noqa: F401  (fixture)
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.enums import DocumentStatus
from app.workers import document_tasks, status_tracking

pytestmark = pytest.mark.requires_postgres

TEXT = (
    "Expense policy. Receipts are required for every claim above twenty euros. "
    "Claims are approved by the line manager within five working days.\n\n"
    "Travel. Rail is preferred for trips under four hours. Hotel bookings go through the "
    "travel desk and must stay within the city rate published each quarter."
)
PROFILE = {"strategy": "token_recursive", "chunk_size_tokens": 20, "chunk_overlap_tokens": 4}


class _TrackingFactory:
    """Session factory that remembers every session it handed out."""

    def __init__(self, factory: Any) -> None:
        self._factory = factory
        self.sessions: list[AsyncSession] = []
        self.kw = factory.kw

    def __call__(self) -> AsyncSession:
        session = self._factory()
        self.sessions.append(session)
        return session


def test_no_connection_is_held_while_providers_run(
    ingestion_env_pg: IngestionEnv,  # noqa: F811
) -> None:
    env = ingestion_env_pg
    tracking = _TrackingFactory(env.factory)
    for module in (document_tasks, status_tracking):
        env.monkeypatch.setattr(module, "SessionLocal", tracking)
    env.monkeypatch.setattr(settings, "ingest_embed_batch_chunks", 2)
    env.monkeypatch.setattr(settings, "enterprise_graph_enabled", True)
    env.monkeypatch.setattr(settings, "feature_enable_entity_extraction", True)

    observations: list[tuple[str, int, list[bool]]] = []
    probe = PoolProbe(env.engine)

    def _observe(kind: str) -> None:
        in_tx = [session.in_transaction() for session in tracking.sessions]
        observations.append((kind, probe.checked_out, in_tx))

    fakes = env.fakes
    fakes.embeddings.before_call = lambda _index: _observe("embed")
    fakes.qdrant.before_upsert = lambda _index: _observe("upsert")
    real_get = fakes.minio.get_object
    # R06-06: the per-run cleanup moved to the index stage (stale delete and count).
    real_delete = fakes.qdrant.delete_stale_document_points
    real_count = fakes.qdrant.count_document_points

    def _get_object(**kwargs: Any) -> Any:
        _observe("object_read")
        return real_get(**kwargs)

    async def _delete(**kwargs: Any) -> Any:
        _observe("qdrant_cleanup")
        return await real_delete(**kwargs)

    async def _count(**kwargs: Any) -> Any:
        _observe("qdrant_count")
        return await real_count(**kwargs)

    class _Extraction:
        async def extract_from_chunks(self, **_: Any) -> Any:
            _observe("graph_extraction")
            return type(
                "R",
                (),
                {
                    "entities": [],
                    "batch_count": 1,
                    "validation_errors": 0,
                    "llm_errors": 0,
                    "total_chunks": 0,
                },
            )()

    env.monkeypatch.setattr(fakes.minio, "get_object", _get_object)
    env.monkeypatch.setattr(fakes.qdrant, "delete_stale_document_points", _delete)
    env.monkeypatch.setattr(fakes.qdrant, "count_document_points", _count)
    env.monkeypatch.setattr(document_tasks, "_entity_extraction_service", _Extraction())
    env.set_content(TEXT.encode())
    seeded = env.seed()

    with probe:
        result = env.run_task(
            document_tasks.process_document,
            seeded.document_id,
            task_id="session-probe",
            chunking_profile_config=PROFILE,
            organization_id=str(seeded.organization_id),
            user_id=str(seeded.user_id),
        )

    assert result["status"] == DocumentStatus.indexed.value
    for kind, checked_out, in_tx in observations:
        assert checked_out == 0, f"{kind}: {checked_out} connection(s) checked out"
        assert not any(in_tx), f"{kind}: a pipeline session is in a transaction"
    kinds = [kind for kind, _, _ in observations]
    assert {
        "object_read",
        "qdrant_cleanup",
        "qdrant_count",
        "graph_extraction",
        "embed",
        "upsert",
    } <= set(kinds)
    assert kinds.count("embed") >= 2 and kinds.count("upsert") == kinds.count("embed")
    assert tracking.sessions, "the pipeline opened no session through the factory"
    assert probe.checked_out == 0
