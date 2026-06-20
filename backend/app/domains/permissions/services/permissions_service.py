from __future__ import annotations

from app.domains.permissions.schemas.permissions import (
    ResourceAccessEntryResponse,
    RoleMatrixEntry,
    UpdateRolePermissionsResponse,
)
from app.domains.roles.schemas.roles import BUILTIN_ROLE_META
from app.models.authorization import ResourceAccessDeny, ResourceAccessGrant
from app.models.permissions import ROLE_PERMISSIONS

_SAFE_ADMIN_PERMISSIONS = frozenset({"roles:manage", "roles:view"})
_OWNER_ROLE = "owner"

# Permissions that must never be removed from the owner role.
_OWNER_REQUIRED_PERMISSIONS = frozenset(
    {
        "roles:manage",
        "team:manage",
    }
)


def _canonical_permissions(role_name: str) -> frozenset[str]:
    return ROLE_PERMISSIONS.get(role_name, frozenset())


def check_role_permission_safety(
    role_name: str,
    new_permissions: list[str],
    *,
    all_roles_current: dict[str, frozenset[str]],
) -> str | None:
    """Return an error message if the proposed change is unsafe, else None."""
    new_set = frozenset(new_permissions)

    if role_name == _OWNER_ROLE:
        owner_retains_admin_power = bool(_OWNER_REQUIRED_PERMISSIONS.intersection(new_set))
        if not owner_retains_admin_power:
            return (
                "Cannot remove required owner permissions: "
                f"{sorted(_OWNER_REQUIRED_PERMISSIONS)}. "
                "Owner must retain role or team management."
            )

    # Ensure at least one privileged role retains roles:manage so admins
    # can never lock themselves out.
    privileged_roles = {"owner", "admin"}
    updated = {**all_roles_current, role_name: new_set}
    can_manage_roles = any("roles:manage" in updated.get(r, frozenset()) for r in privileged_roles)
    if not can_manage_roles:
        return (
            "Unsafe change: no privileged role (owner/admin) would retain 'roles:manage'. "
            "At least one must keep this permission to prevent lockout."
        )

    return None


class PermissionsService:
    def build_role_matrix_entry(
        self,
        role_name: str,
        effective_permissions: frozenset[str],
        is_builtin: bool,
    ) -> RoleMatrixEntry:
        canonical = _canonical_permissions(role_name)
        overridden = sorted(canonical.symmetric_difference(effective_permissions))
        meta = BUILTIN_ROLE_META.get(
            role_name, {"label": role_name.replace("_", " ").title(), "description": ""}
        )
        return RoleMatrixEntry(
            role=role_name,
            label=meta["label"],
            description=meta["description"],
            is_builtin=is_builtin,
            permissions=sorted(effective_permissions),
            overridden_permissions=overridden,
        )

    def build_update_response(
        self,
        role_name: str,
        new_permissions: list[str],
    ) -> UpdateRolePermissionsResponse:
        canonical = _canonical_permissions(role_name)
        overridden = sorted(canonical.symmetric_difference(frozenset(new_permissions)))
        return UpdateRolePermissionsResponse(
            role=role_name,
            permissions=sorted(new_permissions),
            overridden_permissions=overridden,
        )

    def grant_to_response(self, grant: ResourceAccessGrant) -> ResourceAccessEntryResponse:
        return ResourceAccessEntryResponse(
            id=str(grant.id),
            organization_id=str(grant.organization_id),
            user_id=str(grant.user_id) if grant.user_id else None,
            role_name=grant.role_name,
            principal_type=grant.principal_type,
            principal_value=grant.principal_value,
            resource_type=grant.resource_type,
            resource_id=grant.resource_id,
            action=grant.action,
            status=grant.status,
            expires_at=grant.expires_at,
            reason=grant.reason,
            created_by_user_id=(
                str(grant.created_by_user_id) if grant.created_by_user_id else None
            ),
            created_at=grant.created_at,
            updated_at=grant.updated_at,
            kind="grant",
        )

    def deny_to_response(self, deny: ResourceAccessDeny) -> ResourceAccessEntryResponse:
        return ResourceAccessEntryResponse(
            id=str(deny.id),
            organization_id=str(deny.organization_id),
            user_id=str(deny.user_id) if deny.user_id else None,
            role_name=deny.role_name,
            principal_type=deny.principal_type,
            principal_value=deny.principal_value,
            resource_type=deny.resource_type,
            resource_id=deny.resource_id,
            action=deny.action,
            status=deny.status,
            expires_at=deny.expires_at,
            reason=deny.reason,
            created_by_user_id=(str(deny.created_by_user_id) if deny.created_by_user_id else None),
            created_at=deny.created_at,
            updated_at=deny.updated_at,
            kind="deny",
        )
