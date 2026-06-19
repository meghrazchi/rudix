from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.authorization import AuthorizationConflict


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


class ConflictsRepository:
    async def list_conflicts(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        severity_db: str | None = None,
        status: str | None = None,
        resource_type: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[AuthorizationConflict], int]:
        base = select(AuthorizationConflict).where(
            AuthorizationConflict.organization_id == organization_id
        )
        count_q = select(func.count()).select_from(
            select(AuthorizationConflict.id)
            .where(AuthorizationConflict.organization_id == organization_id)
            .subquery()
        )

        if severity_db:
            base = base.where(AuthorizationConflict.severity == severity_db)
            count_q = count_q.where(AuthorizationConflict.severity == severity_db)
        if status:
            base = base.where(AuthorizationConflict.status == status)
            count_q = count_q.where(AuthorizationConflict.status == status)
        if resource_type:
            base = base.where(AuthorizationConflict.resource_type == resource_type)
            count_q = count_q.where(AuthorizationConflict.resource_type == resource_type)

        offset = (page - 1) * page_size
        q = base.order_by(AuthorizationConflict.detected_at.desc()).offset(offset).limit(page_size)
        rows = (await db.execute(q)).scalars().all()
        total = (await db.execute(count_q)).scalar_one()
        return list(rows), int(total)

    async def get_conflict(
        self,
        db: AsyncSession,
        *,
        conflict_id: UUID,
        organization_id: UUID,
    ) -> AuthorizationConflict | None:
        q = select(AuthorizationConflict).where(
            AuthorizationConflict.id == conflict_id,
            AuthorizationConflict.organization_id == organization_id,
        )
        return (await db.execute(q)).scalar_one_or_none()

    async def create_conflict(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        subject_type: str,
        subject_value: str,
        user_id: UUID | None,
        role_name: str | None,
        resource_type: str,
        resource_id: str | None,
        action: str,
        conflict_type: str,
        severity_db: str,
        conflict_summary: str | None,
        grant_id: UUID | None = None,
        deny_id: UUID | None = None,
        context: dict | None = None,
    ) -> AuthorizationConflict:
        conflict = AuthorizationConflict(
            organization_id=organization_id,
            subject_type=subject_type,
            subject_value=subject_value,
            user_id=user_id,
            role_name=role_name,
            resource_type=resource_type,
            resource_id=resource_id,
            action=action,
            conflict_type=conflict_type,
            severity=severity_db,
            status="open",
            detected_at=_now(),
            conflict_summary=conflict_summary,
            grant_id=grant_id,
            deny_id=deny_id,
            conflict_context_json=context or {},
        )
        db.add(conflict)
        await db.flush()
        return conflict

    async def update_conflict_status(
        self,
        db: AsyncSession,
        *,
        conflict: AuthorizationConflict,
        new_status: str,
        resolution_note: str | None = None,
    ) -> AuthorizationConflict:
        conflict.status = new_status
        if new_status in ("resolved", "dismissed"):
            conflict.resolved_at = _now()
        if resolution_note:
            ctx = dict(conflict.conflict_context_json or {})
            ctx["resolution_note"] = resolution_note
            conflict.conflict_context_json = ctx
        await db.flush()
        return conflict

    async def find_existing_open_conflict(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        subject_value: str,
        resource_type: str,
        resource_id: str | None,
        action: str,
        conflict_type: str,
    ) -> AuthorizationConflict | None:
        q = select(AuthorizationConflict).where(
            AuthorizationConflict.organization_id == organization_id,
            AuthorizationConflict.subject_value == subject_value,
            AuthorizationConflict.resource_type == resource_type,
            AuthorizationConflict.action == action,
            AuthorizationConflict.conflict_type == conflict_type,
            AuthorizationConflict.status.in_(["open", "investigating"]),
        )
        if resource_id is not None:
            q = q.where(AuthorizationConflict.resource_id == resource_id)
        else:
            q = q.where(AuthorizationConflict.resource_id.is_(None))
        return (await db.execute(q)).scalar_one_or_none()
