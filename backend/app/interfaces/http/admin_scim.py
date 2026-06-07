from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.params import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_principal, require_roles
from app.auth.models import AuthenticatedPrincipal
from app.core.config import settings
from app.db.session import get_db_session
from app.domains.admin.services.audit_service import AuditLogService
from app.domains.scim.schemas.scim import (
    DomainCheckResponse,
    DomainVerificationResponse,
    InitiateDomainVerificationRequest,
    SCIMConfigResponse,
    SCIMEnableResponse,
)
from app.domains.scim.services.domain_verification_service import DomainVerificationService
from app.domains.scim.services.scim_service import SCIMService
from app.models.enums import OrganizationRole

router = APIRouter(prefix="/admin/scim", tags=["admin-scim"])

_scim_service = SCIMService()
_domain_service = DomainVerificationService()
_audit_service = AuditLogService()

_require_admin = require_roles(OrganizationRole.owner, OrganizationRole.admin)
_require_owner = require_roles(OrganizationRole.owner)

_TXT_RECORD_PREFIX = "rudix-domain-verify="


def _scim_base_url(organization_id: str) -> str:
    base = str(settings.api_base_url).rstrip("/")
    prefix = settings.api_prefix.rstrip("/")
    return f"{base}{prefix}/scim/v2"


def _config_to_response(config, organization_id: str) -> SCIMConfigResponse:
    return SCIMConfigResponse(
        id=str(config.id),
        organization_id=str(config.organization_id),
        enabled=config.enabled,
        token_hint=config.token_hint,
        scim_base_url=_scim_base_url(organization_id),
        last_sync_at=config.last_sync_at,
        last_sync_error=config.last_sync_error,
        provisioned_count=config.provisioned_count,
        deprovisioned_count=config.deprovisioned_count,
        created_at=config.created_at,
        updated_at=config.updated_at,
    )


def _verification_to_response(v) -> DomainVerificationResponse:
    return DomainVerificationResponse(
        id=str(v.id),
        organization_id=str(v.organization_id),
        domain=v.domain,
        status=v.status,
        verification_token=v.verification_token,
        txt_record_name=f"_rudix-challenge.{v.domain}",
        txt_record_value=f"{_TXT_RECORD_PREFIX}{v.verification_token}",
        verified_at=v.verified_at,
        last_checked_at=v.last_checked_at,
        failure_reason=v.failure_reason,
        created_at=v.created_at,
        updated_at=v.updated_at,
    )


def _request_id(request: Request) -> str | None:
    value = request.headers.get("X-Request-ID", "").strip()
    return value or None


# ── SCIM config endpoints ─────────────────────────────────────────────────────


@router.get("", response_model=SCIMConfigResponse | None)
async def get_scim_config(
    principal: Annotated[AuthenticatedPrincipal, Depends(_require_admin)],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> SCIMConfigResponse | None:
    config = await _scim_service.get_config(db_session, organization_id=principal.organization_id)
    if config is None:
        return None
    return _config_to_response(config, str(principal.organization_id))


@router.post("/enable", response_model=SCIMEnableResponse, status_code=status.HTTP_201_CREATED)
async def enable_scim(
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(_require_owner)],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> SCIMEnableResponse:
    config, raw_token = await _scim_service.enable(
        db_session,
        organization_id=principal.organization_id,
        actor_id=principal.user_id,
    )
    await _audit_service.record(
        db_session,
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        action="admin.scim.enabled",
        resource_type="org_scim_config",
        resource_id=config.id,
        request_id=_request_id(request),
        metadata={"severity": "warning"},
    )
    await db_session.commit()
    return SCIMEnableResponse(
        config=_config_to_response(config, str(principal.organization_id)),
        bearer_token=raw_token,
    )


@router.post("/rotate-token", response_model=SCIMEnableResponse)
async def rotate_scim_token(
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(_require_owner)],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> SCIMEnableResponse:
    try:
        config, raw_token = await _scim_service.rotate_token(
            db_session,
            organization_id=principal.organization_id,
            actor_id=principal.user_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    await _audit_service.record(
        db_session,
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        action="admin.scim.token_rotated",
        resource_type="org_scim_config",
        resource_id=config.id,
        request_id=_request_id(request),
        metadata={"severity": "warning"},
    )
    await db_session.commit()
    return SCIMEnableResponse(
        config=_config_to_response(config, str(principal.organization_id)),
        bearer_token=raw_token,
    )


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def disable_scim(
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(_require_owner)],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> None:
    removed = await _scim_service.disable(db_session, organization_id=principal.organization_id)
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No SCIM configuration found for this organization.",
        )
    await _audit_service.record(
        db_session,
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        action="admin.scim.disabled",
        resource_type="org_scim_config",
        resource_id=None,
        request_id=_request_id(request),
        metadata={"severity": "warning"},
    )
    await db_session.commit()


# ── Domain verification endpoints ─────────────────────────────────────────────


@router.get("/domains", response_model=list[DomainVerificationResponse])
async def list_domain_verifications(
    principal: Annotated[AuthenticatedPrincipal, Depends(_require_admin)],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[DomainVerificationResponse]:
    records = await _domain_service.list_verifications(
        db_session, organization_id=principal.organization_id
    )
    return [_verification_to_response(r) for r in records]


@router.post(
    "/domains",
    response_model=DomainVerificationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def initiate_domain_verification(
    payload: InitiateDomainVerificationRequest,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(_require_owner)],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> DomainVerificationResponse:
    record = await _domain_service.initiate(
        db_session,
        organization_id=principal.organization_id,
        domain=payload.domain,
        actor_id=principal.user_id,
    )
    await _audit_service.record(
        db_session,
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        action="admin.scim.domain_verification.initiated",
        resource_type="org_domain_verification",
        resource_id=record.id,
        request_id=_request_id(request),
        metadata={"domain": record.domain, "severity": "info"},
    )
    await db_session.commit()
    return _verification_to_response(record)


@router.post("/domains/{verification_id}/check", response_model=DomainCheckResponse)
async def check_domain_verification(
    verification_id: str,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(_require_owner)],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> DomainCheckResponse:
    try:
        vid = UUID(verification_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Domain verification not found.",
        ) from exc

    try:
        record = await _domain_service.check(
            db_session,
            verification_id=vid,
            organization_id=principal.organization_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    await _audit_service.record(
        db_session,
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        action="admin.scim.domain_verification.checked",
        resource_type="org_domain_verification",
        resource_id=record.id,
        request_id=_request_id(request),
        metadata={
            "domain": record.domain,
            "status": record.status,
            "severity": "info" if record.status == "verified" else "warning",
        },
    )
    await db_session.commit()
    return DomainCheckResponse(
        id=str(record.id),
        domain=record.domain,
        status=record.status,
        verified_at=record.verified_at,
        last_checked_at=record.last_checked_at,
        failure_reason=record.failure_reason,
    )


@router.delete("/domains/{verification_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_domain_verification(
    verification_id: str,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(_require_owner)],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> None:
    try:
        vid = UUID(verification_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Domain verification not found.",
        ) from exc

    removed = await _domain_service.delete(
        db_session,
        verification_id=vid,
        organization_id=principal.organization_id,
    )
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Domain verification not found.",
        )
    await _audit_service.record(
        db_session,
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        action="admin.scim.domain_verification.deleted",
        resource_type="org_domain_verification",
        resource_id=None,
        request_id=_request_id(request),
        metadata={"severity": "info"},
    )
    await db_session.commit()
