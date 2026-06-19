"""Admin endpoints for F335: Authorization conflict detection and access explanation.

Endpoints
---------
GET    /admin/permissions/conflicts               — list conflicts (paginated)
GET    /admin/permissions/conflicts/{id}          — get conflict detail
PATCH  /admin/permissions/conflicts/{id}/status   — update status
POST   /admin/permissions/conflicts/scan          — trigger conflict scan
GET    /admin/permissions/explain-decision        — explain why access is allowed/denied
"""

from __future__ import annotations

import uuid
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_permission
from app.auth.models import AuthenticatedPrincipal
from app.auth.permission_service import PermissionService
from app.auth.policy_engine import (
    Action,
    DenyReason,
    PermissionResult,
    PolicyEngine,
    ResourceContext,
    ResourceType,
    SubjectContext,
)
from app.core.logging import get_logger
from app.db.session import get_db_session
from app.domains.admin.services.audit_service import AuditLogService
from app.domains.permissions.repositories.conflicts import ConflictsRepository
from app.domains.permissions.schemas.conflicts import (
    DB_TO_SEVERITY,
    SEVERITY_TO_DB,
    ConflictListResponse,
    ConflictResponse,
    ExplainDecisionRequest,
    ExplainDecisionResponse,
    ScanResult,
    TraceStep,
    UpdateConflictStatusRequest,
    remediation_for,
)
from app.domains.permissions.services.conflict_detection_service import (
    ConflictDetectionService,
)
from app.models.authorization import AuthorizationConflict
from app.models.organization_member import OrganizationMember
from app.models.permissions import ROLE_PERMISSIONS, PermissionType

router = APIRouter(prefix="/admin/permissions", tags=["permissions"])

_repo = ConflictsRepository()
_detection_svc = ConflictDetectionService()
_audit = AuditLogService()
_engine = PolicyEngine()
_perm_svc = PermissionService()
_logger = get_logger("events.conflicts")


def _org_id(principal: AuthenticatedPrincipal) -> UUID:
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


def _user_id(principal: AuthenticatedPrincipal) -> UUID:
    try:
        return UUID(principal.user_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid principal context",
        ) from exc


def _request_id(request: Request) -> str | None:
    rid = getattr(request.state, "request_id", None)
    if isinstance(rid, str) and rid.strip():
        return rid
    return request.headers.get("x-request-id")


def _conflict_to_response(c: AuthorizationConflict) -> ConflictResponse:
    severity_api = DB_TO_SEVERITY.get(c.severity, c.severity)
    return ConflictResponse(
        id=str(c.id),
        organization_id=str(c.organization_id),
        subject_type=c.subject_type,
        subject_value=c.subject_value,
        user_id=str(c.user_id) if c.user_id else None,
        role_name=c.role_name,
        resource_type=c.resource_type,
        resource_id=c.resource_id,
        action=c.action,
        conflict_type=c.conflict_type,
        severity=severity_api,
        status=c.status,
        detected_at=c.detected_at,
        resolved_at=c.resolved_at,
        conflict_summary=c.conflict_summary,
        grant_id=str(c.grant_id) if c.grant_id else None,
        deny_id=str(c.deny_id) if c.deny_id else None,
        remediation=remediation_for(c.conflict_type),
        context=c.conflict_context_json or {},
    )


def _parse_trace(raw_trace: list[str]) -> list[TraceStep]:
    steps: list[TraceStep] = []
    for entry in raw_trace:
        if ":allow" in entry:
            rule = entry.split(":allow")[0]
            steps.append(TraceStep(rule=rule, outcome="allow", detail=None))
        elif ":deny(" in entry:
            rule = entry.split(":deny(")[0]
            reason_part = entry.split(":deny(")[-1].rstrip(")")
            steps.append(TraceStep(rule=rule, outcome="deny", detail=reason_part))
        elif ":pass" in entry:
            rule = entry.split(":pass")[0]
            detail = entry.split(":pass")[-1].lstrip("(").rstrip(")") or None
            steps.append(TraceStep(rule=rule, outcome="pass", detail=detail or None))
        else:
            steps.append(TraceStep(rule=entry, outcome="pass", detail=None))
    return steps


