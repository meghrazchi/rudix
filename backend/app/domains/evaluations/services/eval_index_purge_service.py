"""Finds and purges evaluation (``eval-``) index versions left in PostgreSQL and Qdrant.

Evaluation chunking comparisons re-ingest documents under ``eval-<run hex10>-<n>``.
Runs that finished before evaluation index cleanup existed, or whose cleanup failed,
leave those chunk rows and vectors behind. This service reports them per organization
and version, and deletes them when asked. It never deletes non-eval versions: those
outside ``settings.active_index_versions`` are only reported, because production
retrieval no longer serves them and an operator must decide (reindex or list them in
``DOCUMENT_ACTIVE_INDEX_VERSIONS``).

Only counts are reported. Chunk text is never read.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol
from uuid import UUID

from qdrant_client.http.models import PointIdsList
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.document import Document, DocumentChunk
from app.models.enums import EvaluationRunStatus
from app.models.evaluation import EvaluationRun

EVAL_INDEX_VERSION_PREFIX = "eval-"
EXIT_OK = 0
EXIT_INACTIVE_VERSIONS = 2

VersionClass = Literal["active", "inactive", "eval", "eval_in_progress"]

logger = get_logger("evaluation.index_purge")


class QdrantScrollDeleteClient(Protocol):
    def scroll(self, *args: Any, **kwargs: Any) -> Any: ...

    def delete(self, *args: Any, **kwargs: Any) -> Any: ...


@dataclass
class VersionReport:
    organization_id: str
    index_version: str
    classification: VersionClass
    chunk_count: int = 0
    point_count: int = 0
    chunks_deleted: int = 0
    points_deleted: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "organization_id": self.organization_id,
            "index_version": self.index_version,
            "classification": self.classification,
            "chunk_count": self.chunk_count,
            "point_count": self.point_count,
            "chunks_deleted": self.chunks_deleted,
            "points_deleted": self.points_deleted,
        }


@dataclass
class PurgeReport:
    applied: bool
    versions: list[VersionReport] = field(default_factory=list)
    points_without_version: int = 0

    @property
    def inactive_versions(self) -> list[VersionReport]:
        return [item for item in self.versions if item.classification == "inactive"]

    @property
    def exit_code(self) -> int:
        return EXIT_INACTIVE_VERSIONS if self.inactive_versions else EXIT_OK

    @property
    def chunks_deleted(self) -> int:
        return sum(item.chunks_deleted for item in self.versions)

    @property
    def points_deleted(self) -> int:
        return sum(item.points_deleted for item in self.versions)


def classify_index_version(
    index_version: str,
    *,
    active_versions: Iterable[str],
    protected_prefixes: Iterable[str],
) -> VersionClass:
    if index_version.startswith(EVAL_INDEX_VERSION_PREFIX):
        if any(index_version.startswith(prefix) for prefix in protected_prefixes):
            return "eval_in_progress"
        return "eval"
    if index_version in set(active_versions):
        return "active"
    return "inactive"


class EvalIndexPurgeService:
    def __init__(
        self,
        *,
        qdrant_client: QdrantScrollDeleteClient | None,
        collection: str | None = None,
        batch_size: int = 256,
        active_versions: Sequence[str] | None = None,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be at least 1")
        self._qdrant_client = qdrant_client
        self._collection = collection or settings.qdrant_collection
        self._batch_size = batch_size
        self._active_versions = tuple(
            active_versions if active_versions is not None else settings.active_index_versions
        )

    async def run(
        self,
        session: AsyncSession,
        *,
        apply: bool,
        organization_id: UUID | None = None,
    ) -> PurgeReport:
        protected_prefixes = await self._protected_prefixes(session)
        report = PurgeReport(applied=apply)
        by_key: dict[tuple[str, str], VersionReport] = {}

        def _entry(org_id: str, version: str) -> VersionReport:
            key = (org_id, version)
            if key not in by_key:
                by_key[key] = VersionReport(
                    organization_id=org_id,
                    index_version=version,
                    classification=classify_index_version(
                        version,
                        active_versions=self._active_versions,
                        protected_prefixes=protected_prefixes,
                    ),
                )
            return by_key[key]

        for org_id, version, count in await self._chunk_counts(session, organization_id):
            _entry(org_id, version).chunk_count = count

        points_by_key: dict[tuple[str, str], list[Any]] = {}
        if self._qdrant_client is not None:
            point_counts: dict[tuple[str, str], int] = {}
            report.points_without_version = self._scan_points(
                organization_id, points_by_key, point_counts
            )
            for (org_id, version), count in point_counts.items():
                _entry(org_id, version).point_count = count

        if apply:
            for entry in by_key.values():
                if entry.classification != "eval":
                    continue
                if entry.chunk_count:
                    entry.chunks_deleted = await self._delete_chunks(
                        session,
                        organization_id=UUID(entry.organization_id),
                        index_version=entry.index_version,
                    )
                point_ids = points_by_key.get((entry.organization_id, entry.index_version), [])
                if point_ids:
                    entry.points_deleted = self._delete_points(point_ids)

        report.versions = sorted(
            by_key.values(), key=lambda item: (item.organization_id, item.index_version)
        )
        logger.info(
            "evaluation.index_purge.completed",
            applied=apply,
            organization_id=str(organization_id) if organization_id else None,
            version_count=len(report.versions),
            inactive_version_count=len(report.inactive_versions),
            chunks_deleted=report.chunks_deleted,
            points_deleted=report.points_deleted,
            points_without_version=report.points_without_version,
        )
        return report

    @staticmethod
    async def _protected_prefixes(session: AsyncSession) -> list[str]:
        rows = await session.execute(
            select(EvaluationRun.id).where(
                EvaluationRun.status.in_(
                    [EvaluationRunStatus.queued.value, EvaluationRunStatus.running.value]
                )
            )
        )
        return [f"{EVAL_INDEX_VERSION_PREFIX}{run_id.hex[:10]}-" for run_id in rows.scalars()]

    @staticmethod
    async def _chunk_counts(
        session: AsyncSession, organization_id: UUID | None
    ) -> list[tuple[str, str, int]]:
        statement = (
            select(
                Document.organization_id,
                DocumentChunk.index_version,
                func.count(DocumentChunk.id),
            )
            .join(Document, Document.id == DocumentChunk.document_id)
            .group_by(Document.organization_id, DocumentChunk.index_version)
        )
        if organization_id is not None:
            statement = statement.where(Document.organization_id == organization_id)
        rows = (await session.execute(statement)).all()
        return [(str(org_id), str(version), int(count)) for org_id, version, count in rows]

    async def _delete_chunks(
        self, session: AsyncSession, *, organization_id: UUID, index_version: str
    ) -> int:
        deleted = 0
        while True:
            ids = list(
                (
                    await session.execute(
                        select(DocumentChunk.id)
                        .join(Document, Document.id == DocumentChunk.document_id)
                        .where(
                            Document.organization_id == organization_id,
                            DocumentChunk.index_version == index_version,
                        )
                        .limit(self._batch_size)
                    )
                ).scalars()
            )
            if not ids:
                return deleted
            await session.execute(delete(DocumentChunk).where(DocumentChunk.id.in_(ids)))
            await session.commit()
            deleted += len(ids)

    def _scan_points(
        self,
        organization_id: UUID | None,
        points_by_key: dict[tuple[str, str], list[Any]],
        point_counts: dict[tuple[str, str], int],
    ) -> int:
        """Counts points per (org, version); keeps point IDs only for eval versions.

        Only eval points can ever be deleted, so production point IDs are not held in
        memory while scrolling a large collection.
        """
        assert self._qdrant_client is not None
        scope = str(organization_id) if organization_id is not None else None
        without_version = 0
        offset: Any = None
        while True:
            points, offset = self._qdrant_client.scroll(
                collection_name=self._collection,
                limit=self._batch_size,
                offset=offset,
                with_payload=["organization_id", "document_id", "index_version"],
                with_vectors=False,
            )
            for point in points:
                payload = getattr(point, "payload", None) or {}
                org_id = str(payload.get("organization_id") or "").strip()
                version = str(payload.get("index_version") or "").strip()
                if scope is not None and org_id != scope:
                    continue
                if not org_id or not version:
                    without_version += 1
                    continue
                key = (org_id, version)
                point_counts[key] = point_counts.get(key, 0) + 1
                if version.startswith(EVAL_INDEX_VERSION_PREFIX):
                    points_by_key.setdefault(key, []).append(point.id)
            if offset is None:
                return without_version

    def _delete_points(self, point_ids: list[Any]) -> int:
        assert self._qdrant_client is not None
        for start in range(0, len(point_ids), self._batch_size):
            batch = point_ids[start : start + self._batch_size]
            self._qdrant_client.delete(
                collection_name=self._collection,
                points_selector=PointIdsList(points=batch),
                wait=True,
            )
        return len(point_ids)
