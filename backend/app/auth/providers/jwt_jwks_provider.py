from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
import jwt
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.errors import AuthenticationError, AuthorizationError
from app.auth.models import AuthenticatedPrincipal
from app.auth.providers.base import BaseAuthProvider
from app.auth.repository import AuthRepository
from app.core.config import AuthProvider, settings

_SUPPORTED_ASYMMETRIC_ALGORITHMS = {"RS256", "RS384", "RS512"}


class JwtJwksAuthProvider(BaseAuthProvider):
    """JWT verifier backed by provider JWKS (Clerk/Supabase)."""

    def __init__(self) -> None:
        self._repository = AuthRepository()
        self._jwks_cache_ttl = timedelta(seconds=settings.auth_jwks_cache_ttl_seconds)
        self._jwks_cache_expires_at: datetime | None = None
        self._jwks_by_kid: dict[str, dict[str, Any]] = {}
        self._jwks_refresh_lock = asyncio.Lock()

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

        first_org, first_role = next(iter(organization_roles.items()))
        return first_org, first_role

    @staticmethod
    def _normalize_issuer(value: str) -> str:
        return value.rstrip("/")

    def _provider_config(self) -> tuple[str, str, str, str]:
        if settings.auth_provider == AuthProvider.clerk:
            if settings.clerk_jwks_url is None:
                raise AuthenticationError("Clerk JWKS URL is not configured")
            if settings.clerk_jwt_issuer is None:
                raise AuthenticationError("Clerk JWT issuer is not configured")
            if settings.clerk_jwt_audience is None:
                raise AuthenticationError("Clerk JWT audience is not configured")
            return (
                "clerk",
                str(settings.clerk_jwks_url),
                self._normalize_issuer(str(settings.clerk_jwt_issuer)),
                settings.clerk_jwt_audience,
            )

        if settings.auth_provider == AuthProvider.supabase:
            if settings.supabase_jwks_url is None:
                raise AuthenticationError("Supabase JWKS URL is not configured")
            if settings.supabase_jwt_issuer is None:
                raise AuthenticationError("Supabase JWT issuer is not configured")
            if settings.supabase_jwt_audience is None:
                raise AuthenticationError("Supabase JWT audience is not configured")
            return (
                "supabase",
                str(settings.supabase_jwks_url),
                self._normalize_issuer(str(settings.supabase_jwt_issuer)),
                settings.supabase_jwt_audience,
            )

        raise AuthenticationError("Selected auth provider is not supported")

    async def _fetch_jwks(self, jwks_url: str) -> dict[str, Any]:
        timeout = httpx.Timeout(
            connect=settings.dependency_connect_timeout_seconds,
            read=settings.dependency_read_timeout_seconds,
            write=settings.dependency_read_timeout_seconds,
            pool=settings.dependency_connect_timeout_seconds,
        )
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(jwks_url)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise AuthenticationError("JWKS response is invalid")
            return payload

    @staticmethod
    def _parse_jwks(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
        raw_keys = payload.get("keys")
        if not isinstance(raw_keys, list):
            raise AuthenticationError("JWKS response is invalid")

        keys_by_kid: dict[str, dict[str, Any]] = {}
        for key in raw_keys:
            if not isinstance(key, dict):
                continue
            kid = key.get("kid")
            if not isinstance(kid, str) or not kid.strip():
                continue
            keys_by_kid[kid.strip()] = key

        if not keys_by_kid:
            raise AuthenticationError("No signing keys are available")
        return keys_by_kid

    def _is_cache_valid(self) -> bool:
        if self._jwks_cache_expires_at is None:
            return False
        return datetime.now(UTC) < self._jwks_cache_expires_at

    async def _refresh_jwks(self, *, jwks_url: str, force: bool) -> None:
        if not force and self._is_cache_valid() and self._jwks_by_kid:
            return

        async with self._jwks_refresh_lock:
            if not force and self._is_cache_valid() and self._jwks_by_kid:
                return

            payload = await self._fetch_jwks(jwks_url)
            self._jwks_by_kid = self._parse_jwks(payload)
            self._jwks_cache_expires_at = datetime.now(UTC) + self._jwks_cache_ttl

    async def _resolve_jwk(self, *, jwks_url: str, kid: str) -> dict[str, Any]:
        await self._refresh_jwks(jwks_url=jwks_url, force=False)
        cached = self._jwks_by_kid.get(kid)
        if cached is not None:
            return cached

        # Signing key rotation can introduce a new kid before local cache TTL expires.
        await self._refresh_jwks(jwks_url=jwks_url, force=True)
        rotated = self._jwks_by_kid.get(kid)
        if rotated is None:
            raise AuthenticationError("Token signing key is unknown")
        return rotated

    async def _decode_and_validate_claims(self, token: str) -> tuple[str, dict[str, Any]]:
        provider_name, jwks_url, expected_issuer, expected_audience = self._provider_config()
        try:
            header = jwt.get_unverified_header(token)
        except jwt.InvalidTokenError as exc:
            raise AuthenticationError("Invalid token format") from exc

        kid = header.get("kid")
        if not isinstance(kid, str) or not kid.strip():
            raise AuthenticationError("Token signing key id is missing")

        algorithm = header.get("alg")
        if algorithm not in _SUPPORTED_ASYMMETRIC_ALGORITHMS:
            raise AuthenticationError("Unsupported token algorithm")

        jwk = await self._resolve_jwk(jwks_url=jwks_url, kid=kid.strip())
        try:
            signing_key = jwt.PyJWK.from_dict(jwk, algorithm=algorithm).key
        except jwt.PyJWTError as exc:
            raise AuthenticationError("Token signing key is invalid") from exc

        try:
            claims = jwt.decode(
                token,
                key=signing_key,
                algorithms=[algorithm],
                audience=expected_audience,
                issuer=expected_issuer,
                options={"require": ["sub", "exp", "iss", "aud"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise AuthenticationError("Token has expired") from exc
        except jwt.InvalidIssuerError as exc:
            raise AuthenticationError("Invalid token issuer") from exc
        except jwt.InvalidAudienceError as exc:
            raise AuthenticationError("Invalid token audience") from exc
        except jwt.InvalidSignatureError as exc:
            raise AuthenticationError("Invalid token signature") from exc
        except jwt.MissingRequiredClaimError as exc:
            raise AuthenticationError(f"Token claim '{exc.claim}' is missing") from exc
        except jwt.InvalidTokenError as exc:
            raise AuthenticationError("Invalid token") from exc

        if not isinstance(claims, dict):
            raise AuthenticationError("Invalid token payload")
        return provider_name, claims

    async def authenticate(self, request: Request, session: AsyncSession) -> AuthenticatedPrincipal:
        token = self._extract_bearer_token(request)
        provider_name, claims = await self._decode_and_validate_claims(token)

        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject.strip():
            raise AuthenticationError("Token subject is missing")

        subject_value = subject.strip()
        try:
            user = await self._repository.get_user_by_id(session, user_id=UUID(subject_value))
        except ValueError:
            user = await self._repository.get_user_by_external_auth_id(
                session,
                external_auth_id=subject_value,
            )

        if user is None:
            raise AuthenticationError("Unknown principal")

        if not user.memberships:
            raise AuthorizationError("No organization membership found for principal")

        organization_roles = {
            str(membership.organization_id): membership.role for membership in user.memberships
        }
        requested_org = self._resolve_requested_org(request)
        token_org_id = claims.get("org_id")
        if requested_org is None and isinstance(token_org_id, str) and token_org_id.strip():
            requested_org = token_org_id.strip()
        active_org, active_role = self._select_active_organization(
            requested_org=requested_org,
            default_org=str(user.organization_id),
            organization_roles=organization_roles,
        )

        token_email = claims.get("email")
        email = token_email if isinstance(token_email, str) and token_email.strip() else user.email

        return AuthenticatedPrincipal(
            user_id=str(user.id),
            organization_id=active_org,
            email=email,
            roles=[active_role],
            auth_provider=provider_name,
        )
