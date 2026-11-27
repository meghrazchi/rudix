"""Run identity and stage order of the distributed ingestion chain (R06-01 part 2).

Plan contract 4.2.4: ``run_id`` (artifact namespace) and ``claim_token`` (the
``documents.processing_task_id`` holding the claim) travel in every stage task's kwargs.

- A fresh claim starts a new run. The id is derived from the document and the claiming
  task's id (``uuid5``), so a redelivery or ``self.retry`` of the same ``documents.process``
  message reaches the same run instead of starting a second chain.
- ``resume_run_id`` (reaper re-queue, failed-job retry) continues that run while it is
  unfinished (no completed ``finalize`` row).
- ``INGEST_PIPELINE_MODE=inline`` keeps the part 1 rule: the run id is the claim's task id.
"""

from __future__ import annotations

from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select

from app.models.document_processing import DocumentProcessingStage
from app.models.failed_job import FailedJob
from app.workers.ingestion.deps import current_deps
from app.workers.ingestion.stages.base import StageName
from app.workers.ingestion.store import COMPLETED

CHAIN_ORDER: tuple[StageName, ...] = (
    StageName.extract,
    StageName.clean_detect,
    StageName.dlp,
    StageName.chunk,
    StageName.embed,
    StageName.index,
    StageName.finalize,
    StageName.graph_extract,
)

PROCESS_MODE = "process"
REINDEX_MODE = "reindex"


def next_stage(stage: StageName) -> StageName | None:
    index = CHAIN_ORDER.index(stage)
    return CHAIN_ORDER[index + 1] if index + 1 < len(CHAIN_ORDER) else None


def fresh_run_id(document_id: str, claim_token: str) -> str:
    return uuid5(NAMESPACE_URL, f"rudix:ingest:{document_id}:{claim_token}").hex


async def run_is_unfinished(document_id: UUID, run_id: str) -> bool:
    """True when the run has stage rows and its ``finalize`` row is not completed."""
    stage = DocumentProcessingStage
    async with current_deps().SessionLocal() as session:
        rows = (
            await session.execute(
                select(stage.stage, stage.status).where(
                    stage.document_id == document_id, stage.run_id == run_id
                )
            )
        ).all()
    if not rows:
        return False
    statuses = {str(name): str(status) for name, status in rows}
    return statuses.get(StageName.finalize) != COMPLETED


async def run_id_from_failed_job(job_id: str, organization_id: str | None) -> str | None:
    """``metadata.run_id`` of a failed stage task, for a dashboard retry (F156)."""
    try:
        job_uuid = UUID(job_id)
    except (TypeError, ValueError):
        return None
    stmt = select(FailedJob.metadata_json, FailedJob.organization_id).where(
        FailedJob.id == job_uuid
    )
    async with current_deps().SessionLocal() as session:
        row = (await session.execute(stmt)).first()
    if row is None:
        return None
    metadata, owner = row
    if organization_id is not None and str(owner) != str(organization_id):
        return None
    run_id = (metadata or {}).get("run_id")
    return str(run_id) if run_id else None


async def resolve_run_id(
    document_id: str,
    *,
    claim_token: str,
    resume_run_id: str | None,
    job_id: str | None,
    organization_id: str | None,
    chain: bool,
) -> tuple[str, bool]:
    """``(run_id, resumed)`` for a claimed ``documents.process`` or ``.reindex``."""
    candidate = resume_run_id
    if candidate is None and job_id is not None:
        candidate = await run_id_from_failed_job(job_id, organization_id)
    if candidate:
        try:
            document_uuid = UUID(document_id)
        except ValueError:
            document_uuid = None
        if document_uuid is not None and await run_is_unfinished(document_uuid, candidate):
            return candidate, True
    if not chain:
        return claim_token, False
    return fresh_run_id(document_id, claim_token), False


async def completed_stages(document_id: UUID, run_id: str) -> set[str]:
    stage = DocumentProcessingStage
    async with current_deps().SessionLocal() as session:
        rows = await session.execute(
            select(stage.stage).where(
                stage.document_id == document_id,
                stage.run_id == run_id,
                stage.status == COMPLETED,
            )
        )
        return {str(row[0]) for row in rows}


def first_incomplete(done: set[str]) -> StageName | None:
    for name in CHAIN_ORDER:
        if name not in done:
            return name
    return None


def stage_kwargs(
    *,
    document_id: str,
    organization_id: str | None,
    user_id: str | None,
    request_id: str | None,
    run_id: str,
    claim_token: str,
    chunking_profile_config: dict | None,
    profile_source: str,
    mode: str,
    force: bool,
) -> dict[str, Any]:
    """Kwargs of every stage message (JSON only: ids, flags, the chunking profile)."""
    return {
        "document_id": document_id,
        "organization_id": organization_id,
        "user_id": user_id,
        "request_id": request_id,
        "run_id": run_id,
        "claim_token": claim_token,
        "chunking_profile_config": chunking_profile_config,
        "profile_source": profile_source,
        "mode": mode,
        "force": force,
    }
