"""Response schemas for the F354 Permission and Access Report.

Plain Pydantic models, no ORM coupling — mirrors the style of
`app/domains/admin/schemas/usage_adoption.py` (F353). Severity/remediation
concepts are re-exported from `app.domains.permissions.schemas.conflicts`
rather than duplicated.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class PermissionsAccessSummaryResponse(BaseModel):
    total_users: int
    admin_users: int
    external_users: int
    external_users_is_heuristic: bool
    broad_access_users: int
    permission_conflicts_open: int
    orphaned_grants: int
    expired_active_grants: int
    connector_acl_mismatches: int
    resources_without_owner: int
    unauthorized_access_attempts: int
    generated_at: datetime


class RoleCountRow(BaseModel):
    role: str
    count: int


class AccessSourceCountRow(BaseModel):
    access_source: str
    count: int


class ResourceTypeCountRow(BaseModel):
    resource_type: str
    count: int


class BroadAccessUserRow(BaseModel):
    user_id: str
    name: str
    email: str
    role: str
    reason: str


class FailedAccessAttemptPoint(BaseModel):
    date: str
    count: int


class PermissionsAccessChartsResponse(BaseModel):
    users_by_role: list[RoleCountRow]
    access_distribution: list[AccessSourceCountRow]
    conflicts_by_resource_type: list[ResourceTypeCountRow]
    broad_access_users: list[BroadAccessUserRow]
    failed_access_attempts: list[FailedAccessAttemptPoint]
    generated_at: datetime


class PermissionsAccessRowResponse(BaseModel):
    id: str
    user_id: str | None
    user_name: str | None
    user_email: str | None
    role: str | None
    team: str | None
    resource_id: str | None
    resource_type: str
    resource_label: str | None
    access_level: str
    access_source: str
    conflict_status: str | None
    last_access: datetime | None
    grant_id: str | None
    conflict_id: str | None


class PermissionsAccessRowListResponse(BaseModel):
    items: list[PermissionsAccessRowResponse]
    total: int
    page: int
    page_size: int
