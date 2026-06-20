from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime, timedelta
from math import floor
from time import time
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_principal
from app.auth.errors import AuthenticationError
from app.auth.models import AuthenticatedPrincipal
from app.auth.passwords import (
    PasswordHashConfig,
    build_password_hasher,
    hash_password,
    verify_password,
)
from app.auth.permission_service import PermissionService
from app.auth.repository import AuthRepository
from app.auth.session_repository import AuthSessionRepository
from app.auth.token_codec import (
    create_app_access_token,
    create_app_refresh_token,
    decode_app_access_token,
    decode_app_refresh_token,
)
from app.clients import redis_client as redis_module
from app.core.config import AuthProvider, RateLimitRedisFailureMode, settings
from app.db.session import get_db_session
from app.domains.admin.services.audit_service import AuditLogService
from app.domains.auth.schemas.auth import (
    AuthActiveSessionListResponse,
    AuthActiveSessionResponse,
    AuthCurrentSessionResponse,
    AuthEffectivePermissionsResponse,
    AuthLoginRequest,
    AuthLogoutRequest,
    AuthLogoutResponse,
    AuthRefreshRequest,
    AuthRefreshResponse,
    AuthSessionResponse,
)
from app.domains.sso.schemas.sso import SSODiscoverRequest, SSODiscoverResponse
from app.domains.sso.services.sso_service import SSOService
from app.models.enums import OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User

router = APIRouter(prefix="/auth", tags=["auth"])

_REFRESH_COOKIE_NAME = "rudix_refresh_token"
_repository = AuthRepository()
_session_repository = AuthSessionRepository()
_permission_service = PermissionService()
_audit_log_service = AuditLogService()
_sso_service = SSOService()

_password_hasher = build_password_hasher(
    PasswordHashConfig(
        memory_cost=settings.app_auth_password_hash_memory_cost_kib,
        time_cost=settings.app_auth_password_hash_time_cost,
        parallelism=settings.app_auth_password_hash_parallelism,
        hash_length=settings.app_auth_password_hash_length,
        salt_length=settings.app_auth_password_salt_length,
    )
)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _trim_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _request_id_from_request(request: Request | None) -> str | None:
    if request is None:
        return None
    return _trim_to_none(request.headers.get("X-Request-ID"))


def _ip_address_from_request(request: Request | None) -> str | None:
    if request is None:
        return None
    forwarded_for = _trim_to_none(request.headers.get("X-Forwarded-For"))
    if forwarded_for:
        first = forwarded_for.split(",", maxsplit=1)[0].strip()
        if first:
            return first
    if request.client and request.client.host:
        return _trim_to_none(request.client.host)
    return None


def _organization_uuid_from_claim(claims: dict[str, object]) -> UUID | None:
    org_claim = claims.get("org_id")
    if not isinstance(org_claim, str):
        return None
    try:
        return UUID(org_claim)
    except ValueError:
        return None


def _session_id_from_claims(claims: dict[str, object]) -> str | None:
    jti = claims.get("jti")
    return jti if isinstance(jti, str) and jti.strip() else None


async def _enforce_auth_rate_limit(
    *,
    action: str,
    key_parts: list[str],
    limit: int,
    window_seconds: int = 60,
) -> None:
    if not settings.is_rate_limit_active:
        return

    redis = redis_module.redis_client
    if redis is None:
        if settings.rate_limit_redis_failure_mode == RateLimitRedisFailureMode.closed:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"code": "rate_limiter_unavailable", "message": "Rate limiter unavailable"},
            )
        return

    bucket = floor(time() / max(1, window_seconds))
    key = f"rate_limit:v1:auth:{action}:{':'.join(key_parts)}:{bucket}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, window_seconds)
    ttl = await redis.ttl(key)
    if ttl <= 0:
        await redis.expire(key, window_seconds)
        ttl = window_seconds

    if count > limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "rate_limit_exceeded",
                "message": f"Rate limit exceeded for auth.{action}",
                "retry_after_seconds": max(1, int(ttl)),
            },
            headers={"Retry-After": str(max(1, int(ttl)))},
        )


async def _record_auth_audit(
    db_session: AsyncSession,
    *,
    organization_id: UUID | None,
    user_id: UUID | None,
    action: str,
    request: Request | None,
    metadata: dict[str, object],
) -> bool:
    if organization_id is None:
        return False
    enriched_metadata = dict(metadata)
    request_id = _request_id_from_request(request)
    ip_address = _ip_address_from_request(request)
    if ip_address and "ip_address" not in enriched_metadata:
        enriched_metadata["ip_address"] = ip_address
    return await _audit_log_service.record(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        action=action,
        resource_type="auth_session",
        resource_id=user_id,
        request_id=request_id,
        metadata=enriched_metadata,
    )


