from __future__ import annotations

from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.errors import AuthenticationError, AuthorizationError
from app.auth.models import AuthenticatedPrincipal
from app.auth.principal_snapshot import (
    PRINCIPAL_SNAPSHOT_ADAPTER,
    PrincipalSnapshot,
    build_snapshot,
    store_request_snapshot,
)
from app.auth.providers.base import BaseAuthProvider
from app.auth.repository import AuthRepository
from app.auth.session_repository import AuthSessionRepository
from app.auth.token_codec import decode_app_access_token
from app.core.cache import NAMESPACE_AUTH_PRINCIPAL, UserScope, get_or_load
from app.core.config import settings
from app.models.auth_session import AuthRefreshSession


class AppAuthProvider(BaseAuthProvider):
    """App-managed bearer token provider with backend-owned authorization checks."""

    def __init__(self) -> None:
        self._repository = AuthRepository()
        self._session_repository = AuthSessionRepository()

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

    async def load_active_session(
        self,
        session: AsyncSession,
        *,
        session_id: UUID,
    ) -> AuthRefreshSession | None:
        """Return the active session row, or raise when the session was revoked or expired.

        A session id with no stored row at all is accepted (returns ``None``), as
        it always has been; callers then skip the owner check.
        """
        session_record = await self._session_repository.get_active_session_by_id(
            session,
            session_id=session_id,
        )
        if session_record is None:
            session_history = await self._session_repository.get_session_by_id(
                session,
                session_id=session_id,
            )
            if session_history is not None:
                raise AuthenticationError("Session has been revoked")
        return session_record

    @staticmethod
    def ensure_session_owner(session_record: AuthRefreshSession | None, *, user_id: UUID) -> None:
        if session_record is not None and session_record.user_id != user_id:
            raise AuthenticationError("Session does not belong to the authenticated principal")

    async def _load_snapshot(
        self,
        session: AsyncSession,
        *,
        subject: str,
        subject_uuid: UUID | None,
        session_id: UUID,
    ) -> PrincipalSnapshot:
        """Read the session row and the user with memberships (raises when revoked)."""
        session_record = await self.load_active_session(session, session_id=session_id)
        if subject_uuid is not None:
            user = await self._repository.get_user_by_id(session, user_id=subject_uuid)
        else:
            user = await self._repository.get_user_by_external_auth_id(
                session,
                external_auth_id=subject,
            )
        if user is None:
            raise AuthenticationError("Unknown principal")
        return build_snapshot(user, session_record)

    async def _principal_snapshot(
        self,
        session: AsyncSession,
        *,
        subject: str,
        session_id: UUID,
    ) -> PrincipalSnapshot:
        try:
            subject_uuid: UUID | None = UUID(subject)
        except ValueError:
            subject_uuid = None

        async def load() -> PrincipalSnapshot:
            return await self._load_snapshot(
                session, subject=subject, subject_uuid=subject_uuid, session_id=session_id
            )

        if subject_uuid is None:
            # External subject ids have no user scope until the row is read: not cached.
            return await load()
        return await get_or_load(
            scope=UserScope(subject_uuid),
            namespace=NAMESPACE_AUTH_PRINCIPAL,
            key_id=str(session_id),
            ttl=settings.cache_ttl_auth_session_seconds,
            adapter=PRINCIPAL_SNAPSHOT_ADAPTER,
            loader=load,
        )

    async def authenticate(self, request: Request, session: AsyncSession) -> AuthenticatedPrincipal:
        token = self._extract_bearer_token(request)
        claims = decode_app_access_token(token)

        session_id_value = claims.get("session_id")
        if not isinstance(session_id_value, str) or not session_id_value.strip():
            raise AuthenticationError("Token session is missing")

        try:
            session_uuid = UUID(session_id_value)
        except ValueError as exc:
            raise AuthenticationError("Token session is invalid") from exc

        subject = str(claims["sub"]).strip()
        snapshot = await self._principal_snapshot(session, subject=subject, session_id=session_uuid)
        store_request_snapshot(request, snapshot)

        if snapshot.session.present and snapshot.session.is_expired():
            # Same outcome as the uncached lookup: no active row, but the session exists.
            raise AuthenticationError("Session has been revoked")

        if not snapshot.is_active:
            raise AuthenticationError("Account has been deprovisioned")

        if snapshot.session.present and snapshot.session.owner_user_id != snapshot.user_id:
            raise AuthenticationError("Session does not belong to the authenticated principal")

        if not snapshot.memberships:
            raise AuthorizationError("No organization membership found for principal")

        organization_roles = {
            org_id: membership.role for org_id, membership in snapshot.memberships.items()
        }
        requested_org = self._resolve_requested_org(request)
        token_org_id = claims.get("org_id")
        if requested_org is None and isinstance(token_org_id, str) and token_org_id.strip():
            requested_org = token_org_id.strip()
        active_org, active_role = self._select_active_organization(
            requested_org=requested_org,
            default_org=str(snapshot.default_organization_id),
            organization_roles=organization_roles,
        )

        return AuthenticatedPrincipal(
            user_id=str(snapshot.user_id),
            organization_id=active_org,
            email=snapshot.email,
            roles=[active_role],
            auth_provider="app",
            auth_session_id=str(session_uuid),
        )
