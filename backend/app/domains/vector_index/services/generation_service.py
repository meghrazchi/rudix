"""Vector index generation registry (R06-08).

Legacy mode (``QDRANT_COLLECTION_ALIAS`` unset) never touches the database: reads and
writes use ``QDRANT_COLLECTION`` and the configured embedding model, as before 0.6.0.

Alias mode reads ``vector_index_generations`` for the alias and caches the result for
``VECTOR_INDEX_REGISTRY_CACHE_SECONDS`` per process:

- reads go to the collection the alias points at (the active generation), embedded with
  that generation's model. The snapshot is shared by every request of the process, so a
  refresh can land between a query's embedding and its search (the chat prefetch embeds
  seconds before retrieval). ``read_target_for_vector`` therefore searches the active
  generation when the query vector has its dimension, and otherwise the newest retired
  (or building) generation with that dimension: a query embedded just before a swap or
  rollback is served by the collection its model fills instead of failing. The retired
  collection stays readable for ``QDRANT_RETIRED_GRACE_HOURS``, far longer than the cache;
- writes go to the active generation, plus the building (or verifying) one during a build;
- deletes go to every generation whose collection still exists (not ``dropped``).

Until a generation is adopted, alias mode behaves like legacy mode.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from uuid import UUID

from app.core.config import settings
from app.core.logging import get_logger
from app.domains.vector_index.repositories import generations as repo
from app.models.vector_index import VectorIndexGeneration

logger = get_logger("vector_index")

_SLUG_MAX = 40


@dataclass(frozen=True)
class GenerationTarget:
    """One collection a document is written to, with the model that fills it."""

    collection_name: str
    embedding_model: str
    vector_size: int
    generation: int | None = None
    generation_id: UUID | None = None
    state: str = "legacy"

    @property
    def is_legacy(self) -> bool:
        return self.generation_id is None


@dataclass(frozen=True)
class RegistrySnapshot:
    alias: str | None
    active: GenerationTarget | None
    building: GenerationTarget | None
    delete_collections: tuple[str, ...]
    # Retired generations, newest first (search fallback for a vector of another dimension).
    retired: tuple[GenerationTarget, ...] = ()

    @property
    def read_collection(self) -> str:
        if self.alias is not None and self.active is not None:
            return self.active.collection_name
        return settings.qdrant_collection

    @property
    def write_targets(self) -> list[GenerationTarget]:
        primary = self.active or legacy_target()
        return [primary, self.building] if self.building is not None else [primary]


def configured_alias() -> str | None:
    """The alias, or None in legacy mode; it may never equal ``QDRANT_COLLECTION``."""
    alias = (settings.qdrant_collection_alias or "").strip()
    if not alias:
        return None
    if alias == settings.qdrant_collection:
        raise ValueError("QDRANT_COLLECTION_ALIAS must differ from QDRANT_COLLECTION")
    return alias


def model_slug(model: str) -> str:
    """Lowercase, ``[a-z0-9_]`` only, at most 40 characters."""
    slug = re.sub(r"[^a-z0-9_]+", "_", model.strip().lower()).strip("_")
    return (slug[:_SLUG_MAX].rstrip("_")) or "model"


def generation_collection_name(model: str, generation: int) -> str:
    return f"{settings.qdrant_collection}_{model_slug(model)}_v{int(generation)}"


def legacy_target() -> GenerationTarget:
    return GenerationTarget(
        collection_name=settings.qdrant_collection,
        embedding_model=settings.openai_embedding_model.strip(),
        vector_size=settings.qdrant_vector_size,
    )


def to_target(row: VectorIndexGeneration) -> GenerationTarget:
    return GenerationTarget(
        collection_name=row.collection_name,
        embedding_model=row.embedding_model,
        vector_size=int(row.vector_size),
        generation=int(row.generation),
        generation_id=row.id,
        state=row.state,
    )


def build_snapshot(alias: str | None, rows: list[VectorIndexGeneration]) -> RegistrySnapshot:
    if alias is None:
        return RegistrySnapshot(None, None, None, (settings.qdrant_collection,))
    active = repo.pick(rows, ("active",))
    building = repo.pick(rows, repo.BUILDING_STATES)
    collections = tuple(
        dict.fromkeys(row.collection_name for row in rows if row.state in repo.LIVE_STATES)
    )
    retired = sorted(
        (row for row in rows if row.state == "retired"),
        key=lambda row: row.generation,
        reverse=True,
    )
    return RegistrySnapshot(
        alias=alias,
        active=to_target(active) if active is not None else None,
        building=to_target(building) if building is not None else None,
        delete_collections=collections or (settings.qdrant_collection,),
        retired=tuple(to_target(row) for row in retired),
    )


class GenerationRegistry:
    """Per-process TTL cache of the alias's generations."""

    def __init__(self) -> None:
        self._snapshot: RegistrySnapshot | None = None
        self._loaded_at = 0.0

    def invalidate(self) -> None:
        self._snapshot = None
        self._loaded_at = 0.0

    def cached(self) -> RegistrySnapshot | None:
        """The last loaded snapshot (sync callers); None before the first load."""
        if configured_alias() is None:
            return build_snapshot(None, [])
        return self._snapshot

    async def snapshot(self, *, force: bool = False) -> RegistrySnapshot:
        alias = configured_alias()
        if alias is None:
            return build_snapshot(None, [])
        ttl = settings.vector_index_registry_cache_seconds
        fresh = time.monotonic() - self._loaded_at < ttl
        if self._snapshot is not None and self._snapshot.alias == alias and fresh and not force:
            return self._snapshot
        try:
            rows = await self._load(alias)
        except Exception as exc:
            if self._snapshot is None or self._snapshot.alias != alias:
                raise
            logger.warning("vector_index.registry.refresh_failed", error_type=type(exc).__name__)
            return self._snapshot
        self._snapshot = build_snapshot(alias, rows)
        self._loaded_at = time.monotonic()
        return self._snapshot

    @staticmethod
    async def _load(alias: str) -> list[VectorIndexGeneration]:
        from app.db import session as db_session_module

        async with db_session_module.SessionLocal() as session:
            rows = await repo.list_generations(session, alias_name=alias)
            session.expunge_all()
        return rows


