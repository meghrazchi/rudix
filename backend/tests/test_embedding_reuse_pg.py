"""Embedding reuse and concurrent embed batches on PostgreSQL (R06-06, R06-07).

Concurrent batches share one lock for their short sessions; on PostgreSQL every session is
its own connection, so this checks that concurrent batches write each part once, keep the
point set of a sequential run, and that parent-text resolution stays inside the tenant.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from ingestion_golden_support import (
    IngestionEnv,
    ingestion_env_pg,  # noqa: F401  (fixture)
)
from inmemory_qdrant import InMemoryQdrant
from sqlalchemy import func, select
from test_embedding_reuse import TEXT, CountingProvider, VectorEnv

from app.clients import qdrant_client as qdrant_module
from app.core.config import settings
from app.domains.chat.services.query_retrieval_service import QueryRetrievalService
from app.domains.documents.services.embedding_service import EmbeddingService
from app.domains.documents.services.qdrant_service import QdrantService
from app.models.document_processing import DocumentStageArtifact
from app.workers import document_tasks

pytestmark = pytest.mark.requires_postgres

HIERARCHICAL = {"strategy": "hierarchical", "chunk_size_tokens": 30, "chunk_overlap_tokens": 5}


@pytest.fixture
def pg_vectors(
    ingestion_env_pg: IngestionEnv,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> VectorEnv:
    client = InMemoryQdrant()
    # Longer than one short PostgreSQL session, so batches overlap at the provider.
    provider = CountingProvider(delay=0.2)
    monkeypatch.setattr(qdrant_module, "qdrant_client", client)
    monkeypatch.setattr(document_tasks, "_qdrant_service", QdrantService())
    monkeypatch.setattr(
        document_tasks,
        "_embedding_service",
        EmbeddingService(provider=provider, model_name=settings.openai_embedding_model),
    )
    return VectorEnv(ingestion_env_pg, client, provider)


def test_concurrent_batches_on_postgres_match_sequential_and_reuse(
    pg_vectors: VectorEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "ingest_embed_batch_chunks", 2)
    pg_vectors.env.set_content(TEXT.encode())
    points = {}
    for limit in (1, 3):
        monkeypatch.setattr(settings, "embedding_max_concurrent_batches", limit)
        seeded = pg_vectors.env.seed()
        pg_vectors.process(seeded, f"pg-{limit}-{uuid4().hex[:6]}")
        points[limit] = {k: (v[1], v[2]) for k, v in pg_vectors.points(seeded).items()}
    assert len(points[1]) >= 4 and points[1] == points[3]
    assert pg_vectors.provider.max_in_flight > 1

    pg_vectors.provider.calls.clear()
    pg_vectors.reindex(seeded, f"pg-reindex-{uuid4().hex[:6]}")
    assert pg_vectors.provider.calls == []
    assert {k: (v[1], v[2]) for k, v in pg_vectors.points(seeded).items()} == points[3]

    async def _parts() -> int:
        async with pg_vectors.env.factory() as session:
            return int(
                await session.scalar(
                    select(func.count()).where(
                        DocumentStageArtifact.document_id == seeded.document_id
                    )
                )
                or 0
            )

    # finalize purged the run's artifacts after the concurrent batches wrote them once each.
    assert pg_vectors.env.run_async(_parts()) == 0


def test_parent_text_resolution_on_postgres_stays_in_the_organisation(
    pg_vectors: VectorEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "qdrant_store_parent_text", False)
    pg_vectors.env.set_content(
        b"# Leave\n\nEmployees receive twenty days of paid annual leave each year. Requests "
        b"go through the people portal two weeks in advance.\n\n# Travel\n\nBusiness travel "
        b"is booked through the travel desk for every trip."
    )
    seeded = pg_vectors.env.seed()
    pg_vectors.env.run_task(
        document_tasks.process_document,
        seeded.document_id,
        task_id=f"pg-parents-{uuid4().hex[:6]}",
        chunking_profile_config=HIERARCHICAL,
        **pg_vectors.ids(seeded),
    )
    service = QueryRetrievalService(session_factory=pg_vectors.env.factory)
    candidates = pg_vectors.env.run_async(
        service.aretrieve_candidates(
            query_vector=[0.0],
            organization_id=seeded.organization_id,
            document_ids=None,
            initial_top_k=50,
            qdrant_client=pg_vectors.client,  # type: ignore[arg-type]
        )
    )
    children = [c for c in candidates if c.chunk_level == 1]
    assert children and all(c.parent_text for c in children)
    stripped = [c.__class__(**{**vars(c), "parent_text": None}) for c in children]
    other_org = pg_vectors.env.run_async(
        service.resolve_parent_texts(stripped, organization_id=uuid4())
    )
    assert all(c.parent_text is None for c in other_org)
