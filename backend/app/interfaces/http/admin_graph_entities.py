"""Admin HTTP endpoints for Enterprise Graph entity management (F281).

No Cypher appears in this module — all graph operations are delegated to
GraphService which composes the repository layer.

Routes:
  GET  /admin/graph/entities                           — list entities in org
  POST /admin/graph/entities                           — upsert entity
  GET  /admin/graph/entities/{entity_id}               — get entity
  DELETE /admin/graph/entities/{entity_id}             — delete entity
  GET  /admin/graph/entities/{entity_id}/aliases       — entity aliases
  GET  /admin/graph/entities/{entity_id}/evidence      — entity evidence links
  GET  /admin/graph/entities/{entity_id}/relations     — entity relationships
  GET  /admin/graph/entity-resolution/candidates       — review candidates
  POST /admin/graph/entity-resolution/merge            — record merge decision
  POST /admin/graph/entity-resolution/split            — record split decision
  GET  /admin/graph/documents/{document_id}/extraction-runs — extraction run history

Auth: owner/admin only.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.core.config import settings
from app.domains.graph.repositories.relation_repository import RELATIONSHIP_TYPES
from app.domains.graph.services.graph_service import GraphService
from app.models.enums import OrganizationRole
from app.rate_limit import RateLimitScope, enforce_rate_limit

router = APIRouter(prefix="/admin/graph", tags=["admin-graph"])


def _require_graph_enabled() -> None:
    if not settings.enterprise_graph_enabled:
        raise HTTPException(status_code=503, detail="enterprise_graph_disabled")


def _graph_service() -> GraphService:
    return GraphService()


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class UpsertEntityRequest(BaseModel):
    entity_id: str = Field(..., min_length=1)
    entity_type: str = Field(..., min_length=1)
    canonical_name: str = Field(..., min_length=1)
    workspace_id: str | None = None
    external_source_id: str | None = None
    properties: dict[str, Any] | None = None


class EntityResponse(BaseModel):
    entity_id: str
    entity_type: str
    canonical_name: str
    organization_id: str
    workspace_id: str | None = None
    external_source_id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class EntityAliasItem(BaseModel):
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


class EntityAliasListResponse(BaseModel):
    entity_id: str
    items: list[EntityAliasItem]


class EntityResolutionCandidateItem(BaseModel):
    entity_id: str
    entity_type: str
    canonical_name: str
    normalized_name: str | None = None
    external_source_id: str | None = None
    resolution_status: str | None = None
    resolution_confidence: float | None = None
    aliases: list[str] = Field(default_factory=list)
    alias_normalized_names: list[str] = Field(default_factory=list)
    alias_count: int = 0


class EntityResolutionCandidateListResponse(BaseModel):
    items: list[EntityResolutionCandidateItem]


class EntityMergeDecisionRequest(BaseModel):
    target_entity_id: str = Field(..., min_length=1)
    source_entity_ids: list[str] = Field(default_factory=list, min_length=1)
    reason: str | None = None
    reviewer_id: str | None = None


class EntitySplitDecisionRequest(BaseModel):
    target_entity_id: str = Field(..., min_length=1)
    source_entity_ids: list[str] = Field(default_factory=list, min_length=1)
    reason: str | None = None
    reviewer_id: str | None = None


class EntityDecisionResponse(BaseModel):
    decision_id: str
    decision_kind: str
    target_entity_id: str
    source_entity_ids: list[str]
    reason: str | None = None
    reviewer_id: str | None = None


class EntityListResponse(BaseModel):
    items: list[dict[str, Any]]
    total: int


class EvidenceItem(BaseModel):
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


class EvidenceListResponse(BaseModel):
    entity_id: str
    items: list[EvidenceItem]


class RelationItem(BaseModel):
    from_entity_id: str
    rel_type: str
    to_entity_id: str
    properties: dict[str, Any]


class RelationListResponse(BaseModel):
    entity_id: str
    items: list[RelationItem]


class ExtractionRunItem(BaseModel):
    run_id: str
    document_id: str
    strategy: str
    status: str
    entity_count: int | None = None
    error: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class ExtractionRunListResponse(BaseModel):
    document_id: str
    items: list[ExtractionRunItem]


class DeleteResponse(BaseModel):
    deleted: bool


# ---------------------------------------------------------------------------
# Dependency alias
# ---------------------------------------------------------------------------

_AdminPrincipal = Annotated[
    AuthenticatedPrincipal,
    Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
]
_RateLimit = Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))]


# ---------------------------------------------------------------------------
# Entity endpoints
# ---------------------------------------------------------------------------


@router.get("/entities", response_model=EntityListResponse)
async def list_entities(
    principal: _AdminPrincipal,
    _: _RateLimit,
    workspace_id: str | None = Query(default=None),
    entity_type: str | None = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> EntityListResponse:
    """List graph entities scoped to the caller's organization."""
    _require_graph_enabled()
    svc = _graph_service()
    items = await svc.list_entities(
        organization_id=principal.organization_id,
        workspace_id=workspace_id,
        entity_type=entity_type,
        skip=skip,
        limit=limit,
    )
    return EntityListResponse(items=items, total=len(items))


