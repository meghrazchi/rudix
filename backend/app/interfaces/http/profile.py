"""
Profile endpoints – authenticated user's own record.

Auth:   Bearer JWT required (enforced by the parent protected_router).
Org:    Write operations are scoped to principal.organization_id.
Roles:  All endpoints: any authenticated user (own record only).
        DELETE /me: owner accounts must transfer org ownership first.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_principal
from app.auth.models import AuthenticatedPrincipal
from app.auth.session_repository import AuthSessionRepository
from app.clients.minio_client import get_minio_client
from app.core.config import settings
from app.db.session import get_db_session
from app.domains.admin.services.audit_service import AuditLogService
from app.models.auth_session import AuthRefreshSession
from app.models.organization_member import OrganizationMember
from app.models.user import User

router = APIRouter(prefix="/me", tags=["profile"])

_AUDIT = AuditLogService()
_SESSION_REPO = AuthSessionRepository()

# ── Constants ─────────────────────────────────────────────────────────────────

_AVATAR_ALLOWED_CONTENT_TYPES = {"image/png", "image/jpeg", "image/webp"}
_AVATAR_MAX_BYTES = 5 * 1024 * 1024  # 5 MB
_AVATAR_OBJECT_PREFIX = "avatars"
_AVATAR_URL_TTL = 7 * 24 * 3600  # 7 days presigned expiry

# ── Helpers ───────────────────────────────────────────────────────────────────


async def _get_user(db: AsyncSession, *, principal: AuthenticatedPrincipal) -> User:
    row = await db.execute(select(User).where(User.id == uuid.UUID(principal.user_id)))
    user = row.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    return user


def _avatar_presigned_url(object_key: str) -> str | None:
    client = get_minio_client(lazy_init=False)
    if client is None or not object_key:
        return None
    try:
        return client.generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.minio_bucket, "Key": object_key},
            ExpiresIn=_AVATAR_URL_TTL,
        )
    except Exception:
        return None


def _resolve_avatar_url(user: User) -> str | None:
    """Return presigned URL if the stored value looks like an object key, else return as-is."""
    raw = user.avatar_url
    if not raw:
        return None
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw
    return _avatar_presigned_url(raw)


def _parse_preferences(user: User) -> dict:
    if not user.preferences_json:
        return {}
    try:
        parsed = json.loads(user.preferences_json)
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, ValueError):
        return {}


def _user_display_name(user: User) -> str:
    if user.display_name:
        return user.display_name
    local = user.email.split("@")[0] if user.email and "@" in user.email else ""
    return (
        " ".join(p.capitalize() for p in local.split(".") if p)
        or local
        or user.email
        or ""
    )


def _build_user_response(user: User) -> dict:
    return {
        "id": str(user.id),
        "email": user.email or "",
        "name": _user_display_name(user),
        "avatar_url": _resolve_avatar_url(user),
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


# ── Response / request schemas ────────────────────────────────────────────────


class UserProfileResponse(BaseModel):
    id: str
    email: str
    name: str
    avatar_url: str | None
    created_at: str | None


class PatchMeBody(BaseModel):
    name: str | None = None


class PreferencesResponse(BaseModel):
    language: str | None = None
    timezone: str | None = None
    date_format: str | None = None
    theme: str | None = None
    landing_page: str | None = None
    keyboard_shortcut_hints: bool | None = None
    email_notifications: bool | None = None
    digest_frequency: str | None = None


class PatchPreferencesBody(BaseModel):
    language: str | None = None
    timezone: str | None = None
    date_format: str | None = None
    theme: str | None = None
    landing_page: str | None = None
    keyboard_shortcut_hints: bool | None = None
    email_notifications: bool | None = None
    digest_frequency: str | None = None


# ── GET /me ───────────────────────────────────────────────────────────────────


@router.get("", response_model=UserProfileResponse)
async def get_me(
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> UserProfileResponse:
    user = await _get_user(db, principal=principal)
    return UserProfileResponse(**_build_user_response(user))


# ── PATCH /me ─────────────────────────────────────────────────────────────────


@router.patch("", response_model=UserProfileResponse)
async def update_me(
    body: PatchMeBody,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> UserProfileResponse:
    user = await _get_user(db, principal=principal)

    if body.name is not None:
        name = body.name.strip()
        if not name or len(name) > 200:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Name must be between 1 and 200 characters.",
            )
        user.display_name = name

    await db.commit()
    await db.refresh(user)

    if principal.organization_id:
        await _AUDIT.record(
            db,
            organization_id=uuid.UUID(principal.organization_id),
            user_id=uuid.UUID(principal.user_id),
            action="user.profile.updated",
            resource_type="user",
            resource_id=principal.user_id,
            metadata={"fields_updated": ["name"] if body.name is not None else []},
        )

    return UserProfileResponse(**_build_user_response(user))


# ── POST /me/avatar ───────────────────────────────────────────────────────────


@router.post("/avatar", response_model=UserProfileResponse)
async def upload_avatar(
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    file: UploadFile = File(...),
) -> UserProfileResponse:
    content_type = (file.content_type or "").lower()
    if content_type not in _AVATAR_ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Avatar must be PNG, JPEG, or WEBP.",
        )

    ext_map = {
        "image/png": "png",
        "image/jpeg": "jpg",
        "image/webp": "webp",
    }
    ext = ext_map[content_type]

    data = await file.read()
    if len(data) > _AVATAR_MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Avatar file exceeds the 5 MB limit.",
        )
    if len(data) == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty file.")

    # Magic-bytes check: PNG (8 bytes), JPEG (2 bytes FF D8), WEBP (4+4 bytes)
    if content_type == "image/png" and not data[:8] == b"\x89PNG\r\n\x1a\n":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid PNG file.")
    if content_type == "image/jpeg" and not data[:2] == b"\xff\xd8":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JPEG file.")
    if content_type == "image/webp" and not (data[:4] == b"RIFF" and data[8:12] == b"WEBP"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid WEBP file.")

    client = get_minio_client(lazy_init=False)
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Object storage is not configured. Avatar upload is unavailable.",
        )

    user = await _get_user(db, principal=principal)

    # Delete old avatar if stored as an object key
    old_key = user.avatar_url
    if old_key and not (old_key.startswith("http://") or old_key.startswith("https://")):
        try:
            client.delete_object(Bucket=settings.minio_bucket, Key=old_key)
        except Exception:
            pass

    object_key = f"{_AVATAR_OBJECT_PREFIX}/{principal.user_id}/{uuid.uuid4()}.{ext}"
    import io
    client.put_object(
        Bucket=settings.minio_bucket,
        Key=object_key,
        Body=io.BytesIO(data),
        ContentType=content_type,
        ContentLength=len(data),
    )

    user.avatar_url = object_key
    await db.commit()
    await db.refresh(user)

    if principal.organization_id:
        await _AUDIT.record(
            db,
            organization_id=uuid.UUID(principal.organization_id),
            user_id=uuid.UUID(principal.user_id),
            action="user.avatar.uploaded",
            resource_type="user",
            resource_id=principal.user_id,
        )

    return UserProfileResponse(**_build_user_response(user))


# ── DELETE /me/avatar ─────────────────────────────────────────────────────────


@router.delete("/avatar", status_code=status.HTTP_204_NO_CONTENT)
async def remove_avatar(
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> None:
    user = await _get_user(db, principal=principal)

    old_key = user.avatar_url
    if old_key and not (old_key.startswith("http://") or old_key.startswith("https://")):
        client = get_minio_client(lazy_init=False)
        if client is not None:
            try:
                client.delete_object(Bucket=settings.minio_bucket, Key=old_key)
            except Exception:
                pass

    user.avatar_url = None
    await db.commit()

    if principal.organization_id:
        await _AUDIT.record(
            db,
            organization_id=uuid.UUID(principal.organization_id),
            user_id=uuid.UUID(principal.user_id),
            action="user.avatar.removed",
            resource_type="user",
            resource_id=principal.user_id,
        )


# ── GET /me/preferences ───────────────────────────────────────────────────────


@router.get("/preferences", response_model=PreferencesResponse)
async def get_my_preferences(
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> PreferencesResponse:
    user = await _get_user(db, principal=principal)
    prefs = _parse_preferences(user)
    return PreferencesResponse(
        language=prefs.get("language"),
        timezone=prefs.get("timezone"),
        date_format=prefs.get("date_format"),
        theme=prefs.get("theme"),
        landing_page=prefs.get("landing_page"),
        keyboard_shortcut_hints=prefs.get("keyboard_shortcut_hints"),
        email_notifications=prefs.get("email_notifications"),
        digest_frequency=prefs.get("digest_frequency"),
    )


# ── PATCH /me/preferences ─────────────────────────────────────────────────────


@router.patch("/preferences", response_model=PreferencesResponse)
async def update_my_preferences(
    body: PatchPreferencesBody,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> PreferencesResponse:
    user = await _get_user(db, principal=principal)
    prefs = _parse_preferences(user)

    patch = body.model_dump(exclude_none=True)
    if body.language is not None:
        prefs["language"] = body.language
    if body.timezone is not None:
        prefs["timezone"] = body.timezone
    if body.date_format is not None:
        prefs["date_format"] = body.date_format
    if body.theme is not None:
        if body.theme not in ("light", "dark", "system"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="theme must be one of: light, dark, system.",
            )
        prefs["theme"] = body.theme
    if body.landing_page is not None:
        prefs["landing_page"] = body.landing_page
    if body.keyboard_shortcut_hints is not None:
        prefs["keyboard_shortcut_hints"] = body.keyboard_shortcut_hints
    if body.email_notifications is not None:
        prefs["email_notifications"] = body.email_notifications
    if body.digest_frequency is not None:
        if body.digest_frequency not in ("daily", "weekly", "never"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="digest_frequency must be one of: daily, weekly, never.",
            )
        prefs["digest_frequency"] = body.digest_frequency

    user.preferences_json = json.dumps(prefs)
    await db.commit()

    return PreferencesResponse(
        language=prefs.get("language"),
        timezone=prefs.get("timezone"),
        date_format=prefs.get("date_format"),
        theme=prefs.get("theme"),
        landing_page=prefs.get("landing_page"),
        keyboard_shortcut_hints=prefs.get("keyboard_shortcut_hints"),
        email_notifications=prefs.get("email_notifications"),
        digest_frequency=prefs.get("digest_frequency"),
    )


# ── POST /me/sign-out-all ─────────────────────────────────────────────────────


@router.post("/sign-out-all", status_code=status.HTTP_204_NO_CONTENT)
async def sign_out_all_devices(
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> None:
    user_uuid = uuid.UUID(principal.user_id)
    now = datetime.now(UTC)

    await _SESSION_REPO.mark_user_sessions_revoked(
        db,
        user_id=user_uuid,
        revoked_at=now,
        reason="sign_out_all",
    )
    await db.commit()

    if principal.organization_id:
        await _AUDIT.record(
            db,
            organization_id=uuid.UUID(principal.organization_id),
            user_id=user_uuid,
            action="user.session.revoked_all",
            resource_type="user",
            resource_id=principal.user_id,
        )


# ── DELETE /me ────────────────────────────────────────────────────────────────


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_personal_account(
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> None:
    user_uuid = uuid.UUID(principal.user_id)

    # Prevent deletion when the user is the sole owner of any organization.
    if principal.organization_id:
        org_uuid = uuid.UUID(principal.organization_id)
        owner_count_row = await db.execute(
            select(func.count(OrganizationMember.id)).where(
                OrganizationMember.organization_id == org_uuid,
                OrganizationMember.role == "owner",
            )
        )
        owner_count: int = owner_count_row.scalar_one() or 0
        if owner_count <= 1:
            is_owner_row = await db.execute(
                select(OrganizationMember).where(
                    OrganizationMember.organization_id == org_uuid,
                    OrganizationMember.user_id == user_uuid,
                    OrganizationMember.role == "owner",
                )
            )
            if is_owner_row.scalar_one_or_none() is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "You are the sole owner of your organization. "
                        "Transfer ownership before deleting your account."
                    ),
                )

    # Revoke all sessions first.
    await _SESSION_REPO.mark_user_sessions_revoked(
        db,
        user_id=user_uuid,
        revoked_at=datetime.now(UTC),
        reason="account_deleted",
    )

    # Record audit event before deletion (so we still have principal context).
    if principal.organization_id:
        await _AUDIT.record(
            db,
            organization_id=uuid.UUID(principal.organization_id),
            user_id=user_uuid,
            action="user.account.deleted",
            resource_type="user",
            resource_id=principal.user_id,
        )

    user = await _get_user(db, principal=principal)

    # Clean up avatar from object storage.
    avatar_key = user.avatar_url
    if avatar_key and not (
        avatar_key.startswith("http://") or avatar_key.startswith("https://")
    ):
        client = get_minio_client(lazy_init=False)
        if client is not None:
            try:
                client.delete_object(Bucket=settings.minio_bucket, Key=avatar_key)
            except Exception:
                pass

    await db.delete(user)
    await db.commit()
