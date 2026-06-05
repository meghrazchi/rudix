from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.db.session import get_db_session
from app.domains.connectors.schemas.connectors import ProviderRegistration
from app.domains.connectors.services.oauth_http_client import HttpOAuthTokenClient
from app.domains.connectors.services.oauth_lifecycle import (
    ConnectorOAuthLifecycleService,
    ConnectorSyncBlockedError,
    OAuthLifecycleError,
    OAuthRefreshError,
    OAuthStateValidationError,
)
from app.domains.connectors.services.provider_registry import default_provider_registry
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


class ProviderRateLimitResponse(BaseModel):
    name: str
    max_requests: int
    window_seconds: int
    burst: int | None = None


class ProviderExportFormatResponse(BaseModel):
    format: str
    mime_type: str


class ProviderCapabilitiesResponse(BaseModel):
    auth_type: str
    capabilities: list[str]
    rate_limits: list[ProviderRateLimitResponse]
    export_formats: list[ProviderExportFormatResponse]
    max_page_size: int | None = None
    notes: str | None = None


class ProviderSummaryResponse(BaseModel):
    key: str
    display_name: str
    enabled_by_default: bool
    has_oauth: bool
    capabilities: ProviderCapabilitiesResponse


class ProvidersListResponse(BaseModel):
    items: list[ProviderSummaryResponse]
    total: int


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


def _provider_summary(reg: ProviderRegistration) -> ProviderSummaryResponse:
    caps = reg.capabilities
    return ProviderSummaryResponse(
        key=reg.key,
        display_name=reg.display_name,
        enabled_by_default=reg.enabled_by_default,
        has_oauth=reg.oauth is not None,
        capabilities=ProviderCapabilitiesResponse(
            auth_type=caps.auth_type.value,
            capabilities=sorted(c.value for c in caps.capabilities),
            rate_limits=[
                ProviderRateLimitResponse(
                    name=rl.name,
                    max_requests=rl.max_requests,
                    window_seconds=rl.window_seconds,
                    burst=rl.burst,
                )
                for rl in caps.rate_limits
            ],
            export_formats=[
                ProviderExportFormatResponse(format=ef.format, mime_type=ef.mime_type)
                for ef in caps.export_formats
            ],
            max_page_size=caps.max_page_size,
            notes=caps.notes,
        ),
    )


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


@router.get("/providers", response_model=ProvidersListResponse)
async def list_providers(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
) -> ProvidersListResponse:
    """Return all registered providers with their capabilities.

    The frontend uses this to render capability badges and conditionally show
    setup fields (e.g. export-format selector, webhook toggle).
    """
    del principal
    registrations = default_provider_registry.list()
    items = [_provider_summary(reg) for reg in registrations]
    return ProvidersListResponse(items=items, total=len(items))


@router.get("/providers/{provider_key}", response_model=ProviderSummaryResponse)
async def get_provider(
    provider_key: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
) -> ProviderSummaryResponse:
    """Return a single provider registration with full capability detail."""
    del principal
    reg = default_provider_registry.get(provider_key.strip().lower())
    if reg is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Provider not found: {provider_key!r}",
        )
    return _provider_summary(reg)


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
