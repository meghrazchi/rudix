"""Celery tasks of the distributed ingestion chain (R06-01 part 2).

``documents.ingest.extract``, ``.clean_detect``, ``.dlp``, ``.chunk`` (processing queue),
``.embed``, ``.index``, ``.finalize`` (embedding queue), and ``documents.graph_extract``
(graph queue). Kwargs: ``document_id, organization_id, user_id, request_id, run_id,
claim_token, chunking_profile_config, profile_source, mode, force``.

A stage task that fails for good records ``FailedJob`` as ``documents.process`` (or
``documents.reindex``) with ``metadata = {stage, run_id}``, so the failed-job dashboard
retry dispatches the process task with ``job_id`` and the run resumes at that stage. A
``documents.graph_extract`` that fails for good (infrastructure, not extraction: those are
recorded on the graph status) records ``documents.graph_reindex`` and marks the graph
status failed; the document stays ``indexed``.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.core.config import settings
from app.models.enums import GraphExtractionStatus
from app.workers.base_task import PermanentTaskError, TransientTaskError
from app.workers.celery_app import celery_app
from app.workers.ingestion.chain import REINDEX_MODE
from app.workers.ingestion.deps import current_deps
from app.workers.ingestion.stage_task import (
    execute_plan,
    run_stage_message,
    stage_message_kwargs,
)
from app.workers.ingestion.stages.base import StageName
from app.workers.ingestion.task_base import DocumentTask


def _process_queue(mode: Any) -> str:
    if mode == REINDEX_MODE:
        return settings.celery_queue_documents_reindex
    return settings.celery_queue_documents_processing


class IngestStageTask(DocumentTask):
    abstract = True
    stage: StageName = StageName.extract

    def failed_job_identity(
        self, kwargs: dict[str, Any], queue_name: str | None
    ) -> tuple[str, str | None, dict[str, Any]]:
        mode = kwargs.get("mode")
        name = "documents.reindex" if mode == REINDEX_MODE else "documents.process"
        metadata = {"stage": str(self.stage), "run_id": kwargs.get("run_id")}
        return name, _process_queue(mode), metadata

    def will_retry(self, exc: Exception) -> bool:
        if isinstance(exc, PermanentTaskError):
            return False
        if not isinstance(exc, (TransientTaskError, *self.autoretry_for)):
            return False
        return int(getattr(self.request, "retries", 0) or 0) < int(self.max_retries or 0)


class GraphExtractTask(IngestStageTask):
    abstract = True
    stage = StageName.graph_extract

    def failed_job_identity(
        self, kwargs: dict[str, Any], queue_name: str | None
    ) -> tuple[str, str | None, dict[str, Any]]:
        metadata = {"stage": str(self.stage), "run_id": kwargs.get("run_id")}
        return "documents.graph_reindex", settings.celery_queue_documents_reindex, metadata

    def on_terminal_failure(
        self, *, exc: Exception, args: tuple[Any, ...], kwargs: dict[str, Any]
    ) -> None:
        """A graph task failure never fails the document; only the graph status."""
        deps = current_deps()
        try:
            document_id = UUID(str(kwargs.get("document_id")))
        except ValueError:
            return
        try:
            deps.run(
                deps.update_document_graph_status_async(
                    document_id, status=GraphExtractionStatus.failed.value, run_id=None
                )
            )
        except Exception:
            return


def run_stage_task(task: IngestStageTask, **kwargs: Any) -> dict[str, Any]:
    deps = current_deps()
    kw = stage_message_kwargs(**kwargs)
    message_id = str(getattr(task.request, "id", None) or f"adhoc-{kw['run_id']}-{task.stage}")
    plan = deps.run(
        run_stage_message(task.stage, kw, message_id=message_id, will_retry=task.will_retry)
    )
    return execute_plan(deps, plan, kw)


def _define(stage: StageName, name: str, base: type[IngestStageTask]) -> Any:
    def body(
        self: IngestStageTask,
        *,
        document_id: str,
        run_id: str,
        claim_token: str,
        organization_id: str | None = None,
        user_id: str | None = None,
        request_id: str | None = None,
        chunking_profile_config: dict | None = None,
        profile_source: str = "system_default",
        mode: str = "process",
        force: bool = False,
        job_id: str | None = None,
    ) -> dict[str, Any]:
        return run_stage_task(
            self,
            document_id=document_id,
            run_id=run_id,
            claim_token=claim_token,
            organization_id=organization_id,
            user_id=user_id,
            request_id=request_id,
            chunking_profile_config=chunking_profile_config,
            profile_source=profile_source,
            mode=mode,
            force=force,
        )

    body.__name__ = f"ingest_{stage}"
    body.__qualname__ = body.__name__
    task_base = type(f"Ingest{stage.title().replace('_', '')}Task", (base,), {"stage": stage})
    return celery_app.task(name=name, bind=True, base=task_base, ignore_result=True)(body)


STAGE_TASKS: dict[StageName, Any] = {
    stage: _define(stage, f"documents.ingest.{stage}", IngestStageTask)
    for stage in (
        StageName.extract,
        StageName.clean_detect,
        StageName.dlp,
        StageName.chunk,
        StageName.embed,
        StageName.index,
        StageName.finalize,
    )
}
STAGE_TASKS[StageName.graph_extract] = _define(
    StageName.graph_extract, "documents.graph_extract", GraphExtractTask
)

extract_task = STAGE_TASKS[StageName.extract]
graph_extract_task = STAGE_TASKS[StageName.graph_extract]
