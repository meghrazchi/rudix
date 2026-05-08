from __future__ import annotations

from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.errors import AuthenticationError, AuthorizationError
from app.auth.models import AuthenticatedPrincipal
from app.auth.providers.base import BaseAuthProvider
from app.auth.repository import AuthRepository
from app.auth.token_codec import decode_app_access_token


class AppAuthProvider(BaseAuthProvider):
    """App-managed bearer token provider with backend-owned authorization checks."""

    def __init__(self) -> None:
        self._repository = AuthRepository()

    @staticmethod
    def _extract_bearer_token(request: Request) -> str:
        authorization = request.headers.get("authorization")
        if not authorization:
            raise AuthenticationError("Missing bearer token")

        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            raise AuthenticationError("Invalid authorization header")
        return token.strip()

    @staticmethod
    def _resolve_requested_org(request: Request) -> str | None:
        header_value = request.headers.get("x-organization-id")
        if header_value is None:
            return None
        cleaned = header_value.strip()
        if not cleaned:
            raise AuthorizationError("x-organization-id header is invalid")
        return cleaned

    @staticmethod
    def _select_active_organization(
        *,
        requested_org: str | None,
        default_org: str,
        organization_roles: dict[str, str],
    ) -> tuple[str, str]:
        if requested_org is not None:
            role = organization_roles.get(requested_org)
            if role is None:
                raise AuthorizationError("Cross-organization access is not allowed")
            return requested_org, role

        role = organization_roles.get(default_org)
        if role is not None:
            return default_org, role

        # Fallback for edge cases where organization_id on users table differs from membership rows.
        first_org, first_role = next(iter(organization_roles.items()))
        return first_org, first_role

    async def authenticate(self, request: Request, session: AsyncSession) -> AuthenticatedPrincipal:
        token = self._extract_bearer_token(request)
        claims = decode_app_access_token(token)

        subject = str(claims["sub"]).strip()
        try:
            user = await self._repository.get_user_by_id(session, user_id=UUID(subject))
        except ValueError:
            user = await self._repository.get_user_by_external_auth_id(
                session,
                external_auth_id=subject,
            )

        if user is None:
            raise AuthenticationError("Unknown principal")

        if not user.memberships:
            raise AuthorizationError("No organization membership found for principal")

        organization_roles = {
            str(membership.organization_id): membership.role
            for membership in user.memberships
        }
        requested_org = self._resolve_requested_org(request)
        active_org, active_role = self._select_active_organization(
            requested_org=requested_org,
            default_org=str(user.organization_id),
            organization_roles=organization_roles,
        )

        return AuthenticatedPrincipal(
            user_id=str(user.id),
            organization_id=active_org,
            email=user.email,
            roles=[active_role],
            auth_provider="app",
        )
