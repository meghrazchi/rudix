"""Admin HTTP endpoints for Enterprise Graph relation management (F284/F290).

Routes:
  GET    /admin/graph/relations                        — list relations (filterable)
  POST   /admin/graph/relations                        — create relation with evidence
  GET    /admin/graph/relations/{relation_id}          — get single relation
  PATCH  /admin/graph/relations/{relation_id}/status   — update review status
  DELETE /admin/graph/relations/{relation_id}          — delete relation

Auth:
  Reads  — owner/admin role (require_roles).
  Writes — graph:relations:manage permission (require_permission); admin/owner hold
           this by default; custom roles can be granted it for RBAC extensibility.

Evidence is required on creation — relations without provenance are rejected.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_permission, require_roles
from app.auth.models import AuthenticatedPrincipal
from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import get_db_session
from app.domains.admin.audit_events import (
    GRAPH_RELATION_CREATED,
    GRAPH_RELATION_DELETED,
    GRAPH_RELATION_STATUS_CHANGED,
)
from app.domains.admin.services.audit_service import AuditLogService
from app.domains.graph.repositories.relation_repository import (
    RELATION_STATUSES,
    RELATIONSHIP_TYPES,
    RelationStatus,
)
from app.domains.graph.services.graph_service import GraphService
from app.models.enums import OrganizationRole
from app.models.permissions import PermissionType
from app.rate_limit import RateLimitScope, enforce_rate_limit

router = APIRouter(prefix="/admin/graph", tags=["admin-graph"])

_audit_log_service = AuditLogService()
_logger = get_logger("events.graph_relations")


def _require_graph_enabled() -> None:
    if not settings.enterprise_graph_enabled:
        raise HTTPException(status_code=503, detail="enterprise_graph_disabled")


def _graph_service() -> GraphService:
    return GraphService()


def _org_id(principal: AuthenticatedPrincipal) -> UUID:
    try:
        return UUID(principal.organization_id)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=403, detail="invalid_organization_context") from exc


def _user_id(principal: AuthenticatedPrincipal) -> UUID | None:
    try:
        return UUID(principal.user_id)
    except (TypeError, ValueError):
        return None


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


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
# Dependency aliases
# ---------------------------------------------------------------------------

_AdminReadPrincipal = Annotated[
    AuthenticatedPrincipal,
    Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
]
_AdminWritePrincipal = Annotated[
    AuthenticatedPrincipal,
    Depends(require_permission(PermissionType.graph_relations_manage)),
]
_RateLimit = Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/relations")
async def list_relations(
    principal: _AdminReadPrincipal,
    _: Annotated[None, Depends(_require_graph_enabled)],
    svc: Annotated[GraphService, Depends(_graph_service)],
    _rl: _RateLimit,
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
    request: Request,
    body: CreateRelationRequest,
    principal: _AdminWritePrincipal,
    _: Annotated[None, Depends(_require_graph_enabled)],
    svc: Annotated[GraphService, Depends(_graph_service)],
    _rl: _RateLimit,
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict:
    """Create or merge an evidence-backed relation. Evidence is required."""
    organization_id = _org_id(principal)
    actor_id = _user_id(principal)

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
    await _audit_log_service.record(
        db_session,
        organization_id=organization_id,
        user_id=actor_id,
        action=GRAPH_RELATION_CREATED,
        resource_type="graph_relation",
        resource_id=body.relation_id,
        request_id=_request_id(request),
        metadata={
            "from_entity_id": body.from_entity_id,
            "rel_type": body.rel_type,
            "to_entity_id": body.to_entity_id,
            "initial_status": body.initial_status,
            "confidence": body.confidence,
        },
    )
    _logger.info(
        "graph.relation.created",
        organization_id=str(organization_id),
        user_id=str(actor_id) if actor_id else None,
        relation_id=body.relation_id,
        rel_type=body.rel_type,
    )
    return relation or {"relation_id": body.relation_id, "status": "created"}


@router.get("/relations/{relation_id}")
async def get_relation(
    relation_id: str,
    principal: _AdminReadPrincipal,
    _: Annotated[None, Depends(_require_graph_enabled)],
    svc: Annotated[GraphService, Depends(_graph_service)],
    _rl: _RateLimit,
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
    request: Request,
    relation_id: str,
    body: UpdateRelationStatusRequest,
    principal: _AdminWritePrincipal,
    _: Annotated[None, Depends(_require_graph_enabled)],
    svc: Annotated[GraphService, Depends(_graph_service)],
    _rl: _RateLimit,
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict:
    """Transition the review status of a relation (verify, reject, etc.)."""
    organization_id = _org_id(principal)
    actor_id = _user_id(principal)

    updated = await svc.update_relation_status(
        organization_id=principal.organization_id,
        relation_id=relation_id,
        status=body.status,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="relation_not_found")

    await _audit_log_service.record(
        db_session,
        organization_id=organization_id,
        user_id=actor_id,
        action=GRAPH_RELATION_STATUS_CHANGED,
        resource_type="graph_relation",
        resource_id=relation_id,
        request_id=_request_id(request),
        metadata={"relation_id": relation_id, "new_status": body.status},
    )
    _logger.info(
        "graph.relation.status_changed",
        organization_id=str(organization_id),
        user_id=str(actor_id) if actor_id else None,
        relation_id=relation_id,
        new_status=body.status,
    )
    return {"relation_id": relation_id, "status": body.status, "updated": True}


@router.delete("/relations/{relation_id}")
async def delete_relation(
    request: Request,
    relation_id: str,
    principal: _AdminWritePrincipal,
    _: Annotated[None, Depends(_require_graph_enabled)],
    svc: Annotated[GraphService, Depends(_graph_service)],
    _rl: _RateLimit,
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict:
    """Delete a relation by its stable relation_id."""
    organization_id = _org_id(principal)
    actor_id = _user_id(principal)

    deleted = await svc.delete_relation_by_id(
        organization_id=principal.organization_id,
        relation_id=relation_id,
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="relation_not_found")

    await _audit_log_service.record(
        db_session,
        organization_id=organization_id,
        user_id=actor_id,
        action=GRAPH_RELATION_DELETED,
        resource_type="graph_relation",
        resource_id=relation_id,
        request_id=_request_id(request),
        metadata={"relation_id": relation_id},
    )
    _logger.info(
        "graph.relation.deleted",
        organization_id=str(organization_id),
        user_id=str(actor_id) if actor_id else None,
        relation_id=relation_id,
    )
    return {"relation_id": relation_id, "deleted": True}
