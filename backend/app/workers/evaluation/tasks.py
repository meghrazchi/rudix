"""The ``evaluations.run`` Celery task and its worker audit helpers.

Routed to ``CELERY_QUEUE_EVALUATIONS`` (``celery_app.TASK_ROUTES``), which the ``eval``
worker pool consumes in staging and production (R06-04), so evaluation load never shares
a worker with chat-adjacent or ingestion queues. Collaborators are read from the
``evaluation_tasks`` facade at call time.
"""

from __future__ import annotations

from typing import Any

from app.core.logging import log_evaluation_event
from app.models.enums import EvaluationRunStatus
from app.workers.base_task import PermanentTaskError, RudixTask, TransientTaskError
from app.workers.celery_app import celery_app
from app.workers.evaluation import facade
from app.workers.evaluation.config import _parse_optional_uuid


async def _record_worker_audit_async(
    *,
    action: str,
    resource_type: str,
    resource_id: str | None,
    organization_id: str | None,
    user_id: str | None,
    request_id: str | None,
    metadata: dict[str, Any] | None = None,
) -> None:
    organization_uuid = _parse_optional_uuid(organization_id)
    if organization_uuid is None:
        return
    f = facade()
    try:
        async with f.SessionLocal() as audit_session:
            wrote_audit = await f._audit_log_service.record(
                audit_session,
                organization_id=organization_uuid,
                user_id=_parse_optional_uuid(user_id),
                action=action,
                resource_type=resource_type,
                resource_id=_parse_optional_uuid(resource_id),
                request_id=request_id,
                metadata=metadata or {},
            )
            if wrote_audit:
                await audit_session.commit()
    except Exception:
        return


def _record_worker_audit(
    *,
    action: str,
    resource_type: str,
    resource_id: str | None,
    organization_id: str | None,
    user_id: str | None,
    request_id: str | None,
    metadata: dict[str, Any] | None = None,
) -> None:
    f = facade()
    f._run(
        f._record_worker_audit_async(
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            organization_id=organization_id,
            user_id=user_id,
            request_id=request_id,
            metadata=metadata,
        )
    )


class EvaluationTask(RudixTask):
    abstract = True

    def on_terminal_failure(
        self,
        *,
        exc: Exception,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> None:
        evaluation_run_id = kwargs.get("evaluation_run_id")
        if evaluation_run_id is None and args:
            evaluation_run_id = args[0]
        if not isinstance(evaluation_run_id, str):
            return
        f = facade()
        try:
            f.set_evaluation_status(
                evaluation_run_id,
                status=EvaluationRunStatus.failed,
                mark_completed=True,
            )
            log_evaluation_event(
                event="evaluation.run.failed",
                job_id=evaluation_run_id,
                request_id=kwargs.get("request_id"),
                organization_id=kwargs.get("organization_id"),
                user_id=kwargs.get("user_id"),
                status_code=EvaluationRunStatus.failed.value,
                error=str(exc),
            )
            f._record_worker_audit(
                action="evaluation.run.failed",
                resource_type="evaluation_run",
                resource_id=evaluation_run_id,
                organization_id=kwargs.get("organization_id"),
                user_id=kwargs.get("user_id"),
                request_id=kwargs.get("request_id"),
                metadata={
                    "status": EvaluationRunStatus.failed.value,
                    "task_name": self.name,
                    "error_type": exc.__class__.__name__,
                },
            )
            from app.workers.notification_helper import emit_notification

            emit_notification(
                organization_id=kwargs.get("organization_id"),
                user_id=kwargs.get("user_id"),
                event_type="evaluation_failed",
                severity="error",
                title="Evaluation run failed",
                message="The evaluation run could not be completed.",
                href=f"/evaluations/runs/{evaluation_run_id}",
                source_id=evaluation_run_id,
            )
        except Exception:
            return


def _notify_final(
    *,
    final_status: EvaluationRunStatus,
    summary: dict[str, Any],
    evaluation_run_id: str,
    organization_id: str | None,
    user_id: str | None,
) -> None:
    from app.workers.notification_helper import emit_notification

    completed = final_status == EvaluationRunStatus.completed
    emit_notification(
        organization_id=organization_id,
        user_id=user_id,
        event_type="evaluation_complete" if completed else "evaluation_failed",
        severity="info" if completed else "error",
        title="Evaluation run completed" if completed else "Evaluation run failed",
        message=(
            f"{summary['question_success_count']}/{summary['question_total_count']} "
            "question(s) passed."
            if completed
            else "All questions failed during evaluation."
        ),
        href=f"/evaluations/runs/{evaluation_run_id}",
        source_id=evaluation_run_id,
    )


@celery_app.task(name="evaluations.run", bind=True, base=EvaluationTask, ignore_result=True)
def run_evaluation(
    self: EvaluationTask,
    evaluation_run_id: str,
    *,
    request_id: str | None = None,
    organization_id: str | None = None,
    user_id: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Run evaluation questions through the query pipeline and persist per-question outcomes."""
    f = facade()
    ids: dict[str, Any] = {
        "job_id": evaluation_run_id,
        "request_id": request_id,
        "organization_id": organization_id,
        "user_id": user_id,
    }
    try:
        status = f.get_evaluation_status(evaluation_run_id)
    except ValueError as exc:
        raise PermanentTaskError(f"Invalid evaluation_run_id: {evaluation_run_id}") from exc
    if status is None:
        raise PermanentTaskError(f"Evaluation run not found: {evaluation_run_id}")

    if not force and status == EvaluationRunStatus.completed.value:
        log_evaluation_event(event="evaluation.run.skipped", status_code=status, **ids)
        return {"evaluation_run_id": evaluation_run_id, "status": "skipped"}

    if not f.set_evaluation_status(
        evaluation_run_id, status=EvaluationRunStatus.running, mark_started=True
    ):
        raise TransientTaskError(
            f"Unable to move evaluation run to running state: {evaluation_run_id}"
        )
    log_evaluation_event(
        event="evaluation.run.started", status_code=EvaluationRunStatus.running.value, **ids
    )

    summary = f._run(
        f._run_evaluation_async(
            evaluation_run_id,
            request_id=request_id,
            organization_id=organization_id,
            user_id=user_id,
        )
    )
    final_status = (
        EvaluationRunStatus.failed
        if summary["all_questions_failed"]
        else EvaluationRunStatus.completed
    )
    if not f.set_evaluation_status(evaluation_run_id, status=final_status, mark_completed=True):
        raise TransientTaskError(
            f"Unable to move evaluation run to final state: {evaluation_run_id}"
        )

    counts = {
        "question_total_count": summary["question_total_count"],
        "question_success_count": summary["question_success_count"],
        "question_failure_count": summary["question_failure_count"],
    }
    log_evaluation_event(
        event="evaluation.run.completed", status_code=final_status.value, **ids, **counts
    )
    f._record_worker_audit(
        action="evaluation.run.completed",
        resource_type="evaluation_run",
        resource_id=evaluation_run_id,
        organization_id=organization_id,
        user_id=user_id,
        request_id=request_id,
        metadata={"status": final_status.value, **counts},
    )
    _notify_final(
        final_status=final_status,
        summary=summary,
        evaluation_run_id=evaluation_run_id,
        organization_id=organization_id,
        user_id=user_id,
    )
    return {
        "evaluation_run_id": evaluation_run_id,
        "status": final_status.value,
        **counts,
        "metrics_summary": summary.get("metrics_summary"),
    }
