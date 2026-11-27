"""Stage rows and stage artifacts of one ingestion run (R06-01).

``DbStageStore`` keeps ``document_processing_stages`` and ``document_stage_artifacts``;
every method opens its own short session (``mark_completed`` can join the caller's
transaction instead, which finalize uses to commit its row with ``indexed``).
``MemoryStageStore`` keeps the same state in memory for evaluation re-ingest, which must
not leave rows behind.

A lease is one conditional ``UPDATE ... RETURNING``: the stage row is taken when it is
pending or failed, or running and either owned by the caller or silent for longer than
``INGEST_STAGE_LEASE_SECONDS``.
"""

from __future__ import annotations

import json
import zlib
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID, uuid4

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.document_processing import DocumentProcessingStage, DocumentStageArtifact
from app.workers.ingestion.errors import DocumentPipelinePermanentError

PENDING, RUNNING, COMPLETED, FAILED = "pending", "running", "completed", "failed"
_ITER_PAGE_SIZE = 16


@dataclass
class StageRecord:
    stage: str
    status: str
    attempt: int = 0
    owner_task_id: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None


def encode_artifact(payload: Any) -> bytes:
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return zlib.compress(raw)


def decode_artifact(content: bytes) -> Any:
    return json.loads(zlib.decompress(content).decode("utf-8"))


def checked_artifact(stage: str, payload: Any) -> bytes:
    content = encode_artifact(payload)
    if len(content) > settings.ingest_artifact_max_part_bytes:
        raise DocumentPipelinePermanentError(
            stage=stage,
            code="STAGE_ARTIFACT_TOO_LARGE",
            category="validation",
            message="stage artifact part exceeds INGEST_ARTIFACT_MAX_PART_BYTES",
        )
    return content


class StageStore(Protocol):
    async def load(self) -> dict[str, StageRecord]: ...

    async def lease(self, stage: str, *, owner: str) -> StageRecord | None: ...

    async def heartbeat(self, stage: str) -> None: ...

    async def mark_completed(
        self,
        stage: str,
        *,
        metrics: dict[str, Any],
        artifact_ref: str | None = None,
        session: AsyncSession | None = None,
    ) -> None: ...

    async def mark_failed(self, stage: str, *, error_code: str) -> None: ...

    async def reset(self, stage: str) -> None: ...

    async def write_artifacts(
        self, stage: str, parts: dict[int, Any], *, replace_stage: bool
    ) -> None: ...

    def iter_artifacts(self, stage: str) -> AsyncIterator[Any]: ...

    async def artifact_parts(self, stage: str) -> set[int]: ...

    async def delete_run_artifacts(self) -> None: ...

    async def purge_other_runs(self) -> None: ...


def _now() -> datetime:
    return datetime.now(UTC)