@router.post("/entities", response_model=dict)
async def upsert_entity(
    body: UpsertEntityRequest,
    principal: _AdminPrincipal,
    _: _RateLimit,
) -> dict:
    """Create or update a graph entity in the caller's organization."""
    _require_graph_enabled()
    svc = _graph_service()
    await svc.upsert_entity(
        organization_id=principal.organization_id,
        entity_id=body.entity_id,
        entity_type=body.entity_type,
        canonical_name=body.canonical_name,
        workspace_id=body.workspace_id,
        external_source_id=body.external_source_id,
        properties=body.properties,
    )
    entity = await svc.get_entity(
        organization_id=principal.organization_id,
        entity_id=body.entity_id,
    )
    if entity is None:
        raise HTTPException(status_code=503, detail="graph_unavailable")
    return entity


@router.get("/entities/{entity_id}", response_model=dict)
async def get_entity(
    entity_id: str,
    principal: _AdminPrincipal,
    _: _RateLimit,
) -> dict:
    """Fetch a single graph entity by entity_id (scoped to caller's org)."""
    _require_graph_enabled()
    svc = _graph_service()
    entity = await svc.get_entity(
        organization_id=principal.organization_id,
        entity_id=entity_id,
    )
    if entity is None:
        raise HTTPException(status_code=404, detail="entity_not_found")
    return entity


@router.delete("/entities/{entity_id}", response_model=DeleteResponse)
async def delete_entity(
    entity_id: str,
    principal: _AdminPrincipal,
    _: _RateLimit,
) -> DeleteResponse:
    """Delete a graph entity and its relationships (scoped to caller's org)."""
    _require_graph_enabled()
    svc = _graph_service()
    deleted = await svc.delete_entity(
        organization_id=principal.organization_id,
        entity_id=entity_id,
    )
    return DeleteResponse(deleted=deleted)


@router.get("/entities/{entity_id}/aliases", response_model=EntityAliasListResponse)
async def get_entity_aliases(
    entity_id: str,
    principal: _AdminPrincipal,
    _: _RateLimit,
    limit: int = Query(default=50, ge=1, le=200),
) -> EntityAliasListResponse:
    """Return alias and mention records for an entity."""
    _require_graph_enabled()
    svc = _graph_service()
    items_raw = await svc.list_entity_aliases(
        organization_id=principal.organization_id,
        entity_id=entity_id,
        limit=limit,
    )
    items = [EntityAliasItem(**item) for item in items_raw]
    return EntityAliasListResponse(entity_id=entity_id, items=items)


# ---------------------------------------------------------------------------
# Evidence endpoint
# ---------------------------------------------------------------------------


@router.get("/entities/{entity_id}/evidence", response_model=EvidenceListResponse)
async def get_entity_evidence(
    entity_id: str,
    principal: _AdminPrincipal,
    _: _RateLimit,
    limit: int = Query(default=50, ge=1, le=200),
) -> EvidenceListResponse:
    """Return chunk evidence links for an entity (scoped to caller's org)."""
    _require_graph_enabled()
    svc = _graph_service()
    items_raw = await svc.get_entity_evidence(
        organization_id=principal.organization_id,
        entity_id=entity_id,
        limit=limit,
    )
    items = [
        EvidenceItem(
            chunk_id=r.get("chunk_id", ""),
            source_document_id=r.get("source_document_id", ""),
            workspace_id=r.get("workspace_id"),
            document_version_id=r.get("document_version_id"),
            page_number=r.get("page_number"),
            source_connector=r.get("source_connector"),
            external_url=r.get("external_url"),
            extraction_run_id=r.get("extraction_run_id"),
            confidence=r.get("confidence"),
            evidence_text=r.get("evidence_text"),
            citation_text=r.get("citation_text"),
            citation_reference=r.get("citation_reference"),
            created_at=r.get("created_at"),
        )
        for r in items_raw
    ]
    return EvidenceListResponse(entity_id=entity_id, items=items)


# ---------------------------------------------------------------------------
# Relations endpoint
# ---------------------------------------------------------------------------


@router.get("/entities/{entity_id}/relations", response_model=RelationListResponse)
async def get_entity_relations(
    entity_id: str,
    principal: _AdminPrincipal,
    _: _RateLimit,
    rel_type: str | None = Query(default=None),
    direction: str = Query(default="out", pattern="^(out|in|both)$"),
    limit: int = Query(default=100, ge=1, le=500),
) -> RelationListResponse:
    """Return relationships for an entity (scoped to caller's org)."""
    _require_graph_enabled()

    if rel_type is not None and rel_type not in RELATIONSHIP_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"unknown_rel_type: valid values are {list(RELATIONSHIP_TYPES)}",
        )

    svc = _graph_service()
    items_raw = await svc.get_entity_relations(
        organization_id=principal.organization_id,
        entity_id=entity_id,
        rel_type=rel_type,
        direction=direction,  # type: ignore[arg-type]
        limit=limit,
    )
    items = [
        RelationItem(
            from_entity_id=r["from_entity_id"],
            rel_type=r["rel_type"],
            to_entity_id=r["to_entity_id"],
            properties=r.get("properties", {}),
        )
        for r in items_raw
    ]
    return RelationListResponse(entity_id=entity_id, items=items)


