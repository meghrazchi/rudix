from app.core.logging import log_document_event, log_task_failure
from app.workers.celery_app import celery_app


@celery_app.task(name="documents.process_document", autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def process_document(document_id: str) -> dict[str, str]:
    """Placeholder for extract/chunk/embed/index workflow."""
    try:
        log_document_event(
            event="document.processing",
            document_id=document_id,
            status_code="started",
        )
        result = {"document_id": document_id, "status": "not_implemented"}
        log_document_event(
            event="document.processing",
            document_id=document_id,
            status_code="success",
        )
        return result
    except Exception as exc:  # pragma: no cover - defensive scaffold path.
        log_task_failure(
            task_name="documents.process_document",
            document_id=document_id,
            error=str(exc),
        )
        raise
