from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.authorization import ResourceAccessDeny, ResourceAccessGrant


class PermissionsRepository:
    async def list_grants(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        resource_type: str | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[ResourceAccessGrant], int]:
        base = select(ResourceAccessGrant).where(
            ResourceAccessGrant.organization_id == organization_id
        )
        if resource_type:
            base = base.where(ResourceAccessGrant.resource_type == resource_type)
        if status:
            base = base.where(ResourceAccessGrant.status == status)

        total_q = select(func.count()).select_from(base.subquery())
        total = (await db.execute(total_q)).scalar_one()

        rows_q = (
            base.order_by(ResourceAccessGrant.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        rows = list((await db.execute(rows_q)).scalars().all())
        return rows, total

    async def get_grant(
        self, db: AsyncSession, *, grant_id: UUID, organization_id: UUID
    ) -> ResourceAccessGrant | None:
        result = await db.execute(
            select(ResourceAccessGrant).where(
                ResourceAccessGrant.id == grant_id,
                ResourceAccessGrant.organization_id == organization_id,
            )
        )
        return result.scalar_one_or_none()

    async def create_grant(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        created_by_user_id: UUID,
        principal_type: str,
        principal_value: str,
        resource_type: str,
        resource_id: str | None,
        action: str,
        expires_at: datetime | None = None,
        reason: str | None = None,
    ) -> ResourceAccessGrant:
        grant = ResourceAccessGrant(
            organization_id=organization_id,
            created_by_user_id=created_by_user_id,
            principal_type=principal_type,
            principal_value=principal_value,
            resource_type=resource_type,
            resource_id=resource_id,
            action=action,
            status="active",
            expires_at=expires_at,
            reason=reason,
        )
        db.add(grant)
        await db.flush()
        return grant

    async def revoke_grant(self, db: AsyncSession, *, grant: ResourceAccessGrant) -> None:
        grant.status = "revoked"
        db.add(grant)
        await db.flush()

    async def list_denies(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        resource_type: str | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[ResourceAccessDeny], int]:
        base = select(ResourceAccessDeny).where(
            ResourceAccessDeny.organization_id == organization_id
        )
        if resource_type:
            base = base.where(ResourceAccessDeny.resource_type == resource_type)
        if status:
            base = base.where(ResourceAccessDeny.status == status)

        total_q = select(func.count()).select_from(base.subquery())
        total = (await db.execute(total_q)).scalar_one()

        rows_q = (
            base.order_by(ResourceAccessDeny.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        rows = list((await db.execute(rows_q)).scalars().all())
        return rows, total

    async def get_deny(
        self, db: AsyncSession, *, deny_id: UUID, organization_id: UUID
    ) -> ResourceAccessDeny | None:
        result = await db.execute(
            select(ResourceAccessDeny).where(
                ResourceAccessDeny.id == deny_id,
                ResourceAccessDeny.organization_id == organization_id,
            )
        )
        return result.scalar_one_or_none()

    async def create_deny(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        created_by_user_id: UUID,
        principal_type: str,
        principal_value: str,
        resource_type: str,
        resource_id: str | None,
        action: str,
        expires_at: datetime | None = None,
        reason: str | None = None,
    ) -> ResourceAccessDeny:
        deny = ResourceAccessDeny(
            organization_id=organization_id,
            created_by_user_id=created_by_user_id,
            principal_type=principal_type,
            principal_value=principal_value,
            resource_type=resource_type,
            resource_id=resource_id,
            action=action,
            status="active",
            expires_at=expires_at,
            reason=reason,
        )
        db.add(deny)
        await db.flush()
        return deny

    async def revoke_deny(self, db: AsyncSession, *, deny: ResourceAccessDeny) -> None:
        deny.status = "revoked"
        db.add(deny)
        await db.flush()