def _display_name_from_email(email: str) -> str:
    local_part = email.split("@")[0].strip()
    if not local_part:
        return "Rudix User"
    chunks = [chunk for chunk in local_part.replace("_", "-").split("-") if chunk]
    if not chunks:
        return "Rudix User"
    return " ".join(chunk[:1].upper() + chunk[1:] for chunk in chunks)


def _workspace_slug_from_email(email: str) -> str:
    local_part = email.split("@")[0].strip().lower()
    slug_base = "".join(ch if ch.isalnum() else "-" for ch in local_part)
    slug_base = "-".join(part for part in slug_base.split("-") if part)
    if not slug_base:
        slug_base = "workspace"
    return f"{slug_base}-{uuid4().hex[:8]}"


async def _resolve_user_from_subject(
    db_session: AsyncSession,
    *,
    subject: str,
) -> User | None:
    try:
        return await _repository.get_user_by_id(db_session, user_id=UUID(subject))
    except ValueError:
        return await _repository.get_user_by_external_auth_id(
            db_session,
            external_auth_id=subject,
        )


def _select_active_membership(
    user: User,
    *,
    organization_id: str | None,
) -> OrganizationMember:
    if not user.memberships:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No organization membership found for principal",
        )

    if organization_id is not None:
        for membership in user.memberships:
            if str(membership.organization_id) == organization_id:
                return membership
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cross-organization access is not allowed",
        )

    for membership in user.memberships:
        if membership.organization_id == user.organization_id:
            return membership

    return user.memberships[0]


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    response.set_cookie(
        key=_REFRESH_COOKIE_NAME,
        value=refresh_token,
        httponly=True,
        secure=bool(settings.app_auth_cookie_secure),
        samesite=settings.app_auth_cookie_same_site,  # type: ignore[arg-type]
        max_age=settings.app_auth_refresh_token_ttl_seconds,
        path=settings.app_auth_cookie_path,
        domain=settings.app_auth_cookie_domain,
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=_REFRESH_COOKIE_NAME,
        path=settings.app_auth_cookie_path,
        secure=bool(settings.app_auth_cookie_secure),
        httponly=True,
        samesite=settings.app_auth_cookie_same_site,  # type: ignore[arg-type]
        domain=settings.app_auth_cookie_domain,
    )


def _hash_refresh_token(refresh_token: str) -> str:
    return hashlib.sha256(refresh_token.encode("utf-8")).hexdigest()


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _is_account_locked(user: User) -> bool:
    if user.account_locked_until is None:
        return False
    return user.account_locked_until > _now_utc()


def _increment_failed_login_attempts(user: User) -> None:
    user.failed_login_attempts += 1


def _reset_failed_login_state(user: User) -> None:
    user.failed_login_attempts = 0
    user.account_locked_at = None
    user.account_locked_until = None


def _lock_account(user: User) -> None:
    user.account_locked_at = _now_utc()
    user.account_locked_until = _now_utc() + timedelta(minutes=15)
    user.password_state = "locked"


def _build_session_response(
    *,
    user: User,
    membership: OrganizationMember,
    access_token: str,
    session_id: UUID,
) -> AuthSessionResponse:
    organization = membership.organization
    return AuthSessionResponse(
        access_token=access_token,
        expires_in=settings.app_auth_access_token_ttl_seconds,
        user_id=str(user.id),
        email=user.email,
        role=membership.role,
        organization_id=str(membership.organization_id),
        organization_name=organization.name if organization is not None else None,
        session_id=str(session_id),
    )


def _build_refresh_response(
    *,
    user: User,
    membership: OrganizationMember,
    access_token: str,
    session_id: UUID,
) -> AuthRefreshResponse:
    organization = membership.organization
    return AuthRefreshResponse(
        access_token=access_token,
        expires_in=settings.app_auth_access_token_ttl_seconds,
        user_id=str(user.id),
        email=user.email,
        role=membership.role,
        organization_id=str(membership.organization_id),
        organization_name=organization.name if organization is not None else None,
        session_id=str(session_id),
    )


def _session_claims_to_response(
    *,
    user: User,
    membership: OrganizationMember,
    session_id: UUID,
    access_token_expires_in: int,
) -> AuthCurrentSessionResponse:
    organization = membership.organization
    return AuthCurrentSessionResponse(
        session_id=str(session_id),
        user_id=str(user.id),
        email=user.email,
        role=membership.role,
        organization_id=str(membership.organization_id),
        organization_name=organization.name if organization is not None else None,
        access_token_expires_in=access_token_expires_in,
    )


