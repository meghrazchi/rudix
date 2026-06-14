"""Member-facing Enterprise Graph explorer endpoints.

These routes expose read-only, organization-scoped graph discovery for the UI.
Neo4j downtime or disabled feature flags return a safe 503 so non-graph Rudix
features continue to work independently.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.auth.dependencies import get_current_principal
from app.auth.models import AuthenticatedPrincipal
from app.domains.graph.services.graph_service import GraphService
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


RelationshipDirection = Literal["out", "in", "both"]
_Principal = Annotated[AuthenticatedPrincipal, Depends(get_current_principal)]
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
