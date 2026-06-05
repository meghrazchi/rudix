from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.db.session import get_db_session
from app.domains.connectors.services.oauth_http_client import HttpOAuthTokenClient
from app.domains.connectors.services.oauth_lifecycle import (
    ConnectorOAuthLifecycleService,
    ConnectorSyncBlockedError,
    OAuthLifecycleError,
    OAuthRefreshError,
    OAuthStateValidationError,
)
from app.models.connector import ConnectorConnection
from app.models.enums import OrganizationRole

router = APIRouter(prefix="/connectors", tags=["connectors"])

_ADMIN_ROLES = (OrganizationRole.owner.value, OrganizationRole.admin.value)


class OAuthConnectRequest(BaseModel):
    provider_key: str = Field(min_length=1, max_length=64)
    redirect_uri: str = Field(min_length=1, max_length=2048)
    requested_scopes: list[str] | None = None
    collection_id: UUID | None = None
    connection_id: UUID | None = None
    display_name: str | None = Field(default=None, max_length=255)
    external_account_id: str | None = Field(default=None, max_length=512)
    client_id: str | None = Field(default=None, max_length=255)


class OAuthConnectResponse(BaseModel):
    state: str
    authorization_url: str
    expires_at: str
    scopes: list[str]


class OAuthCallbackRequest(BaseModel):
    state: str = Field(min_length=1, max_length=512)
    code: str | None = Field(default=None, max_length=4096)
    error: str | None = Field(default=None, max_length=512)


class ConnectorConnectionResponse(BaseModel):
    id: str
    provider_key: str
    display_name: str
    external_account_id: str | None
    status: str
    auth_config: dict[str, Any]


class ConnectorDiagnosticsResponse(BaseModel):
    connection_id: str
    provider_key: str
    status: str
    error_message: str | None
    auth_type: str | None
    credential_status: str | None
    credential_version: int | None
    credential_fingerprint: str | None
    scopes: list[str]
    expires_at: str | None
    metadata: dict[str, Any]


class ConnectorRefreshResponse(BaseModel):
    credential_status: str
    scopes: list[str]
    expires_at: str | None


class ConnectorDisconnectResponse(BaseModel):
    connection_id: str
    status: str
    disabled_sync_jobs: int
    remote_revoked_token_count: int


def _service() -> ConnectorOAuthLifecycleService:
    return ConnectorOAuthLifecycleService(token_client=HttpOAuthTokenClient())


def _org_id(principal: AuthenticatedPrincipal) -> UUID:
    if principal.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No active organization context for principal",
        )
    try:
        return UUID(principal.organization_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Principal organization context is invalid",
        ) from exc


def _user_id(principal: AuthenticatedPrincipal) -> UUID:
    try:
        return UUID(principal.user_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Principal user context is invalid",
        ) from exc


def _connection_response(connection: ConnectorConnection) -> ConnectorConnectionResponse:
    auth_config = dict(connection.auth_config_json or {})
    return ConnectorConnectionResponse(
        id=str(connection.id),
        provider_key=str(auth_config.get("provider_key") or connection.provider.key),
        display_name=connection.display_name,
        external_account_id=connection.external_account_id,
        status=connection.status,
        auth_config=auth_config,
    )


@router.post("/oauth/connect", response_model=OAuthConnectResponse)
async def begin_oauth_connect(
    payload: OAuthConnectRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> OAuthConnectResponse:
    organization_id = _org_id(principal)
    result = await _service().begin_connect(
        db_session,
        organization_id=organization_id,
        provider_key=payload.provider_key,
        redirect_uri=payload.redirect_uri,
        user_id=_user_id(principal),
        requested_scopes=payload.requested_scopes,
        collection_id=payload.collection_id,
        connection_id=payload.connection_id,
        display_name=payload.display_name,
        external_account_id=payload.external_account_id,
        client_id=payload.client_id,
    )
    await db_session.commit()
    return OAuthConnectResponse(
        state=result.state,
        authorization_url=result.authorization_url,
        expires_at=result.expires_at.isoformat(),
        scopes=result.scopes,
    )


@router.post("/oauth/callback", response_model=ConnectorConnectionResponse)
async def complete_oauth_callback(
    payload: OAuthCallbackRequest,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ConnectorConnectionResponse:
    del request
    try:
        connection = await _service().complete_callback(
            db_session,
            organization_id=_org_id(principal),
            state=payload.state,
            code=payload.code,
            error=payload.error,
            user_id=_user_id(principal),
        )
    except OAuthStateValidationError as exc:
        await db_session.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except OAuthLifecycleError as exc:
        await db_session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    await db_session.commit()
    return _connection_response(connection)


@router.post("/{connection_id}/refresh", response_model=ConnectorRefreshResponse)
async def refresh_connector_credential(
    connection_id: UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ConnectorRefreshResponse:
    try:
        payload = await _service().refresh_oauth_credential(
            db_session,
            organization_id=_org_id(principal),
            connection_id=connection_id,
        )
    except (OAuthRefreshError, ConnectorSyncBlockedError, OAuthLifecycleError) as exc:
        await db_session.commit()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await db_session.commit()
    return ConnectorRefreshResponse(
        credential_status="active",
        scopes=payload.scopes,
        expires_at=payload.expires_at.isoformat() if payload.expires_at else None,
    )


@router.post("/{connection_id}/disconnect", response_model=ConnectorDisconnectResponse)
async def disconnect_connector(
    connection_id: UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ConnectorDisconnectResponse:
    result = await _service().disconnect(
        db_session,
        organization_id=_org_id(principal),
        connection_id=connection_id,
        user_id=_user_id(principal),
    )
    await db_session.commit()
    return ConnectorDisconnectResponse(**result)


@router.get("/{connection_id}/diagnostics", response_model=ConnectorDiagnosticsResponse)
async def connector_diagnostics(
    connection_id: UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ConnectorDiagnosticsResponse:
    result = await _service().diagnostics(
        db_session,
        organization_id=_org_id(principal),
        connection_id=connection_id,
    )
    return ConnectorDiagnosticsResponse(**result)