def _extract_bearer_token_from_request(request: Request) -> str | None:
    authorization = _trim_to_none(request.headers.get("authorization"))
    if authorization is None:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer":
        return None
    cleaned = _trim_to_none(token)
    return cleaned


async def _auto_provision_user(
    db_session: AsyncSession,
    *,
    email: str,
    password: str | None = None,
) -> User:
    display_name = _display_name_from_email(email)
    organization = Organization(
        name=f"{display_name} Workspace",
        slug=_workspace_slug_from_email(email),
    )
    db_session.add(organization)
    await db_session.flush()

    user = User(
        organization_id=organization.id,
        external_auth_id=str(uuid4()),
        email=email,
        display_name=display_name,
        hashed_password=hash_password(password, _password_hasher) if password else None,
        password_state="active" if password else "unset",
        password_changed_at=_now_utc() if password else None,
    )
    db_session.add(user)
    await db_session.flush()

    db_session.add(
        OrganizationMember(
            organization_id=organization.id,
            user_id=user.id,
            role=OrganizationRole.owner.value,
        )
    )
    await db_session.commit()

    hydrated_user = await _repository.get_user_by_id(db_session, user_id=user.id)
    if hydrated_user is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="User provisioning failed",
        )
    return hydrated_user


@router.post("/login", response_model=AuthSessionResponse)
async def login(
    payload: AuthLoginRequest,
    request: Request,
    response: Response,
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AuthSessionResponse:
    if settings.auth_provider != AuthProvider.app:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Password login is unavailable for the selected auth provider",
        )

    email = _normalize_email(payload.email)
    await _enforce_auth_rate_limit(
        action="login",
        key_parts=[email, _ip_address_from_request(request) or "unknown"],
        limit=settings.rate_limit_auth_login_requests,
        window_seconds=settings.rate_limit_window_seconds,
    )
    user = await _repository.get_user_by_email(db_session, email=email)
    if user is None:
        if not settings.app_auth_auto_provision_users:
            await _record_auth_audit(
                db_session,
                organization_id=None,
                user_id=None,
                action="auth.login.failed",
                request=request,
                metadata={
                    "status_code": status.HTTP_401_UNAUTHORIZED,
                    "result": "failure",
                    "severity": "warning",
                    "reason": "unknown_email",
                    "email": email,
                },
            )
            await db_session.commit()
            raise _unauthorized("Invalid email or password")
        user = await _auto_provision_user(db_session, email=email, password=payload.password)

    if _is_account_locked(user):
        await _record_auth_audit(
            db_session,
            organization_id=user.organization_id,
            user_id=user.id,
            action="auth.login.failed",
            request=request,
            metadata={
                "status_code": status.HTTP_423_LOCKED,
                "result": "failure",
                "severity": "warning",
                "reason": "account_locked",
                "email": user.email,
            },
        )
        await db_session.commit()
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail="Account is temporarily locked",
        )

    if user.hashed_password is None:
        await _record_auth_audit(
            db_session,
            organization_id=user.organization_id,
            user_id=user.id,
            action="auth.login.failed",
            request=request,
            metadata={
                "status_code": status.HTTP_401_UNAUTHORIZED,
                "result": "failure",
                "severity": "warning",
                "reason": "password_not_configured",
                "email": user.email,
            },
        )
        await db_session.commit()
        raise _unauthorized("Invalid email or password")

    if not verify_password(payload.password, user.hashed_password, _password_hasher):
        _increment_failed_login_attempts(user)
        lock_reason = None
        if user.failed_login_attempts >= 5:
            _lock_account(user)
            lock_reason = "account_locked"
            await _record_auth_audit(
                db_session,
                organization_id=user.organization_id,
                user_id=user.id,
                action="auth.account.locked",
                request=request,
                metadata={
                    "status_code": status.HTTP_423_LOCKED,
                    "result": "failure",
                    "severity": "warning",
                    "reason": "too_many_failed_logins",
                    "email": user.email,
                },
            )
        await _record_auth_audit(
            db_session,
            organization_id=user.organization_id,
            user_id=user.id,
            action="auth.login.failed",
            request=request,
            metadata={
                "status_code": status.HTTP_401_UNAUTHORIZED,
                "result": "failure",
                "severity": "warning",
                "reason": lock_reason or "invalid_password",
                "email": user.email,
            },
        )
        await db_session.commit()
        raise _unauthorized("Invalid email or password")

    _reset_failed_login_state(user)
    user.password_state = "active"
    user.password_changed_at = user.password_changed_at or _now_utc()

    membership = _select_active_membership(user, organization_id=None)
    session_id = uuid4()
    refresh_token = create_app_refresh_token(
        subject=str(user.id),
        session_id=str(session_id),
        role=membership.role,
        organization_id=str(membership.organization_id),
        email=user.email,
    )
    access_token = create_app_access_token(
        subject=str(user.id),
        session_id=str(session_id),
        role=membership.role,
        organization_id=str(membership.organization_id),
        email=user.email,
    )
    _set_refresh_cookie(response, refresh_token)
    refresh_jti = str(decode_app_refresh_token(refresh_token)["jti"])
    await _session_repository.create_session(
        db_session,
        organization_id=membership.organization_id,
        user_id=user.id,
        session_id=session_id,
        refresh_token_hash=_hash_refresh_token(refresh_token),
        refresh_token_jti=refresh_jti,
        device_name=None,
        user_agent=_trim_to_none(request.headers.get("user-agent")),
        ip_address=_ip_address_from_request(request),
        expires_at=_now_utc() + timedelta(seconds=settings.app_auth_refresh_token_ttl_seconds),
    )
    await _record_auth_audit(
        db_session,
        organization_id=membership.organization_id,
        user_id=user.id,
        action="auth.login.succeeded",
        request=request,
        metadata={
            "status_code": status.HTTP_200_OK,
            "result": "success",
            "severity": "info",
            "email": user.email,
            "role": membership.role,
            "session_id": str(session_id),
        },
    )
    await db_session.commit()

    return _build_session_response(
        user=user,
        membership=membership,
        access_token=access_token,
        session_id=session_id,
    )


