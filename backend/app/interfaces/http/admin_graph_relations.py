"""Admin HTTP endpoints for Enterprise Graph relation management (F284).

Routes:
  GET    /admin/graph/relations                        — list relations (filterable)
  POST   /admin/graph/relations                        — create relation with evidence
  GET    /admin/graph/relations/{relation_id}          — get single relation
  PATCH  /admin/graph/relations/{relation_id}/status   — update review status
  DELETE /admin/graph/relations/{relation_id}          — delete relation

Auth: owner/admin only.
Evidence is required on creation — relations without provenance are rejected.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator

from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.core.config import settings
from app.domains.graph.repositories.relation_repository import (
    RELATION_STATUSES,
    RELATIONSHIP_TYPES,
    RelationStatus,
)
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


class CreateRelationRequest(BaseModel):
    from_entity_id: str = Field(..., min_length=1)
    to_entity_id: str = Field(..., min_length=1)
    rel_type: str = Field(..., min_length=1)
    relation_id: str = Field(..., min_length=1)
    # Evidence — at least one required
    evidence_text: str | None = Field(default=None, max_length=2000)
    citation_text: str | None = Field(default=None, max_length=2000)
    citation_reference: str | None = Field(default=None, max_length=512)
    # Provenance
    chunk_id: str | None = None
    source_document_id: str | None = None
    page_number: int | None = Field(default=None, ge=0)
    workspace_id: str | None = None
    source_connector: str | None = None
    extraction_run_id: str | None = None
    # Scoring and state
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    initial_status: RelationStatus = "unverified"

    @model_validator(mode="after")
    def require_evidence(self) -> CreateRelationRequest:
        if not any([self.evidence_text, self.citation_text, self.citation_reference]):
            raise ValueError(
                "At least one of evidence_text, citation_text, or citation_reference is required"
            )
        return self

    @model_validator(mode="after")
    def validate_rel_type(self) -> CreateRelationRequest:
        if self.rel_type not in RELATIONSHIP_TYPES:
            raise ValueError(
                f"Unknown rel_type '{self.rel_type}'. Valid types: {', '.join(RELATIONSHIP_TYPES)}"
            )
        return self


class UpdateRelationStatusRequest(BaseModel):
    status: RelationStatus


class RelationResponse(BaseModel):
    relation_id: str | None
    organization_id: str | None
    from_entity_id: str | None
    rel_type: str | None
    to_entity_id: str | None
    status: str | None
    confidence: float | None
    evidence_text: str | None
    citation_text: str | None
    citation_reference: str | None
    chunk_id: str | None
    source_document_id: str | None
    page_number: int | None
    workspace_id: str | None
    extraction_run_id: str | None
    created_at: str | None
    updated_at: str | None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/relations")
async def list_relations(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    _: Annotated[None, Depends(_require_graph_enabled)],
    svc: Annotated[GraphService, Depends(_graph_service)],
    _rl: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    status: Annotated[str | None, Query()] = None,
    rel_type: Annotated[str | None, Query()] = None,
    workspace_id: Annotated[str | None, Query()] = None,
    min_confidence: Annotated[float | None, Query(ge=0.0, le=1.0)] = None,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[dict]:
    """List relations for the caller's organization with optional filters."""
    if status is not None and status not in RELATION_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid status '{status}'. Valid: {sorted(RELATION_STATUSES)}",
        )
    if rel_type is not None and rel_type not in RELATIONSHIP_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid rel_type '{rel_type}'. Valid: {list(RELATIONSHIP_TYPES)}",
        )
    return await svc.list_relations(
        organization_id=principal.organization_id,
        status=status,  # type: ignore[arg-type]
        rel_type=rel_type,
        workspace_id=workspace_id,
        min_confidence=min_confidence,
        skip=skip,
        limit=limit,
    )


@router.post("/relations")
async def create_relation(
    body: CreateRelationRequest,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    _: Annotated[None, Depends(_require_graph_enabled)],
    svc: Annotated[GraphService, Depends(_graph_service)],
    _rl: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
) -> dict:
    """Create or merge an evidence-backed relation. Evidence is required."""
    try:
        await svc.create_relation_with_evidence(
            organization_id=principal.organization_id,
            from_entity_id=body.from_entity_id,
            to_entity_id=body.to_entity_id,
            rel_type=body.rel_type,
            relation_id=body.relation_id,
            evidence_text=body.evidence_text,
            citation_text=body.citation_text,
            citation_reference=body.citation_reference,
            chunk_id=body.chunk_id,
            source_document_id=body.source_document_id,
            page_number=body.page_number,
            workspace_id=body.workspace_id,
            source_connector=body.source_connector,
            extraction_run_id=body.extraction_run_id,
            confidence=body.confidence,
            initial_status=body.initial_status,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    relation = await svc.get_relation(
        organization_id=principal.organization_id,
        relation_id=body.relation_id,
    )
    return relation or {"relation_id": body.relation_id, "status": "created"}


@router.get("/relations/{relation_id}")
async def get_relation(
    relation_id: str,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    _: Annotated[None, Depends(_require_graph_enabled)],
    svc: Annotated[GraphService, Depends(_graph_service)],
    _rl: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
) -> dict:
    """Get a single relation by its stable relation_id."""
    relation = await svc.get_relation(
        organization_id=principal.organization_id,
        relation_id=relation_id,
    )
    if relation is None:
        raise HTTPException(status_code=404, detail="relation_not_found")
    return relation


@router.patch("/relations/{relation_id}/status")
async def update_relation_status(
    relation_id: str,
    body: UpdateRelationStatusRequest,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    _: Annotated[None, Depends(_require_graph_enabled)],
    svc: Annotated[GraphService, Depends(_graph_service)],
    _rl: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
) -> dict:
    """Transition the review status of a relation (verify, reject, etc.)."""
    updated = await svc.update_relation_status(
        organization_id=principal.organization_id,
        relation_id=relation_id,
        status=body.status,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="relation_not_found")
    return {"relation_id": relation_id, "status": body.status, "updated": True}


@router.delete("/relations/{relation_id}")
async def delete_relation(
    relation_id: str,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    _: Annotated[None, Depends(_require_graph_enabled)],
    svc: Annotated[GraphService, Depends(_graph_service)],
    _rl: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
) -> dict:
    """Delete a relation by its stable relation_id."""
    deleted = await svc.delete_relation_by_id(
        organization_id=principal.organization_id,
        relation_id=relation_id,
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="relation_not_found")
    return {"relation_id": relation_id, "deleted": True}
