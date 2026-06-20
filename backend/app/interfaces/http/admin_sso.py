from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.db.session import get_db_session
from app.domains.admin.services.audit_service import AuditLogService
from app.domains.sso.schemas.sso import (
    SSOConfigResponse,
    TestConnectionRequest,
    TestConnectionResponse,
    UpsertSSOConfigRequest,
)
from app.domains.sso.services.sso_service import SSOService
from app.models.enums import OrganizationRole

router = APIRouter(prefix="/admin/sso", tags=["admin-sso"])

_sso_service = SSOService()
_audit_service = AuditLogService()

_require_admin = require_roles(OrganizationRole.owner, OrganizationRole.admin)
_require_owner = require_roles(OrganizationRole.owner)


def _principal_organization_id(principal: AuthenticatedPrincipal) -> UUID:
    if principal.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No organization membership found for principal",
        )
    try:
        return UUID(principal.organization_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization identifier is invalid",
        ) from exc


def _principal_user_id(principal: AuthenticatedPrincipal) -> UUID:
    try:
        return UUID(principal.user_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User identifier is invalid",
        ) from exc


def _config_to_response(config) -> SSOConfigResponse:
    return SSOConfigResponse(
        id=str(config.id),
        organization_id=str(config.organization_id),
        sso_type=config.sso_type,
        domain=config.domain,
        enabled=config.enabled,
        idp_metadata_url=config.idp_metadata_url,
        sp_entity_id=config.sp_entity_id,
        sp_acs_url=config.sp_acs_url,
        idp_entity_id=config.idp_entity_id,
        idp_sso_url=config.idp_sso_url,
        attribute_mapping=config.attribute_mapping or {},
        last_test_at=config.last_test_at,
        last_test_result=config.last_test_result,
        created_at=config.created_at,
        updated_at=config.updated_at,
    )


@router.get("", response_model=SSOConfigResponse | None)
async def get_sso_config(
    principal: Annotated[AuthenticatedPrincipal, Depends(_require_admin)],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> SSOConfigResponse | None:
    organization_id = _principal_organization_id(principal)
    config = await _sso_service.get_config(db_session, organization_id=organization_id)
    if config is None:
        return None
    return _config_to_response(config)


@router.put("", response_model=SSOConfigResponse)
async def upsert_sso_config(
    payload: UpsertSSOConfigRequest,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(_require_owner)],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> SSOConfigResponse:
    organization_id = _principal_organization_id(principal)
    user_id = _principal_user_id(principal)
    config = await _sso_service.upsert_config(
        db_session,
        organization_id=organization_id,
        payload=payload.model_dump(exclude={"change_note"}),
        actor_id=user_id,
    )
    await _audit_service.record(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        action="admin.sso.config.updated",
        resource_type="org_sso_config",
        resource_id=config.id,
        request_id=_request_id(request),
        metadata={
            "domain": config.domain,
            "enabled": config.enabled,
            "sso_type": config.sso_type,
            "note": payload.change_note,
            "severity": "info",
        },
    )
    await db_session.commit()
    return _config_to_response(config)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_sso_config(
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(_require_owner)],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> None:
    organization_id = _principal_organization_id(principal)
    user_id = _principal_user_id(principal)
    removed = await _sso_service.delete_config(db_session, organization_id=organization_id)
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No SSO configuration found for this organization.",
        )
    await _audit_service.record(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        action="admin.sso.config.deleted",
        resource_type="org_sso_config",
        resource_id=None,
        request_id=_request_id(request),
        metadata={"severity": "warning"},
    )
    await db_session.commit()


@router.post("/test-connection", response_model=TestConnectionResponse)
async def test_sso_connection(
    payload: TestConnectionRequest,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(_require_owner)],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> TestConnectionResponse:
    organization_id = _principal_organization_id(principal)
    user_id = _principal_user_id(principal)
    result = await _sso_service.test_connection(
        db_session,
        organization_id=organization_id,
        idp_metadata_url=payload.idp_metadata_url,
        idp_metadata_xml=payload.idp_metadata_xml,
        idp_sso_url=payload.idp_sso_url,
    )
    await _audit_service.record(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        action="admin.sso.connection.tested",
        resource_type="org_sso_config",
        resource_id=None,
        request_id=_request_id(request),
        metadata={
            "result": result["result"],
            "detail": result["detail"],
            "severity": "info" if result["success"] else "warning",
        },
    )
    await db_session.commit()
    return TestConnectionResponse(**result)


def _request_id(request: Request) -> str | None:
    value = request.headers.get("X-Request-ID", "").strip()
    return value or None
