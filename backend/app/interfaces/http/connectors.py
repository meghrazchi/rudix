from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.authorization_service import AuthorizationService
from app.auth.dependencies import get_current_principal, require_permission, require_roles
from app.auth.models import AuthenticatedPrincipal
from app.auth.policy_engine import Action
from app.auth.resource_context_builder import build_connector_resource_context
from app.models.permissions import PermissionType
from app.core.config import settings
from app.db.session import get_db_session
from app.domains.admin.services.audit_service import sanitize_metadata
from app.domains.connectors.schemas.connectors import ProviderRegistration
from app.domains.connectors.services.connector_service import (
    ConnectorPlatformDisabledError,
    ConnectorPlatformService,
    ensure_connector_platform_enabled,
)
from app.domains.connectors.services.oauth_http_client import HttpOAuthTokenClient
from app.domains.connectors.services.oauth_lifecycle import (
    ConnectorOAuthLifecycleService,
    ConnectorSyncBlockedError,
    OAuthLifecycleError,
    OAuthRefreshError,
    OAuthStateValidationError,
)
from app.domains.connectors.services.permission_review_service import (
    PermissionReviewNotFoundError,
    PermissionReviewService,
)
from app.domains.connectors.services.provider_registry import (
    ProviderRegistryError,
    default_provider_registry,
)
from app.domains.connectors.services.sync_engine import ConnectorSyncEngine
from app.models.connector import ConnectorConnection, ExternalItem
from app.models.document import Document
from app.models.enums import ConnectorAuthType, OrganizationRole

router = APIRouter(prefix="/connectors", tags=["connectors"])
public_router = APIRouter(prefix="/connectors", tags=["connectors"])

_ADMIN_ROLES = (OrganizationRole.owner.value, OrganizationRole.admin.value)
_ALL_MEMBER_ROLES = tuple(role.value for role in OrganizationRole)
_authorization_service = AuthorizationService()


async def _ensure_default_sync_job(
    db_session: AsyncSession,
    *,
    organization_id: UUID,
    connection_id: UUID,
    display_name: str,
    user_id: UUID | None = None,
) -> None:
    engine = ConnectorSyncEngine()
    jobs = await engine.list_sync_jobs(
        db_session, organization_id=organization_id, connection_id=connection_id
    )
    if not jobs:
        await engine.create_sync_job(
            db_session,
            organization_id=organization_id,
            connection_id=connection_id,
            name=f"{display_name} — default sync",
            user_id=user_id,
        )


class OAuthConnectRequest(BaseModel):
    provider_key: str = Field(min_length=1, max_length=64)
    redirect_uri: str = Field(min_length=1, max_length=2048)
    requested_scopes: list[str] | None = None
    collection_id: UUID | None = None
    connection_id: UUID | None = None
    display_name: str | None = Field(default=None, max_length=255)
    external_account_id: str | None = Field(default=None, max_length=512)
    client_id: str | None = Field(default=None, max_length=255)
    config: dict[str, Any] = Field(default_factory=dict)


class CreateConnectorConnectionRequest(BaseModel):
    provider_key: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=255)
    collection_id: UUID | None = None
    external_account_id: str | None = Field(default=None, max_length=512)
    config: dict[str, Any] = Field(default_factory=dict)


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
    config_schema: dict[str, Any]


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


class ConnectorConnectionSummaryResponse(BaseModel):
    id: str
    provider_key: str
    provider: ProviderSummaryResponse
    display_name: str
    external_account_id: str | None
    collection_id: str | None
    status: str
    auth_config: dict[str, Any]
    last_sync_at: str | None
    error_message: str | None
    source_count: int
    indexed_document_count: int
    sync_job_count: int
    created_at: str
    updated_at: str


class ConnectorConnectionDetailResponse(ConnectorConnectionSummaryResponse):
    diagnostics: ConnectorDiagnosticsResponse
    source_permission_snapshots: list[SourcePermissionSnapshotResponse] = Field(
        default_factory=list
    )


class SourcePermissionSnapshotResponse(BaseModel):
    id: str
    provider_source_id: str
    name: str
    source_type: str
    is_enabled: bool
    permissions: dict[str, Any]


ConnectorConnectionDetailResponse.model_rebuild()


class ConnectorConnectionsListResponse(BaseModel):
    items: list[ConnectorConnectionSummaryResponse]
    total: int


class ConnectorRefreshResponse(BaseModel):
    credential_status: str
    scopes: list[str]
    expires_at: str | None


class ConnectorDisconnectResponse(BaseModel):
    connection_id: str
    status: str
    disabled_sync_jobs: int
    remote_revoked_token_count: int