@router.post("/token/refresh", response_model=AuthRefreshResponse)
async def refresh_access_token(
    request: Request,
    response: Response,
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    payload: AuthRefreshRequest | None = None,
) -> AuthRefreshResponse:
    if settings.auth_provider != AuthProvider.app:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Refresh is unavailable for the selected auth provider",
        )

    raw_refresh_token = _trim_to_none(request.cookies.get(_REFRESH_COOKIE_NAME))
    if raw_refresh_token is None and payload is not None:
        raw_refresh_token = _trim_to_none(payload.refresh_token)
    if raw_refresh_token is None:
        raise _unauthorized("Missing refresh token")

    try:
        claims = decode_app_refresh_token(raw_refresh_token)
    except AuthenticationError as exc:
        raise _unauthorized(str(exc)) from exc

    audit_org_id = _organization_uuid_from_claim(claims)
    session_id = _session_id_from_claims(claims)
    await _enforce_auth_rate_limit(
        action="refresh",
        key_parts=[session_id or _hash_refresh_token(raw_refresh_token)],
        limit=settings.rate_limit_auth_refresh_requests,
        window_seconds=settings.rate_limit_window_seconds,
    )
    token_hash = _hash_refresh_token(raw_refresh_token)
    session_record = await _session_repository.get_session_by_token_hash(
        db_session, refresh_token_hash=token_hash
    )
    if session_record is None:
        await _record_auth_audit(
            db_session,
            organization_id=audit_org_id,
            user_id=None,
            action="auth.token.refresh.failed",
            request=request,
            metadata={
                "status_code": status.HTTP_401_UNAUTHORIZED,
                "result": "failure",
                "severity": "warning",
                "reason": "refresh_session_not_found",
                "session_id": session_id,
            },
        )
        await db_session.commit()
        raise _unauthorized("Refresh session is not valid")

    user = await _repository.get_user_by_id(db_session, user_id=session_record.user_id)
    if user is None:
        await _session_repository.mark_session_revoked(
            db_session,
            session_id=session_record.session_id,
            revoked_at=_now_utc(),
            reason="user_missing",
        )
        await _record_auth_audit(
            db_session,
            organization_id=audit_org_id,
            user_id=None,
            action="auth.token.refresh.failed",
            request=request,
            metadata={
                "status_code": status.HTTP_401_UNAUTHORIZED,
                "result": "failure",
                "severity": "warning",
                "reason": "unknown_principal",
                "session_id": session_id,
            },
        )
        await db_session.commit()
        raise _unauthorized("Unknown principal")

    if _is_account_locked(user):
        await _record_auth_audit(
            db_session,
            organization_id=session_record.organization_id,
            user_id=user.id,
            action="auth.token.refresh.failed",
            request=request,
            metadata={
                "status_code": status.HTTP_423_LOCKED,
                "result": "failure",
                "severity": "warning",
                "reason": "account_locked",
                "session_id": session_id,
            },
        )
        await db_session.commit()
        raise HTTPException(status_code=status.HTTP_423_LOCKED, detail="Account is locked")

    if session_record.revoked_at is not None:
        if session_record.revoked_reason == "rotated":
            await _session_repository.mark_user_sessions_revoked(
                db_session,
                user_id=user.id,
                revoked_at=_now_utc(),
                reason="refresh_token_reuse_detected",
            )
            await _record_auth_audit(
                db_session,
                organization_id=session_record.organization_id,
                user_id=user.id,
                action="auth.token.reuse_detected",
                request=request,
                metadata={
                    "status_code": status.HTTP_403_FORBIDDEN,
                    "result": "failure",
                    "severity": "warning",
                    "reason": "refresh_token_reuse_detected",
                    "session_id": str(session_record.session_id),
                },
            )
            await db_session.commit()
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Refresh token reuse detected",
            )

        await _record_auth_audit(
            db_session,
            organization_id=session_record.organization_id,
            user_id=user.id,
            action="auth.token.refresh.failed",
            request=request,
            metadata={
                "status_code": status.HTTP_401_UNAUTHORIZED,
                "result": "failure",
                "severity": "warning",
                "reason": "refresh_session_revoked",
                "session_id": session_id,
            },
        )
        await db_session.commit()
        raise _unauthorized("Refresh session is not valid")

    org_claim = claims.get("org_id")
    organization_id = _trim_to_none(org_claim if isinstance(org_claim, str) else None)
    if organization_id is None:
        organization_id = str(session_record.organization_id)

    if organization_id != str(session_record.organization_id):
        await _record_auth_audit(
            db_session,
            organization_id=session_record.organization_id,
            user_id=user.id,
            action="auth.token.refresh.failed",
            request=request,
            metadata={
                "status_code": status.HTTP_403_FORBIDDEN,
                "result": "failure",
                "severity": "warning",
                "reason": "membership_access_denied",
                "session_id": session_id,
            },
        )
        await db_session.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cross-organization access is not allowed",
        )

    membership = _select_active_membership(user, organization_id=organization_id)
    await _session_repository.update_last_used(
        db_session,
        refresh_token_hash=token_hash,
        last_used_at=_now_utc(),
    )
    await _session_repository.mark_token_revoked(
        db_session,
        refresh_token_hash=token_hash,
        revoked_at=_now_utc(),
        reason="rotated",
    )

    next_session_id = session_record.session_id
    next_refresh_token = create_app_refresh_token(
        subject=str(user.id),
        session_id=str(next_session_id),
        role=membership.role,
        organization_id=str(membership.organization_id),
        email=user.email,
    )
    next_access_token = create_app_access_token(
        subject=str(user.id),
        session_id=str(next_session_id),
        role=membership.role,
        organization_id=str(membership.organization_id),
        email=user.email,
    )
    _set_refresh_cookie(response, next_refresh_token)
    next_refresh_jti = str(decode_app_refresh_token(next_refresh_token)["jti"])
    await _session_repository.create_session(
        db_session,
        organization_id=membership.organization_id,
        user_id=user.id,
        session_id=next_session_id,
        refresh_token_hash=_hash_refresh_token(next_refresh_token),
        refresh_token_jti=next_refresh_jti,
        device_name=session_record.device_name,
        user_agent=session_record.user_agent,
        ip_address=session_record.ip_address,
        expires_at=_now_utc() + timedelta(seconds=settings.app_auth_refresh_token_ttl_seconds),
    )
    await _record_auth_audit(
        db_session,
        organization_id=membership.organization_id,
        user_id=user.id,
        action="auth.token.refresh.succeeded",
        request=request,
        metadata={
            "status_code": status.HTTP_200_OK,
            "result": "success",
            "severity": "info",
            "session_id": str(next_session_id),
            "previous_session_id": session_id,
        },
    )
    await db_session.commit()

    return _build_refresh_response(
        user=user,
        membership=membership,
        access_token=next_access_token,
        session_id=next_session_id,
    )


