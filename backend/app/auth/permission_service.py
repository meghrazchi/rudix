from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.custom_role import CustomRole, CustomRolePermission
from app.models.permissions import ROLE_PERMISSIONS


class PermissionService:
    async def get_user_permissions(
        self,
        db_session: AsyncSession,
        *,
        roles: list[str],
        custom_role_id: UUID | None = None,
    ) -> frozenset[str]:
        permissions: set[str] = set()

        for role in roles:
            perms = ROLE_PERMISSIONS.get(role)
            if perms:
                permissions.update(perms)

        if custom_role_id is not None:
            result = await db_session.execute(
                select(CustomRolePermission.permission).where(
                    CustomRolePermission.custom_role_id == custom_role_id
                )
            )
            for row in result.scalars():
                permissions.add(row)

            custom_role_result = await db_session.execute(
                select(CustomRole.base_role).where(CustomRole.id == custom_role_id)
            )
            base_role = custom_role_result.scalar_one_or_none()
            if base_role:
                base_perms = ROLE_PERMISSIONS.get(base_role)
                if base_perms:
                    permissions.update(base_perms)

        return frozenset(permissions)

    def get_builtin_permissions(self, roles: list[str]) -> frozenset[str]:
        permissions: set[str] = set()
        for role in roles:
            perms = ROLE_PERMISSIONS.get(role)
            if perms:
                permissions.update(perms)
        return frozenset(permissions)
