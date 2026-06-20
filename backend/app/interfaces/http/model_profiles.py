"""Admin HTTP endpoints for model profiles (F220).

Endpoints:
  GET    /model-profiles              — list all org profiles
  GET    /model-profiles/effective    — resolved effective policy for all tasks
  POST   /model-profiles/validate     — validate a proposed profile without saving
  GET    /model-profiles/{task_type}  — get profile for specific task type
  PUT    /model-profiles/{task_type}  — create or update profile for task type
  DELETE /model-profiles/{task_type}  — remove profile (reverts task to env default)

Auth: owner/admin for write operations; any org member for reads.
Secrets never returned — api keys are referenced by presence only.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.db.session import get_db_session
from app.domains.admin.audit_events import MODEL_PROFILE_DELETED, MODEL_PROFILE_UPSERTED
from app.domains.admin.services.audit_service import AuditLogService
from app.domains.ai.profile.schemas import (
    EffectiveModelPolicyResponse,
    ModelProfileListResponse,
    ModelProfileResponse,
    TaskType,
    UpsertModelProfileRequest,
    ValidateProfileRequest,
    ValidateProfileResponse,
)
from app.domains.ai.profile.service import (
    delete_profile,
    get_profile,
    list_profiles,
    profile_to_response,
    resolve_effective_policy,
    upsert_profile,
    validate_profile,
)
from app.models.enums import OrganizationRole

router = APIRouter(prefix="/model-profiles", tags=["model-profiles"])

_audit = AuditLogService()

_ALL_ROLES = (
    OrganizationRole.owner.value,
    OrganizationRole.admin.value,
    OrganizationRole.member.value,
    OrganizationRole.viewer.value,
)
_ADMIN_ROLES = (OrganizationRole.owner.value, OrganizationRole.admin.value)


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


def _parse_task_type(raw: str) -> TaskType:
    try:
        return TaskType(raw)
    except ValueError:
        valid = ", ".join(t.value for t in TaskType)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid task_type '{raw}'. Valid values: {valid}",
        ) from None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=ModelProfileListResponse)
async def list_model_profiles(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ALL_ROLES))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ModelProfileListResponse:
    """List all configured model profiles for the organization.

    Auth: any org member.
    """
    organization_id = _org_id(principal)
    profiles = await list_profiles(db_session, organization_id=organization_id)
    return ModelProfileListResponse(
        items=[profile_to_response(p) for p in profiles],
        total=len(profiles),
    )


@router.get("/effective", response_model=EffectiveModelPolicyResponse)
async def get_effective_model_policy(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ALL_ROLES))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> EffectiveModelPolicyResponse:
    """Return the resolved effective model policy for all task types.

    Merges org profiles over env defaults. Safe for admin UI — no secrets.
    Auth: any org member.
    """
    organization_id = _org_id(principal)
    return await resolve_effective_policy(db_session, organization_id=organization_id)


@router.post("/validate", response_model=ValidateProfileResponse)
async def validate_model_profile(
    payload: ValidateProfileRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
) -> ValidateProfileResponse:
    """Validate a proposed profile configuration without persisting it.

    Returns a list of policy violations. An empty issues list means the
    proposed profile is compatible with the current feature flags.
    Auth: owner or admin.
    """
    return validate_profile(payload)


@router.get("/{task_type}", response_model=ModelProfileResponse)
async def get_model_profile(
    task_type: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ALL_ROLES))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ModelProfileResponse:
    """Return the org profile for a specific task type.

    Auth: any org member.
    """
    task = _parse_task_type(task_type)
    organization_id = _org_id(principal)
    profile = await get_profile(db_session, organization_id=organization_id, task_type=task)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No profile configured for task type '{task_type}'",
        )
    return profile_to_response(profile)


@router.put("/{task_type}", response_model=ModelProfileResponse)
async def upsert_model_profile(
    task_type: str,
    request: Request,
    payload: UpsertModelProfileRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ModelProfileResponse:
    """Create or update the model profile for a specific task type.

    Runs policy validation before persisting. Returns 422 if the proposed
    profile violates any enabled policy rules.
    Auth: owner or admin.
    """
    task = _parse_task_type(task_type)
    organization_id = _org_id(principal)
    user_id = _user_id(principal)
    request_id = _request_id(request)

    # Validate before writing
    from app.domains.ai.profile.schemas import ValidateProfileRequest as VReq

    validation = validate_profile(
        VReq(
            task_type=task,
            provider_type=payload.provider_type,
            base_model=payload.base_model,
            json_mode=payload.json_mode,
            is_experimental=payload.is_experimental,
            fallback_provider_key=payload.fallback_provider_key,
        )
    )
    if not validation.valid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "Profile validation failed",
                "issues": [i.model_dump() for i in validation.issues],
            },
        )

    profile = await upsert_profile(
        db_session,
        organization_id=organization_id,
        task_type=task,
        profile_name=payload.profile_name,
        provider_type=payload.provider_type,
        base_model=payload.base_model,
        context_window=payload.context_window,
        max_tokens=payload.max_tokens,
        temperature=payload.temperature,
        json_mode=payload.json_mode,
        streaming=payload.streaming,
        fallback_provider_key=payload.fallback_provider_key,
        is_experimental=payload.is_experimental,
        cost_metadata=payload.cost_metadata,
        updated_by_id=user_id,
        change_note=payload.change_note,
    )
    await db_session.commit()
    await db_session.refresh(profile)

    await _audit.record(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        action=MODEL_PROFILE_UPSERTED,
        resource_type="org_model_profile",
        resource_id=profile.id,
        request_id=request_id,
        metadata={
            "task_type": task.value,
            "provider_type": profile.provider_type,
            "base_model": profile.base_model,
            "version": profile.version,
            "is_experimental": profile.is_experimental,
        },
    )
    await db_session.commit()

    return profile_to_response(profile)


@router.delete("/{task_type}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_model_profile(
    task_type: str,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    change_note: Annotated[str | None, Query(max_length=1000)] = None,
) -> None:
    """Remove the org profile for a task type, reverting it to the env default.

    Auth: owner or admin.
    """
    task = _parse_task_type(task_type)
    organization_id = _org_id(principal)
    user_id = _user_id(principal)
    request_id = _request_id(request)

    deleted = await delete_profile(
        db_session,
        organization_id=organization_id,
        task_type=task,
        deleted_by_id=user_id,
        change_note=change_note,
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No profile configured for task type '{task_type}'",
        )
    await db_session.commit()

    await _audit.record(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        action=MODEL_PROFILE_DELETED,
        resource_type="org_model_profile",
        resource_id=None,
        request_id=request_id,
        metadata={"task_type": task.value},
    )
    await db_session.commit()
