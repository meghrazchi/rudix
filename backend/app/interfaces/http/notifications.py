from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_principal
from app.auth.models import AuthenticatedPrincipal
from app.db.session import get_db_session
from app.domains.notifications.repositories.notifications import NotificationRepository
from app.domains.notifications.schemas.notifications import (
    MarkAllReadResponse,
    MarkReadResponse,
    NotificationListResponse,
    NotificationResponse,
    UnreadCountResponse,
)

router = APIRouter(prefix="/notifications", tags=["notifications"])
_notification_repository = NotificationRepository()


def _principal_user_and_org(principal: AuthenticatedPrincipal) -> tuple[UUID, UUID]:
    if principal.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No active organization context for principal",
        )
    try:
        return UUID(principal.user_id), UUID(principal.organization_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Principal identity context is invalid",
        ) from exc


@router.get("", response_model=NotificationListResponse)
async def list_notifications(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db_session),
) -> NotificationListResponse:
    user_id, org_id = _principal_user_and_org(principal)
    items, total, unread_count = await _notification_repository.list_with_counts(
        db, organization_id=org_id, user_id=user_id, limit=limit, offset=offset
    )
    return NotificationListResponse(
        items=[NotificationResponse.from_model(n) for n in items],
        total=total,
        limit=limit,
        offset=offset,
        unread_count=unread_count,
    )


@router.get("/unread-count", response_model=UnreadCountResponse)
async def get_unread_count(
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db_session),
) -> UnreadCountResponse:
    user_id, org_id = _principal_user_and_org(principal)
    count = await _notification_repository.count_unread(
        db, organization_id=org_id, user_id=user_id
    )
    return UnreadCountResponse(unread_count=count)


@router.patch("/{notification_id}/read", response_model=MarkReadResponse)
async def mark_notification_read(
    notification_id: str,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db_session),
) -> MarkReadResponse:
    user_id, org_id = _principal_user_and_org(principal)
    try:
        notif_uuid = UUID(notification_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid notification_id format",
        ) from exc

    updated = await _notification_repository.mark_read(
        db,
        notification_id=notif_uuid,
        organization_id=org_id,
        user_id=user_id,
        is_read=True,
    )
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found",
        )
    await db.commit()
    return MarkReadResponse(notification_id=notification_id, is_read=True)


@router.patch("/{notification_id}/unread", response_model=MarkReadResponse)
async def mark_notification_unread(
    notification_id: str,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db_session),
) -> MarkReadResponse:
    user_id, org_id = _principal_user_and_org(principal)
    try:
        notif_uuid = UUID(notification_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid notification_id format",
        ) from exc

    updated = await _notification_repository.mark_read(
        db,
        notification_id=notif_uuid,
        organization_id=org_id,
        user_id=user_id,
        is_read=False,
    )
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found",
        )
    await db.commit()
    return MarkReadResponse(notification_id=notification_id, is_read=False)


@router.post("/mark-all-read", response_model=MarkAllReadResponse)
async def mark_all_notifications_read(
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db_session),
) -> MarkAllReadResponse:
    user_id, org_id = _principal_user_and_org(principal)
    marked_count = await _notification_repository.mark_all_read(
        db, organization_id=org_id, user_id=user_id
    )
    await db.commit()
    return MarkAllReadResponse(marked_count=marked_count)
