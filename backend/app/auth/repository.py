from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.organization_member import OrganizationMember
from app.models.user import User


class AuthRepository:
    async def get_user_by_id(self, session: AsyncSession, *, user_id: UUID) -> User | None:
        result = await session.execute(
            select(User)
            .where(User.id == user_id)
            .options(selectinload(User.memberships))
        )
        return result.scalar_one_or_none()

    async def get_user_by_external_auth_id(self, session: AsyncSession, *, external_auth_id: str) -> User | None:
        result = await session.execute(
            select(User)
            .where(User.external_auth_id == external_auth_id)
            .options(selectinload(User.memberships))
        )
        return result.scalar_one_or_none()

    async def get_membership(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        user_id: UUID,
    ) -> OrganizationMember | None:
        result = await session.execute(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == organization_id,
                OrganizationMember.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()
