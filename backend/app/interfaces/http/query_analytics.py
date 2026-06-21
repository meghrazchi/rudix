from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.db.session import get_db_session
from app.domains.query_analytics.schemas.query_analytics import (
    ConvertKnowledgeGapRequest,
    ConvertKnowledgeGapResponse,
    CreateKnowledgeGapRequest,
    DetectGapsRequest,
    DetectGapsResponse,
    KnowledgeGapListResponse,
    KnowledgeGapResponse,
    QueryAnalyticsSummaryResponse,
    QueryTrendsResponse,
    UpdateKnowledgeGapRequest,
)
from app.domains.query_analytics.services.query_analytics_service import QueryAnalyticsService
from app.models.enums import OrganizationRole
from app.rate_limit import RateLimitScope, enforce_rate_limit

router = APIRouter(prefix="/admin/query-analytics", tags=["query-analytics"])
_service = QueryAnalyticsService()


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


_AdminRoles = Annotated[
    AuthenticatedPrincipal,
    Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
]
_RateLimit = Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))]
_DB = Annotated[AsyncSession, Depends(get_db_session)]


@router.get("/summary", response_model=QueryAnalyticsSummaryResponse)
async def get_summary(
    principal: _AdminRoles,
    _: _RateLimit,
    db_session: _DB,
    from_date: Annotated[date | None, Query(alias="from")] = None,
    to_date: Annotated[date | None, Query(alias="to")] = None,
) -> QueryAnalyticsSummaryResponse:
    org_id = _org_id(principal)
    return await _service.build_summary(
        db_session, organization_id=org_id, from_date=from_date, to_date=to_date
    )


@router.get("/trends", response_model=QueryTrendsResponse)
async def get_trends(
    principal: _AdminRoles,
    _: _RateLimit,
    db_session: _DB,
    from_date: Annotated[date | None, Query(alias="from")] = None,
    to_date: Annotated[date | None, Query(alias="to")] = None,
) -> QueryTrendsResponse:
    org_id = _org_id(principal)
    return await _service.build_trends(
        db_session, organization_id=org_id, from_date=from_date, to_date=to_date
    )


@router.get("/export")
async def export_csv(
    principal: _AdminRoles,
    _: _RateLimit,
    db_session: _DB,
    from_date: Annotated[date | None, Query(alias="from")] = None,
    to_date: Annotated[date | None, Query(alias="to")] = None,
) -> Response:
    org_id = _org_id(principal)
    csv_content = await _service.build_export_csv(
        db_session, organization_id=org_id, from_date=from_date, to_date=to_date
    )
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=query-analytics.csv"},
    )


@router.get("/gaps", response_model=KnowledgeGapListResponse)
async def list_gaps(
    principal: _AdminRoles,
    _: _RateLimit,
    db_session: _DB,
    gap_status: Annotated[str | None, Query(alias="status")] = None,
    gap_type: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> KnowledgeGapListResponse:
    org_id = _org_id(principal)
    return await _service.list_gaps(
        db_session,
        organization_id=org_id,
        status=gap_status,
        gap_type=gap_type,
        limit=limit,
        offset=offset,
    )


@router.post("/gaps", response_model=KnowledgeGapResponse, status_code=status.HTTP_201_CREATED)
async def create_gap(
    principal: _AdminRoles,
    _: _RateLimit,
    db_session: _DB,
    body: CreateKnowledgeGapRequest,
) -> KnowledgeGapResponse:
    org_id = _org_id(principal)
    collection_id = UUID(body.collection_id) if body.collection_id else None
    gap = await _service.create_gap(
        db_session,
        organization_id=org_id,
        gap_type=body.gap_type,
        topic_label=body.topic_label,
        description=body.description,
        occurrence_count=body.occurrence_count,
        avg_confidence=body.avg_confidence,
        example_query=body.example_query,
        collection_id=collection_id,
        gap_source=body.gap_source,
    )
    await db_session.commit()
    return gap


@router.patch("/gaps/{gap_id}", response_model=KnowledgeGapResponse)
async def update_gap(
    gap_id: UUID,
    principal: _AdminRoles,
    _: _RateLimit,
    db_session: _DB,
    body: UpdateKnowledgeGapRequest,
) -> KnowledgeGapResponse:
    org_id = _org_id(principal)
    linked_doc_id = UUID(body.linked_document_id) if body.linked_document_id else None
    result = await _service.update_gap(
        db_session,
        organization_id=org_id,
        gap_id=gap_id,
        status=body.status,
        reviewer_notes=body.reviewer_notes,
        linked_document_id=linked_doc_id,
        description=body.description,
    )
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge gap not found")
    await db_session.commit()
    return result


@router.post("/gaps/{gap_id}/convert", response_model=ConvertKnowledgeGapResponse)
async def convert_gap(
    gap_id: UUID,
    principal: _AdminRoles,
    _: _RateLimit,
    db_session: _DB,
    body: ConvertKnowledgeGapRequest,
) -> ConvertKnowledgeGapResponse:
    org_id = _org_id(principal)
    result = await _service.convert_gap(
        db_session,
        organization_id=org_id,
        gap_id=gap_id,
        target=body.target,
        notes=body.notes,
    )
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge gap not found")
    await db_session.commit()
    return result


@router.post("/gaps/detect", response_model=DetectGapsResponse)
async def detect_gaps(
    principal: _AdminRoles,
    _: _RateLimit,
    db_session: _DB,
    body: DetectGapsRequest,
) -> DetectGapsResponse:
    org_id = _org_id(principal)
    result = await _service.detect_gaps(
        db_session,
        organization_id=org_id,
        from_date=body.from_date,
        to_date=body.to_date,
        low_confidence_threshold=body.low_confidence_threshold,
        min_occurrences=body.min_occurrences,
    )
    await db_session.commit()
    return result
