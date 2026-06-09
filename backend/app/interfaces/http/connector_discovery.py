from __future__ import annotations

import json
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.db.session import get_db_session
from app.domains.connectors.schemas.discovery import (
    ConnectorDiscoveredSourceListResponse,
    ConnectorDiscoveredSourceResponse,
)
from app.domains.connectors.services.connector_service import (
    ConnectorPlatformDisabledError,
    ensure_connector_platform_enabled,
)
from app.domains.connectors.services.credential_vault import ConnectorCredentialVault
from app.domains.connectors.services.provider_adapter import default_sync_adapter_registry
from app.domains.connectors.services.provider_registry import (
    ProviderRegistryError,
    default_provider_registry,
)
from app.models.enums import OrganizationRole

router = APIRouter(prefix="/connectors", tags=["connector-discovery"])

_ADMIN_ROLES = (OrganizationRole.owner.value, OrganizationRole.admin.value)


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


def _require_connector_platform_enabled() -> None:
    try:
        ensure_connector_platform_enabled()
    except ConnectorPlatformDisabledError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


def _decode_cursor(cursor: str | None) -> dict[str, Any]:
    if not cursor:
        return {}
    try:
        raw = json.loads(cursor)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="cursor must be valid JSON",
        ) from exc
    if not isinstance(raw, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="cursor must decode to an object",
        )
    return raw


def _encode_source_items(
    items: list[dict[str, Any]],
    *,
    next_cursor: dict[str, Any] | None = None,
    has_more: bool = False,
) -> ConnectorDiscoveredSourceListResponse:
    return ConnectorDiscoveredSourceListResponse(
        items=[ConnectorDiscoveredSourceResponse.model_validate(item) for item in items],
        total=len(items),
        next_cursor=next_cursor,
        has_more=has_more,
    )


@router.get(
    "/connections/{connection_id}/providers/{provider_key}/discover/{scope}",
    response_model=ConnectorDiscoveredSourceListResponse,
)
async def discover_connector_sources(
    connection_id: UUID,
    provider_key: str,
    scope: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[None, Depends(_require_connector_platform_enabled)],
    cursor: str | None = Query(default=None),
    site_id: str | None = Query(default=None, min_length=1, max_length=1024),
    drive_id: str | None = Query(default=None, min_length=1, max_length=1024),
    folder_id: str | None = Query(default=None, min_length=1, max_length=1024),
    page_size: int = Query(default=50, ge=1, le=200),
) -> ConnectorDiscoveredSourceListResponse:
    organization_id = _org_id(principal)
    try:
        provider = default_provider_registry.require(provider_key)
    except ProviderRegistryError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Provider not found: {provider_key!r}",
        ) from exc

    if provider.key != "microsoft-sharepoint-onedrive":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Source discovery is only implemented for Microsoft SharePoint / OneDrive",
        )

    from app.domains.connectors.repositories.connectors import ConnectorRepository

    repository = ConnectorRepository()
    vault = ConnectorCredentialVault(repository=repository)
    connection = await repository.get_connection(
        db_session,
        organization_id=organization_id,
        connection_id=connection_id,
    )
    if connection is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Connector connection not found",
        )

    try:
        _credential, payload = await vault.load_current(
            db_session,
            organization_id=organization_id,
            connection_id=connection_id,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Connector credential is not available for discovery",
        ) from exc

    adapter: Any = default_sync_adapter_registry.require(provider.key)
    access_token = payload.access_token
    decoded_cursor = _decode_cursor(cursor)
    normalized_scope = scope.strip().lower()

    if normalized_scope == "sites":
        items, next_cursor, has_more = await adapter.discover_sites(
            access_token=access_token,
            page_size=page_size,
            cursor=decoded_cursor,
        )
        return _encode_source_items(items, next_cursor=next_cursor, has_more=has_more)

    if normalized_scope in {"drives", "libraries"}:
        if site_id:
            items = await adapter.discover_site_drives(access_token=access_token, site_id=site_id)
            return _encode_source_items(items)
        items = await adapter.discover_my_drives(access_token=access_token)
        return _encode_source_items(items)

    if normalized_scope == "folders":
        if drive_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="drive_id is required when discovering folders",
            )
        items = await adapter.discover_drive_children(
            access_token=access_token,
            drive_id=drive_id,
            folder_id=folder_id,
        )
        return _encode_source_items(items)

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="scope must be one of: sites, drives, libraries, folders",
    )
