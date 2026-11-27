"""Organisation-wide reindex backfill (moved from document_tasks, R06-01)."""

from __future__ import annotations

from uuid import UUID

from app.models.enums import DocumentStatus
from app.workers.base_task import PermanentTaskError
from app.workers.celery_app import celery_app
from app.workers.ingestion.deps import current_deps
from app.workers.ingestion.errors import parse_uuid


async def _backfill_dispatch_async(
    organization_uuid: UUID,
    *,
    chunking_profile_config: dict | None,
    request_id: str | None,
    user_id: str | None,
) -> int:
    """Query all indexed documents for an org and dispatch reindex tasks for each."""
    deps = current_deps()
    dispatched = 0
    offset = 0
    page_size = 100
    while True:
        async with deps.SessionLocal() as session:
            docs = await deps.document_repository.list_documents(
                session,
                organization_id=organization_uuid,
                status=DocumentStatus.indexed.value,
                limit=page_size,
                offset=offset,
            )
        if not docs:
            break
        for doc in docs:
            celery_app.send_task(
                "documents.reindex",
                kwargs={
                    "document_id": str(doc.id),
                    "organization_id": str(organization_uuid),
                    "user_id": user_id,
                    "request_id": request_id,
                    "chunking_profile_config": chunking_profile_config,
                },
            )
            dispatched += 1
        offset += len(docs)
        if len(docs) < page_size:
            break
    return dispatched


def run_backfill_task(
    *,
    organization_id: str,
    chunking_profile_config: dict | None,
    request_id: str | None,
    user_id: str | None,
) -> dict[str, str | int]:
    """Body of ``documents.backfill``."""
    deps = current_deps()
    try:
        org_uuid = parse_uuid(organization_id)
    except ValueError as exc:
        raise PermanentTaskError(f"Invalid organization_id: {organization_id}") from exc

    try:
        deps.make_chunking_service(chunking_profile_config)
    except ValueError as exc:
        raise PermanentTaskError(f"Invalid chunking_profile_config: {exc}") from exc

    dispatched = deps.run(
        deps.backfill_dispatch_async(
            org_uuid,
            chunking_profile_config=chunking_profile_config,
            request_id=request_id,
            user_id=user_id,
        )
    )
    deps.log_document_event(
        event="document.backfill.completed",
        organization_id=organization_id,
        user_id=user_id,
        request_id=request_id,
        dispatched_count=dispatched,
    )
    deps.record_worker_audit(
        action="document.backfill.completed",
        resource_type="organization",
        resource_id=organization_id,
        organization_id=organization_id,
        user_id=user_id,
        request_id=request_id,
        metadata={"dispatched_count": dispatched},
    )
    return {"organization_id": organization_id, "dispatched_count": dispatched}
