"""Eager Celery harness for the distributed ingestion chain (R06-01 part 2).

``ChainHarness`` switches ``INGEST_PIPELINE_MODE`` to ``chain`` and runs Celery eagerly, so
``documents.process`` and every stage task execute in-process through their real
``apply_async`` hand-off. Each dispatched stage message is recorded with a deterministic
task id, so a test can redeliver exactly that message (same id and kwargs) the way RabbitMQ
does after a worker dies with an unacknowledged message.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import pytest
from ingestion_golden_support import IngestionEnv, Seeded
from sqlalchemy import func, select

from app.core.config import settings
from app.models.document import Document, DocumentChunk
from app.models.document_processing import DocumentProcessingStage, DocumentStageArtifact
from app.models.failed_job import FailedJob
from app.models.pipeline import PipelineEvent, PipelineRun
from app.models.usage import AuditLog, UsageEvent
from app.workers import document_tasks
from app.workers.celery_app import celery_app
from app.workers.ingestion import dispatch as dispatch_module
from app.workers.ingestion import stage_task as stage_task_module
from app.workers.ingestion.stages.base import StageName

TEXT = (
    "Annual leave policy. Employees receive twenty days of paid annual leave each year. "
    "Requests are submitted through the people portal at least two weeks in advance.\n\n"
    "Carry over. Up to five unused days carry over into the first quarter of the next "
    "year. Days that are not used by the end of March expire without compensation.\n\n"
    "Sick leave. Sick leave is separate from annual leave and requires a medical note "
    "after three consecutive days. Managers record sick leave in the absence calendar.\n\n"
    "Travel. Business travel is booked through the travel desk. Economy class applies to "
    "flights under six hours and premium economy applies to longer flights."
)
PROFILE = {"strategy": "token_recursive", "chunk_size_tokens": 25, "chunk_overlap_tokens": 5}


class WorkerKilled(BaseException):
    """Stands in for the worker process dying inside a task."""


@dataclass
class Message:
    stage: StageName
    kwargs: dict[str, Any]
    task_id: str


@dataclass
class ChainHarness:
    env: IngestionEnv
    messages: list[Message] = field(default_factory=list)

    def dispatch(self, stage: StageName, kwargs: dict[str, Any]) -> Any:
        message = Message(stage, dict(kwargs), f"{stage}-{len(self.messages)}")
        self.messages.append(message)
        task = dispatch_module.stage_task(stage)
        return task.apply_async(kwargs=kwargs, task_id=message.task_id)

    def process(self, seeded: Seeded, *, task_id: str = "process-1", **kwargs: Any) -> Any:
        payload = {
            "organization_id": str(seeded.organization_id),
            "user_id": str(seeded.user_id),
            **kwargs,
        }
        return document_tasks.process_document.apply(
            args=[str(seeded.document_id)], kwargs=payload, task_id=task_id
        )

    def redeliver(self, message: Message, *, task_id: str | None = None) -> Any:
        task = dispatch_module.stage_task(message.stage)
        return task.apply(kwargs=message.kwargs, task_id=task_id or message.task_id)

    def last(self, stage: StageName) -> Message:
        return [m for m in self.messages if m.stage == stage][-1]

    def stages(self) -> list[str]:
        return [str(m.stage) for m in self.messages]


@pytest.fixture
def chain(ingestion_env: IngestionEnv) -> Iterator[ChainHarness]:
    yield from _harness(ingestion_env)


@pytest.fixture
def chain_pg(ingestion_env_pg: IngestionEnv) -> Iterator[ChainHarness]:
    yield from _harness(ingestion_env_pg)


def _harness(env: IngestionEnv) -> Iterator[ChainHarness]:
    harness = ChainHarness(env)
    env.monkeypatch.setattr(settings, "ingest_pipeline_mode", "chain")
    env.monkeypatch.setattr(settings, "ingest_embed_batch_chunks", 2)
    env.monkeypatch.setattr(dispatch_module, "dispatch_stage", harness.dispatch)
    env.monkeypatch.setattr(stage_task_module, "dispatch_stage", harness.dispatch)
    always_eager = celery_app.conf.task_always_eager
    propagates = celery_app.conf.task_eager_propagates
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = False
    env.set_content(TEXT.encode())
    try:
        yield harness
    finally:
        celery_app.conf.task_always_eager = always_eager
        celery_app.conf.task_eager_propagates = propagates


async def state(env: IngestionEnv, seeded: Seeded) -> dict[str, Any]:
    async with env.factory() as session:
        document = (
            await session.execute(select(Document).where(Document.id == seeded.document_id))
        ).scalar_one()
        chunks = list(
            (
                await session.execute(
                    select(DocumentChunk).where(DocumentChunk.document_id == seeded.document_id)
                )
            ).scalars()
        )

        async def _count(model: Any, *conditions: Any) -> int:
            stmt = select(func.count()).select_from(model).where(*conditions)
            return int((await session.execute(stmt)).scalar_one())

        stage_rows = list(
            (
                await session.execute(
                    select(DocumentProcessingStage).where(
                        DocumentProcessingStage.document_id == seeded.document_id
                    )
                )
            ).scalars()
        )
        return {
            "status": document.status,
            "claim": document.processing_task_id,
            "chunk_count": len(chunks),
            "point_ids": {c.qdrant_point_id for c in chunks if c.qdrant_point_id},
            "usage": await _count(
                UsageEvent,
                UsageEvent.organization_id == seeded.organization_id,
                UsageEvent.event_type == "document.embedding",
            ),
            "audits": await _count(
                AuditLog,
                AuditLog.organization_id == seeded.organization_id,
                AuditLog.action == "document.process.completed",
            ),
            "artifacts": await _count(
                DocumentStageArtifact, DocumentStageArtifact.document_id == seeded.document_id
            ),
            "completed": sorted(r.stage for r in stage_rows if r.status == "completed"),
            "runs": sorted({r.run_id for r in stage_rows}),
            "stage_metrics": {r.stage: dict(r.metrics or {}) for r in stage_rows},
            "pipeline_runs": await _count(
                PipelineRun, PipelineRun.document_id == seeded.document_id
            ),
            "pipeline_events": await _count(
                PipelineEvent,
                PipelineEvent.pipeline_run_id.in_(
                    select(PipelineRun.id).where(PipelineRun.document_id == seeded.document_id)
                ),
            ),
            "failed_jobs": [
                (job.task_name, dict(job.metadata_json or {}), job.id)
                for job in (
                    await session.execute(
                        select(FailedJob).where(FailedJob.entity_id == seeded.document_id)
                    )
                ).scalars()
            ],
        }


ALL_STAGES = sorted(str(stage) for stage in StageName)
