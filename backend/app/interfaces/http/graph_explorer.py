"""Member-facing Enterprise Graph explorer endpoints.

These routes expose read-only, organization-scoped graph discovery for the UI.
Neo4j downtime or disabled feature flags return a safe 503 so non-graph Rudix
features continue to work independently.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.auth.dependencies import require_permission
from app.auth.models import AuthenticatedPrincipal
from app.domains.graph.services.graph_service import GraphService
from app.models.permissions import PermissionType
from app.rate_limit import RateLimitScope, enforce_rate_limit

router = APIRouter(prefix="/graph", tags=["graph-explorer"])


def _graph_service() -> GraphService:
    return GraphService()


def _require_graph_available() -> None:
    if not _graph_service().is_available():
        raise HTTPException(
            status_code=503,
            detail="enterprise_graph_unavailable",
        )


class GraphEntitySearchItem(BaseModel):
    entity_id: str
    entity_type: str | None = None
    canonical_name: str
    normalized_name: str | None = None
    aliases: list[str] = Field(default_factory=list)
    alias_count: int = 0
    workspace_id: str | None = None
    external_source_id: str | None = None
    resolution_status: str | None = None
    resolution_confidence: float | None = None
    confidence: float | None = None
    last_updated_at: str | None = None
    evidence_count: int = 0
    related_document_count: int = 0


class GraphEntitySearchResponse(BaseModel):
    items: list[GraphEntitySearchItem]
    total: int
    skip: int
    limit: int
    query: str | None = None
    entity_type: str | None = None
    min_confidence: float | None = None
    source_document_id: str | None = None
    source_connector: str | None = None
    rel_type: str | None = None
    relationship_direction: str


class GraphAliasItem(BaseModel):
    alias_id: str
    entity_id: str
    alias_name: str
    normalized_name: str | None = None
    source_document_id: str | None = None
    chunk_id: str | None = None
    workspace_id: str | None = None
    source_external_id: str | None = None
    source_connector: str | None = None
    language: str | None = None
    confidence: float | None = None
    evidence_text: str | None = None
    page_number: int | None = None
    created_at: str | None = None
    updated_at: str | None = None


class GraphEvidenceItem(BaseModel):
    chunk_id: str
    source_document_id: str
    workspace_id: str | None = None
    document_version_id: str | None = None
    page_number: int | None = None
    source_connector: str | None = None
    external_url: str | None = None
    extraction_run_id: str | None = None
    confidence: float | None = None
    evidence_text: str | None = None
    citation_text: str | None = None
    citation_reference: str | None = None
    created_at: str | None = None


class GraphRelationItem(BaseModel):
    relation_id: str | None = None
    from_entity_id: str
    rel_type: str
    to_entity_id: str
    status: str | None = None
    confidence: float | None = None
    properties: dict[str, Any] = Field(default_factory=dict)


class GraphConnectedDocumentItem(BaseModel):
    document_id: str
    page_numbers: list[int] = Field(default_factory=list)
    evidence_count: int = 0
    max_confidence: float = 0.0
    source_connectors: list[str] = Field(default_factory=list)


class GraphConnectedEntityItem(BaseModel):
    entity_id: str
    entity_type: str | None = None
    canonical_name: str | None = None
    normalized_name: str | None = None
    relation_count: int = 0


class GraphEntityDetailResponse(BaseModel):
    entity: GraphEntitySearchItem
    aliases: list[GraphAliasItem]
    evidence: list[GraphEvidenceItem]
    relationships: list[GraphRelationItem]
    connected_documents: list[GraphConnectedDocumentItem]
    connected_entities: list[GraphConnectedEntityItem]
    summary: dict[str, int]


class DocumentGraphInsightEntityItem(BaseModel):
    entity_id: str
    entity_type: str | None = None
    canonical_name: str
    confidence: float | None = None
    evidence_count: int = 0


class DocumentGraphInsightEvidenceItem(BaseModel):
    chunk_id: str
    source_document_id: str
    page_number: int | None = None
    confidence: float | None = None
    evidence_text: str | None = None
    citation_text: str | None = None
    citation_reference: str | None = None
    extraction_run_id: str | None = None


class DocumentGraphInsightRunItem(BaseModel):
    run_id: str
    status: str
    strategy: str | None = None
    entity_count: int | None = None
    error: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class DocumentGraphInsightsResponse(BaseModel):
    entity_count: int = 0
    relation_count: int = 0
    avg_confidence: float | None = None
    entities_by_type: dict[str, int] = Field(default_factory=dict)
    top_entities: list[DocumentGraphInsightEntityItem] = Field(default_factory=list)
    recent_evidence: list[DocumentGraphInsightEvidenceItem] = Field(default_factory=list)
    extraction_runs: list[DocumentGraphInsightRunItem] = Field(default_factory=list)
    last_run_at: str | None = None


class GraphEntityTypeCountItem(BaseModel):
    entity_type: str
    count: int
    avg_confidence: float | None = None


class GraphStatsResponse(BaseModel):
    total_entities: int
    total_relations: int
    avg_confidence: float | None = None
    low_confidence_count: int
    entities_by_type: list[GraphEntityTypeCountItem]
    graph_available: bool


class GraphRelationshipListResponse(BaseModel):
    items: list[GraphRelationItem]
    total: int
    skip: int
    limit: int
    has_more: bool = False


class GraphNeighborItem(BaseModel):
    entity_id: str
    entity_type: str | None = None
    canonical_name: str | None = None
    normalized_name: str | None = None
    relation_count: int = 0
    confidence: float | None = None
    rel_type: str | None = None
    direction: str | None = None


RelationshipDirection = Literal["out", "in", "both"]
_Principal = Annotated[
    AuthenticatedPrincipal, Depends(require_permission(PermissionType.graph_view))
]
_RateLimit = Annotated[None, Depends(enforce_rate_limit(RateLimitScope.chat))]


@router.get("/entities", response_model=GraphEntitySearchResponse)
async def search_entities(
    principal: _Principal,
    _: _RateLimit,
    query: Annotated[str | None, Query(min_length=1)] = None,
    entity_type: Annotated[str | None, Query(min_length=1)] = None,
    min_confidence: Annotated[float | None, Query(ge=0.0, le=1.0)] = None,
    source_document_id: Annotated[str | None, Query(min_length=1)] = None,
    source_connector: Annotated[str | None, Query(min_length=1)] = None,
    rel_type: Annotated[str | None, Query(min_length=1)] = None,
    relationship_direction: Annotated[RelationshipDirection, Query()] = "both",
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 25,
) -> GraphEntitySearchResponse:
    """Search graph entities with safe org-scoped filters."""
    _require_graph_available()
    svc = _graph_service()
    result = await svc.search_entities(
        organization_id=principal.organization_id,
        query=query,
        entity_type=entity_type,
        min_confidence=min_confidence,
        source_document_id=source_document_id,
        source_connector=source_connector,
        rel_type=rel_type,
        relationship_direction=relationship_direction,
        skip=skip,
        limit=limit,
    )
    items = [GraphEntitySearchItem(**item) for item in result["items"]]
    return GraphEntitySearchResponse(
        items=items,
        total=int(result["total"]),
        skip=skip,
        limit=limit,
        query=query,
        entity_type=entity_type,
        min_confidence=min_confidence,
        source_document_id=source_document_id,
        source_connector=source_connector,
        rel_type=rel_type,
        relationship_direction=relationship_direction,
    )


@router.get("/entities/{entity_id}", response_model=GraphEntityDetailResponse)
async def get_entity_detail(
    entity_id: str,
    principal: _Principal,
    _: _RateLimit,
    rel_type: Annotated[str | None, Query(min_length=1)] = None,
    relationship_direction: Annotated[RelationshipDirection, Query()] = "both",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> GraphEntityDetailResponse:
    """Return entity details, relationships, and provenance for the explorer."""
    _require_graph_available()
    svc = _graph_service()
    detail = await svc.get_entity_detail(
        organization_id=principal.organization_id,
        entity_id=entity_id,
        rel_type=rel_type,
        relationship_direction=relationship_direction,
        limit=limit,
    )
    if detail is None:
        raise HTTPException(status_code=404, detail="entity_not_found")

    return GraphEntityDetailResponse(
        entity=GraphEntitySearchItem(**detail["entity"]),
        aliases=[GraphAliasItem(**item) for item in detail["aliases"]],
        evidence=[GraphEvidenceItem(**item) for item in detail["evidence"]],
        relationships=[GraphRelationItem(**item) for item in detail["relationships"]],
        connected_documents=[
            GraphConnectedDocumentItem(**item) for item in detail["connected_documents"]
        ],
        connected_entities=[
            GraphConnectedEntityItem(**item) for item in detail["connected_entities"]
        ],
        summary=dict(detail["summary"]),
    )


@router.get("/documents/{document_id}/insights", response_model=DocumentGraphInsightsResponse)
async def get_document_graph_insights(
    document_id: str,
    principal: _Principal,
    _: _RateLimit,
) -> DocumentGraphInsightsResponse:
    """Return graph facts extracted from a document for the Insights panel (F289).

    Returns a safe 503 when Enterprise Graph is disabled or Neo4j is
    unreachable so the document details page degrades gracefully.
    """
    _require_graph_available()
    svc = _graph_service()
    data = await svc.get_document_insights(
        organization_id=principal.organization_id,
        document_id=document_id,
    )

    top_entities = [
        DocumentGraphInsightEntityItem(
            entity_id=str(item.get("entity_id") or ""),
            entity_type=item.get("entity_type"),
            canonical_name=str(item.get("canonical_name") or ""),
            confidence=item.get("confidence"),
            evidence_count=int(item.get("evidence_count") or 0),
        )
        for item in (data.get("top_entities") or [])
    ]
    recent_evidence = [
        DocumentGraphInsightEvidenceItem(
            chunk_id=str(item.get("chunk_id") or ""),
            source_document_id=str(item.get("source_document_id") or ""),
            page_number=item.get("page_number"),
            confidence=item.get("confidence"),
            evidence_text=item.get("evidence_text"),
            citation_text=item.get("citation_text"),
            citation_reference=item.get("citation_reference"),
            extraction_run_id=item.get("extraction_run_id"),
        )
        for item in (data.get("recent_evidence") or [])
    ]
    extraction_runs = [
        DocumentGraphInsightRunItem(
            run_id=str(run.get("run_id") or ""),
            status=str(run.get("status") or "unknown"),
            strategy=run.get("strategy"),
            entity_count=run.get("entity_count"),
            error=run.get("error"),
            created_at=run.get("created_at"),
            updated_at=run.get("updated_at"),
        )
        for run in (data.get("extraction_runs") or [])
    ]
    return DocumentGraphInsightsResponse(
        entity_count=int(data.get("entity_count") or 0),
        relation_count=int(data.get("relation_count") or 0),
        avg_confidence=data.get("avg_confidence"),
        entities_by_type=dict(data.get("entities_by_type") or {}),
        top_entities=top_entities,
        recent_evidence=recent_evidence,
        extraction_runs=extraction_runs,
        last_run_at=data.get("last_run_at"),
    )


@router.get("/stats", response_model=GraphStatsResponse)
async def get_graph_stats(
    principal: _Principal,
    _: _RateLimit,
) -> GraphStatsResponse:
    """Return org-level graph statistics for the explorer overview panel (F269).

    Always returns a valid response — `graph_available=false` when Neo4j is
    unreachable so the UI can show an empty state rather than an error.
    """
    svc = _graph_service()
    data = await svc.get_graph_stats(organization_id=principal.organization_id)
    return GraphStatsResponse(
        total_entities=data["total_entities"],
        total_relations=data["total_relations"],
        avg_confidence=data.get("avg_confidence"),
        low_confidence_count=data["low_confidence_count"],
        entities_by_type=[GraphEntityTypeCountItem(**item) for item in data["entities_by_type"]],
        graph_available=data["graph_available"],
    )


@router.get("/relationships", response_model=GraphRelationshipListResponse)
async def list_relationships(
    principal: _Principal,
    _: _RateLimit,
    rel_type: Annotated[str | None, Query(min_length=1)] = None,
    min_confidence: Annotated[float | None, Query(ge=0.0, le=1.0)] = None,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 25,
) -> GraphRelationshipListResponse:
    """List org-scoped relationships for the explorer relationships tab (F269)."""
    _require_graph_available()
    svc = _graph_service()
    result = await svc.list_user_relationships(
        organization_id=principal.organization_id,
        rel_type=rel_type,
        min_confidence=min_confidence,
        skip=skip,
        limit=limit,
    )
    return GraphRelationshipListResponse(
        items=[GraphRelationItem(**item) for item in result["items"]],
        total=int(result["total"]),
        skip=skip,
        limit=limit,
        has_more=bool(result.get("has_more", False)),
    )


@router.get("/entities/{entity_id}/neighbors", response_model=list[GraphNeighborItem])
async def get_entity_neighbors(
    entity_id: str,
    principal: _Principal,
    _: _RateLimit,
    depth: Annotated[int, Query(ge=1, le=5)] = 2,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    rel_type: Annotated[str | None, Query(min_length=1)] = None,
) -> list[GraphNeighborItem]:
    """Return multi-hop neighbors of an entity for the interactive graph explorer (F269)."""
    _require_graph_available()
    svc = _graph_service()
    neighbors = await svc.get_entity_neighbors(
        organization_id=principal.organization_id,
        entity_id=entity_id,
        depth=depth,
        limit=limit,
        relationship_types=[rel_type] if rel_type else None,
    )
    return [GraphNeighborItem(**item) for item in neighbors]
