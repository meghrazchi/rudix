"""Fixtures for vector index generation tests (R06-08).

The real ``QdrantService`` and ``EmbeddingService`` run against the in-memory Qdrant
client (collections and aliases) and a provider whose vector size depends on the model,
through the ingestion task bodies on SQLite (or PostgreSQL with ``ingestion_env_pg``).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from uuid import UUID

import pytest
from ingestion_golden_support import IngestionEnv, Seeded
from inmemory_qdrant import InMemoryQdrant, text_vector
from sqlalchemy import delete, select

from app.clients import qdrant_client as qdrant_module
from app.core.config import settings
from app.db.tenant_context import tenant_context_scope
from app.domains.ai.providers.protocols import EmbeddingRequest, EmbeddingResponse
from app.domains.documents.services.embedding_service import EmbeddingService
from app.domains.documents.services.qdrant_service import QdrantService
from app.domains.vector_index.services import lifecycle_service
from app.domains.vector_index.services.generation_service import registry
from app.models.document import DocumentChunk
from app.models.usage import UsageEvent
from app.models.vector_index import VectorIndexGeneration, VectorIndexGenerationDocument
from app.workers import document_tasks
from app.workers.vector_index_tasks import run_build

ALIAS = "rudix_live_vectors"
OLD_MODEL = "embed-old"
NEW_MODEL = "Embed-New/Large v2"
NEW_SIZE = 8
SMALL_CHUNKS = {"strategy": "token_recursive", "chunk_size_tokens": 40, "chunk_overlap_tokens": 5}
TEXT = "\n\n".join(
    [
        "Annual leave policy. Employees receive twenty days of paid annual leave each year. "
        "Requests are submitted through the people portal at least two weeks in advance.",
        "Carry over. Up to five unused days carry over into the first quarter of the next "
        "year. Days that are not used by the end of March expire without compensation.",
        "Sick leave. Sick leave is separate from annual leave and requires a medical note "
        "after three consecutive days. Managers record sick leave in the absence calendar.",
    ]
)


class StopBuild(BaseException):
    """Simulates a killed worker (not an Exception, so nothing catches it)."""


class ModelProvider:
    """Deterministic vectors whose size depends on the requested model."""

    def __init__(self, sizes: dict[str, int]) -> None:
        self.sizes = sizes
        self.calls: list[tuple[str, list[str]]] = []
        self.fail_on_call: int | None = None

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        if self.fail_on_call is not None and len(self.calls) + 1 >= self.fail_on_call:
            self.fail_on_call = None
            raise StopBuild()
        self.calls.append((request.model, list(request.texts)))
        size = self.sizes[request.model]
        return EmbeddingResponse(
            vectors=[text_vector(f"{request.model}:{t}", size) for t in request.texts],
            model=request.model,
            prompt_tokens=len(request.texts),
            total_tokens=len(request.texts),
            latency_ms=1,
        )

    def models(self) -> list[str]:
        return [model for model, _ in self.calls]


class VectorIndexEnv:
    def __init__(self, env: IngestionEnv, client: InMemoryQdrant, provider: ModelProvider):
        self.env, self.client, self.provider = env, client, provider

    def run(self, coro: Any) -> Any:
        return self.env.run_async(coro)

    def seed_indexed(self, task_id: str, *, text: str = TEXT) -> Seeded:
        self.env.set_content(text.encode())
        seeded = self.env.seed()
        self.process(seeded, task_id)
        return seeded

    def process(self, seeded: Seeded, task_id: str, *, force: bool = False) -> Any:
        """Run documents.process; ``force`` reprocesses an indexed document.

        ``run_task`` calls the task body directly, so the tenant that
        ``RudixTask.__call__`` binds on a worker delivery is bound here.
        """
        with tenant_context_scope(seeded.organization_id):
            return self.env.run_task(
                document_tasks.process_document,
                seeded.document_id,
                task_id=task_id,
                chunking_profile_config=SMALL_CHUNKS,
                organization_id=str(seeded.organization_id),
                user_id=str(seeded.user_id),
                force=force,
            )

    def delete(self, seeded: Seeded) -> Any:
        return self.run(
            document_tasks._delete_document_assets_async(
                str(seeded.document_id), organization_id=str(seeded.organization_id)
            )
        )

    def enable_alias(self) -> None:
        self.env.monkeypatch.setattr(settings, "qdrant_collection_alias", ALIAS)
        registry.invalidate()

    def configure_model(self, model: str, size: int) -> None:
        self.env.monkeypatch.setattr(settings, "openai_embedding_model", model)
        self.env.monkeypatch.setattr(settings, "qdrant_vector_size", size)
        service = EmbeddingService(provider=self.provider, model_name=model, provider_type="fake")
        self.env.monkeypatch.setattr(document_tasks, "_embedding_service", service)

    def adopt_and_register(self) -> VectorIndexGeneration:
        self.enable_alias()
        self.run(lifecycle_service.adopt())
        self.configure_model(NEW_MODEL, NEW_SIZE)
        return self.run(lifecycle_service.register_building())

    def build(self, **kwargs: Any) -> Any:
        return self.run(run_build(**kwargs))

    def points(self, collection: str, seeded: Seeded | None = None) -> dict[str, Any]:
        return {
            key: point
            for key, point in self.client.points(collection).items()
            if seeded is None or point.payload["document_id"] == str(seeded.document_id)
        }

    def generations(self) -> dict[int, VectorIndexGeneration]:
        async def _read() -> dict[int, VectorIndexGeneration]:
            async with self.env.factory() as session:
                rows = (await session.execute(select(VectorIndexGeneration))).scalars()
                return {row.generation: row for row in rows}

        return self.run(_read())

    def generation_documents(self, generation_id: UUID) -> dict[UUID, int]:
        async def _read() -> dict[UUID, int]:
            async with self.env.factory() as session:
                rows = await session.execute(
                    select(
                        VectorIndexGenerationDocument.document_id,
                        VectorIndexGenerationDocument.point_count,
                    ).where(VectorIndexGenerationDocument.generation_id == generation_id)
                )
                return {doc: int(count) for doc, count in rows}

        return self.run(_read())

    def chunk_count(self, seeded: Seeded) -> int:
        async def _read() -> int:
            async with self.env.factory() as session:
                rows = await session.execute(
                    select(DocumentChunk.id).where(
                        DocumentChunk.document_id == seeded.document_id,
                        DocumentChunk.qdrant_point_id.is_not(None),
                    )
                )
                return len(list(rows))

        return self.run(_read())

    def usage_events(self) -> list[UsageEvent]:
        async def _read() -> list[UsageEvent]:
            async with self.env.factory() as session:
                rows = await session.execute(
                    select(UsageEvent).where(UsageEvent.event_type == "document.embedding")
                )
                return list(rows.scalars())

        return self.run(_read())


def make_vector_index_env(
    env: IngestionEnv, monkeypatch: pytest.MonkeyPatch
) -> Iterator[VectorIndexEnv]:
    client = InMemoryQdrant()
    client.add_collection(settings.qdrant_collection, size=settings.qdrant_vector_size)
    provider = ModelProvider({OLD_MODEL: settings.qdrant_vector_size, NEW_MODEL: NEW_SIZE})
    monkeypatch.setattr(qdrant_module, "qdrant_client", client)
    monkeypatch.setattr(document_tasks, "_qdrant_service", QdrantService())
    monkeypatch.setattr(settings, "vector_index_registry_cache_seconds", 0.0)
    monkeypatch.setattr(settings, "qdrant_collection_alias", None)
    vi_env = VectorIndexEnv(env, client, provider)
    vi_env.configure_model(OLD_MODEL, settings.qdrant_vector_size)
    registry.invalidate()
    # The generation tables are global (no organisation), so deleting a test's organisations
    # does not clear them. Rows left by another test on a shared database would be adopted or
    # resumed here, so start and end with none.
    env.run_async(_clear_generations(env))
    try:
        yield vi_env
    finally:
        env.run_async(_clear_generations(env))
        registry.invalidate()


async def _clear_generations(env: IngestionEnv) -> None:
    async with env.factory() as session, session.begin():
        await session.execute(delete(VectorIndexGenerationDocument))
        await session.execute(delete(VectorIndexGeneration))
