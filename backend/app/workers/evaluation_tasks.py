from __future__ import annotations

from typing import Any

from app.core.logging import log_evaluation_event
from app.models.enums import EvaluationRunStatus
from app.workers.base_task import PermanentTaskError, RudixTask, TransientTaskError
from app.workers.celery_app import celery_app
from app.workers.status_tracking import get_evaluation_status, set_evaluation_status


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
        try:
            set_evaluation_status(
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
        except Exception:
            return


@celery_app.task(name="evaluations.run", bind=True, base=EvaluationTask)
def run_evaluation(
    self: EvaluationTask,
    evaluation_run_id: str,
    *,
    request_id: str | None = None,
    organization_id: str | None = None,
    user_id: str | None = None,
    force: bool = False,
) -> dict[str, str]:
    """Scaffold task for asynchronous evaluation lifecycle orchestration."""
    try:
        status = get_evaluation_status(evaluation_run_id)
    except ValueError as exc:
        raise PermanentTaskError(f"Invalid evaluation_run_id: {evaluation_run_id}") from exc
    if status is None:
        raise PermanentTaskError(f"Evaluation run not found: {evaluation_run_id}")

    if not force and status == EvaluationRunStatus.completed.value:
        log_evaluation_event(
            event="evaluation.run.skipped",
            job_id=evaluation_run_id,
            request_id=request_id,
            organization_id=organization_id,
            user_id=user_id,
            status_code=status,
        )
        return {"evaluation_run_id": evaluation_run_id, "status": "skipped"}

    running_updated = set_evaluation_status(
        evaluation_run_id,
        status=EvaluationRunStatus.running,
        mark_started=True,
    )
    if not running_updated:
        raise TransientTaskError(f"Unable to move evaluation run to running state: {evaluation_run_id}")

    log_evaluation_event(
        event="evaluation.run.started",
        job_id=evaluation_run_id,
        request_id=request_id,
        organization_id=organization_id,
        user_id=user_id,
        status_code=EvaluationRunStatus.running.value,
    )

    completed_updated = set_evaluation_status(
        evaluation_run_id,
        status=EvaluationRunStatus.completed,
        mark_completed=True,
    )
    if not completed_updated:
        raise TransientTaskError(f"Unable to move evaluation run to completed state: {evaluation_run_id}")

    log_evaluation_event(
        event="evaluation.run.completed",
        job_id=evaluation_run_id,
        request_id=request_id,
        organization_id=organization_id,
        user_id=user_id,
        status_code=EvaluationRunStatus.completed.value,
    )
    return {"evaluation_run_id": evaluation_run_id, "status": EvaluationRunStatus.completed.value}