class ScopeWarningResponse(BaseModel):
    code: str
    message: str
    scope: str | None = None


class PermissionReviewResponse(BaseModel):
    id: str
    connection_id: str
    is_confirmed: bool
    is_broad_scope: bool
    scope_warnings: list[ScopeWarningResponse]
    permission_snapshot: dict[str, Any]
    reviewed_by_user_id: str | None
    reviewed_at: str | None
    created_at: str
    updated_at: str


def _review_service() -> PermissionReviewService:
    return PermissionReviewService()


def _service() -> ConnectorOAuthLifecycleService:
    return ConnectorOAuthLifecycleService(token_client=HttpOAuthTokenClient())


def _platform_service() -> ConnectorPlatformService:
    return ConnectorPlatformService()


def _require_connector_platform_enabled() -> None:
    try:
        ensure_connector_platform_enabled()
    except ConnectorPlatformDisabledError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


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
        config_schema=dict(reg.config_schema or {}),
    )


def _provider_summary_from_model(provider: Any) -> ProviderSummaryResponse:
    return ProviderSummaryResponse(
        key=provider.key,
        display_name=provider.display_name,
        enabled_by_default=provider.is_enabled,
        has_oauth=provider.auth_type == ConnectorAuthType.oauth2.value,
        capabilities=ProviderCapabilitiesResponse(
            auth_type=provider.auth_type,
            capabilities=sorted(str(cap) for cap in provider.capabilities_json or []),
            rate_limits=[
                ProviderRateLimitResponse(
                    name=str(rate_limit.get("name", "")),
                    max_requests=int(rate_limit.get("max_requests", 0)),
                    window_seconds=int(rate_limit.get("window_seconds", 0)),
                    burst=(
                        int(rate_limit["burst"]) if rate_limit.get("burst") is not None else None
                    ),
                )
                for rate_limit in (provider.rate_limits_json or [])
            ],
            export_formats=[
                ProviderExportFormatResponse(
                    format=str(export_format.get("format", "")),
                    mime_type=str(export_format.get("mime_type", "")),
                )
                for export_format in (provider.export_formats_json or [])
            ],
            max_page_size=None,
            notes=None,
        ),
        config_schema=dict(provider.config_schema_json or {}),
    )


def _connection_summary_response(
    connection: ConnectorConnection,
    *,
    indexed_document_count: int,
) -> ConnectorConnectionSummaryResponse:
    provider = connection.provider
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Connector provider is not loaded",
        )
    auth_config = dict(connection.auth_config_json or {})
    return ConnectorConnectionSummaryResponse(
        id=str(connection.id),
        provider_key=provider.key,
        provider=_provider_summary_from_model(provider),
        display_name=connection.display_name,
        external_account_id=connection.external_account_id,
        collection_id=str(connection.collection_id) if connection.collection_id else None,
        status=connection.status,
        auth_config=auth_config,
        last_sync_at=connection.last_sync_at.isoformat() if connection.last_sync_at else None,
        error_message=connection.error_message,
        source_count=len(connection.sources or []),
        indexed_document_count=indexed_document_count,
        sync_job_count=len(connection.sync_jobs or []),
        created_at=connection.created_at.isoformat(),
        updated_at=connection.updated_at.isoformat(),
    )


def _source_permission_snapshots(
    connection: ConnectorConnection,
) -> list[SourcePermissionSnapshotResponse]:
    snapshots: list[SourcePermissionSnapshotResponse] = []
    for source in connection.sources or []:
        snapshots.append(
            SourcePermissionSnapshotResponse(
                id=str(source.id),
                provider_source_id=source.provider_source_id,
                name=source.name,
                source_type=source.source_type,
                is_enabled=source.is_enabled,
                permissions=sanitize_metadata(source.permissions_json),
            )
        )
    return snapshots


async def _load_connections(
    db_session: AsyncSession,
    *,
    organization_id: UUID,
) -> list[ConnectorConnection]:
    result = await db_session.execute(
        select(ConnectorConnection)
        .options(
            selectinload(ConnectorConnection.provider),
            selectinload(ConnectorConnection.sources),
            selectinload(ConnectorConnection.sync_jobs),
        )
        .where(ConnectorConnection.organization_id == organization_id)
        .order_by(ConnectorConnection.created_at.desc())
    )
    return list(result.scalars().all())


async def _connection_indexed_document_count(
    db_session: AsyncSession,
    *,
    organization_id: UUID,
    connection_id: UUID,
) -> int:
    result = await db_session.execute(
        select(func.count(Document.id))
        .join(
            ExternalItem,
            ExternalItem.id == Document.connector_external_item_id,
        )
        .where(
            Document.organization_id == organization_id,
            ExternalItem.connection_id == connection_id,
            Document.ingestion_source == "connector",
            Document.status == "indexed",
        )
    )
    return int(result.scalar_one())


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


