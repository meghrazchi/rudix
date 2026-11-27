from __future__ import annotations

from uuid import UUID

from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import NAMESPACE_PERMISSION_SET, OrgScope, get_or_load
from app.core.config import settings
from app.models.custom_role import CustomRole, CustomRolePermission
from app.models.permissions import ROLE_PERMISSIONS

_PERMISSION_LIST_ADAPTER: TypeAdapter[list[str]] = TypeAdapter(list[str])


class PermissionService:
    async def get_user_permissions(
        self,
        db_session: AsyncSession,
        *,
        roles: list[str],
        custom_role_id: UUID | None = None,
        organization_id: UUID | None = None,
    ) -> frozenset[str]:
        """Built-in role permissions plus the custom role's (and its base role's).

        With ``organization_id`` the custom-role part is cached per (organisation, custom
        role) under the organisation scope (R04-05); a custom role belongs to exactly one
        organisation, so the key never serves another organisation's role.
        """
        permissions: set[str] = set()

        for role in roles:
            perms = ROLE_PERMISSIONS.get(role)
            if perms:
                permissions.update(perms)

        if custom_role_id is not None:
            role_id: UUID = custom_role_id
            if organization_id is None:
                permissions.update(await self._load_custom_role_permissions(db_session, role_id))
            else:
                cached: list[str] = await get_or_load(
                    scope=OrgScope(organization_id),
                    namespace=NAMESPACE_PERMISSION_SET,
                    key_id=str(role_id),
                    ttl=settings.cache_ttl_permissions_seconds,
                    adapter=_PERMISSION_LIST_ADAPTER,
                    loader=lambda: self._load_custom_role_permissions(db_session, role_id),
                )
                permissions.update(cached)

        return frozenset(permissions)

    @staticmethod
    async def _load_custom_role_permissions(
        db_session: AsyncSession, custom_role_id: UUID
    ) -> list[str]:
        permissions: set[str] = set()
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
        return sorted(permissions)

    def get_builtin_permissions(self, roles: list[str]) -> frozenset[str]:
        permissions: set[str] = set()
        for role in roles:
            perms = ROLE_PERMISSIONS.get(role)
            if perms:
                permissions.update(perms)
        return frozenset(permissions)
