"""Route guard that accepts either a human role or a scoped machine credential.

Interactive users are checked by organization role, exactly like ``require_roles``.
Service-account (``svc_``) and API-key (``rudix_``) principals never carry roles, so
they are checked against the permissions their scopes grant instead. Use this only on
routes that automation (for example the CI quality gate) must reach.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from typing import Annotated

from fastapi import Depends, HTTPException, status

from app.auth.dependencies import get_current_principal
from app.auth.models import AuthenticatedPrincipal


def _normalize(values: Iterable[str]) -> frozenset[str]:
    normalized: set[str] = set()
    for value in values:
        raw = getattr(value, "value", value)
        if isinstance(raw, str) and raw.strip():
            normalized.add(raw.strip())
    return frozenset(normalized)


def require_roles_or_token_permissions(
    *,
    roles: Iterable[str],
    token_permissions: Iterable[str],
) -> Callable[[AuthenticatedPrincipal], Awaitable[AuthenticatedPrincipal]]:
    """Allow a human with one of ``roles`` or a token holding all ``token_permissions``."""
    allowed_roles = _normalize(roles)
    required_permissions = _normalize(token_permissions)
    if not allowed_roles or not required_permissions:
        # An empty set would silently allow every caller of that kind.
        raise ValueError("roles and token_permissions must both be non-empty")

    async def dependency(
        principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    ) -> AuthenticatedPrincipal:
        if principal.api_key_permissions is not None:
            if required_permissions.issubset(principal.api_key_permissions):
                return principal
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Token does not have the required scopes",
            )

        principal_roles = {role.strip() for role in principal.roles if role.strip()}
        if principal_roles.intersection(allowed_roles):
            return principal
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient role for requested operation",
        )

    return dependency


def is_service_account(principal: AuthenticatedPrincipal) -> bool:
    """True when the caller is a service account, whose id is not a ``users.id``."""
    return principal.auth_provider == "service_account"
