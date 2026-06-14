"""Admin HTTP endpoints for Enterprise Graph entity management (F281).

No Cypher appears in this module — all graph operations are delegated to
GraphService which composes the repository layer.

Routes:
  GET  /admin/graph/entities                           — list entities in org
  POST /admin/graph/entities                           — upsert entity
  GET  /admin/graph/entities/{entity_id}               — get entity
  DELETE /admin/graph/entities/{entity_id}             — delete entity
  GET  /admin/graph/entities/{entity_id}/evidence      — entity evidence links
  GET  /admin/graph/entities/{entity_id}/relations     — entity relationships
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


class EntityListResponse(BaseModel):
    items: list[dict[str, Any]]
    total: int


class EvidenceItem(BaseModel):
    chunk_id: str
    source_document_id: str
    confidence: float | None = None
    evidence_text: str | None = None
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
            confidence=r.get("confidence"),
            evidence_text=r.get("evidence_text"),
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
