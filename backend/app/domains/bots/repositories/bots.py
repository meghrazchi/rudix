from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bot import BotInstallation, BotUserMapping
from app.models.organization_member import OrganizationMember
from app.models.user import User


class BotRepository:
    async def list_installations(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
    ) -> list[BotInstallation]:
        result = await session.execute(
            select(BotInstallation)
            .where(BotInstallation.organization_id == organization_id)
            .order_by(BotInstallation.created_at.desc(), BotInstallation.id.desc())
        )
        return list(result.scalars().all())

    async def get_installation(
        self,
        session: AsyncSession,
        *,
        installation_id: UUID,
        organization_id: UUID,
    ) -> BotInstallation | None:
        result = await session.execute(
            select(BotInstallation).where(
                BotInstallation.id == installation_id,
                BotInstallation.organization_id == organization_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_installation_by_external_scope(
        self,
        session: AsyncSession,
        *,
        provider: str,
        external_workspace_id: str,
        external_tenant_id: str = "",
        external_team_id: str = "",
    ) -> BotInstallation | None:
        result = await session.execute(
            select(BotInstallation).where(
                BotInstallation.provider == provider,
                BotInstallation.external_workspace_id == external_workspace_id,
                BotInstallation.external_tenant_id == external_tenant_id,
                BotInstallation.external_team_id == external_team_id,
            )
        )
        return result.scalar_one_or_none()

    async def create_installation(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        provider: str,
        external_workspace_id: str,
        external_tenant_id: str,
        external_team_id: str,
        display_name: str | None,
        status: str,
        default_source_scope: dict,
        config: dict,
        installed_by_user_id: UUID | None,
    ) -> BotInstallation:
        installation = BotInstallation(
            organization_id=organization_id,
            provider=provider,
            external_workspace_id=external_workspace_id,
            external_tenant_id=external_tenant_id,
            external_team_id=external_team_id,
            display_name=display_name,
            status=status,
            default_source_scope_json=default_source_scope,
            config_json=config,
            installed_by_user_id=installed_by_user_id,
        )
        session.add(installation)
        await session.flush()
        await session.refresh(installation)
        return installation

    async def update_installation(
        self,
        session: AsyncSession,
        *,
        installation: BotInstallation,
        display_name: str | None = None,
        status: str | None = None,
        default_source_scope: dict | None = None,
        config: dict | None = None,
    ) -> BotInstallation:
        if display_name is not None:
            installation.display_name = display_name
        if status is not None:
            installation.status = status
        if default_source_scope is not None:
            installation.default_source_scope_json = default_source_scope
        if config is not None:
            installation.config_json = config
        session.add(installation)
        await session.flush()
        await session.refresh(installation)
        return installation

    async def list_user_mappings(
        self,
        session: AsyncSession,
        *,
        installation_id: UUID,
        organization_id: UUID,
    ) -> list[BotUserMapping]:
        result = await session.execute(
            select(BotUserMapping)
            .where(
                BotUserMapping.installation_id == installation_id,
                BotUserMapping.organization_id == organization_id,
            )
            .order_by(BotUserMapping.created_at.desc(), BotUserMapping.id.desc())
        )
        return list(result.scalars().all())

    async def get_user_mapping(
        self,
        session: AsyncSession,
        *,
        installation_id: UUID,
        organization_id: UUID,
        external_user_id: str,
    ) -> BotUserMapping | None:
        result = await session.execute(
            select(BotUserMapping).where(
                BotUserMapping.installation_id == installation_id,
                BotUserMapping.organization_id == organization_id,
                BotUserMapping.external_user_id == external_user_id,
            )
        )
        return result.scalar_one_or_none()

    async def upsert_user_mapping(
        self,
        session: AsyncSession,
        *,
        installation_id: UUID,
        organization_id: UUID,
        external_user_id: str,
        rudix_user_id: UUID,
        external_email: str | None,
        status: str,
        created_by_user_id: UUID | None,
    ) -> BotUserMapping:
        existing = await self.get_user_mapping(
            session,
            installation_id=installation_id,
            organization_id=organization_id,
            external_user_id=external_user_id,
        )
        if existing is not None:
            existing.rudix_user_id = rudix_user_id
            existing.external_email = external_email
            existing.status = status
            session.add(existing)
            await session.flush()
            await session.refresh(existing)
            return existing

        mapping = BotUserMapping(
            organization_id=organization_id,
            installation_id=installation_id,
            rudix_user_id=rudix_user_id,
            external_user_id=external_user_id,
            external_email=external_email,
            status=status,
            created_by_user_id=created_by_user_id,
        )
        session.add(mapping)
        await session.flush()
        await session.refresh(mapping)
        return mapping

    async def get_active_mapped_user(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        mapping: BotUserMapping,
    ) -> tuple[User, list[str]] | None:
        result = await session.execute(
            select(User, OrganizationMember.role)
            .join(
                OrganizationMember,
                OrganizationMember.user_id == User.id,
            )
            .where(
                User.id == mapping.rudix_user_id,
                User.organization_id == organization_id,
                User.is_active.is_(True),
                OrganizationMember.organization_id == organization_id,
                OrganizationMember.user_id == mapping.rudix_user_id,
            )
        )
        rows = result.all()
        if not rows:
            return None
        user = rows[0][0]
        roles = [str(row[1]) for row in rows if row[1]]
        return user, roles
