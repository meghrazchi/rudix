from __future__ import annotations

from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chunking_profile import OrganizationChunkingProfile


class ChunkingProfileRepository:
    async def list_by_organization(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
    ) -> list[OrganizationChunkingProfile]:
        result = await session.execute(
            select(OrganizationChunkingProfile)
            .where(OrganizationChunkingProfile.organization_id == organization_id)
            .order_by(
                OrganizationChunkingProfile.is_default.desc(),
                OrganizationChunkingProfile.created_at,
            )
        )
        return list(result.scalars().all())

    async def get_by_id(
        self,
        session: AsyncSession,
        *,
        profile_id: UUID,
        organization_id: UUID,
    ) -> OrganizationChunkingProfile | None:
        result = await session.execute(
            select(OrganizationChunkingProfile).where(
                OrganizationChunkingProfile.id == profile_id,
                OrganizationChunkingProfile.organization_id == organization_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_slug(
        self,
        session: AsyncSession,
        *,
        slug: str,
        organization_id: UUID,
    ) -> OrganizationChunkingProfile | None:
        result = await session.execute(
            select(OrganizationChunkingProfile).where(
                OrganizationChunkingProfile.slug == slug,
                OrganizationChunkingProfile.organization_id == organization_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_org_default(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
    ) -> OrganizationChunkingProfile | None:
        result = await session.execute(
            select(OrganizationChunkingProfile).where(
                OrganizationChunkingProfile.organization_id == organization_id,
                OrganizationChunkingProfile.is_default.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        created_by_user_id: UUID | None,
        name: str,
        slug: str,
        config_json: dict,
        is_default: bool = False,
        is_system: bool = False,
    ) -> OrganizationChunkingProfile:
        profile = OrganizationChunkingProfile(
            organization_id=organization_id,
            created_by_user_id=created_by_user_id,
            updated_by_user_id=created_by_user_id,
            name=name,
            slug=slug,
            config_json=config_json,
            is_default=is_default,
            is_system=is_system,
        )
        session.add(profile)
        await session.flush()
        await session.refresh(profile)
        return profile

    async def update(
        self,
        session: AsyncSession,
        *,
        profile: OrganizationChunkingProfile,
        updated_by_user_id: UUID | None,
        name: str | None = None,
        config_json: dict | None = None,
        is_default: bool | None = None,
    ) -> OrganizationChunkingProfile:
        if name is not None:
            profile.name = name
        if config_json is not None:
            profile.config_json = config_json
        if is_default is not None:
            profile.is_default = is_default
        profile.updated_by_user_id = updated_by_user_id
        await session.flush()
        await session.refresh(profile)
        return profile

    async def clear_org_default(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        exclude_profile_id: UUID | None = None,
    ) -> None:
        stmt = (
            update(OrganizationChunkingProfile)
            .where(
                OrganizationChunkingProfile.organization_id == organization_id,
                OrganizationChunkingProfile.is_default.is_(True),
            )
            .values(is_default=False)
        )
        if exclude_profile_id is not None:
            stmt = stmt.where(OrganizationChunkingProfile.id != exclude_profile_id)
        await session.execute(stmt)

    async def delete(
        self,
        session: AsyncSession,
        *,
        profile: OrganizationChunkingProfile,
    ) -> None:
        await session.delete(profile)
        await session.flush()