@router.get("/connections", response_model=ConnectorConnectionsListResponse)
async def list_connections(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ConnectorConnectionsListResponse:
    connections = await _load_connections(
        db_session,
        organization_id=_org_id(principal),
    )
    organization_id = _org_id(principal)
    items = []
    for connection in connections:
        indexed_document_count = await _connection_indexed_document_count(
            db_session,
            organization_id=organization_id,
            connection_id=connection.id,
        )
        items.append(
            _connection_summary_response(
                connection,
                indexed_document_count=indexed_document_count,
            )
        )
    return ConnectorConnectionsListResponse(
        items=items,
        total=len(connections),
    )


@router.get("/available", response_model=ConnectorConnectionsListResponse)
async def list_available_connections(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(PermissionType.documents_view)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ConnectorConnectionsListResponse:
    """Returns active connector connections for the chat scope picker.

    Accessible to all org members, not just admins.
    """
    organization_id = _org_id(principal)
    connections = await _load_connections(db_session, organization_id=organization_id)
    active = [c for c in connections if c.status == "active"]

    # Filter connections through the policy engine for non-admin principals.
    user_roles = list(principal.roles or [])
    if not frozenset(_ADMIN_ROLES).intersection(user_roles):
        resource_contexts = [
            build_connector_resource_context(
                connection=conn, organization_id=organization_id
            )
            for conn in active
        ]
        accessible_ids = {
            ctx.resource_id
            for ctx in await _authorization_service.filter_accessible_resources(
                principal, Action.list, resource_contexts, db_session
            )
        }
        active = [c for c in active if str(c.id) in accessible_ids]

    items = []
    for connection in active:
        indexed_document_count = await _connection_indexed_document_count(
            db_session,
            organization_id=organization_id,
            connection_id=connection.id,
        )
        items.append(
            _connection_summary_response(
                connection,
                indexed_document_count=indexed_document_count,
            )
        )
    return ConnectorConnectionsListResponse(
        items=items,
        total=len(active),
    )


@router.get("/connections/{connection_id}", response_model=ConnectorConnectionDetailResponse)
async def get_connection(
    connection_id: UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ConnectorConnectionDetailResponse:
    organization_id = _org_id(principal)
    connections = await _load_connections(db_session, organization_id=organization_id)
    connection = next((item for item in connections if item.id == connection_id), None)
    if connection is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Connector connection not found",
        )
    indexed_document_count = await _connection_indexed_document_count(
        db_session,
        organization_id=organization_id,
        connection_id=connection_id,
    )
    diagnostics = await _service().diagnostics(
        db_session,
        organization_id=organization_id,
        connection_id=connection_id,
    )
    return ConnectorConnectionDetailResponse(
        **_connection_summary_response(
            connection,
            indexed_document_count=indexed_document_count,
        ).model_dump(),
        diagnostics=ConnectorDiagnosticsResponse(**diagnostics),
        source_permission_snapshots=_source_permission_snapshots(connection),
    )


@router.post(
    "/connections",
    response_model=ConnectorConnectionSummaryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_connection(
    payload: CreateConnectorConnectionRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[None, Depends(_require_connector_platform_enabled)],
) -> ConnectorConnectionSummaryResponse:
    organization_id = _org_id(principal)
    try:
        provider = default_provider_registry.require(payload.provider_key)
    except ProviderRegistryError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Provider not found: {payload.provider_key!r}",
        ) from exc
    if provider.capabilities.auth_type is ConnectorAuthType.oauth2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OAuth providers must use the OAuth connect flow",
        )
    connection = await _platform_service().create_connection(
        db_session,
        organization_id=organization_id,
        provider_key=payload.provider_key,
        display_name=payload.display_name,
        created_by_user_id=_user_id(principal),
        external_account_id=payload.external_account_id,
        auth_config={"provider_key": payload.provider_key, **payload.config},
    )
    await _ensure_default_sync_job(
        db_session,
        organization_id=organization_id,
        connection_id=connection.id,
        display_name=payload.display_name,
        user_id=_user_id(principal),
    )
    await db_session.commit()
    await db_session.refresh(connection)
    loaded = await _load_connections(db_session, organization_id=organization_id)
    created = next((item for item in loaded if item.id == connection.id), connection)
    indexed_document_count = await _connection_indexed_document_count(
        db_session,
        organization_id=organization_id,
        connection_id=connection.id,
    )
    return _connection_summary_response(
        created,
        indexed_document_count=indexed_document_count,
    )


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
    _: Annotated[None, Depends(_require_connector_platform_enabled)],
) -> OAuthConnectResponse:
    organization_id = _org_id(principal)
    try:
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
            config=payload.config,
        )
    except OAuthLifecycleError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    await db_session.commit()
    return OAuthConnectResponse(
        state=result.state,
        authorization_url=result.authorization_url,
        expires_at=result.expires_at.isoformat(),
        scopes=result.scopes,
    )


