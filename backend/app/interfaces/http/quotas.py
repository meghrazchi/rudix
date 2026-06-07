"""Quota and rate-limit management endpoints (F154).

Admin endpoints:
  GET  /admin/quotas/policy          — current quota policy
  PATCH /admin/quotas/policy         — upsert quota policy
  DELETE /admin/quotas/policy        — reset to system defaults
  GET  /admin/quotas/usage           — current usage vs limits dashboard
  GET  /admin/quotas/overrides       — list manual overrides
  POST /admin/quotas/overrides       — create manual override
  DELETE /admin/quotas/overrides/{id} — remove override
  GET  /admin/quotas/change-log      — policy change history

User endpoint:
  GET  /quotas/my-usage              — calling user's quota status
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.core.logging import log_evaluation_event
from app.db.session import get_db_session
from app.domains.admin.services.audit_service import AuditLogService
from app.domains.quota.repositories.quota_repository import QuotaRepository
from app.domains.quota.schemas.quota_schemas import (
    CreateQuotaOverrideRequest,
    OrgQuotaDashboardResponse,
    OrgQuotaPolicyResponse,
    QuotaChangeLogEntryResponse,
    QuotaChangeLogResponse,
    QuotaOverrideListResponse,
    QuotaOverrideResponse,
    QuotaType,
    UpdateOrgQuotaPolicyRequest,
)
from app.domains.quota.services.quota_service import (
    delete_policy_with_log,
    get_effective_limits,
    get_quota_dashboard,
    upsert_policy_with_log,
)
from app.models.enums import OrganizationRole
from app.models.quotas import OrgQuotaChangeLog, OrgQuotaOverride, OrgQuotaPolicy

admin_router = APIRouter(prefix="/admin/quotas", tags=["admin-quotas"])
user_router = APIRouter(prefix="/quotas", tags=["quotas"])

_repo = QuotaRepository()
_audit_service = AuditLogService()

_ALL_ROLES = (
    OrganizationRole.owner.value,
    OrganizationRole.admin.value,
    OrganizationRole.member.value,
    OrganizationRole.viewer.value,
)
_ADMIN_ROLES = (OrganizationRole.owner.value, OrganizationRole.admin.value)
_OWNER_ROLES = (OrganizationRole.owner.value,)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
            detail="Invalid user context",
        ) from exc


def _request_id(request: Request) -> str | None:
    rid = getattr(request.state, "request_id", None)
    if isinstance(rid, str) and rid.strip():
        return rid
    return request.headers.get("x-request-id")


def _policy_to_response(policy: OrgQuotaPolicy) -> OrgQuotaPolicyResponse:
    return OrgQuotaPolicyResponse(
        organization_id=str(policy.organization_id),
        limits=dict(policy.limits or {}),
        version=policy.version,
        updated_by_id=str(policy.updated_by_id) if policy.updated_by_id else None,
        updated_at=policy.updated_at,
    )


def _override_to_response(override: OrgQuotaOverride) -> QuotaOverrideResponse:
    return QuotaOverrideResponse(
        override_id=str(override.id),
        organization_id=str(override.organization_id),
        quota_type=override.quota_type,
        target_user_id=str(override.target_user_id) if override.target_user_id else None,
        hard_limit_override=override.hard_limit_override,
        reason=override.reason,
        created_by_id=str(override.created_by_id) if override.created_by_id else None,
        expires_at=override.expires_at,
        created_at=override.created_at,
    )


def _change_log_entry_to_response(entry: OrgQuotaChangeLog) -> QuotaChangeLogEntryResponse:
    return QuotaChangeLogEntryResponse(
        entry_id=str(entry.id),
        organization_id=str(entry.organization_id),
        version_number=entry.version_number,
        policy_snapshot=dict(entry.policy_snapshot or {}),
        change_note=entry.change_note,
        changed_by_id=str(entry.changed_by_id) if entry.changed_by_id else None,
        created_at=entry.created_at,
    )


def _merge_limits_from_request(
    existing_limits: dict,
    payload: UpdateOrgQuotaPolicyRequest,
) -> dict:
    """Merge request payload into existing limits dict (partial update)."""
    merged = dict(existing_limits)
    for qt in QuotaType:
        config = getattr(payload, qt, None)
        if config is not None:
            merged[qt] = {
                "soft_limit": config.soft_limit,
                "hard_limit": config.hard_limit,
                "reset_window": config.reset_window,
            }
    return merged


# ---------------------------------------------------------------------------
# Admin: Policy endpoints
# ---------------------------------------------------------------------------


@admin_router.get("/policy", response_model=OrgQuotaPolicyResponse)
async def get_quota_policy(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> OrgQuotaPolicyResponse:
    """Return the org's current quota policy.

    Auth: owner or admin.
    """
    organization_id = _org_id(principal)
    policy = await _repo.get_policy(db_session, organization_id=organization_id)
    if policy is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No quota policy configured for this organization",
        )
    return _policy_to_response(policy)


@admin_router.patch("/policy", response_model=OrgQuotaPolicyResponse)
async def update_quota_policy(
    request: Request,
    payload: UpdateOrgQuotaPolicyRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> OrgQuotaPolicyResponse:
    """Create or update the org quota policy.

    Auth: owner or admin. Only supplied quota types are modified.
    """
    organization_id = _org_id(principal)
    user_id = _user_id(principal)
    request_id = _request_id(request)

    existing = await _repo.get_policy(db_session, organization_id=organization_id)
    current_limits = dict(existing.limits or {}) if existing else {}
    merged = _merge_limits_from_request(current_limits, payload)

    policy = await upsert_policy_with_log(
        db_session,
        organization_id=organization_id,
        limits=merged,
        updated_by_id=user_id,
        change_note=payload.change_note,
    )
    await db_session.commit()
    await db_session.refresh(policy)

    await _audit_service.record(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        action="quota_policy.updated",
        resource_type="org_quota_policy",
        resource_id=policy.id,
        request_id=request_id,
        metadata={"version": policy.version, "quota_types_updated": list(merged.keys())},
    )
    await db_session.commit()

    log_evaluation_event(
        event="quota_policy.updated",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        job_id=str(policy.id),
        status_code=status.HTTP_200_OK,
    )
    return _policy_to_response(policy)


@admin_router.delete("/policy", status_code=status.HTTP_204_NO_CONTENT)
async def reset_quota_policy(
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    change_note: Annotated[str | None, Query(max_length=1000)] = None,
) -> None:
    """Delete org quota overrides and revert to system defaults.

    Auth: owner or admin.
    """
    organization_id = _org_id(principal)
    user_id = _user_id(principal)
    request_id = _request_id(request)

    policy = await _repo.get_policy(db_session, organization_id=organization_id)
    if policy is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No quota policy to reset",
        )

    await delete_policy_with_log(
        db_session,
        organization_id=organization_id,
        deleted_by_id=user_id,
        change_note=change_note,
    )
    await db_session.commit()

    await _audit_service.record(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        action="quota_policy.reset",
        resource_type="org_quota_policy",
        resource_id=None,
        request_id=request_id,
        metadata={},
    )
    await db_session.commit()


# ---------------------------------------------------------------------------
# Admin: Usage dashboard
# ---------------------------------------------------------------------------


@admin_router.get("/usage", response_model=OrgQuotaDashboardResponse)
async def get_quota_usage(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> OrgQuotaDashboardResponse:
    """Return current quota usage vs limits for the org.

    Auth: owner or admin. Resets expired windows before responding.
    """
    organization_id = _org_id(principal)
    dashboard = await get_quota_dashboard(db_session, organization_id=organization_id)
    await db_session.commit()
    return dashboard


# ---------------------------------------------------------------------------
# Admin: Overrides
# ---------------------------------------------------------------------------


@admin_router.get("/overrides", response_model=QuotaOverrideListResponse)
async def list_quota_overrides(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> QuotaOverrideListResponse:
    """List active quota overrides for the org.

    Auth: owner or admin.
    """
    organization_id = _org_id(principal)
    overrides = await _repo.list_overrides(
        db_session, organization_id=organization_id, limit=limit, offset=offset
    )
    total = await _repo.count_overrides(db_session, organization_id=organization_id)
    return QuotaOverrideListResponse(
        items=[_override_to_response(o) for o in overrides],
        total=total,
    )


@admin_router.post(
    "/overrides", response_model=QuotaOverrideResponse, status_code=status.HTTP_201_CREATED
)
async def create_quota_override(
    request: Request,
    payload: CreateQuotaOverrideRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_OWNER_ROLES))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> QuotaOverrideResponse:
    """Create a manual quota override (org-wide or per-user).

    Auth: owner only. Audited.
    """
    organization_id = _org_id(principal)
    user_id = _user_id(principal)
    request_id = _request_id(request)

    if payload.quota_type not in [qt.value for qt in QuotaType]:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid quota_type: {payload.quota_type!r}",
        )

    target_user_uuid: UUID | None = None
    if payload.target_user_id is not None:
        try:
            target_user_uuid = UUID(payload.target_user_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid target_user_id format",
            ) from exc

    override = await _repo.create_override(
        db_session,
        organization_id=organization_id,
        quota_type=payload.quota_type,
        target_user_id=target_user_uuid,
        hard_limit_override=payload.hard_limit_override,
        reason=payload.reason,
        created_by_id=user_id,
        expires_at=payload.expires_at,
    )
    await db_session.commit()
    await db_session.refresh(override)

    await _audit_service.record(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        action="quota_override.created",
        resource_type="org_quota_override",
        resource_id=override.id,
        request_id=request_id,
        metadata={
            "quota_type": override.quota_type,
            "hard_limit_override": override.hard_limit_override,
            "target_user_id": str(override.target_user_id) if override.target_user_id else None,
        },
    )
    await db_session.commit()
    return _override_to_response(override)


@admin_router.delete("/overrides/{override_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_quota_override(
    override_id: UUID,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_OWNER_ROLES))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> None:
    """Remove a quota override.

    Auth: owner only. Audited.
    """
    organization_id = _org_id(principal)
    user_id = _user_id(principal)
    request_id = _request_id(request)

    override = await _repo.get_override(
        db_session, override_id=override_id, organization_id=organization_id
    )
    if override is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Override not found",
        )

    await _repo.delete_override(db_session, override)
    await db_session.commit()

    await _audit_service.record(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        action="quota_override.deleted",
        resource_type="org_quota_override",
        resource_id=override_id,
        request_id=request_id,
        metadata={},
    )
    await db_session.commit()


# ---------------------------------------------------------------------------
# Admin: Change log
# ---------------------------------------------------------------------------


@admin_router.get("/change-log", response_model=QuotaChangeLogResponse)
async def list_quota_change_log(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> QuotaChangeLogResponse:
    """Return the org's quota policy change history.

    Auth: owner or admin.
    """
    organization_id = _org_id(principal)
    entries = await _repo.list_change_log(
        db_session, organization_id=organization_id, limit=limit, offset=offset
    )
    total = await _repo.count_change_log(db_session, organization_id=organization_id)
    return QuotaChangeLogResponse(
        items=[_change_log_entry_to_response(e) for e in entries],
        total=total,
    )


# ---------------------------------------------------------------------------
# User: my usage
# ---------------------------------------------------------------------------


@user_router.get("/my-usage", response_model=OrgQuotaDashboardResponse)
async def get_my_quota_usage(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ALL_ROLES))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> OrgQuotaDashboardResponse:
    """Return the current user's org quota status.

    Auth: any authenticated org member. Shows org-level usage — no per-user breakdown.
    Used by the UI to display warnings when approaching or over limits.
    """
    organization_id = _org_id(principal)
    dashboard = await get_quota_dashboard(db_session, organization_id=organization_id)
    await db_session.commit()
    return dashboard
