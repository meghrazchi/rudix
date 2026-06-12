from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.feature_flags import OrgFeatureFlagOverride


class FeatureFlagRepository:
    async def list_by_organization(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
    ) -> list[OrgFeatureFlagOverride]:
        result = await session.execute(
            select(OrgFeatureFlagOverride)
            .where(OrgFeatureFlagOverride.organization_id == organization_id)
            .order_by(OrgFeatureFlagOverride.flag_name)
        )
        return list(result.scalars().all())

    async def get(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        flag_name: str,
    ) -> OrgFeatureFlagOverride | None:
        result = await session.execute(
            select(OrgFeatureFlagOverride).where(
                OrgFeatureFlagOverride.organization_id == organization_id,
                OrgFeatureFlagOverride.flag_name == flag_name,
            )
        )
        return result.scalar_one_or_none()

    async def upsert(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        flag_name: str,
        enabled: bool,
        reason: str | None,
        overridden_by_user_id: UUID | None,
    ) -> OrgFeatureFlagOverride:
        existing = await self.get(
            session, organization_id=organization_id, flag_name=flag_name
        )
        if existing is None:
            override = OrgFeatureFlagOverride(
                organization_id=organization_id,
                flag_name=flag_name,
                enabled=enabled,
                reason=reason,
                overridden_by_user_id=overridden_by_user_id,
            )
            session.add(override)
        else:
            existing.enabled = enabled
            existing.reason = reason
            existing.overridden_by_user_id = overridden_by_user_id
            override = existing
        await session.flush()
        await session.refresh(override)
        return override

    async def delete(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        flag_name: str,
    ) -> bool:
        result = await session.execute(
            delete(OrgFeatureFlagOverride).where(
                OrgFeatureFlagOverride.organization_id == organization_id,
                OrgFeatureFlagOverride.flag_name == flag_name,
            )
        )
        return result.rowcount > 0
