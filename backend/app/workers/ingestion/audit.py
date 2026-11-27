"""Worker audit helpers (moved from document_tasks, R06-01)."""

from __future__ import annotations

from typing import Any

from app.workers.ingestion.deps import current_deps
from app.workers.ingestion.errors import parse_optional_uuid


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
    organization_uuid = parse_optional_uuid(organization_id)
    if organization_uuid is None:
        return
    user_uuid = parse_optional_uuid(user_id)
    parsed_resource_id = parse_optional_uuid(resource_id)
    deps = current_deps()
    try:
        async with deps.SessionLocal() as audit_session:
            wrote_audit = await deps.audit_log_service.record(
                audit_session,
                organization_id=organization_uuid,
                user_id=user_uuid,
                action=action,
                resource_type=resource_type,
                resource_id=parsed_resource_id,
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
    deps = current_deps()
    deps.run(
        deps.record_worker_audit_async(
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            organization_id=organization_id,
            user_id=user_id,
            request_id=request_id,
            metadata=metadata,
        )
    )
