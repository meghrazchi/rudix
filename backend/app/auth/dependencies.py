from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.errors import AuthenticationError, AuthorizationError
from app.auth.factory import get_auth_provider
from app.auth.models import AuthenticatedPrincipal
from app.auth.permission_service import PermissionService
from app.db.session import get_db_session
from app.models.connector import ConnectorConnection, ExternalItem
from app.domains.documents.repositories.documents import DocumentRepository
from app.models.document import Document
from app.models.enums import ConnectorConnectionStatus
from app.models.organization_member import OrganizationMember

_permission_service = PermissionService()

_document_repository = DocumentRepository()


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _active_organization_id(principal: AuthenticatedPrincipal) -> UUID:
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


def _parse_document_id(document_id: str) -> UUID:
    try:
        return UUID(document_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Document not found"
        ) from exc


_API_KEY_PREFIX = "rudix_"


async def _authenticate_api_key(
    request: Request,
    raw_key: str,
    db_session: AsyncSession,
) -> AuthenticatedPrincipal:
    """Authenticate a request using a scoped API key bearer token."""
    from app.domains.api_keys.repositories.api_keys import ApiKeysRepository
    from app.domains.api_keys.services.api_keys_service import ApiKeysService

    key_hash = ApiKeysService.hash_key(raw_key)
    repo = ApiKeysRepository()
    api_key = await repo.get_active_key_by_hash(db_session, key_hash=key_hash)

    if api_key is None:
        raise AuthenticationError("Invalid or revoked API key")

    if ApiKeysService.is_expired(api_key):
        raise AuthenticationError("API key has expired")

    client_ip: str | None = None
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        client_ip = forwarded_for.split(",")[0].strip()
    elif request.client:
        client_ip = request.client.host

    await repo.record_usage(
        db_session,
        key_id=api_key.id,
        used_at=datetime.now(tz=timezone.utc),
        ip_address=client_ip,
    )

    scopes = api_key.scopes if isinstance(api_key.scopes, list) else []
    permissions = ApiKeysService.scopes_to_permissions(scopes)

    return AuthenticatedPrincipal(
        user_id=str(api_key.created_by_id) if api_key.created_by_id else str(api_key.id),
        organization_id=str(api_key.organization_id),
        roles=[],
        auth_provider="api_key",
        api_key_id=str(api_key.id),
        api_key_permissions=permissions,
    )


async def get_current_principal(
    request: Request,
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AuthenticatedPrincipal:
    authorization = request.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() == "bearer" and token.strip().startswith(_API_KEY_PREFIX):
        try:
            principal = await _authenticate_api_key(request, token.strip(), db_session)
            request.state.auth_principal = principal
            return principal
        except AuthenticationError as exc:
            raise _unauthorized(str(exc)) from exc

    provider = get_auth_provider()
    try:
        principal = await provider.authenticate(request, db_session)
        request.state.auth_principal = principal
        return principal
    except AuthenticationError as exc:
        raise _unauthorized(str(exc)) from exc
    except AuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


def require_roles(
    *allowed_roles: str,
) -> Callable[[AuthenticatedPrincipal], Awaitable[AuthenticatedPrincipal]]:
    normalized_allowed_roles = {role.strip() for role in allowed_roles if role.strip()}

    async def dependency(
        principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    ) -> AuthenticatedPrincipal:
        if not normalized_allowed_roles:
            return principal

        principal_roles = {role.strip() for role in principal.roles if role.strip()}
        if principal_roles.intersection(normalized_allowed_roles):
            return principal

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient role for requested operation",
        )

    return dependency


def require_permission(
    *required_permissions: str,
) -> Callable[[AuthenticatedPrincipal, AsyncSession], Awaitable[AuthenticatedPrincipal]]:
    """FastAPI dependency that checks the caller has ALL of the given permissions.

    Resolves custom role permissions from the database when the member has a
    custom_role_id assigned. Falls back to the built-in ROLE_PERMISSIONS map for
    standard roles.
    """
    normalized_perms = frozenset(p.strip() for p in required_permissions if p.strip())

    async def dependency(
        principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
        db_session: Annotated[AsyncSession, Depends(get_db_session)],
    ) -> AuthenticatedPrincipal:
        if not normalized_perms:
            return principal

        # API key principals carry their own pre-resolved permission set.
        if principal.api_key_permissions is not None:
            if not normalized_perms.issubset(principal.api_key_permissions):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="API key does not have the required scopes",
                )
            return principal

        custom_role_id: UUID | None = None
        if principal.organization_id:
            try:
                org_uuid = UUID(principal.organization_id)
                user_uuid = UUID(principal.user_id)
            except ValueError:
                org_uuid = None
                user_uuid = None

            if org_uuid and user_uuid:
                result = await db_session.execute(
                    select(OrganizationMember.custom_role_id).where(
                        OrganizationMember.organization_id == org_uuid,
                        OrganizationMember.user_id == user_uuid,
                    )
                )
                row = result.scalar_one_or_none()
                if row is not None:
                    custom_role_id = row

        user_perms = await _permission_service.get_user_permissions(
            db_session,
            roles=principal.roles,
            custom_role_id=custom_role_id,
        )
        if not normalized_perms.issubset(user_perms):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions for requested operation",
            )
        return principal

    return dependency


async def ensure_document_ids_access(
    *,
    document_ids: Iterable[str],
    principal: AuthenticatedPrincipal,
    db_session: AsyncSession,
) -> list[UUID]:
    parsed_ids: list[UUID] = []
    seen: set[UUID] = set()
    for document_id in document_ids:
        parsed_id = _parse_document_id(document_id)
        if parsed_id in seen:
            continue
        seen.add(parsed_id)
        parsed_ids.append(parsed_id)

    if not parsed_ids:
        return []

    organization_id = _active_organization_id(principal)
    for parsed_id in parsed_ids:
        document = await _document_repository.get_document(
            db_session,
            document_id=parsed_id,
            organization_id=organization_id,
        )
        if document is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
        if document.connector_external_item_id is not None:
            result = await db_session.execute(
                select(ExternalItem.deleted_at, ConnectorConnection.status)
                .join(
                    ConnectorConnection,
                    ConnectorConnection.id == ExternalItem.connection_id,
                )
                .where(
                    ExternalItem.id == document.connector_external_item_id,
                    ExternalItem.organization_id == organization_id,
                )
            )
            row = result.first()
            if row is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Document not found",
                )
            deleted_at, connection_status = row
            if (
                deleted_at is not None
                or connection_status != ConnectorConnectionStatus.active.value
            ):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Document not found",
                )

    return parsed_ids


async def require_document_access(
    document_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> Document:
    organization_id = _active_organization_id(principal)
    parsed_document_id = _parse_document_id(document_id)
    document = await _document_repository.get_document(
        db_session,
        document_id=parsed_document_id,
        organization_id=organization_id,
    )
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return document
