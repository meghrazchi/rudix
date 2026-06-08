from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.custom_role import CustomRole, CustomRolePermission


class RolesRepository:
    async def list_custom_roles(
        self,
        db_session: AsyncSession,
        *,
        organization_id: UUID,
    ) -> list[CustomRole]:
        result = await db_session.execute(
            select(CustomRole)
            .options(selectinload(CustomRole.permissions))
            .where(CustomRole.organization_id == organization_id)
            .order_by(CustomRole.name)
        )
        return list(result.scalars())

    async def get_custom_role(
        self,
        db_session: AsyncSession,
        *,
        role_id: UUID,
        organization_id: UUID,
    ) -> CustomRole | None:
        result = await db_session.execute(
            select(CustomRole)
            .options(selectinload(CustomRole.permissions))
            .where(
                CustomRole.id == role_id,
                CustomRole.organization_id == organization_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_custom_role_by_name(
        self,
        db_session: AsyncSession,
        *,
        name: str,
        organization_id: UUID,
    ) -> CustomRole | None:
        result = await db_session.execute(
            select(CustomRole)
            .where(
                CustomRole.name == name,
                CustomRole.organization_id == organization_id,
            )
        )
        return result.scalar_one_or_none()

    async def create_custom_role(
        self,
        db_session: AsyncSession,
        *,
        organization_id: UUID,
        name: str,
        description: str | None,
        base_role: str | None,
        permissions: list[str],
        created_by_id: UUID | None,
    ) -> CustomRole:
        role = CustomRole(
            organization_id=organization_id,
            name=name,
            description=description,
            base_role=base_role,
            created_by_id=created_by_id,
        )
        db_session.add(role)
        await db_session.flush()

        for perm in permissions:
            db_session.add(
                CustomRolePermission(custom_role_id=role.id, permission=perm)
            )
        await db_session.flush()
        await db_session.refresh(role, ["permissions"])
        return role

    async def update_custom_role(
        self,
        db_session: AsyncSession,
        *,
        role: CustomRole,
        name: str | None,
        description: str | None,
        base_role: str | None,
        permissions: list[str] | None,
    ) -> CustomRole:
        if name is not None:
            role.name = name
        if description is not None:
            role.description = description
        if base_role is not None:
            role.base_role = base_role

        if permissions is not None:
            for existing_perm in list(role.permissions):
                await db_session.delete(existing_perm)
            await db_session.flush()

            for perm in permissions:
                db_session.add(
                    CustomRolePermission(custom_role_id=role.id, permission=perm)
                )

        await db_session.flush()
        await db_session.refresh(role, ["permissions"])
        return role

    async def delete_custom_role(
        self,
        db_session: AsyncSession,
        *,
        role: CustomRole,
    ) -> None:
        await db_session.delete(role)
        await db_session.flush()
