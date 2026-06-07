from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.rag_profile import (
    RagProfile,
    RagProfileCollectionOverride,
    RagProfileVersion,
)


class RagProfileRepository:
    # ------------------------------------------------------------------
    # Profile CRUD
    # ------------------------------------------------------------------

    async def create_profile(
        self,
        db_session: AsyncSession,
        *,
        organization_id: UUID,
        name: str,
        description: str | None,
        config: dict,
        is_default: bool,
        created_by_id: UUID | None,
    ) -> RagProfile:
        profile = RagProfile(
            organization_id=organization_id,
            name=name,
            description=description,
            config=config,
            is_default=is_default,
            version=1,
            created_by_id=created_by_id,
            updated_by_id=created_by_id,
        )
        db_session.add(profile)
        await db_session.flush()
        return profile

    async def get_profile(
        self,
        db_session: AsyncSession,
        *,
        profile_id: UUID,
        organization_id: UUID,
    ) -> RagProfile | None:
        stmt = select(RagProfile).where(
            RagProfile.id == profile_id,
            RagProfile.organization_id == organization_id,
        )
        result = await db_session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_profiles(
        self,
        db_session: AsyncSession,
        *,
        organization_id: UUID,
        include_archived: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[RagProfile]:
        stmt = select(RagProfile).where(
            RagProfile.organization_id == organization_id,
        )
        if not include_archived:
            stmt = stmt.where(RagProfile.is_archived.is_(False))
        stmt = (
            stmt.order_by(
                RagProfile.is_default.desc(),
                RagProfile.created_at.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
        result = await db_session.execute(stmt)
        return list(result.scalars().all())

    async def count_profiles(
        self,
        db_session: AsyncSession,
        *,
        organization_id: UUID,
        include_archived: bool = False,
    ) -> int:
        stmt = select(func.count(RagProfile.id)).where(
            RagProfile.organization_id == organization_id,
        )
        if not include_archived:
            stmt = stmt.where(RagProfile.is_archived.is_(False))
        result = await db_session.execute(stmt)
        return result.scalar_one()

    async def get_default_profile(
        self,
        db_session: AsyncSession,
        *,
        organization_id: UUID,
    ) -> RagProfile | None:
        stmt = select(RagProfile).where(
            RagProfile.organization_id == organization_id,
            RagProfile.is_default.is_(True),
            RagProfile.is_archived.is_(False),
        )
        result = await db_session.execute(stmt)
        return result.scalar_one_or_none()

    async def clear_default_flag(
        self,
        db_session: AsyncSession,
        *,
        organization_id: UUID,
        exclude_id: UUID | None = None,
    ) -> None:
        """Unset is_default on all profiles in the org (except exclude_id)."""
        from sqlalchemy import update

        stmt = (
            update(RagProfile)
            .where(
                RagProfile.organization_id == organization_id,
                RagProfile.is_default.is_(True),
            )
            .values(is_default=False)
        )
        if exclude_id is not None:
            stmt = stmt.where(RagProfile.id != exclude_id)
        await db_session.execute(stmt)

    async def update_profile(
        self,
        db_session: AsyncSession,
        profile: RagProfile,
        *,
        name: str | None = None,
        description: str | None = None,
        config: dict | None = None,
        is_default: bool | None = None,
        is_archived: bool | None = None,
        updated_by_id: UUID | None = None,
        bump_version: bool = False,
    ) -> RagProfile:
        if name is not None:
            profile.name = name
        if description is not None:
            profile.description = description
        if config is not None:
            profile.config = config
        if is_default is not None:
            profile.is_default = is_default
        if is_archived is not None:
            profile.is_archived = is_archived
        if updated_by_id is not None:
            profile.updated_by_id = updated_by_id
        if bump_version:
            profile.version = (profile.version or 1) + 1
        await db_session.flush()
        return profile

    # ------------------------------------------------------------------
    # Versioning
    # ------------------------------------------------------------------

    async def create_version_snapshot(
        self,
        db_session: AsyncSession,
        *,
        rag_profile_id: UUID,
        version_number: int,
        config_snapshot: dict,
        change_note: str | None,
        changed_by_id: UUID | None,
    ) -> RagProfileVersion:
        version = RagProfileVersion(
            rag_profile_id=rag_profile_id,
            version_number=version_number,
            config_snapshot=config_snapshot,
            change_note=change_note,
            changed_by_id=changed_by_id,
        )
        db_session.add(version)
        await db_session.flush()
        return version

    async def list_versions(
        self,
        db_session: AsyncSession,
        *,
        rag_profile_id: UUID,
        organization_id: UUID,
    ) -> list[RagProfileVersion]:
        stmt = (
            select(RagProfileVersion)
            .join(RagProfile, RagProfileVersion.rag_profile_id == RagProfile.id)
            .where(
                RagProfileVersion.rag_profile_id == rag_profile_id,
                RagProfile.organization_id == organization_id,
            )
            .order_by(RagProfileVersion.version_number.desc())
        )
        result = await db_session.execute(stmt)
        return list(result.scalars().all())

    async def get_version(
        self,
        db_session: AsyncSession,
        *,
        rag_profile_id: UUID,
        version_number: int,
        organization_id: UUID,
    ) -> RagProfileVersion | None:
        stmt = (
            select(RagProfileVersion)
            .join(RagProfile, RagProfileVersion.rag_profile_id == RagProfile.id)
            .where(
                RagProfileVersion.rag_profile_id == rag_profile_id,
                RagProfileVersion.version_number == version_number,
                RagProfile.organization_id == organization_id,
            )
        )
        result = await db_session.execute(stmt)
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------
    # Collection overrides
    # ------------------------------------------------------------------

    async def get_collection_override(
        self,
        db_session: AsyncSession,
        *,
        organization_id: UUID,
        collection_id: UUID,
    ) -> RagProfileCollectionOverride | None:
        stmt = select(RagProfileCollectionOverride).where(
            RagProfileCollectionOverride.organization_id == organization_id,
            RagProfileCollectionOverride.collection_id == collection_id,
        )
        result = await db_session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_collection_overrides(
        self,
        db_session: AsyncSession,
        *,
        organization_id: UUID,
    ) -> list[RagProfileCollectionOverride]:
        stmt = (
            select(RagProfileCollectionOverride)
            .where(
                RagProfileCollectionOverride.organization_id == organization_id,
            )
            .order_by(RagProfileCollectionOverride.created_at.desc())
        )
        result = await db_session.execute(stmt)
        return list(result.scalars().all())

    async def upsert_collection_override(
        self,
        db_session: AsyncSession,
        *,
        organization_id: UUID,
        collection_id: UUID,
        rag_profile_id: UUID,
        created_by_id: UUID | None,
    ) -> RagProfileCollectionOverride:
        existing = await self.get_collection_override(
            db_session,
            organization_id=organization_id,
            collection_id=collection_id,
        )
        if existing is not None:
            existing.rag_profile_id = rag_profile_id
            await db_session.flush()
            return existing

        override = RagProfileCollectionOverride(
            organization_id=organization_id,
            collection_id=collection_id,
            rag_profile_id=rag_profile_id,
            created_by_id=created_by_id,
        )
        db_session.add(override)
        await db_session.flush()
        return override

    async def delete_collection_override(
        self,
        db_session: AsyncSession,
        override: RagProfileCollectionOverride,
    ) -> None:
        await db_session.delete(override)
        await db_session.flush()
