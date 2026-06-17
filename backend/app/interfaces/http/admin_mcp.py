from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_permission
from app.auth.models import AuthenticatedPrincipal
from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import get_db_session
from app.domains.admin.services.audit_service import AuditLogService
from app.domains.mcp.repository import MCPPolicyRepository
from app.domains.mcp.schemas import (
    MCPAuditEvent,
    MCPAuditEventListResponse,
    MCPDependencyStatus,
    MCPStatusResponse,
    MCPToolInfo,
    MCPToolListResponse,
    OrgMCPPolicyResponse,
    UpdateMCPPolicyRequest,
)
from app.models.permissions import PermissionType
from app.models.usage import AuditLog
from app.rate_limit import RateLimitScope, enforce_rate_limit

router = APIRouter(prefix="/admin/mcp", tags=["admin-mcp"])

_policy_repo = MCPPolicyRepository()
_audit_service = AuditLogService()
_logger = get_logger("admin.mcp")

_MCP_AUDIT_ACTION_PREFIX = "mcp."


def _org_and_user(principal: AuthenticatedPrincipal) -> tuple[UUID, UUID]:
    if principal.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No active organization context for principal",
        )
    try:
        return UUID(principal.organization_id), UUID(principal.user_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Principal identity context is invalid",
        ) from exc


def _request_id(request: Request) -> str | None:
    rid = getattr(request.state, "request_id", None)
    if isinstance(rid, str) and rid.strip():
        return rid
    return request.headers.get("x-request-id")


def _policy_to_response(policy, organization_id: UUID) -> OrgMCPPolicyResponse:
    return OrgMCPPolicyResponse(
        organization_id=str(organization_id),
        enabled=policy.enabled,
        read_only=policy.read_only,
        allowed_tools=policy.allowed_tools,
        capabilities_owner=policy.capabilities_owner,
        capabilities_admin=policy.capabilities_admin,
        capabilities_member=policy.capabilities_member,
        capabilities_viewer=policy.capabilities_viewer,
        rate_limit_enabled=policy.rate_limit_enabled,
        rate_limit_requests=policy.rate_limit_requests,
        rate_limit_window_seconds=policy.rate_limit_window_seconds,
        updated_by_user_id=(
            str(policy.updated_by_user_id) if policy.updated_by_user_id else None
        ),
        updated_at=policy.updated_at if hasattr(policy, "updated_at") and policy.updated_at else datetime.now(tz=UTC),
    )


@router.get("/policy", response_model=OrgMCPPolicyResponse)
async def get_mcp_policy(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(PermissionType.mcp_manage)),
    ],
    _rate_limit: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> OrgMCPPolicyResponse:
    """Get the org-scoped MCP policy. Returns defaults if not yet configured."""
    organization_id, _ = _org_and_user(principal)
    policy = await _policy_repo.get_or_default(db_session, organization_id=organization_id)
    return _policy_to_response(policy, organization_id)


@router.patch("/policy", response_model=OrgMCPPolicyResponse)
async def update_mcp_policy(
    payload: UpdateMCPPolicyRequest,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(PermissionType.mcp_manage)),
    ],
    _rate_limit: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> OrgMCPPolicyResponse:
    """Update MCP policy fields. Only fields present in the request body are changed."""
    organization_id, user_id = _org_and_user(principal)
    rid = _request_id(request)

    from app.domains.mcp.repository import _UNSET

    upsert_kwargs: dict = {
        "organization_id": organization_id,
        "updated_by_user_id": user_id,
    }
    if payload.enabled is not None:
        upsert_kwargs["enabled"] = payload.enabled
    if payload.read_only is not None:
        upsert_kwargs["read_only"] = payload.read_only
    if payload.rate_limit_enabled is not None:
        upsert_kwargs["rate_limit_enabled"] = payload.rate_limit_enabled
    if payload.rate_limit_requests is not None:
        upsert_kwargs["rate_limit_requests"] = payload.rate_limit_requests
    if payload.rate_limit_window_seconds is not None:
        upsert_kwargs["rate_limit_window_seconds"] = payload.rate_limit_window_seconds

    # Use model_fields_set to detect explicit null assignments
    set_fields = payload.model_fields_set
    for field in (
        "allowed_tools",
        "capabilities_owner",
        "capabilities_admin",
        "capabilities_member",
        "capabilities_viewer",
    ):
        if field in set_fields:
            upsert_kwargs[field] = getattr(payload, field)

    policy = await _policy_repo.upsert(db_session, **upsert_kwargs)

    await _audit_service.record(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        action="mcp.policy.updated",
        resource_type="mcp_policy",
        request_id=rid,
        metadata={
            "fields_changed": list(set_fields),
            "enabled": policy.enabled,
            "read_only": policy.read_only,
        },
    )
    await db_session.commit()

    _logger.info(
        "admin.mcp.policy.updated",
        organization_id=str(organization_id),
        user_id=str(user_id),
        fields_changed=list(set_fields),
    )
    return _policy_to_response(policy, organization_id)


