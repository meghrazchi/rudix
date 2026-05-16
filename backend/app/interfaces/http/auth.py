from __future__ import annotations

from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.errors import AuthenticationError
from app.auth.refresh_token_store import refresh_token_store
from app.auth.repository import AuthRepository
from app.auth.token_codec import (
    create_app_access_token,
    create_app_refresh_token,
    decode_app_refresh_token,
)
from app.core.config import AuthProvider, settings
from app.db.session import get_db_session
from app.domains.auth.schemas.auth import (
    AuthLoginRequest,
    AuthLogoutRequest,
    AuthLogoutResponse,
    AuthRefreshRequest,
    AuthRefreshResponse,
    AuthSessionResponse,
)
from app.models.enums import OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User

router = APIRouter(prefix="/auth", tags=["auth"])

_REFRESH_COOKIE_NAME = "rudix_refresh_token"
_REFRESH_COOKIE_PATH = f"{settings.api_prefix}/auth"
_repository = AuthRepository()


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


def _ensure_password_login_allowed(password: str) -> None:
    configured_password = _trim_to_none(
        settings.app_auth_login_password.get_secret_value()
        if settings.app_auth_login_password
        else None,
    )

    if configured_password is not None:
        if password != configured_password:
            raise _unauthorized("Invalid email or password")
        return

    if settings.is_production:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Password login is not configured",
        )


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
        secure=settings.is_production,
        samesite="lax",
        max_age=settings.app_auth_refresh_token_ttl_seconds,
        path=_REFRESH_COOKIE_PATH,
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=_REFRESH_COOKIE_NAME,
        path=_REFRESH_COOKIE_PATH,
        secure=settings.is_production,
        httponly=True,
        samesite="lax",
    )


async def _auto_provision_user(
    db_session: AsyncSession,
    *,
    email: str,
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


def _build_session_payload(user: User, membership: OrganizationMember) -> tuple[str, str]:
    organization_id = str(membership.organization_id)
    access_token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=organization_id,
        email=user.email,
    )
    refresh_token = create_app_refresh_token(
        subject=user.external_auth_id,
        organization_id=organization_id,
        email=user.email,
    )
    return access_token, refresh_token


@router.post("/login", response_model=AuthSessionResponse)
async def login(
    payload: AuthLoginRequest,
    response: Response,
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AuthSessionResponse:
    if settings.auth_provider != AuthProvider.app:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Password login is unavailable for the selected auth provider",
        )

    _ensure_password_login_allowed(payload.password)

    email = _normalize_email(payload.email)
    user = await _repository.get_user_by_email(db_session, email=email)
    if user is None:
        if not settings.app_auth_auto_provision_users:
            raise _unauthorized("Invalid email or password")
        user = await _auto_provision_user(db_session, email=email)

    membership = _select_active_membership(user, organization_id=None)
    access_token, refresh_token = _build_session_payload(user, membership)
    _set_refresh_cookie(response, refresh_token)

    organization = membership.organization
    organization_name = organization.name if organization is not None else None

    return AuthSessionResponse(
        access_token=access_token,
        refresh_token=None,
        expires_in=settings.app_auth_access_token_ttl_seconds,
        user_id=str(user.id),
        email=user.email,
        role=membership.role,
        organization_id=str(membership.organization_id),
        organization_name=organization_name,
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

    raw_refresh_token = _trim_to_none(payload.refresh_token) if payload else None
    raw_refresh_token = raw_refresh_token or _trim_to_none(
        request.cookies.get(_REFRESH_COOKIE_NAME),
    )
    if raw_refresh_token is None:
        raise _unauthorized("Missing refresh token")

    if refresh_token_store.is_revoked(raw_refresh_token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Refresh token has been revoked",
        )

    try:
        claims = decode_app_refresh_token(raw_refresh_token)
    except AuthenticationError as exc:
        raise _unauthorized(str(exc)) from exc

    subject = str(claims["sub"]).strip()
    org_claim = claims.get("org_id")
    organization_id = _trim_to_none(org_claim if isinstance(org_claim, str) else None)
    user = await _resolve_user_from_subject(db_session, subject=subject)
    if user is None:
        raise _unauthorized("Unknown principal")

    membership = _select_active_membership(user, organization_id=organization_id)

    original_exp = claims.get("exp")
    if isinstance(original_exp, int):
        refresh_token_store.revoke(raw_refresh_token, expires_at_epoch=original_exp)

    access_token, refresh_token = _build_session_payload(user, membership)
    _set_refresh_cookie(response, refresh_token)

    return AuthRefreshResponse(
        access_token=access_token,
        refresh_token=None,
        expires_in=settings.app_auth_access_token_ttl_seconds,
    )


@router.post("/logout", response_model=AuthLogoutResponse)
async def logout(
    request: Request,
    response: Response,
    payload: AuthLogoutRequest | None = None,
) -> AuthLogoutResponse:
    raw_refresh_token = _trim_to_none(payload.refresh_token) if payload else None
    raw_refresh_token = raw_refresh_token or _trim_to_none(
        request.cookies.get(_REFRESH_COOKIE_NAME),
    )

    if raw_refresh_token is not None:
        try:
            claims = decode_app_refresh_token(raw_refresh_token)
            exp = claims.get("exp")
            if isinstance(exp, int):
                refresh_token_store.revoke(raw_refresh_token, expires_at_epoch=exp)
        except AuthenticationError:
            # Logout remains idempotent for malformed/expired tokens.
            pass

    _clear_refresh_cookie(response)
    return AuthLogoutResponse(success=True)
