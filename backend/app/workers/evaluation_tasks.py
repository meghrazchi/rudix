from app.core.logging import log_evaluation_event, log_task_failure
from app.workers.celery_app import celery_app


@celery_app.task(name="evaluations.run", autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def run_evaluation(evaluation_run_id: str) -> dict[str, str]:
    """Placeholder for asynchronous evaluation workflow."""
    try:
        log_evaluation_event(
            event="evaluation.run",
            job_id=evaluation_run_id,
            status_code="started",
        )
        result = {"evaluation_run_id": evaluation_run_id, "status": "not_implemented"}
        log_evaluation_event(
            event="evaluation.run",
            job_id=evaluation_run_id,
            status_code="success",
        )
        return result
    except Exception as exc:  # pragma: no cover - defensive scaffold path.
        log_task_failure(
            task_name="evaluations.run",
            job_id=evaluation_run_id,
            error=str(exc),
        )
        raise