@router.post("/logout", response_model=AuthLogoutResponse)
async def logout(
    request: Request,
    response: Response,
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    payload: AuthLogoutRequest | None = None,
) -> AuthLogoutResponse:
    raw_refresh_token = _trim_to_none(request.cookies.get(_REFRESH_COOKIE_NAME))
    if raw_refresh_token is None and payload is not None:
        raw_refresh_token = _trim_to_none(payload.refresh_token)
    audit_org_id: UUID | None = None
    audit_user_id: UUID | None = None
    audit_session_id: str | None = None

    if raw_refresh_token is not None:
        try:
            claims = decode_app_refresh_token(raw_refresh_token)
            audit_org_id = _organization_uuid_from_claim(claims)
            audit_session_id = _session_id_from_claims(claims)
            await _enforce_auth_rate_limit(
                action="logout",
                key_parts=[audit_session_id or _hash_refresh_token(raw_refresh_token)],
                limit=settings.rate_limit_auth_logout_requests,
                window_seconds=settings.rate_limit_window_seconds,
            )
            subject = claims.get("sub")
            if isinstance(subject, str) and subject.strip():
                audit_user = await _resolve_user_from_subject(db_session, subject=subject.strip())
                if audit_user is not None:
                    audit_user_id = audit_user.id
            token_hash = _hash_refresh_token(raw_refresh_token)
            session_record = await _session_repository.get_session_by_token_hash(
                db_session, refresh_token_hash=token_hash
            )
            if session_record is not None:
                await _session_repository.mark_session_revoked(
                    db_session,
                    session_id=session_record.session_id,
                    revoked_at=_now_utc(),
                    reason="logout",
                )
        except AuthenticationError:
            # Logout remains idempotent for malformed/expired tokens.
            pass

    _clear_refresh_cookie(response)
    await _record_auth_audit(
        db_session,
        organization_id=audit_org_id,
        user_id=audit_user_id,
        action="auth.logout.completed",
        request=request,
        metadata={
            "status_code": status.HTTP_200_OK,
            "result": "success",
            "severity": "info",
            "session_id": audit_session_id,
            "token_present": raw_refresh_token is not None,
        },
    )
    await db_session.commit()
    return AuthLogoutResponse(success=True)


