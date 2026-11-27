"""Inline stage runner: runs the stages of one run in order and skips finished ones (R06-01).

For each stage: skip it when its row is completed (and the artifacts later stages still need
are present), otherwise lease the row, run the stage, and mark it completed or failed.
Only ``Exception`` is handled; a ``BaseException`` (worker shutdown, a killed process in
tests) leaves the row ``running`` so the next delivery with the same run id resumes it.
"""

from __future__ import annotations

import time
from collections.abc import Sequence

from app.core.document_errors import details_from_exception
from app.core.logging import get_logger
from app.core.metrics_workers import record_ingest_stage
from app.workers.ingestion.context import StageContext
from app.workers.ingestion.errors import DocumentPipelineTransientError
from app.workers.ingestion.stages.base import ARTIFACT_CONSUMERS, Stage, StageName
from app.workers.ingestion.store import COMPLETED, StageRecord

logger = get_logger("worker.ingestion")


async def _artifacts_missing(
    ctx: StageContext,
    stage: StageName,
    records: dict[str, StageRecord],
    planned: set[str],
) -> bool:
    consumers = [name for name in ARTIFACT_CONSUMERS.get(stage, ()) if name in planned]
    if all(records.get(name) and records[name].status == COMPLETED for name in consumers):
        return False
    expected = int(records[stage].metrics.get("artifact_parts", 0))
    if expected == 0:
        return False
    return len(await ctx.store.artifact_parts(stage)) < expected


async def run_inline(ctx: StageContext, stages: Sequence[Stage]) -> dict[str, StageRecord]:
    records = await ctx.store.load()
    for name, record in records.items():
        if record.status == COMPLETED:
            ctx.metrics[name] = dict(record.metrics)

    planned = {stage.name for stage in stages}
    for stage in stages:
        record = records.get(stage.name)
        if record is not None and record.status == COMPLETED:
            if not await _artifacts_missing(ctx, stage.name, records, planned):
                record_ingest_stage(stage.name, "skipped", 0.0)
                logger.info(
                    "ingestion.stage.skipped",
                    stage=stage.name,
                    document_id=ctx.document_id_str,
                    organization_id=ctx.organization_id,
                    run_id=ctx.run_id,
                )
                continue
            await ctx.store.reset(stage.name)
            ctx.metrics.pop(stage.name, None)

        leased = await ctx.store.lease(stage.name, owner=ctx.owner)
        if leased is None:
            raise DocumentPipelineTransientError(
                stage=stage.name,
                code="STAGE_LEASE_HELD",
                category="infrastructure",
                message=f"stage {stage.name} is running in another task",
            )
        started = time.monotonic()
        try:
            outcome = await stage.run(ctx)
        except Exception as exc:
            code = str(details_from_exception(exc).get("code", type(exc).__name__))[:64]
            try:
                await ctx.store.mark_failed(stage.name, error_code=code)
            except Exception:
                logger.warning(
                    "ingestion.stage.mark_failed_error",
                    stage=stage.name,
                    document_id=ctx.document_id_str,
                    run_id=ctx.run_id,
                )
            record_ingest_stage(stage.name, "failed", time.monotonic() - started)
            raise
        if not outcome.marked:
            await ctx.store.mark_completed(
                stage.name, metrics=outcome.metrics, artifact_ref=outcome.artifact_ref
            )
        ctx.metrics[stage.name] = dict(outcome.metrics)
        records[stage.name] = StageRecord(
            stage=stage.name, status=COMPLETED, attempt=leased.attempt, metrics=outcome.metrics
        )
        record_ingest_stage(stage.name, "completed", time.monotonic() - started)
    return records