# ---------------------------------------------------------------------------
# Resolution endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/entity-resolution/candidates",
    response_model=EntityResolutionCandidateListResponse,
)
async def list_entity_resolution_candidates(
    principal: _AdminPrincipal,
    _: _RateLimit,
    entity_type: str | None = Query(default=None),
    name_query: str | None = Query(default=None, min_length=1),
    source_external_id: str | None = Query(default=None, min_length=1),
    limit: int = Query(default=20, ge=1, le=100),
) -> EntityResolutionCandidateListResponse:
    """Return candidate canonical entities for review."""
    _require_graph_enabled()
    if name_query is None and source_external_id is None:
        raise HTTPException(
            status_code=422,
            detail="resolution_query_required",
        )
    svc = _graph_service()
    items_raw = await svc.find_entity_resolution_candidates(
        organization_id=principal.organization_id,
        entity_type=entity_type,
        normalized_name=name_query,
        aliases=[name_query] if name_query else None,
        source_external_id=source_external_id,
        limit=limit,
    )
    items = [EntityResolutionCandidateItem(**item) for item in items_raw]
    return EntityResolutionCandidateListResponse(items=items)


@router.post("/entity-resolution/merge", response_model=EntityDecisionResponse)
async def record_entity_merge_decision(
    body: EntityMergeDecisionRequest,
    principal: _AdminPrincipal,
    _: _RateLimit,
) -> EntityDecisionResponse:
    """Record a manual merge decision for later replay and audit."""
    _require_graph_enabled()
    svc = _graph_service()
    await svc.record_entity_merge_decision(
        organization_id=principal.organization_id,
        target_entity_id=body.target_entity_id,
        source_entity_ids=body.source_entity_ids,
        reason=body.reason,
        reviewer_id=body.reviewer_id,
    )
    decision_id = svc.build_entity_merge_decision_id(
        organization_id=principal.organization_id,
        target_entity_id=body.target_entity_id,
        source_entity_ids=body.source_entity_ids,
    )
    return EntityDecisionResponse(
        decision_id=str(decision_id),
        decision_kind="merge",
        target_entity_id=body.target_entity_id,
        source_entity_ids=body.source_entity_ids,
        reason=body.reason,
        reviewer_id=body.reviewer_id,
    )


@router.post("/entity-resolution/split", response_model=EntityDecisionResponse)
async def record_entity_split_decision(
    body: EntitySplitDecisionRequest,
    principal: _AdminPrincipal,
    _: _RateLimit,
) -> EntityDecisionResponse:
    """Record a manual split decision for later replay and audit."""
    _require_graph_enabled()
    svc = _graph_service()
    await svc.record_entity_split_decision(
        organization_id=principal.organization_id,
        target_entity_id=body.target_entity_id,
        source_entity_ids=body.source_entity_ids,
        reason=body.reason,
        reviewer_id=body.reviewer_id,
    )
    decision_id = svc.build_entity_split_decision_id(
        organization_id=principal.organization_id,
        target_entity_id=body.target_entity_id,
        source_entity_ids=body.source_entity_ids,
    )
    return EntityDecisionResponse(
        decision_id=str(decision_id),
        decision_kind="split",
        target_entity_id=body.target_entity_id,
        source_entity_ids=body.source_entity_ids,
        reason=body.reason,
        reviewer_id=body.reviewer_id,
    )


# ---------------------------------------------------------------------------
# Extraction runs endpoint
# ---------------------------------------------------------------------------


@router.get(
    "/documents/{document_id}/extraction-runs",
    response_model=ExtractionRunListResponse,
)
async def get_extraction_runs(
    document_id: str,
    principal: _AdminPrincipal,
    _: _RateLimit,
    limit: int = Query(default=20, ge=1, le=100),
) -> ExtractionRunListResponse:
    """Return graph extraction run history for a document (scoped to caller's org)."""
    _require_graph_enabled()
    svc = _graph_service()
    items_raw = await svc.get_document_extraction_runs(
        organization_id=principal.organization_id,
        document_id=document_id,
        limit=limit,
    )
    items = [
        ExtractionRunItem(
            run_id=r.get("run_id", ""),
            document_id=r.get("document_id", ""),
            strategy=r.get("strategy", ""),
            status=r.get("status", ""),
            entity_count=r.get("entity_count"),
            error=r.get("error"),
            created_at=r.get("created_at"),
            updated_at=r.get("updated_at"),
        )
        for r in items_raw
    ]
    return ExtractionRunListResponse(document_id=document_id, items=items)
