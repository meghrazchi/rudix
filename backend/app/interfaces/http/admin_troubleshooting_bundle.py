"""Admin endpoints for F329: Safe troubleshooting bundle export.

Endpoints
---------
POST /admin/troubleshooting-bundle/export
    Generate a redacted diagnostic bundle for a chat message, document,
    connector sync run, evaluation run, or failed job and stream it to the
    authorized admin as a JSON file (with an optional Markdown summary).

Security
--------
- Requires security_center_view permission (admin / owner only).
- Every export is recorded in the audit log.
- Redaction is applied before any data leaves the service.
"""

from __future__ import annotations

import json
import uuid
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_permission
from app.auth.models import AuthenticatedPrincipal
from app.core.logging import get_logger
from app.db.session import get_db_session
from app.domains.admin.schemas.troubleshooting_bundle import (
    TroubleshootingBundleRequest,
    TroubleshootingBundleResponse,
)
from app.domains.admin.services.audit_service import AuditLogService
from app.domains.admin.services.troubleshooting_bundle_service import (
    AccessDeniedError,
    NotFoundError,
    TroubleshootingBundleService,
)
from app.models.permissions import PermissionType

router = APIRouter(prefix="/admin/troubleshooting-bundle", tags=["admin-troubleshooting-bundle"])

_bundle_svc = TroubleshootingBundleService()
_audit = AuditLogService()
_logger = get_logger("events.troubleshooting_bundle")


def _get_org_id(principal: AuthenticatedPrincipal) -> UUID:
    if principal.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No active organization context",
        )
    try:
        return UUID(principal.organization_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid organization context",
        ) from exc


def _get_actor_id(principal: AuthenticatedPrincipal) -> UUID:
    try:
        return UUID(principal.user_id)
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid principal context",
        ) from exc


def _build_filename(bundle: TroubleshootingBundleResponse, ext: str) -> str:
    ts = bundle.generated_at.strftime("%Y%m%d_%H%M%S")
    return f"bundle_{bundle.source_type}_{bundle.source_id[:8]}_{ts}.{ext}"


@router.post(
    "/export",
    summary="Export a redacted troubleshooting bundle",
    response_class=Response,
    responses={
        200: {
            "content": {
                "application/json": {},
                "text/markdown": {},
            },
            "description": "Redacted troubleshooting bundle (JSON or Markdown)",
        },
        404: {"description": "Source resource not found"},
        403: {"description": "Not authorized"},
    },
)
async def export_troubleshooting_bundle(
    body: TroubleshootingBundleRequest,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(PermissionType.security_center_view)),
    ],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> Response:
    """Generate and download a redacted troubleshooting bundle.

    The bundle includes trace IDs, pipeline lifecycle stages, retrieval
    diagnostics, model/provider metadata, citations (without raw content),
    redacted logs, and configuration fingerprints.

    All sensitive values (credentials, prompts, source content, PII) are
    stripped according to the configurable redaction rules before export.
    Every export is recorded in the audit log.
    """
    org_id = _get_org_id(principal)
    actor_id = _get_actor_id(principal)
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())

    try:
        bundle = await _bundle_svc.build(
            db,
            source_type=body.source_type,
            source_id=body.source_id,
            organization_id=org_id,
            actor_user_id=actor_id,
            config=body.redaction,
            include_markdown=body.include_markdown,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AccessDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    await _audit.record(
        db,
        organization_id=org_id,
        user_id=actor_id,
        action="troubleshooting_bundle.export",
        resource_type=body.source_type.value,
        resource_id=body.source_id,
        request_id=request_id,
        metadata={
            "bundle_id": bundle.bundle_id,
            "source_type": body.source_type.value,
            "source_id": str(body.source_id),
            "include_markdown": body.include_markdown,
            "redact_prompts": body.redaction.redact_prompts,
            "redact_snippets": body.redaction.redact_snippets,
            "redact_pii": body.redaction.redact_pii,
            "redact_source_content": body.redaction.redact_source_content,
        },
    )

    _logger.info(
        "troubleshooting_bundle.exported",
        bundle_id=bundle.bundle_id,
        source_type=body.source_type.value,
        source_id=str(body.source_id),
        actor_id=str(actor_id),
        org_id=str(org_id),
        request_id=request_id,
    )

    if body.include_markdown and bundle.markdown_summary:
        filename = _build_filename(bundle, "md")
        return Response(
            content=bundle.markdown_summary,
            media_type="text/markdown",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    payload = bundle.model_dump(mode="json")
    filename = _build_filename(bundle, "json")
    return Response(
        content=json.dumps(payload, indent=2, default=str),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
