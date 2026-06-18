from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.models.authorization import AUTHORIZATION_ACTIONS, GRANT_STATUSES, PRINCIPAL_TYPES
from app.models.permissions import PERMISSION_CATALOG

_VALID_PERMISSIONS = {entry["permission"] for entry in PERMISSION_CATALOG}
_VALID_ACTIONS = set(AUTHORIZATION_ACTIONS)
_VALID_PRINCIPAL_TYPES = set(PRINCIPAL_TYPES)
_VALID_GRANT_STATUSES = set(GRANT_STATUSES)


# ── Role matrix ────────────────────────────────────────────────────────────────

class RoleMatrixEntry(BaseModel):
    role: str
    label: str
    description: str
    is_builtin: bool
    permissions: list[str]
    overridden_permissions: list[str]  # permissions that differ from canonical defaults


class RoleMatrixResponse(BaseModel):
    roles: list[RoleMatrixEntry]
    all_permissions: list[str]


class UpdateRolePermissionsRequest(BaseModel):
    permissions: list[str] = Field(min_length=0)


class UpdateRolePermissionsResponse(BaseModel):
    role: str
    permissions: list[str]
    overridden_permissions: list[str]


# ── Resource access grants / denies ───────────────────────────────────────────

class ResourceAccessEntryResponse(BaseModel):
    id: str
    organization_id: str
    user_id: str | None
    role_name: str | None
    principal_type: str
    principal_value: str
    resource_type: str
    resource_id: str | None
    action: str
    status: str
    expires_at: datetime | None
    reason: str | None
    created_by_user_id: str | None
    created_at: datetime
    updated_at: datetime
    kind: str  # "grant" or "deny"


class ResourceAccessListResponse(BaseModel):
    items: list[ResourceAccessEntryResponse]
    total: int
    page: int
    page_size: int


class CreateResourceAccessRequest(BaseModel):
    principal_type: str = Field(pattern=r"^(user|team|group|role)$")
    principal_value: str = Field(min_length=1, max_length=255)
    resource_type: str = Field(min_length=1, max_length=128)
    resource_id: str | None = Field(default=None, max_length=255)
    action: str = Field(pattern=r"^(read_only|manage|sync|export|evaluate|cite|search)$")
    expires_at: datetime | None = None
    reason: str | None = Field(default=None, max_length=1024)