@router.post("/logout-all", response_model=AuthLogoutResponse)
async def logout_all_devices(
    request: Request,
    response: Response,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AuthLogoutResponse:
    user_id = UUID(principal.user_id)
    await _enforce_auth_rate_limit(
        action="logout_all",
        key_parts=[str(user_id)],
        limit=settings.rate_limit_auth_logout_requests,
        window_seconds=settings.rate_limit_window_seconds,
    )
    await _session_repository.mark_user_sessions_revoked(
        db_session,
        user_id=user_id,
        revoked_at=_now_utc(),
        reason="logout_all",
    )
    await _record_auth_audit(
        db_session,
        organization_id=UUID(principal.organization_id) if principal.organization_id else None,
        user_id=user_id,
        action="auth.logout_all.completed",
        request=request,
        metadata={
            "status_code": status.HTTP_200_OK,
            "result": "success",
            "severity": "info",
        },
    )
    _clear_refresh_cookie(response)
    await db_session.commit()
    return AuthLogoutResponse(success=True)


@router.get("/session", response_model=AuthCurrentSessionResponse)
async def current_session(
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AuthCurrentSessionResponse:
    access_token = _extract_bearer_token_from_request(request)
    if access_token is None:
        raise _unauthorized("Missing bearer token")

    claims = decode_app_access_token(access_token)
    session_id_value = _session_id_from_claims(claims)
    if session_id_value is None:
        raise _unauthorized("Token session is missing")
    exp = claims.get("exp")
    if not isinstance(exp, int):
        raise _unauthorized("Token expiration is invalid")
    access_token_expires_in = max(0, int(exp - time()))

    user = await _repository.get_user_by_id(db_session, user_id=UUID(principal.user_id))
    if user is None:
        raise _unauthorized("Unknown principal")

    membership = _select_active_membership(user, organization_id=principal.organization_id)
    return _session_claims_to_response(
        user=user,
        membership=membership,
        session_id=UUID(session_id_value),
        access_token_expires_in=access_token_expires_in,
    )


@router.get("/sessions", response_model=AuthActiveSessionListResponse)
async def list_active_sessions(
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: int = 20,
    offset: int = 0,
) -> AuthActiveSessionListResponse:
    user_id = UUID(principal.user_id)
    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    items = await _session_repository.list_active_sessions_for_user(
        db_session,
        user_id=user_id,
        limit=limit,
        offset=offset,
    )
    total = await _session_repository.count_active_sessions_for_user(
        db_session,
        user_id=user_id,
    )
    return AuthActiveSessionListResponse(
        total=total,
        items=[
            AuthActiveSessionResponse(
                session_id=str(item.session_id),
                device_name=item.device_name,
                user_agent=item.user_agent,
                ip_address=item.ip_address,
                created_at=item.created_at,
                last_used_at=item.last_used_at,
                expires_at=item.expires_at,
                revoked_at=item.revoked_at,
                revoked_reason=item.revoked_reason,
            )
            for item in items
        ],
    )


@router.get("/effective-permissions", response_model=AuthEffectivePermissionsResponse)
async def get_effective_permissions(
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AuthEffectivePermissionsResponse:
    """Return the caller's resolved permission set, accounting for custom roles."""
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

    if principal.api_key_permissions is not None:
        permissions = sorted(principal.api_key_permissions)
        return AuthEffectivePermissionsResponse(
            permissions=permissions,
            role="",
            custom_role_id=None,
        )

    user_perms = await _permission_service.get_user_permissions(
        db_session,
        roles=list(principal.roles or []),
        custom_role_id=custom_role_id,
    )
    role = principal.roles[0] if principal.roles else ""
    return AuthEffectivePermissionsResponse(
        permissions=sorted(user_perms),
        role=role,
        custom_role_id=str(custom_role_id) if custom_role_id else None,
    )


# ──────────────────────────────────────────────────────────────────────────────
# SSO / SAML endpoints
# ──────────────────────────────────────────────────────────────────────────────


def _domain_from_email(email: str) -> str | None:
    parts = email.strip().lower().split("@", maxsplit=1)
    if len(parts) == 2 and parts[1]:
        return parts[1]
    return None


@router.post("/sso/discover", response_model=SSODiscoverResponse)
async def sso_discover(
    payload: SSODiscoverRequest,
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> SSODiscoverResponse:
    """Return SSO redirect URL for a given email address, or indicate no SSO is configured."""
    domain = _domain_from_email(payload.email)
    if domain is None:
        return SSODiscoverResponse(sso_enabled=False, sso_type=None, redirect_url=None, domain=None)

    config = await _sso_service.get_config_by_domain(db_session, domain=domain)
    if config is None or not config.enabled:
        return SSODiscoverResponse(
            sso_enabled=False, sso_type=None, redirect_url=None, domain=domain
        )

    org_id_str = str(config.organization_id)
    initiate_url = (
        f"{str(settings.api_base_url).rstrip('/')}"
        f"{settings.api_prefix}/auth/sso/{org_id_str}/initiate"
    )
    return SSODiscoverResponse(
        sso_enabled=True,
        sso_type=config.sso_type,
        redirect_url=initiate_url,
        domain=domain,
    )


@router.get("/sso/{organization_id}/initiate")
async def sso_initiate(
    organization_id: str,
    request: Request,
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    next: str = "/dashboard",
) -> RedirectResponse:
    """Redirect user to the IdP for authentication."""
    config = await _sso_service.get_config_by_org_id_str(
        db_session, organization_id=organization_id
    )
    if config is None or not config.enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="SSO is not configured or enabled for this organization.",
        )

    relay_state = base64.urlsafe_b64encode(f"org={organization_id}&next={next}".encode()).decode(
        "utf-8"
    )

    redirect_url = _sso_service.build_authn_redirect_url(config, relay_state=relay_state)
    if redirect_url is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SSO configuration is incomplete — IdP SSO URL is missing.",
        )

    return RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)


@router.post("/sso/{organization_id}/callback", response_model=None)
async def sso_callback(
    organization_id: str,
    request: Request,
    response: Response,
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    SAMLResponse: Annotated[str | None, Form()] = None,
    RelayState: Annotated[str | None, Form()] = None,
) -> AuthSessionResponse | RedirectResponse:
    """
    Accept a SAML Response POST from the IdP, validate, provision user, and issue tokens.
    RelayState carries the post-login redirect path encoded as base64.
    """
    config = await _sso_service.get_config_by_org_id_str(
        db_session, organization_id=organization_id
    )
    if config is None or not config.enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="SSO is not configured or enabled for this organization.",
        )

    if not SAMLResponse:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="SAMLResponse form field is required.",
        )

    try:
        parsed = _sso_service.parse_saml_callback(
            saml_response_b64=SAMLResponse,
            config=config,
        )
    except ValueError as exc:
        await _record_auth_audit(
            db_session,
            organization_id=config.organization_id,
            user_id=None,
            action="auth.sso.callback.failed",
            request=request,
            metadata={
                "status_code": status.HTTP_400_BAD_REQUEST,
                "result": "failure",
                "severity": "warning",
                "reason": "saml_parse_error",
                "detail": str(exc),
            },
        )
        await db_session.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid SAML response: {exc}",
        ) from exc

    email = parsed["email"]
    display_name: str | None = parsed.get("display_name")
    sso_org_id: UUID = config.organization_id

    user = await _repository.get_user_by_email(db_session, email=email)
    if user is None:
        if not settings.app_auth_auto_provision_users:
            await _record_auth_audit(
                db_session,
                organization_id=sso_org_id,
                user_id=None,
                action="auth.sso.callback.failed",
                request=request,
                metadata={
                    "status_code": status.HTTP_403_FORBIDDEN,
                    "result": "failure",
                    "severity": "warning",
                    "reason": "user_not_found",
                    "email": email,
                },
            )
            await db_session.commit()
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User not found and auto-provisioning is disabled.",
            )
        provisioned_display = display_name or _display_name_from_email(email)
        user = User(
            organization_id=sso_org_id,
            external_auth_id=str(uuid4()),
            email=email,
            display_name=provisioned_display,
        )
        db_session.add(user)
        await db_session.flush()
        db_session.add(
            OrganizationMember(
                organization_id=sso_org_id,
                user_id=user.id,
                role=OrganizationRole.member.value,
            )
        )
        await db_session.flush()
        user = await _repository.get_user_by_id(db_session, user_id=user.id)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="User provisioning failed.",
            )

    membership = _select_active_membership(user, organization_id=str(sso_org_id))
    session_id = uuid4()
    refresh_token = create_app_refresh_token(
        subject=str(user.id),
        session_id=str(session_id),
        role=membership.role,
        organization_id=str(membership.organization_id),
        email=user.email,
    )
    access_token = create_app_access_token(
        subject=str(user.id),
        session_id=str(session_id),
        role=membership.role,
        organization_id=str(membership.organization_id),
        email=user.email,
    )
    _set_refresh_cookie(response, refresh_token)
    refresh_jti = str(decode_app_refresh_token(refresh_token)["jti"])
    await _session_repository.create_session(
        db_session,
        organization_id=membership.organization_id,
        user_id=user.id,
        session_id=session_id,
        refresh_token_hash=_hash_refresh_token(refresh_token),
        refresh_token_jti=refresh_jti,
        device_name=None,
        user_agent=_trim_to_none(request.headers.get("user-agent")),
        ip_address=_ip_address_from_request(request),
        expires_at=_now_utc() + timedelta(seconds=settings.app_auth_refresh_token_ttl_seconds),
    )
    await _record_auth_audit(
        db_session,
        organization_id=membership.organization_id,
        user_id=user.id,
        action="auth.sso.login.succeeded",
        request=request,
        metadata={
            "status_code": status.HTTP_200_OK,
            "result": "success",
            "severity": "info",
            "email": user.email,
            "role": membership.role,
            "session_id": str(session_id),
            "sso_type": config.sso_type,
            "idp_entity_id": config.idp_entity_id,
        },
    )
    await db_session.commit()

    session_response = _build_session_response(
        user=user,
        membership=membership,
        access_token=access_token,
        session_id=session_id,
    )

    # Decode RelayState to extract the post-login navigation target.
    next_path = "/dashboard"
    if RelayState:
        try:
            relay_decoded = base64.urlsafe_b64decode(RelayState.encode("utf-8")).decode("utf-8")
            for part in relay_decoded.split("&"):
                if part.startswith("next="):
                    next_path = part[5:] or "/dashboard"
        except Exception:
            pass

    # When the browser sent a form POST (SAML flow), redirect to the frontend
    # callback page with the session as URL params.  API clients get JSON.
    accept = request.headers.get("accept", "")
    content_type = request.headers.get("content-type", "")
    is_browser_post = "application/x-www-form-urlencoded" in content_type and "json" not in accept

    if is_browser_post:
        import urllib.parse

        frontend_base = str(settings.frontend_base_url).rstrip("/")
        params: dict[str, str] = {
            "access_token": access_token,
            "user_id": session_response.user_id,
            "email": session_response.email,
            "role": session_response.role,
            "organization_id": session_response.organization_id or "",
            "session_id": session_response.session_id,
            "next": next_path,
        }
        if session_response.organization_name:
            params["organization_name"] = session_response.organization_name
        qs = urllib.parse.urlencode(params)
        redirect_target = f"{frontend_base}/sso/callback?{qs}"
        redirect_response = RedirectResponse(
            url=redirect_target,
            status_code=status.HTTP_302_FOUND,
        )
        _set_refresh_cookie(redirect_response, refresh_token)
        return redirect_response

    return session_response


@router.get("/sso/{organization_id}/metadata")
async def sso_sp_metadata(
    organization_id: str,
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> Response:
    """Return SP SAML metadata XML for the given organization."""
    config = await _sso_service.get_config_by_org_id_str(
        db_session, organization_id=organization_id
    )
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No SSO configuration found for this organization.",
        )

    sp_entity_id = config.sp_entity_id
    sp_acs_url = config.sp_acs_url
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<md:EntityDescriptor"
        ' xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata"'
        f' entityID="{sp_entity_id}">'
        "<md:SPSSODescriptor"
        ' AuthnRequestsSigned="false"'
        ' WantAssertionsSigned="true"'
        ' protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">'
        "<md:AssertionConsumerService"
        ' Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"'
        f' Location="{sp_acs_url}"'
        ' index="1"/>'
        "</md:SPSSODescriptor>"
        "</md:EntityDescriptor>"
    )
    return Response(content=xml, media_type="application/xml")
