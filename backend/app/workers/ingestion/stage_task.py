"""Body of one stage task of the distributed ingestion chain (R06-01 part 2).

Each delivery of ``documents.ingest.<stage>`` (and ``documents.graph_extract``):

1. loads the document and checks its organisation against the ``organization_id`` kwarg
   (``TenantMismatchError`` before any write);
2. stops with ``superseded`` when ``documents.processing_task_id`` no longer equals the
   run's ``claim_token`` (``None`` is accepted once this run's finalize committed, because
   finalize clears the claim);
3. on a completed stage row (a duplicate or redelivered message) dispatches the next stage
   again, idempotently; finalize also reports the run if its completion audit is missing;
4. re-runs a producer stage whose artifacts this stage needs but which are missing;
5. leases the stage row with the message's own id (a live lease held by another message
   returns ``lease_held``; a redelivery of the same message re-takes it), runs the stage,
   marks it completed, and dispatches the next stage before returning, so ``acks_late``
   keeps the message until the hand-off is published.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.core.logging import get_logger
from app.core.metrics_workers import record_ingest_stage_task
from app.workers.base_task import PermanentTaskError, TenantMismatchError
from app.workers.ingestion.chain import REINDEX_MODE, next_stage, stage_kwargs
from app.workers.ingestion.context import StageContext
from app.workers.ingestion.deps import IngestionDeps, current_deps
from app.workers.ingestion.dispatch import dispatch_stage
from app.workers.ingestion.errors import parse_document_id
from app.workers.ingestion.options import IngestionOptions
from app.workers.ingestion.pipeline import (
    _record_failure,
    completed_run_metrics,
    make_store,
    open_recorder,
    result_from_metrics,
)
from app.workers.ingestion.runner import run_leased
from app.workers.ingestion.stages import build_stage
from app.workers.ingestion.stages.base import ARTIFACT_CONSUMERS, StageName
from app.workers.ingestion.store import COMPLETED, StageRecord
from app.workers.ingestion.tenant import check_document_tenant

logger = get_logger("worker.ingestion")


@dataclass
class StagePlan:
    """What the synchronous task wrapper does after the async body returned.

    Reporting and dispatching run outside the event loop: the completion audit uses the
    worker's ``run_async``, and an eager dispatch (tests) runs the next task in-process.
    """

    result: dict[str, Any]
    dispatch: list[tuple[StageName, dict[str, Any]]] = field(default_factory=list)
    report: bool = False


def _producers_of(stage: StageName) -> list[StageName]:
    return [producer for producer, users in ARTIFACT_CONSUMERS.items() if stage in users]


def _options(deps: IngestionDeps, kw: dict[str, Any]) -> IngestionOptions:
    from app.workers.ingestion.process import PROCESS, REINDEX

    mode = REINDEX if kw.get("mode") == REINDEX_MODE else PROCESS
    try:
        service = deps.make_chunking_service(kw.get("chunking_profile_config"))
    except ValueError as exc:
        raise PermanentTaskError(f"Invalid chunking_profile_config: {exc}") from exc
    return IngestionOptions(
        pipeline_type=mode.pipeline_type,
        chunking_service=service,
        profile_source=str(kw.get("profile_source") or "system_default"),
    )


def _claim_ok(stage: StageName, holder: str | None, token: str, finalized: bool) -> bool:
    if holder == token:
        return stage != StageName.graph_extract or finalized
    return holder is None and finalized


def _result(
    stage: StageName,
    outcome: str,
    kw: dict[str, Any],
    *,
    dispatch: list[tuple[StageName, dict[str, Any]]] | None = None,
    report: bool = False,
    **extra: Any,
) -> StagePlan:
    record_ingest_stage_task(str(stage), outcome)
    logger.info(
        f"ingestion.stage_task.{outcome}",
        stage=str(stage),
        document_id=kw.get("document_id"),
        organization_id=kw.get("organization_id"),
        run_id=kw.get("run_id"),
    )
    nexts = [str(name) for name, _ in dispatch or []]
    result = {
        "document_id": kw.get("document_id"),
        "run_id": kw.get("run_id"),
        "stage": str(stage),
        "status": outcome,
        "next": nexts[0] if nexts else None,
        **extra,
    }
    return StagePlan(result=result, dispatch=list(dispatch or []), report=report)


def _forward(stage: StageName, kw: dict[str, Any]) -> list[tuple[StageName, dict[str, Any]]]:
    following = next_stage(stage)
    if following is None:
        return []
    return [(following, _message(kw))]


def _message(kw: dict[str, Any]) -> dict[str, Any]:
    return stage_kwargs(**{k: kw.get(k) for k in _KWARG_NAMES})


_KWARG_NAMES = (
    "document_id",
    "organization_id",
    "user_id",
    "request_id",
    "run_id",
    "claim_token",
    "chunking_profile_config",
    "profile_source",
    "mode",
    "force",
)


def report_run(deps: IngestionDeps, kw: dict[str, Any]) -> bool:
    """Completion log, audit, and notification of the run, once (finalize task, sync)."""
    from app.workers.ingestion.process import PROCESS, REINDEX, report

    mode = REINDEX if kw.get("mode") == REINDEX_MODE else PROCESS
    metrics = deps.run(
        completed_run_metrics(
            str(kw["document_id"]), run_id=str(kw["run_id"]), audit_action=mode.audit_action
        )
    )
    if metrics is None:
        return False
    context = {key: kw.get(key) for key in ("document_id", "request_id", "organization_id")}
    context["user_id"] = kw.get("user_id")
    report(deps, mode, context, bool(kw.get("force")), result_from_metrics(metrics))
    return True


def execute_plan(deps: IngestionDeps, plan: StagePlan, kw: dict[str, Any]) -> dict[str, Any]:
    if plan.report:
        report_run(deps, kw)
    for stage, message in plan.dispatch:
        dispatch_stage(stage, message)
    return plan.result


async def run_stage_message(
    stage: StageName, kw: dict[str, Any], *, message_id: str, will_retry: Any
) -> StagePlan:
    """Run one stage delivery; ``will_retry(exc)`` tells whether a failure is retried."""
    deps = current_deps()
    document_uuid = parse_document_id(str(kw["document_id"]))
    async with deps.SessionLocal() as session:
        document = await deps.document_repository.get_document_by_id(
            session, document_id=document_uuid
        )
    if document is None:
        # Invisible under strict RLS when it belongs to another organisation.
        await check_document_tenant(document_uuid, kw.get("organization_id"))
        return _result(stage, "superseded", kw, reason="document_missing")
    expected = kw.get("organization_id")
    if expected is not None and str(document.organization_id) != str(expected):
        raise TenantMismatchError()
    options = _options(deps, kw)
    run_id = str(kw["run_id"])
    store = make_store(deps, document, options, run_id)
    records = await store.load()
    finalize = records.get(StageName.finalize)
    finalized = finalize is not None and finalize.status == COMPLETED
    if not _claim_ok(stage, document.processing_task_id, str(kw["claim_token"]), finalized):
        return _result(stage, "superseded", kw, reason="claim_moved")

    record = records.get(stage)
    if record is not None and record.status == COMPLETED:
        return _result(
            stage,
            "skipped",
            kw,
            dispatch=_forward(stage, kw),
            report=stage == StageName.finalize,
        )

    for producer in _producers_of(stage):
        if await _artifacts_lost(store, records.get(producer), producer):
            await store.reset(producer)
            return _result(stage, "rerun_producer", kw, dispatch=[(producer, _message(kw))])

    resolved_org = str(expected or document.organization_id)
    resolved_user = str(kw.get("user_id") or document.uploaded_by_user_id)
    ctx = StageContext(
        document_id=document.id,
        organization_id=resolved_org,
        user_id=resolved_user,
        request_id=kw.get("request_id"),
        run_id=run_id,
        claim_token=str(kw["claim_token"]),
        options=options,
        deps=deps,
        recorder=await open_recorder(
            document,
            options=options,
            request_id=kw.get("request_id"),
            organization_id=resolved_org,
            user_id=resolved_user,
            records=records,
        ),
        store=store,
        lease_owner=message_id,
    )
    for name, row in records.items():
        if row.status == COMPLETED:
            ctx.metrics[name] = dict(row.metrics)

    leased = await store.lease(stage, owner=message_id)
    if leased is None:
        return _result(stage, "lease_held", kw)
    try:
        await run_leased(ctx, build_stage(stage), leased)
    except Exception as exc:
        await _on_stage_error(ctx, exc, retried=bool(will_retry(exc)), kw=kw)
        raise
    return _result(
        stage,
        "completed",
        kw,
        dispatch=_forward(stage, kw),
        report=stage == StageName.finalize,
    )


async def _artifacts_lost(store: Any, record: StageRecord | None, producer: StageName) -> bool:
    if record is None or record.status != COMPLETED:
        return False
    expected = int(record.metrics.get("artifact_parts", 0))
    if expected == 0:
        return False
    return len(await store.artifact_parts(producer)) < expected


async def _on_stage_error(
    ctx: StageContext, exc: Exception, *, retried: bool, kw: dict[str, Any]
) -> None:
    """Pipeline-explorer telemetry of a failed stage; the run fails only when terminal."""
    if retried:
        await ctx.recorder.fail_stage_if_open(
            stage=ctx.current_stage, error_message=type(exc).__name__, error_details={}
        )
        return
    await _record_failure(
        ctx, exc, organization_id=kw.get("organization_id"), user_id=kw.get("user_id")
    )


def stage_message_kwargs(**kwargs: Any) -> dict[str, Any]:
    """Normalise a stage task's kwargs (document id as text, defaults filled in)."""
    kw = {name: kwargs.get(name) for name in _KWARG_NAMES}
    kw["document_id"] = str(kw["document_id"])
    kw["profile_source"] = kw["profile_source"] or "system_default"
    kw["mode"] = kw["mode"] or "process"
    kw["force"] = bool(kw["force"])
    return kw
