from app.workers.celery_app import celery_app


@celery_app.task(name="evaluations.run", autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def run_evaluation(evaluation_run_id: str) -> dict[str, str]:
    """Placeholder for asynchronous evaluation workflow."""
    return {"evaluation_run_id": evaluation_run_id, "status": "not_implemented"}