def _remediation_from_decision(
    decision: str,
    matched_rule: str,
    deny_reason: str | None,
    resource_type: str,
) -> list[str]:
    if decision == "allow":
        return []
    suggestions: list[str] = []
    if deny_reason == DenyReason.insufficient_role:
        suggestions.append(
            f"Grant the user a role with sufficient permissions for {resource_type} access."
        )
        suggestions.append("Use Admin > Access Management to add an explicit resource grant.")
    elif deny_reason == DenyReason.explicit_resource_deny:
        suggestions.append("An explicit deny overrides this user's role. Revoke the deny entry.")
        suggestions.append(
            "Go to Admin > Access Management > Resource Denies to find and remove it."
        )
    elif deny_reason == DenyReason.connector_acl_denied:
        suggestions.append(
            "The user is not in the connector ACL. Re-sync the connector or update ACL in the source system."
        )
    elif deny_reason == DenyReason.feature_not_entitled:
        suggestions.append("The feature is disabled for this organisation. Enable it in feature flags.")
    elif deny_reason == DenyReason.collection_not_accessible:
        suggestions.append(
            "The resource is only accessible through a collection the user cannot access."
        )
        suggestions.append("Grant the user collection access or add an explicit resource grant.")
    elif deny_reason == DenyReason.no_organization_context:
        suggestions.append("The user must be a member of an organisation to access this resource.")
    elif deny_reason == DenyReason.tenant_boundary:
        suggestions.append("This resource belongs to a different organisation — cross-tenant access is blocked.")
    else:
        suggestions.append("Review the user's role and any explicit grants or denies.")
    return suggestions


# ── List conflicts ─────────────────────────────────────────────────────────────


@router.get("/conflicts", response_model=ConflictListResponse)
async def list_conflicts(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(PermissionType.security_center_view)),
    ],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    severity: str | None = Query(default=None),
    conflict_status: str | None = Query(default=None, alias="status"),
    resource_type: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> ConflictListResponse:
    """Return paginated list of detected permission conflicts for the organisation."""
    organization_id = _org_id(principal)
    severity_db = SEVERITY_TO_DB.get(severity) if severity else None
    items, total = await _repo.list_conflicts(
        db,
        organization_id=organization_id,
        severity_db=severity_db,
        status=conflict_status,
        resource_type=resource_type,
        page=page,
        page_size=page_size,
    )
    return ConflictListResponse(
        items=[_conflict_to_response(c) for c in items],
        total=total,
        page=page,
        page_size=page_size,
    )


# ── Get conflict detail ────────────────────────────────────────────────────────


