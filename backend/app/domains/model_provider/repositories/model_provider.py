from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.model_provider_settings import (
    OrgModelProviderChangeLog,
    OrgModelProviderSettings,
)


class ModelProviderRepository:
    # ------------------------------------------------------------------
    # Settings CRUD (one row per org — upsert pattern)
    # ------------------------------------------------------------------

    async def get_settings(
        self,
        db_session: AsyncSession,
        *,
        organization_id: UUID,
    ) -> OrgModelProviderSettings | None:
        stmt = select(OrgModelProviderSettings).where(
            OrgModelProviderSettings.organization_id == organization_id,
        )
        result = await db_session.execute(stmt)
        return result.scalar_one_or_none()

    async def upsert_settings(
        self,
        db_session: AsyncSession,
        *,
        organization_id: UUID,
        provider: str | None,
        llm_model: str | None,
        embedding_model: str | None,
        max_tokens: int | None,
        timeout_seconds: int | None,
        max_retries: int | None,
        fallback_model: str | None,
        disabled_models: list[str],
        updated_by_id: UUID | None,
        bump_version: bool = True,
    ) -> OrgModelProviderSettings:
        existing = await self.get_settings(db_session, organization_id=organization_id)
        if existing is not None:
            existing.provider = provider
            existing.llm_model = llm_model
            existing.embedding_model = embedding_model
            existing.max_tokens = max_tokens
            existing.timeout_seconds = timeout_seconds
            existing.max_retries = max_retries
            existing.fallback_model = fallback_model
            existing.disabled_models = disabled_models
            existing.updated_by_id = updated_by_id
            if bump_version:
                existing.version = (existing.version or 1) + 1
            await db_session.flush()
            return existing

        settings = OrgModelProviderSettings(
            organization_id=organization_id,
            provider=provider,
            llm_model=llm_model,
            embedding_model=embedding_model,
            max_tokens=max_tokens,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            fallback_model=fallback_model,
            disabled_models=disabled_models,
            updated_by_id=updated_by_id,
            version=1,
        )
        db_session.add(settings)
        await db_session.flush()
        return settings

    async def delete_settings(
        self,
        db_session: AsyncSession,
        settings: OrgModelProviderSettings,
    ) -> None:
        await db_session.delete(settings)
        await db_session.flush()

    # ------------------------------------------------------------------
    # Change log
    # ------------------------------------------------------------------

    async def create_change_log_entry(
        self,
        db_session: AsyncSession,
        *,
        organization_id: UUID,
        settings_id: UUID,
        version_number: int,
        settings_snapshot: dict,
        change_note: str | None,
        changed_by_id: UUID | None,
    ) -> OrgModelProviderChangeLog:
        entry = OrgModelProviderChangeLog(
            organization_id=organization_id,
            org_model_provider_settings_id=settings_id,
            version_number=version_number,
            settings_snapshot=settings_snapshot,
            change_note=change_note,
            changed_by_id=changed_by_id,
        )
        db_session.add(entry)
        await db_session.flush()
        return entry

    async def list_change_log(
        self,
        db_session: AsyncSession,
        *,
        organization_id: UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> list[OrgModelProviderChangeLog]:
        stmt = (
            select(OrgModelProviderChangeLog)
            .where(OrgModelProviderChangeLog.organization_id == organization_id)
            .order_by(OrgModelProviderChangeLog.version_number.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await db_session.execute(stmt)
        return list(result.scalars().all())

    async def count_change_log(
        self,
        db_session: AsyncSession,
        *,
        organization_id: UUID,
    ) -> int:
        stmt = select(func.count(OrgModelProviderChangeLog.id)).where(
            OrgModelProviderChangeLog.organization_id == organization_id,
        )
        result = await db_session.execute(stmt)
        return result.scalar_one()