class DbStageStore:
    def __init__(
        self,
        session_factory: Callable[[], AsyncSession],
        *,
        organization_id: UUID,
        document_id: UUID,
        run_id: str,
    ) -> None:
        self._factory = session_factory
        self.organization_id = organization_id
        self.document_id = document_id
        self.run_id = run_id

    def _run_filter(self, model: Any) -> Any:
        return and_(
            model.organization_id == self.organization_id,
            model.document_id == self.document_id,
            model.run_id == self.run_id,
        )

    def _stage_filter(self, stage: str) -> Any:
        return and_(
            self._run_filter(DocumentProcessingStage), DocumentProcessingStage.stage == stage
        )

    async def load(self) -> dict[str, StageRecord]:
        async with self._factory() as session:
            rows = (
                await session.execute(
                    select(DocumentProcessingStage).where(self._run_filter(DocumentProcessingStage))
                )
            ).scalars()
            return {
                row.stage: StageRecord(
                    stage=row.stage,
                    status=row.status,
                    attempt=row.attempt,
                    owner_task_id=row.owner_task_id,
                    metrics=dict(row.metrics or {}),
                    error_code=row.error_code,
                )
                for row in rows
            }

    async def _ensure_row(self, session: AsyncSession, stage: str) -> None:
        values = {
            "id": uuid4(),
            "organization_id": self.organization_id,
            "document_id": self.document_id,
            "run_id": self.run_id,
            "stage": stage,
            "status": PENDING,
            "attempt": 0,
            "metrics": {},
        }
        dialect = session.get_bind().dialect.name
        insert_fn = pg_insert if dialect == "postgresql" else sqlite_insert
        stmt = insert_fn(DocumentProcessingStage).values(**values)
        await session.execute(
            stmt.on_conflict_do_nothing(index_elements=["document_id", "run_id", "stage"])
        )

    async def lease(self, stage: str, *, owner: str) -> StageRecord | None:
        now = _now()
        stale_before = now - timedelta(seconds=settings.ingest_stage_lease_seconds)
        model = DocumentProcessingStage
        claimable = or_(
            model.status.in_((PENDING, FAILED)),
            and_(
                model.status == RUNNING,
                or_(
                    model.owner_task_id == owner,
                    model.heartbeat_at.is_(None),
                    model.heartbeat_at < stale_before,
                ),
            ),
        )
        stmt = (
            update(model)
            .where(self._stage_filter(stage), claimable)
            .values(
                status=RUNNING,
                attempt=model.attempt + 1,
                owner_task_id=owner,
                started_at=now,
                heartbeat_at=now,
                error_code=None,
                updated_at=now,
            )
            .returning(model.attempt, model.metrics)
            .execution_options(synchronize_session=False)
        )
        async with self._factory() as session, session.begin():
            await self._ensure_row(session, stage)
            row = (await session.execute(stmt)).first()
        if row is None:
            return None
        return StageRecord(
            stage=stage,
            status=RUNNING,
            attempt=int(row[0]),
            owner_task_id=owner,
            metrics=dict(row[1] or {}),
        )

    async def _update(self, stage: str, session: AsyncSession | None, **values: Any) -> None:
        stmt = (
            update(DocumentProcessingStage)
            .where(self._stage_filter(stage))
            .values(updated_at=_now(), **values)
            .execution_options(synchronize_session=False)
        )
        if session is not None:
            await session.execute(stmt)
            return
        async with self._factory() as own_session, own_session.begin():
            await own_session.execute(stmt)

    async def heartbeat(self, stage: str) -> None:
        await self._update(stage, None, heartbeat_at=_now())

    async def mark_completed(
        self,
        stage: str,
        *,
        metrics: dict[str, Any],
        artifact_ref: str | None = None,
        session: AsyncSession | None = None,
    ) -> None:
        # Database clock, so audit rows written after the run compare against it (finalize).
        await self._update(
            stage,
            session,
            status=COMPLETED,
            finished_at=func.now(),
            heartbeat_at=_now(),
            metrics=metrics,
            artifact_ref=artifact_ref,
            error_code=None,
        )

    async def mark_failed(self, stage: str, *, error_code: str) -> None:
        await self._update(stage, None, status=FAILED, finished_at=_now(), error_code=error_code)

    async def reset(self, stage: str) -> None:
        await self._update(stage, None, status=PENDING, finished_at=None)

    async def write_artifacts(
        self, stage: str, parts: dict[int, Any], *, replace_stage: bool
    ) -> None:
        encoded = {part: checked_artifact(stage, payload) for part, payload in parts.items()}
        artifact = DocumentStageArtifact
        async with self._factory() as session, session.begin():
            scope = and_(self._run_filter(artifact), artifact.stage == stage)
            if replace_stage:
                await session.execute(delete(artifact).where(scope))
            elif encoded:
                await session.execute(
                    delete(artifact).where(scope, artifact.part.in_(list(encoded)))
                )
            for part, content in sorted(encoded.items()):
                session.add(
                    artifact(
                        organization_id=self.organization_id,
                        document_id=self.document_id,
                        run_id=self.run_id,
                        stage=stage,
                        part=part,
                        content=content,
                        content_bytes=len(content),
                    )
                )

    async def iter_artifacts(self, stage: str) -> AsyncIterator[Any]:
        """Yield decoded parts in ``part`` order, one short session per page of parts."""
        artifact = DocumentStageArtifact
        last_part = -1
        while True:
            async with self._factory() as session:
                rows = (
                    await session.execute(
                        select(artifact.part, artifact.content)
                        .where(
                            self._run_filter(artifact),
                            artifact.stage == stage,
                            artifact.part > last_part,
                        )
                        .order_by(artifact.part)
                        .limit(_ITER_PAGE_SIZE)
                    )
                ).all()
            for part, content in rows:
                last_part = int(part)
                yield decode_artifact(content)
            if len(rows) < _ITER_PAGE_SIZE:
                return

    async def artifact_parts(self, stage: str) -> set[int]:
        artifact = DocumentStageArtifact
        async with self._factory() as session:
            rows = await session.execute(
                select(artifact.part).where(self._run_filter(artifact), artifact.stage == stage)
            )
            return {int(row[0]) for row in rows}

    async def delete_run_artifacts(self) -> None:
        async with self._factory() as session, session.begin():
            await session.execute(
                delete(DocumentStageArtifact).where(self._run_filter(DocumentStageArtifact))
            )

    async def purge_other_runs(self) -> None:
        async with self._factory() as session, session.begin():
            for model in (DocumentStageArtifact, DocumentProcessingStage):
                await session.execute(
                    delete(model).where(
                        model.organization_id == self.organization_id,
                        model.document_id == self.document_id,
                        model.run_id != self.run_id,
                    )
                )


