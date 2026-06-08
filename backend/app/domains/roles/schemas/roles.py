from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.models.enums import OrganizationRole
from app.models.permissions import PERMISSION_CATALOG, ROLE_PERMISSIONS

_ALL_VALID_PERMISSIONS = {entry["permission"] for entry in PERMISSION_CATALOG}
_ALL_ROLE_VALUES = {r.value for r in OrganizationRole}


class PermissionEntry(BaseModel):
    permission: str
    category: str
    description: str


class PermissionCatalogResponse(BaseModel):
    items: list[PermissionEntry]
    total: int


class BuiltinRoleResponse(BaseModel):
    role: str
    label: str
    description: str
    permissions: list[str]
    is_builtin: bool = True


class CustomRoleResponse(BaseModel):
    id: str
    organization_id: str
    name: str
    description: str | None
    base_role: str | None
    permissions: list[str]
    created_by_id: str | None
    created_at: datetime
    updated_at: datetime
    is_builtin: bool = False


class RoleListResponse(BaseModel):
    builtin_roles: list[BuiltinRoleResponse]
    custom_roles: list[CustomRoleResponse]


class CreateCustomRoleRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=512)
    base_role: str | None = None
    permissions: list[str] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("name must not be blank")
        if stripped.lower() in _ALL_ROLE_VALUES:
            raise ValueError("name conflicts with a built-in role name")
        return stripped

    @field_validator("base_role")
    @classmethod
    def validate_base_role(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value not in _ALL_ROLE_VALUES:
            raise ValueError(f"base_role must be one of {sorted(_ALL_ROLE_VALUES)}")
        return value

    @field_validator("permissions")
    @classmethod
    def validate_permissions(cls, values: list[str]) -> list[str]:
        unknown = [p for p in values if p not in _ALL_VALID_PERMISSIONS]
        if unknown:
            raise ValueError(f"unknown permissions: {unknown}")
        return list(dict.fromkeys(values))  # deduplicate, preserve order


class UpdateCustomRoleRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    description: str | None = None
    base_role: str | None = None
    permissions: list[str] | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("name must not be blank")
        if stripped.lower() in _ALL_ROLE_VALUES:
            raise ValueError("name conflicts with a built-in role name")
        return stripped

    @field_validator("base_role")
    @classmethod
    def validate_base_role(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value not in _ALL_ROLE_VALUES:
            raise ValueError(f"base_role must be one of {sorted(_ALL_ROLE_VALUES)}")
        return value

    @field_validator("permissions")
    @classmethod
    def validate_permissions(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        unknown = [p for p in values if p not in _ALL_VALID_PERMISSIONS]
        if unknown:
            raise ValueError(f"unknown permissions: {unknown}")
        return list(dict.fromkeys(values))


# Descriptions shown in the UI for each built-in role.
BUILTIN_ROLE_META: dict[str, dict[str, str]] = {
    "owner": {
        "label": "Owner",
        "description": "Full access to all features including billing and role management. Cannot be changed.",
    },
    "admin": {
        "label": "Admin",
        "description": "Full access except billing. Can manage team, roles, security, and all content.",
    },
    "member": {
        "label": "Member",
        "description": "Can upload documents, use chat, and view collections.",
    },
    "viewer": {
        "label": "Viewer",
        "description": "Read-only access to documents, collections, and chat.",
    },
    "reviewer": {
        "label": "Reviewer",
        "description": "Can create and run evaluations and view audit logs in addition to viewer access.",
    },
    "developer": {
        "label": "Developer",
        "description": "Can manage API keys, webhooks, and create agents in addition to member access.",
    },
    "security_admin": {
        "label": "Security Admin",
        "description": "Dedicated security role: can configure SSO/SCIM, view audit logs, and manage security policies.",
    },
    "billing_admin": {
        "label": "Billing Admin",
        "description": "Dedicated billing role: can view and manage billing without access to content.",
    },
}


def builtin_roles_response() -> list[BuiltinRoleResponse]:
    result = []
    for role in OrganizationRole:
        meta = BUILTIN_ROLE_META.get(role.value, {"label": role.value.title(), "description": ""})
        perms = sorted(ROLE_PERMISSIONS.get(role.value, frozenset()))
        result.append(
            BuiltinRoleResponse(
                role=role.value,
                label=meta["label"],
                description=meta["description"],
                permissions=perms,
            )
        )
    return result
