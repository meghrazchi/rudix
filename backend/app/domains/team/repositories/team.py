from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.organization_member import OrganizationMember
from app.models.user import User


class TeamRepository:
    async def list_members(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        limit: int,
        offset: int,
    ) -> list[OrganizationMember]:
        result = await session.execute(
            select(OrganizationMember)
            .where(OrganizationMember.organization_id == organization_id)
            .options(selectinload(OrganizationMember.user))
            .order_by(OrganizationMember.created_at.asc(), OrganizationMember.id.asc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def count_members(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
    ) -> int:
        result = await session.execute(
            select(func.count(OrganizationMember.id)).where(
                OrganizationMember.organization_id == organization_id
            )
        )
        return int(result.scalar_one())

    async def get_member(
        self,
        session: AsyncSession,
        *,
        member_id: UUID,
        organization_id: UUID,
    ) -> OrganizationMember | None:
        result = await session.execute(
            select(OrganizationMember)
            .where(
                OrganizationMember.id == member_id,
                OrganizationMember.organization_id == organization_id,
            )
            .options(selectinload(OrganizationMember.user))
        )
        return result.scalar_one_or_none()

    async def get_member_for_user(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        user_id: UUID,
    ) -> OrganizationMember | None:
        result = await session.execute(
            select(OrganizationMember)
            .where(
                OrganizationMember.organization_id == organization_id,
                OrganizationMember.user_id == user_id,
            )
            .options(selectinload(OrganizationMember.user))
        )
        return result.scalar_one_or_none()

    async def get_user_by_email(self, session: AsyncSession, *, email: str) -> User | None:
        result = await session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def create_user(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        external_auth_id: str,
        email: str,
        display_name: str,
    ) -> User:
        user = User(
            organization_id=organization_id,
            external_auth_id=external_auth_id,
            email=email,
            display_name=display_name,
        )
        session.add(user)
        await session.flush()
        return user

    async def create_member(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        user_id: UUID,
        role: str,
    ) -> OrganizationMember:
        member = OrganizationMember(
            organization_id=organization_id,
            user_id=user_id,
            role=role,
        )
        session.add(member)
        await session.flush()
        return member

    async def delete_member(self, session: AsyncSession, *, member: OrganizationMember) -> None:
        await session.delete(member)
        await session.flush()