@router.get("/conflicts/{conflict_id}", response_model=ConflictResponse)
async def get_conflict(
    conflict_id: str,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(PermissionType.security_center_view)),
    ],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> ConflictResponse:
    """Return a single conflict with full context and remediation advice."""
    organization_id = _org_id(principal)
    try:
        parsed_id = UUID(conflict_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conflict not found") from exc

    conflict = await _repo.get_conflict(db, conflict_id=parsed_id, organization_id=organization_id)
    if conflict is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conflict not found")
    return _conflict_to_response(conflict)


# ── Update conflict status ─────────────────────────────────────────────────────


@router.patch("/conflicts/{conflict_id}/status", response_model=ConflictResponse)
async def update_conflict_status(
    request: Request,
    conflict_id: str,
    payload: UpdateConflictStatusRequest,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(PermissionType.security_center_configure)),
    ],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> ConflictResponse:
    """Transition a conflict to investigating, resolved, or dismissed."""
    organization_id = _org_id(principal)
    actor_id = _user_id(principal)
    request_id = _request_id(request)

    try:
        parsed_id = UUID(conflict_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conflict not found") from exc

    conflict = await _repo.get_conflict(db, conflict_id=parsed_id, organization_id=organization_id)
    if conflict is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conflict not found")

    if conflict.status in ("resolved", "dismissed"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Conflict is already {conflict.status} and cannot be updated.",
        )

    updated = await _repo.update_conflict_status(
        db,
        conflict=conflict,
        new_status=payload.status,
        resolution_note=payload.resolution_note,
    )
    await _audit.record(
        db,
        organization_id=organization_id,
        user_id=actor_id,
        action="permissions.conflict.status_updated",
        resource_type="authorization_conflict",
        resource_id=parsed_id,
        request_id=request_id,
        metadata={
            "new_status": payload.status,
            "conflict_type": conflict.conflict_type,
            "severity": conflict.severity,
        },
    )
    await db.commit()

    _logger.info(
        "permissions.conflict.status_updated",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        conflict_id=conflict_id,
        new_status=payload.status,
    )
    return _conflict_to_response(updated)


# ── Trigger conflict scan ──────────────────────────────────────────────────────


@router.post(
    "/conflicts/scan",
    response_model=ScanResult,
    status_code=status.HTTP_200_OK,
)
async def scan_for_conflicts(
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(PermissionType.security_center_configure)),
    ],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> ScanResult:
    """Scan the organisation's grants, denies, and ACL mappings for conflicts."""
    organization_id = _org_id(principal)
    actor_id = _user_id(principal)
    request_id = _request_id(request)

    result = await _detection_svc.scan(db, organization_id=organization_id)

    await _audit.record(
        db,
        organization_id=organization_id,
        user_id=actor_id,
        action="permissions.conflicts.scanned",
        resource_type="organization",
        resource_id=organization_id,
        request_id=request_id,
        metadata={
            "conflicts_detected": result.conflicts_detected,
            "conflicts_created": result.conflicts_created,
            "scan_duration_ms": result.scan_duration_ms,
        },
    )
    await db.commit()

    _logger.info(
        "permissions.conflicts.scanned",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        conflicts_detected=result.conflicts_detected,
        conflicts_created=result.conflicts_created,
    )
    return result


# ── Explain access decision ────────────────────────────────────────────────────


@router.get("/explain-decision", response_model=ExplainDecisionResponse)
async def explain_decision(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(PermissionType.security_center_view)),
    ],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    subject_user_id: str = Query(),
    resource_type: str = Query(),
    action: str = Query(),
    resource_id: str | None = Query(default=None),
) -> ExplainDecisionResponse:
    """Simulate the policy engine for a given subject/resource/action triple.

    Requires security_center_view. Does NOT expose resource content; only
    structural access metadata is returned.
    """
    organization_id = _org_id(principal)
    rid = str(uuid.uuid4())

    # Validate resource_type and action
    try:
        rt = ResourceType(resource_type)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown resource_type: {resource_type}",
        ) from exc

    try:
        act = Action(action)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown action: {action}",
        ) from exc

    # Resolve the target user's membership + permissions
    try:
        subject_uuid = UUID(subject_user_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="subject_user_id must be a valid UUID",
        ) from exc

    member_row = await db.scalar(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id == subject_uuid,
        )
    )
    if member_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subject user is not a member of this organisation",
        )

    resolved_perms = await _perm_svc.get_user_permissions(
        db,
        roles=[member_row.role],
        custom_role_id=member_row.custom_role_id,
    )

    subject = SubjectContext(
        user_id=subject_user_id,
        organization_id=str(organization_id),
        roles=frozenset([member_row.role]),
        resolved_permissions=resolved_perms,
    )

    resource = ResourceContext(
        resource_type=rt,
        resource_id=resource_id,
        organization_id=str(organization_id),
    )

    result = _engine.authorize(subject, act, resource, request_id=rid)

    trace_steps = _parse_trace(result.trace)
    remediation = _remediation_from_decision(
        result.result.value,
        result.matched_rule,
        result.deny_reason.value if result.deny_reason else None,
        resource_type,
    )

    return ExplainDecisionResponse(
        decision=result.result.value,
        matched_rule=result.matched_rule,
        deny_reason=result.deny_reason.value if result.deny_reason else None,
        subject_user_id=subject_user_id,
        resource_type=resource_type,
        resource_id=resource_id,
        action=action,
        trace=trace_steps,
        remediation=remediation,
        request_id=rid,
    )
