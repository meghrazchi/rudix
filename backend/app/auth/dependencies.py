from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.errors import AuthenticationError, AuthorizationError
from app.auth.factory import get_auth_provider
from app.auth.models import AuthenticatedPrincipal
from app.db.session import get_db_session


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_principal(
    request: Request,
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AuthenticatedPrincipal:
    provider = get_auth_provider()
    try:
        return await provider.authenticate(request, db_session)
    except AuthenticationError as exc:
        raise _unauthorized(str(exc)) from exc
    except AuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


def require_roles(*allowed_roles: str) -> Callable[[AuthenticatedPrincipal], Awaitable[AuthenticatedPrincipal]]:
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