registry = GenerationRegistry()


async def resolve_active_generation() -> GenerationTarget | None:
    """The active generation, or None in legacy mode and before adoption."""
    return (await registry.snapshot()).active


async def resolve_write_targets() -> list[GenerationTarget]:
    """``[active]`` or ``[active, building]``; the legacy collection in legacy mode."""
    return (await registry.snapshot()).write_targets


async def resolve_delete_collections() -> list[str]:
    """Every collection a document's points may live in (not ``dropped``)."""
    return list((await registry.snapshot()).delete_collections)


async def resolve_read_collection() -> str:
    return (await registry.snapshot()).read_collection


def cached_read_target() -> tuple[str, GenerationTarget]:
    """(collection, model target) for sync readers, from the last loaded snapshot."""
    snapshot = registry.cached()
    if snapshot is None or snapshot.active is None:
        return settings.qdrant_collection, legacy_target()
    return snapshot.read_collection, snapshot.active


def read_target_for_vector(dimension: int) -> tuple[str, GenerationTarget]:
    """(collection, target) to search with a query vector of ``dimension``.

    The active generation when the dimension matches it (always in legacy mode and before
    adoption). Otherwise the newest retired generation, then the building one, with that
    dimension: the vector was embedded from a snapshot taken before this process saw a
    swap or rollback. With no match the active generation is returned (Qdrant then reports
    the mismatch, as before).
    """
    collection, active = cached_read_target()
    snapshot = registry.cached()
    if active.vector_size == dimension or snapshot is None or snapshot.active is None:
        return collection, active
    fallbacks = [*snapshot.retired, *([snapshot.building] if snapshot.building else [])]
    for target in fallbacks:
        if target.vector_size == dimension:
            logger.warning(
                "vector_index.query.dimension_fallback",
                active_generation=active.generation,
                generation=target.generation,
                vector_size=dimension,
            )
            return target.collection_name, target
    return collection, active
