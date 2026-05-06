from app.workers.celery_app import celery_app


@celery_app.task(name="documents.process_document", autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def process_document(document_id: str) -> dict[str, str]:
    """Placeholder for extract/chunk/embed/index workflow."""
    return {"document_id": document_id, "status": "not_implemented"}