@public_router.get("/oauth/callback")
async def complete_oauth_callback_get(
    state: str,
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[None, Depends(_require_connector_platform_enabled)],
    code: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    try:
        connection = await _service().complete_callback_public(
            db_session,
            state=state,
            code=code,
            error=error,
        )
    except OAuthStateValidationError as exc:
        await db_session.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except OAuthLifecycleError as exc:
        await db_session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    await db_session.commit()
    frontend_base = str(settings.frontend_base_url).rstrip("/")
    return RedirectResponse(
        url=f"{frontend_base}/connectors/{connection.id}",
        status_code=status.HTTP_302_FOUND,
    )


@router.post("/oauth/callback", response_model=ConnectorConnectionResponse)
async def complete_oauth_callback(
    payload: OAuthCallbackRequest,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[None, Depends(_require_connector_platform_enabled)],
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

    await _ensure_default_sync_job(
        db_session,
        organization_id=_org_id(principal),
        connection_id=connection.id,
        display_name=connection.display_name,
        user_id=_user_id(principal),
    )
    await db_session.commit()
    return _connection_response(connection)


@router.post("/{connection_id}/refresh", response_model=ConnectorRefreshResponse)
async def refresh_connector_credential(
    connection_id: UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[None, Depends(_require_connector_platform_enabled)],
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


@router.delete("/connections/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_connection(
    connection_id: UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[None, Depends(_require_connector_platform_enabled)],
) -> None:
    await _service().delete_connection(
        db_session,
        organization_id=_org_id(principal),
        connection_id=connection_id,
        user_id=_user_id(principal),
    )
    await db_session.commit()


@router.post("/{connection_id}/disconnect", response_model=ConnectorDisconnectResponse)
async def disconnect_connector(
    connection_id: UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[None, Depends(_require_connector_platform_enabled)],
) -> ConnectorDisconnectResponse:
    result = await _service().disconnect(
        db_session,
        organization_id=_org_id(principal),
        connection_id=connection_id,
        user_id=_user_id(principal),
    )
    await db_session.commit()
    return ConnectorDisconnectResponse(**result)


def _permission_review_response(review: Any) -> PermissionReviewResponse:
    from app.models.connector import ConnectorPermissionReview as _CPR

    r: _CPR = review
    return PermissionReviewResponse(
        id=str(r.id),
        connection_id=str(r.connection_id),
        is_confirmed=r.is_confirmed,
        is_broad_scope=r.is_broad_scope,
        scope_warnings=[ScopeWarningResponse(**w) for w in (r.scope_warnings_json or [])],
        permission_snapshot=sanitize_metadata(r.permission_snapshot_json or {}),
        reviewed_by_user_id=(str(r.reviewed_by_user_id) if r.reviewed_by_user_id else None),
        reviewed_at=r.reviewed_at.isoformat() if r.reviewed_at else None,
        created_at=r.created_at.isoformat(),
        updated_at=r.updated_at.isoformat(),
    )


@router.get(
    "/{connection_id}/permission-review",
    response_model=PermissionReviewResponse,
)
async def get_permission_review(
    connection_id: UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PermissionReviewResponse:
    """Return (or lazily generate) the permission review for this connection.

    On first call the service analyses the active credential scopes and source
    configuration to build a snapshot with scope warnings. Subsequent calls
    return the stored record unchanged until the admin refreshes it.
    """
    organization_id = _org_id(principal)
    try:
        review = await _review_service().get_or_create(
            db_session,
            organization_id=organization_id,
            connection_id=connection_id,
        )
    except PermissionReviewNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    await db_session.commit()
    return _permission_review_response(review)


@router.post(
    "/{connection_id}/permission-review/confirm",
    response_model=PermissionReviewResponse,
)
async def confirm_permission_review(
    connection_id: UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PermissionReviewResponse:
    """Confirm the permission review for a connection.

    This must be called before the first sync can be triggered. Generates the
    review record from live credential data if it does not yet exist.
    """
    organization_id = _org_id(principal)
    try:
        review = await _review_service().confirm(
            db_session,
            organization_id=organization_id,
            connection_id=connection_id,
            user_id=_user_id(principal),
        )
    except PermissionReviewNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    await db_session.commit()
    return _permission_review_response(review)


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
