"""Admin endpoints for F354: Permission and Access Report.

GET /admin/permissions-access/summary — top-level risk-posture counters
GET /admin/permissions-access/charts  — users-by-role, access distribution,
                                         conflicts-by-resource-type, broad
                                         access users, failed access attempts
GET /admin/permissions-access/rows    — paginated/filterable access-row table
GET /admin/permissions-access/export  — CSV export of the filtered rows

This is a security/permissions surface, not a generic admin report: reads
require `security_center_view`, export requires `security_center_configure`
(same gating as `admin_conflicts.py` / `admin_access_debugger.py`), rather
than a bare owner/admin role check — this lets custom roles grant or
withhold report access independently of base role.

"Remove broad access" and "fix conflict" row actions reuse the existing
`/admin/permissions/resource-grants/{id}` DELETE and
`/admin/permissions/conflicts/{id}/status` PATCH endpoints directly from the
frontend (via each row's `grant_id`/`conflict_id`) — no new mutating endpoint
here. "Open access debugger" / "review user or resource permissions" are
pure frontend navigation.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_permission
from app.auth.models import AuthenticatedPrincipal
from app.db.session import get_db_session
from app.domains.permissions.schemas.permissions_access_report import (
    PermissionsAccessChartsResponse,
    PermissionsAccessRowListResponse,
    PermissionsAccessSummaryResponse,
)
from app.domains.permissions.services.permissions_access_report_service import (
    PermissionsAccessFilters,
    PermissionsAccessReportService,
)
from app.models.permissions import PermissionType

router = APIRouter(prefix="/admin/permissions-access", tags=["admin-permissions-access"])
_service = PermissionsAccessReportService()

_MAX_PAGE_SIZE = 200

_SecurityView = Annotated[
    AuthenticatedPrincipal,
    Depends(require_permission(PermissionType.security_center_view)),
]
_SecurityConfigure = Annotated[
    AuthenticatedPrincipal,
    Depends(require_permission(PermissionType.security_center_configure)),
]
_DB = Annotated[AsyncSession, Depends(get_db_session)]


def _org_id(principal: AuthenticatedPrincipal) -> UUID:
    if not principal.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="No active organization context"
        )
    try:
        return UUID(principal.organization_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Invalid organization context"
        ) from exc


def _parse_date(value: str | None) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Dates must be in YYYY-MM-DD format",
        ) from exc


def _build_filters(
    *,
    role: str | None,
    access_source: str | None,
    resource_type: str | None,
    conflict_status: str | None,
    search: str | None,
) -> PermissionsAccessFilters:
    return PermissionsAccessFilters(
        role=role,
        access_source=access_source,
        resource_type=resource_type,
        conflict_status=conflict_status,
        search=search,
    )


@router.get("/summary", response_model=PermissionsAccessSummaryResponse)
async def get_permissions_access_summary(
    principal: _SecurityView,
    db_session: _DB,
    from_date: Annotated[str | None, Query(alias="from")] = None,
    to_date: Annotated[str | None, Query(alias="to")] = None,
) -> PermissionsAccessSummaryResponse:
    return await _service.get_summary(
        db_session,
        organization_id=_org_id(principal),
        from_date=_parse_date(from_date),
        to_date=_parse_date(to_date),
    )


@router.get("/charts", response_model=PermissionsAccessChartsResponse)
async def get_permissions_access_charts(
    principal: _SecurityView,
    db_session: _DB,
    from_date: Annotated[str | None, Query(alias="from")] = None,
    to_date: Annotated[str | None, Query(alias="to")] = None,
) -> PermissionsAccessChartsResponse:
    return await _service.get_charts(
        db_session,
        organization_id=_org_id(principal),
        from_date=_parse_date(from_date),
        to_date=_parse_date(to_date),
    )


@router.get("/rows", response_model=PermissionsAccessRowListResponse)
async def list_permissions_access_rows(
    principal: _SecurityView,
    db_session: _DB,
    role: Annotated[str | None, Query()] = None,
    access_source: Annotated[str | None, Query()] = None,
    resource_type: Annotated[str | None, Query()] = None,
    conflict_status: Annotated[str | None, Query()] = None,
    search: Annotated[str | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=_MAX_PAGE_SIZE)] = 25,
) -> PermissionsAccessRowListResponse:
    filters = _build_filters(
        role=role,
        access_source=access_source,
        resource_type=resource_type,
        conflict_status=conflict_status,
        search=search,
    )
    return await _service.list_rows(
        db_session,
        organization_id=_org_id(principal),
        filters=filters,
        page=page,
        page_size=page_size,
    )


@router.get("/export")
async def export_permissions_access_report(
    principal: _SecurityConfigure,
    db_session: _DB,
    role: Annotated[str | None, Query()] = None,
    access_source: Annotated[str | None, Query()] = None,
    resource_type: Annotated[str | None, Query()] = None,
    conflict_status: Annotated[str | None, Query()] = None,
    search: Annotated[str | None, Query()] = None,
) -> Response:
    filters = _build_filters(
        role=role,
        access_source=access_source,
        resource_type=resource_type,
        conflict_status=conflict_status,
        search=search,
    )
    csv_content = await _service.build_export_csv(
        db_session, organization_id=_org_id(principal), filters=filters
    )
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=permissions-access-report.csv"},
    )
