from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.errors import AuthenticationError, AuthorizationError
from app.auth.factory import get_auth_provider
from app.auth.models import AuthenticatedPrincipal
from app.db.session import get_db_session
from app.domains.documents.repositories.documents import DocumentRepository
from app.models.document import Document

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


async def get_current_principal(
    request: Request,
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AuthenticatedPrincipal:
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
