"""Evaluation vectors stay in QDRANT_EVALUATION_COLLECTION (R06-12).

The real ``QdrantService`` and ``QueryRetrievalService`` run against an in-memory Qdrant
that counts every write per collection: with the setting set, eval re-ingest, eval
retrieval and eval cleanup touch only the evaluation collection, organisation scoping
holds there, and document deletion cascades to it.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator
from typing import Any, ClassVar
from uuid import UUID, uuid4

import pytest
from ingestion_golden_support import (
    IngestionEnv,
    Seeded,
    ingestion_env,  # noqa: F401  (fixture)
)
from inmemory_qdrant import InMemoryQdrant
from sqlalchemy import select

from app.clients import minio_client as minio_module
from app.clients import qdrant_client as qdrant_module
from app.core.config import settings
from app.db.tenant_context import tenant_context_scope
from app.domains.chat.services.query_retrieval_service import QueryRetrievalService
from app.domains.documents.services.qdrant_service import QdrantService
from app.domains.vector_index.services.generation_service import registry
from app.models.document import DocumentChunk
from app.workers import document_tasks, evaluation_index_cleanup, evaluation_tasks
from app.workers.evaluation import collection as collection_module
from app.workers.evaluation import target as target_module
from app.workers.evaluation.config import ChunkingComparisonTarget

EVAL = "rudix_eval_vectors"
PROD = "documents"
TEXT = (
    "Annual leave policy. Employees receive twenty days of paid annual leave each year.\n\n"
    "Carry over. Up to five unused days carry over into the first quarter of the next year."
)
TARGET = ChunkingComparisonTarget(
    label="Candidate",
    profile_source="inline_profile",
    chunking_profile_id=None,
    chunking_profile_config={
        "strategy": "token_recursive",
        "chunk_size_tokens": 20,
        "chunk_overlap_tokens": 2,
    },
    chunking_strategy="token_recursive",
    profile_version="cfg-1",
)


class _MinioDeleter:
    def list_objects_v2(self, **kwargs: Any) -> dict[str, Any]:
        return {"IsTruncated": False, "Contents": []}

    def delete_object(self, **_: Any) -> None:
        return None


class CountingQdrant(InMemoryQdrant):
    """Counts point writes and searches per (operation, collection)."""

    def __init__(self) -> None:
        super().__init__()
        self.by_collection: Counter[tuple[str, str]] = Counter()

    def upsert(self, *, collection_name: str, **kwargs: Any) -> None:
        self.by_collection[("upsert", collection_name)] += 1
        super().upsert(collection_name=collection_name, **kwargs)

    def delete(self, *, collection_name: str, **kwargs: Any) -> None:
        self.by_collection[("delete", collection_name)] += 1
        super().delete(collection_name=collection_name, **kwargs)

    def query_points(self, *, collection_name: str, **kwargs: Any) -> Any:
        self.by_collection[("query", collection_name)] += 1
        return super().query_points(collection_name=collection_name, **kwargs)

    def writes_to(self, collection: str) -> int:
        return sum(
            count
            for (operation, name), count in self.by_collection.items()
            if name == collection and operation in {"upsert", "delete"}
        )


class Env:
    def __init__(self, env: IngestionEnv, client: CountingQdrant) -> None:
        self.env, self.client = env, client

    def seed(self) -> Seeded:
        self.env.set_content(TEXT.encode())
        seeded = self.env.seed()
        with tenant_context_scope(seeded.organization_id):
            self.env.run_task(
                document_tasks.process_document,
                seeded.document_id,
                task_id=f"prod-{uuid4().hex[:6]}",
                organization_id=str(seeded.organization_id),
            )
        return seeded

    def prepare(self, seeded: Seeded, run_id: UUID) -> str:
        with tenant_context_scope(seeded.organization_id):
            version, stats = self.env.run_async(
                evaluation_tasks._prepare_chunking_target_corpus_async(
                    evaluation_run_id=run_id,
                    target_index=1,
                    target=TARGET,
                    document_ids=[seeded.document_id],
                    request_id="req-eval",
                    organization_id=str(seeded.organization_id),
                    user_id=None,
                )
            )
        assert stats.chunk_count_total > 0
        return str(version)

    def points(self, collection: str, seeded: Seeded | None = None) -> dict[str, Any]:
        return {
            key: point
            for key, point in self.client.points(collection).items()
            if seeded is None or point.payload["document_id"] == str(seeded.document_id)
        }

    def chunk_versions(self, seeded: Seeded) -> list[str]:
        async def _read() -> list[str]:
            async with self.env.factory() as session:
                rows = await session.execute(
                    select(DocumentChunk.index_version).where(
                        DocumentChunk.document_id == seeded.document_id
                    )
                )
                return sorted(rows.scalars())

        return self.env.run_async(_read())


@pytest.fixture
def iso(
    ingestion_env: IngestionEnv,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Env]:
    client = CountingQdrant()
    client.add_collection(PROD, size=settings.qdrant_vector_size)
    monkeypatch.setattr(settings, "qdrant_collection", PROD)
    monkeypatch.setattr(settings, "qdrant_collection_alias", None)
    monkeypatch.setattr(qdrant_module, "qdrant_client", client)
    monkeypatch.setattr(document_tasks, "_qdrant_service", QdrantService())
    for module in (evaluation_tasks, evaluation_index_cleanup):
        monkeypatch.setattr(module, "SessionLocal", ingestion_env.factory)
    registry.invalidate()
    collection_module.reset_ensured_cache()
    yield Env(ingestion_env, client)
    collection_module.reset_ensured_cache()
    registry.invalidate()


def _enable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "qdrant_evaluation_collection", EVAL)


def test_eval_reingest_retrieval_and_cleanup_use_only_the_eval_collection(
    iso: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    seeded = iso.seed()
    production_before = dict(iso.points(PROD))
    assert production_before
    iso.client.by_collection.clear()
    _enable(monkeypatch)

    version = iso.prepare(seeded, uuid4())

    assert version.startswith("eval-")
    # The collection was created like the active one, with the tenant payload index.
    assert iso.client.vector_configs[EVAL] == (settings.qdrant_vector_size, "cosine")
    assert (EVAL, "organization_id") in iso.client.payload_indexes  # type: ignore[attr-defined]
    eval_points = iso.points(EVAL)
    assert eval_points and {p.payload["index_version"] for p in eval_points.values()} == {version}
    assert iso.client.writes_to(PROD) == 0
    assert iso.points(PROD) == production_before
    assert version in iso.chunk_versions(seeded)  # eval chunks keep today's table

    service = target_module.retrieval_service_for(version)
    assert isinstance(service, QueryRetrievalService)
    assert service.qdrant_collection == EVAL
    candidates = service.retrieve_candidates(
        query_vector=[0.001] * settings.qdrant_vector_size,
        organization_id=seeded.organization_id,
        document_ids=[seeded.document_id],
        initial_top_k=10,
        index_version=version,
    )
    assert candidates and all(c.document_id == seeded.document_id for c in candidates)
    assert iso.client.by_collection[("query", PROD)] == 0
    assert target_module.retrieval_service_for(settings.document_index_version) is None

    result = iso.env.run_async(
        evaluation_index_cleanup.cleanup_eval_index_version_async(
            organization_id=seeded.organization_id,
            document_ids=[seeded.document_id],
            index_version=version,
        )
    )
    assert (result.qdrant_failures, result.chunk_failures) == (0, 0)
    assert result.chunks_deleted > 0
    assert iso.points(EVAL) == {}
    assert iso.client.writes_to(PROD) == 0
    assert iso.points(PROD) == production_before
    assert version not in iso.chunk_versions(seeded)


def test_unset_setting_keeps_eval_vectors_in_the_production_collection(iso: Env) -> None:
    seeded = iso.seed()
    iso.client.by_collection.clear()

    version = iso.prepare(seeded, uuid4())

    assert EVAL not in iso.client.vector_configs
    assert {p.payload["index_version"] for p in iso.points(PROD).values()} >= {version}
    assert target_module.retrieval_service_for(version) is None


def test_cleanup_of_one_organisation_never_touches_another(
    iso: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    org_a, org_b = iso.seed(), iso.seed()
    _enable(monkeypatch)
    run_id = uuid4()
    version = iso.prepare(org_a, run_id)
    assert iso.prepare(org_b, run_id) == version
    b_points = dict(iso.points(EVAL, org_b))
    assert b_points

    # Even when org B's document id is passed, the organisation filter protects it.
    iso.env.run_async(
        evaluation_index_cleanup.cleanup_eval_index_version_async(
            organization_id=org_a.organization_id,
            document_ids=[org_a.document_id, org_b.document_id],
            index_version=version,
        )
    )

    assert iso.points(EVAL, org_a) == {}
    assert iso.points(EVAL, org_b) == b_points


def test_document_deletion_cascades_to_the_eval_collection(
    iso: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    doomed, kept = iso.seed(), iso.seed()
    _enable(monkeypatch)
    run_id = uuid4()
    iso.prepare(doomed, run_id)
    iso.prepare(kept, run_id)
    kept_eval = dict(iso.points(EVAL, kept))
    kept_prod = dict(iso.points(PROD, kept))
    monkeypatch.setattr(minio_module, "minio_client", _MinioDeleter())

    with tenant_context_scope(doomed.organization_id):
        iso.env.run_async(
            document_tasks._delete_document_assets_async(
                str(doomed.document_id), organization_id=str(doomed.organization_id)
            )
        )

    assert iso.points(EVAL, doomed) == {}
    assert iso.points(PROD, doomed) == {}
    assert iso.points(EVAL, kept) == kept_eval
    assert iso.points(PROD, kept) == kept_prod


class _RecordingRetrieval:
    """Stands in for QueryRetrievalService; records the collection and versions it serves."""

    instances: ClassVar[list[_RecordingRetrieval]] = []
    embedding_model = "fake-embedding"

    def __init__(self, *, qdrant_collection: str | None = None) -> None:
        self.collection = qdrant_collection
        self.versions: list[str | None] = []
        _RecordingRetrieval.instances.append(self)

    async def embed_query(self, **_: Any) -> tuple[list[float], int]:
        return [0.1, 0.2], 1

    def retrieve_candidates(self, *, index_version: str | None = None, **_: Any) -> list[Any]:
        self.versions.append(index_version)
        return []


def test_run_reads_baseline_from_production_and_candidates_from_eval(
    iso: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.domains.evaluations.repositories.evaluations import EvaluationRepository
    from app.models.enums import EvaluationRunStatus

    seeded = iso.seed()
    _enable(monkeypatch)

    async def _seed_run() -> str:
        repository = EvaluationRepository()
        async with iso.env.factory() as session:
            evaluation_set = await repository.create_evaluation_set(
                session, organization_id=seeded.organization_id, name="Isolation"
            )
            await repository.create_evaluation_question(
                session, evaluation_set_id=evaluation_set.id, question="How much leave?"
            )
            baseline = {"label": "Live", "profile_source": "system_default"}
            candidate = {
                "label": "Small",
                "chunking_profile_config": TARGET.chunking_profile_config,
            }
            run = await repository.create_evaluation_run(
                session,
                evaluation_set_id=evaluation_set.id,
                status=EvaluationRunStatus.queued.value,
                config={
                    "rerank": False,
                    "selected_document_ids": [str(seeded.document_id)],
                    "comparison_targets": [baseline, candidate],
                },
            )
            await session.commit()
            return str(run.id)

    run_id = iso.env.run_async(_seed_run())
    _RecordingRetrieval.instances = []
    production_reader = _RecordingRetrieval()
    monkeypatch.setattr(evaluation_tasks, "_query_retrieval_service", production_reader)
    monkeypatch.setattr(evaluation_tasks, "QueryRetrievalService", _RecordingRetrieval)
    iso.client.by_collection.clear()

    with tenant_context_scope(seeded.organization_id):
        result = iso.env.run_async(evaluation_tasks._run_evaluation_async(run_id))

    eval_readers = [r for r in _RecordingRetrieval.instances if r is not production_reader]
    assert production_reader.versions == [settings.document_index_version]
    assert [r.collection for r in eval_readers] == [EVAL]
    assert eval_readers[0].versions == [f"eval-{UUID(run_id).hex[:10]}-2"]
    cleanup = result["metrics_summary"]["eval_index_cleanup"]
    assert [entry["index_version"] for entry in cleanup] == eval_readers[0].versions
    assert iso.client.writes_to(PROD) == 0
    assert iso.client.writes_to(EVAL) > 0
    assert iso.points(EVAL) == {}