class MemoryStageStore:
    """Same contract without database rows (evaluation re-ingest)."""

    def __init__(self, *, run_id: str = "memory") -> None:
        self.run_id = run_id
        self.records: dict[str, StageRecord] = {}
        self.artifacts: dict[str, dict[int, bytes]] = {}

    async def load(self) -> dict[str, StageRecord]:
        return {name: StageRecord(**vars(record)) for name, record in self.records.items()}

    async def lease(self, stage: str, *, owner: str) -> StageRecord | None:
        record = self.records.setdefault(stage, StageRecord(stage=stage, status=PENDING))
        if record.status == COMPLETED or (
            record.status == RUNNING and record.owner_task_id != owner
        ):
            return None
        record.status, record.owner_task_id = RUNNING, owner
        record.attempt += 1
        return StageRecord(**vars(record))

    async def heartbeat(self, stage: str) -> None:
        return None

    async def mark_completed(
        self,
        stage: str,
        *,
        metrics: dict[str, Any],
        artifact_ref: str | None = None,
        session: AsyncSession | None = None,
    ) -> None:
        record = self.records.setdefault(stage, StageRecord(stage=stage, status=PENDING))
        record.status, record.metrics, record.error_code = COMPLETED, dict(metrics), None

    async def mark_failed(self, stage: str, *, error_code: str) -> None:
        record = self.records.setdefault(stage, StageRecord(stage=stage, status=PENDING))
        record.status, record.error_code = FAILED, error_code

    async def reset(self, stage: str) -> None:
        if stage in self.records:
            self.records[stage].status = PENDING

    async def write_artifacts(
        self, stage: str, parts: dict[int, Any], *, replace_stage: bool
    ) -> None:
        bucket = self.artifacts.setdefault(stage, {})
        if replace_stage:
            bucket.clear()
        for part, payload in parts.items():
            bucket[part] = checked_artifact(stage, payload)

    async def iter_artifacts(self, stage: str) -> AsyncIterator[Any]:
        for part in sorted(self.artifacts.get(stage, {})):
            yield decode_artifact(self.artifacts[stage][part])

    async def artifact_parts(self, stage: str) -> set[int]:
        return set(self.artifacts.get(stage, {}))

    async def delete_run_artifacts(self) -> None:
        self.artifacts.clear()

    async def purge_other_runs(self) -> None:
        return None
