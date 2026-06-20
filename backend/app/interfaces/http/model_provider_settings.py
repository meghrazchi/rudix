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
from app.domains.model_provider.repositories.model_provider import (
    ModelProviderRepository,
)
from app.domains.model_provider.schemas.model_provider import (
    EffectiveModelProviderPolicyResponse,
    ModelProviderChangeLogEntryResponse,
    ModelProviderChangeLogResponse,
    ModelProviderSettingsResponse,
    UpdateModelProviderSettingsRequest,
)
from app.domains.model_provider.services.model_provider_service import (
    _llm_key_configured,
    build_effective_policy,
    delete_settings_with_log,
    upsert_settings_with_log,
)
from app.models.enums import OrganizationRole
from app.models.model_provider_settings import OrgModelProviderChangeLog, OrgModelProviderSettings

router = APIRouter(prefix="/model-provider-settings", tags=["model-provider-settings"])

_repo = ModelProviderRepository()
_audit_service = AuditLogService()

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


def _settings_to_response(
    settings: OrgModelProviderSettings,
) -> ModelProviderSettingsResponse:
    return ModelProviderSettingsResponse(
        organization_id=str(settings.organization_id),
        provider=settings.provider,
        llm_model=settings.llm_model,
        embedding_model=settings.embedding_model,
        max_tokens=settings.max_tokens,
        timeout_seconds=settings.timeout_seconds,
        max_retries=settings.max_retries,
        fallback_model=settings.fallback_model,
        disabled_models=list(settings.disabled_models or []),
        llm_key_configured=_llm_key_configured(),
        version=settings.version,
        updated_by_id=str(settings.updated_by_id) if settings.updated_by_id else None,
        updated_at=settings.updated_at,
    )


def _change_log_entry_to_response(
    entry: OrgModelProviderChangeLog,
) -> ModelProviderChangeLogEntryResponse:
    return ModelProviderChangeLogEntryResponse(
        entry_id=str(entry.id),
        organization_id=str(entry.organization_id),
        version_number=entry.version_number,
        settings_snapshot=dict(entry.settings_snapshot or {}),
        change_note=entry.change_note,
        changed_by_id=str(entry.changed_by_id) if entry.changed_by_id else None,
        created_at=entry.created_at,
    )


# ---------------------------------------------------------------------------
# Settings endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=ModelProviderSettingsResponse)
async def get_model_provider_settings(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(*_ALL_ROLES)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ModelProviderSettingsResponse:
    """Return current org model provider settings.

    Auth: any authenticated org member.
    Non-secret fields only — LLM API key presence is indicated by
    ``llm_key_configured`` boolean.
    """
    organization_id = _org_id(principal)
    settings = await _repo.get_settings(db_session, organization_id=organization_id)
    if settings is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No model provider settings configured for this organization",
        )
    return _settings_to_response(settings)


@router.patch("", response_model=ModelProviderSettingsResponse)
async def update_model_provider_settings(
    request: Request,
    payload: UpdateModelProviderSettingsRequest,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(*_ADMIN_ROLES)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ModelProviderSettingsResponse:
    """Create or update org model provider settings.

    Auth: owner or admin role.
    Secrets are never accepted or stored here.
    """
    organization_id = _org_id(principal)
    user_id = _user_id(principal)
    request_id = _request_id(request)

    existing = await _repo.get_settings(db_session, organization_id=organization_id)
    merged_disabled = (
        payload.disabled_models
        if payload.disabled_models is not None
        else (list(existing.disabled_models or []) if existing else [])
    )

    settings = await upsert_settings_with_log(
        db_session,
        organization_id=organization_id,
        provider=payload.provider
        if payload.provider is not None
        else (existing.provider if existing else None),
        llm_model=payload.llm_model
        if payload.llm_model is not None
        else (existing.llm_model if existing else None),
        embedding_model=payload.embedding_model
        if payload.embedding_model is not None
        else (existing.embedding_model if existing else None),
        max_tokens=payload.max_tokens
        if payload.max_tokens is not None
        else (existing.max_tokens if existing else None),
        timeout_seconds=payload.timeout_seconds
        if payload.timeout_seconds is not None
        else (existing.timeout_seconds if existing else None),
        max_retries=payload.max_retries
        if payload.max_retries is not None
        else (existing.max_retries if existing else None),
        fallback_model=payload.fallback_model
        if payload.fallback_model is not None
        else (existing.fallback_model if existing else None),
        disabled_models=merged_disabled,
        updated_by_id=user_id,
        change_note=payload.change_note,
    )
    await db_session.commit()
    await db_session.refresh(settings)

    await _audit_service.record(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        action="model_provider_settings.updated",
        resource_type="org_model_provider_settings",
        resource_id=settings.id,
        request_id=request_id,
        metadata={
            "version": settings.version,
            "provider": settings.provider,
            "llm_model": settings.llm_model,
        },
    )
    await db_session.commit()

    log_evaluation_event(
        event="model_provider_settings.updated",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        job_id=str(settings.id),
        status_code=status.HTTP_200_OK,
    )
    return _settings_to_response(settings)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def reset_model_provider_settings(
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(*_ADMIN_ROLES)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    change_note: Annotated[str | None, Query(max_length=1000)] = None,
) -> None:
    """Delete org overrides and revert to system defaults.

    Auth: owner or admin role.
    """
    organization_id = _org_id(principal)
    user_id = _user_id(principal)
    request_id = _request_id(request)

    settings = await _repo.get_settings(db_session, organization_id=organization_id)
    if settings is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No model provider settings to reset",
        )

    await delete_settings_with_log(
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
        action="model_provider_settings.reset",
        resource_type="org_model_provider_settings",
        resource_id=None,
        request_id=request_id,
        metadata={},
    )
    await db_session.commit()


# ---------------------------------------------------------------------------
# Effective policy
# ---------------------------------------------------------------------------


@router.get("/effective-policy", response_model=EffectiveModelProviderPolicyResponse)
async def get_effective_model_provider_policy(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(*_ALL_ROLES)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> EffectiveModelProviderPolicyResponse:
    """Return the resolved effective policy (org overrides merged with system defaults).

    Auth: any authenticated org member.
    Safe to expose in admin UI — no secrets included.
    """
    organization_id = _org_id(principal)
    settings = await _repo.get_settings(db_session, organization_id=organization_id)
    policy = build_effective_policy(settings, str(organization_id))
    return EffectiveModelProviderPolicyResponse(**policy)


# ---------------------------------------------------------------------------
# Change log
# ---------------------------------------------------------------------------


@router.get("/change-log", response_model=ModelProviderChangeLogResponse)
async def list_model_provider_change_log(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(*_ADMIN_ROLES)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ModelProviderChangeLogResponse:
    """Return the org's model provider settings change history.

    Auth: owner or admin role.
    """
    organization_id = _org_id(principal)
    entries = await _repo.list_change_log(
        db_session,
        organization_id=organization_id,
        limit=limit,
        offset=offset,
    )
    total = await _repo.count_change_log(db_session, organization_id=organization_id)
    return ModelProviderChangeLogResponse(
        items=[_change_log_entry_to_response(e) for e in entries],
        total=total,
    )
