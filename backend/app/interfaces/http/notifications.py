from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_principal
from app.auth.models import AuthenticatedPrincipal
from app.db.session import get_db_session
from app.domains.notifications.repositories.notifications import (
    NOTIFICATION_SORT_NAME,
    NotificationRepository,
)
from app.domains.notifications.schemas.notifications import (
    MarkAllReadResponse,
    MarkReadResponse,
    NotificationListResponse,
    NotificationResponse,
    UnreadCountResponse,
)
from app.shared.pagination import encode_cursor, resolve_page_request, split_page

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
    cursor: str | None = Query(default=None, max_length=1024),
    include_total: bool | None = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),  # noqa: B008
    db: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> NotificationListResponse:
    user_id, org_id = _principal_user_and_org(principal)
    page = resolve_page_request(
        cursor=cursor, offset=offset, include_total=include_total, sort_name=NOTIFICATION_SORT_NAME
    )
    fetched, total, unread_count = await _notification_repository.list_with_counts(
        db,
        organization_id=org_id,
        user_id=user_id,
        limit=limit + 1,
        offset=offset,
        keyset=page.keyset,
        include_total=page.include_total,
    )
    items, has_more = split_page(fetched, limit)
    next_cursor = (
        encode_cursor(NOTIFICATION_SORT_NAME, [items[-1].created_at, items[-1].id])
        if has_more
        else None
    )
    return NotificationListResponse(
        items=[NotificationResponse.from_model(n) for n in items],
        total=total,
        limit=limit,
        offset=offset,
        unread_count=unread_count,
        next_cursor=next_cursor,
    )


@router.get("/unread-count", response_model=UnreadCountResponse)
async def get_unread_count(
    principal: AuthenticatedPrincipal = Depends(get_current_principal),  # noqa: B008
    db: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> UnreadCountResponse:
    user_id, org_id = _principal_user_and_org(principal)
    count = await _notification_repository.count_unread(db, organization_id=org_id, user_id=user_id)
    return UnreadCountResponse(unread_count=count)


@router.patch("/{notification_id}/read", response_model=MarkReadResponse)
async def mark_notification_read(
    notification_id: str,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),  # noqa: B008
    db: AsyncSession = Depends(get_db_session),  # noqa: B008
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
    principal: AuthenticatedPrincipal = Depends(get_current_principal),  # noqa: B008
    db: AsyncSession = Depends(get_db_session),  # noqa: B008
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
    principal: AuthenticatedPrincipal = Depends(get_current_principal),  # noqa: B008
    db: AsyncSession = Depends(get_db_session),  # noqa: B008
) -> MarkAllReadResponse:
    user_id, org_id = _principal_user_and_org(principal)
    marked_count = await _notification_repository.mark_all_read(
        db, organization_id=org_id, user_id=user_id
    )
    await db.commit()
    return MarkAllReadResponse(marked_count=marked_count)
