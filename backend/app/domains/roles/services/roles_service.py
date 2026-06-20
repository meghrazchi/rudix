from __future__ import annotations

from app.domains.roles.schemas.roles import CustomRoleResponse
from app.models.custom_role import CustomRole


class RolesService:
    @staticmethod
    def to_custom_role_response(role: CustomRole) -> CustomRoleResponse:
        return CustomRoleResponse(
            id=str(role.id),
            organization_id=str(role.organization_id),
            name=role.name,
            description=role.description,
            base_role=role.base_role,
            permissions=sorted(perm.permission for perm in role.permissions),
            created_by_id=str(role.created_by_id) if role.created_by_id else None,
            created_at=role.created_at,
            updated_at=role.updated_at,
        )
