"""Admin source health dashboard endpoints (F352).

GET /admin/source-health/summary  — top-level health metric counters
GET /admin/source-health/charts   — status distribution, indexing failures,
                                     stale-by-collection, OCR quality,
                                     review-needs-by-owner, connector freshness
GET /admin/source-health/sources  — filterable, paginated source table
GET /admin/source-health/sources/{source_type}/{source_id}/error — error detail
GET /admin/source-health/export   — CSV export of the filtered source table

All mutating actions (re-index, OCR retry, assign reviewer, mark
verified/deprecated) reuse existing endpoints in `documents.py`,
`admin_documents.py`, and `collections.py` rather than being duplicated here
— this router is read-only aggregation.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.db.session import get_db_session
from app.domains.admin.schemas.source_health import (
    SourceHealthChartsResponse,
    SourceHealthErrorDetailResponse,
    SourceHealthListResponse,
    SourceHealthSummaryResponse,
)
from app.domains.admin.services.source_health_service import (
    SourceHealthFilters,
    SourceHealthService,
)
from app.models.enums import OrganizationRole
from app.rate_limit import RateLimitScope, enforce_rate_limit

router = APIRouter(prefix="/admin/source-health", tags=["admin-source-health"])
_service = SourceHealthService()

_VALID_SOURCE_TYPES = frozenset({"file", "connector", "collection"})
_MAX_PAGE_SIZE = 200

_AdminRoles = Annotated[
    AuthenticatedPrincipal,
    Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
]
_RateLimit = Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))]
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


def _validate_source_type(value: str | None) -> str | None:
    if value is not None and value not in _VALID_SOURCE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"source_type must be one of: {sorted(_VALID_SOURCE_TYPES)}",
        )
    return value


def _build_filters(
    *,
    source_type: str | None,
    status_filter: str | None,
    collection_id: str | None,
    owner_id: str | None,
    freshness: str | None,
    review_status: str | None,
    ocr_quality: str | None,
    graph_indexed: str | None,
    missing_metadata: bool | None,
    q: str | None,
) -> SourceHealthFilters:
    return SourceHealthFilters(
        source_type=_validate_source_type(source_type),
        status=status_filter,
        collection_id=collection_id,
        owner_id=owner_id,
        freshness=freshness,
        review_status=review_status,
        ocr_quality=ocr_quality,
        graph_indexed=graph_indexed,
        missing_metadata=missing_metadata,
        q=q,
    )


@router.get("/summary", response_model=SourceHealthSummaryResponse)
async def get_source_health_summary(
    principal: _AdminRoles,
    _: _RateLimit,
    db_session: _DB,
) -> SourceHealthSummaryResponse:
    return await _service.get_summary(db_session, organization_id=_org_id(principal))


@router.get("/charts", response_model=SourceHealthChartsResponse)
async def get_source_health_charts(
    principal: _AdminRoles,
    _: _RateLimit,
    db_session: _DB,
) -> SourceHealthChartsResponse:
    return await _service.get_charts(db_session, organization_id=_org_id(principal))


@router.get("/sources", response_model=SourceHealthListResponse)
async def list_source_health(
    principal: _AdminRoles,
    _: _RateLimit,
    db_session: _DB,
    source_type: Annotated[str | None, Query()] = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    collection_id: Annotated[str | None, Query()] = None,
    owner_id: Annotated[str | None, Query()] = None,
    freshness: Annotated[str | None, Query()] = None,
    review_status: Annotated[str | None, Query()] = None,
    ocr_quality: Annotated[str | None, Query()] = None,
    graph_indexed: Annotated[str | None, Query()] = None,
    missing_metadata: Annotated[bool | None, Query()] = None,
    q: Annotated[str | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=_MAX_PAGE_SIZE)] = 25,
) -> SourceHealthListResponse:
    filters = _build_filters(
        source_type=source_type,
        status_filter=status_filter,
        collection_id=collection_id,
        owner_id=owner_id,
        freshness=freshness,
        review_status=review_status,
        ocr_quality=ocr_quality,
        graph_indexed=graph_indexed,
        missing_metadata=missing_metadata,
        q=q,
    )
    return await _service.list_sources(
        db_session,
        organization_id=_org_id(principal),
        filters=filters,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/sources/{source_type}/{source_id}/error",
    response_model=SourceHealthErrorDetailResponse,
)
async def get_source_health_error(
    source_type: str,
    source_id: str,
    principal: _AdminRoles,
    _: _RateLimit,
    db_session: _DB,
) -> SourceHealthErrorDetailResponse:
    _validate_source_type(source_type)
    try:
        source_uuid = UUID(source_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid source_id format",
        ) from exc

    detail = await _service.get_error_detail(
        db_session,
        organization_id=_org_id(principal),
        source_type=source_type,
        source_id=source_uuid,
    )
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")
    return detail


@router.get("/export")
async def export_source_health(
    principal: _AdminRoles,
    _: _RateLimit,
    db_session: _DB,
    source_type: Annotated[str | None, Query()] = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    collection_id: Annotated[str | None, Query()] = None,
    owner_id: Annotated[str | None, Query()] = None,
    freshness: Annotated[str | None, Query()] = None,
    review_status: Annotated[str | None, Query()] = None,
    ocr_quality: Annotated[str | None, Query()] = None,
    graph_indexed: Annotated[str | None, Query()] = None,
    missing_metadata: Annotated[bool | None, Query()] = None,
    q: Annotated[str | None, Query()] = None,
) -> Response:
    filters = _build_filters(
        source_type=source_type,
        status_filter=status_filter,
        collection_id=collection_id,
        owner_id=owner_id,
        freshness=freshness,
        review_status=review_status,
        ocr_quality=ocr_quality,
        graph_indexed=graph_indexed,
        missing_metadata=missing_metadata,
        q=q,
    )
    csv_content = await _service.build_export_csv(
        db_session, organization_id=_org_id(principal), filters=filters
    )
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=source-health.csv"},
    )