@router.get("/status", response_model=MCPStatusResponse)
async def get_mcp_status(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(PermissionType.mcp_manage)),
    ],
    _rate_limit: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
) -> MCPStatusResponse:
    """Return the current MCP server status: feature flags, dependencies, transport config."""
    sdk_ok = True
    try:
        from app.mcp.dependencies import MCPSDKUnavailableError, load_fastmcp_class

        load_fastmcp_class()
    except Exception:
        sdk_ok = False

    dependencies = {
        "feature_flag": MCPDependencyStatus(
            ok=bool(settings.feature_enable_mcp),
            detail=None if settings.feature_enable_mcp else "feature_enable_mcp_false",
        ),
        "mcp_sdk": MCPDependencyStatus(
            ok=sdk_ok,
            detail=None if sdk_ok else "mcp_sdk_unavailable",
        ),
        "auth_required": MCPDependencyStatus(
            ok=settings.mcp_require_bearer_auth,
            detail=None if settings.mcp_require_bearer_auth else "bearer_auth_disabled",
        ),
    }
    failed = [name for name, dep in dependencies.items() if not dep.ok]

    return MCPStatusResponse(
        feature_enabled=settings.feature_enable_mcp,
        auth_required=settings.mcp_require_bearer_auth,
        transport=settings.mcp_transport.value,
        server_name=settings.mcp_server_name,
        rate_limit_enabled=settings.mcp_rate_limit_enabled,
        rate_limit_requests=settings.mcp_rate_limit_requests,
        rate_limit_window_seconds=settings.mcp_rate_limit_window_seconds,
        http_host=settings.mcp_http_host,
        http_port=settings.mcp_http_port,
        http_path=settings.mcp_http_path,
        dependencies=dependencies,
        failed_dependencies=failed,
    )


@router.get("/tools", response_model=MCPToolListResponse)
async def list_mcp_tools(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(PermissionType.mcp_manage)),
    ],
    _rate_limit: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
) -> MCPToolListResponse:
    """List all MCP tools registered in this server, including deprecated aliases."""
    if not settings.feature_enable_mcp:
        return MCPToolListResponse(items=[], total=0)

    try:
        from app.mcp.server import _build_mcp_tool_runtime

        runtime = _build_mcp_tool_runtime()
        items = [
            MCPToolInfo(
                name=binding.internal_name,
                public_name=binding.public_name,
                description=binding.public_spec.description,
                capability=binding.public_spec.capability,
                deprecated_alias=binding.deprecated_alias,
            )
            for binding in runtime.bindings.values()
        ]
    except Exception:
        items = []

    return MCPToolListResponse(items=items, total=len(items))


@router.get("/audit-events", response_model=MCPAuditEventListResponse)
async def list_mcp_audit_events(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(PermissionType.mcp_manage)),
    ],
    _rate_limit: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> MCPAuditEventListResponse:
    """Return recent MCP audit events for this organization."""
    organization_id, _ = _org_and_user(principal)

    stmt = (
        select(AuditLog)
        .where(
            AuditLog.organization_id == organization_id,
            AuditLog.action.like(f"{_MCP_AUDIT_ACTION_PREFIX}%"),
        )
        .order_by(desc(AuditLog.created_at))
        .offset(offset)
        .limit(limit)
    )
    result = await db_session.execute(stmt)
    rows = result.scalars().all()

    items = [
        MCPAuditEvent(
            id=str(row.id),
            action=row.action,
            user_id=str(row.user_id) if row.user_id else None,
            resource_type=row.resource_type,
            resource_id=str(row.resource_id) if row.resource_id else None,
            metadata=row.metadata_json or {},
            created_at=row.created_at,
        )
        for row in rows
    ]
    return MCPAuditEventListResponse(items=items, total=len(items))
