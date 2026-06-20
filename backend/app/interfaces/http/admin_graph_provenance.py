"""Admin HTTP endpoints for Enterprise Graph provenance and citations (F282).

Every graph fact must be traceable to original Rudix evidence: source documents,
chunks, extraction runs, and connector items. These endpoints expose that
provenance chain and provide citation DTOs for the UI.

Routes:
  POST /admin/graph/evidence
      Create an evidence link with full provenance payload. Validates that at
      least one of citation_text or citation_reference is provided.

  GET  /admin/graph/documents/{document_id}/provenance
      Return all evidence links for every entity extracted from a document,
      with full provenance fields so the UI can build the citation chain.

  GET  /admin/graph/entities/{entity_id}/citations
      Return citation-ready DTOs for all evidence backing an entity. Suitable
      for direct display in the answer citations panel.

Auth: owner/admin only.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator

from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.core.config import settings
from app.domains.graph.services.graph_service import GraphService
from app.models.enums import OrganizationRole
from app.rate_limit import RateLimitScope, enforce_rate_limit

router = APIRouter(prefix="/admin/graph", tags=["admin-graph-provenance"])


def _require_graph_enabled() -> None:
    if not settings.enterprise_graph_enabled:
        raise HTTPException(status_code=503, detail="enterprise_graph_disabled")


def _graph_service() -> GraphService:
    return GraphService()


# ---------------------------------------------------------------------------
# Dependency aliases
# ---------------------------------------------------------------------------

_AdminPrincipal = Annotated[
    AuthenticatedPrincipal,
    Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
]
_RateLimit = Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))]


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class CreateEvidenceRequest(BaseModel):
    """Full provenance payload for evidence-first graph fact creation (F282)."""

    entity_id: str = Field(..., min_length=1)
    chunk_id: str = Field(..., min_length=1)
    source_document_id: str = Field(..., min_length=1)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    workspace_id: str | None = None
    document_version_id: str | None = None
    page_number: int | None = Field(default=None, ge=0)
    source_connector: str | None = None
    external_url: str | None = None
    extraction_run_id: str | None = None
    evidence_text: str | None = None
    citation_text: str | None = None
    citation_reference: str | None = None

    @model_validator(mode="after")
    def require_citation_backing(self) -> CreateEvidenceRequest:
        if not any([self.evidence_text, self.citation_text, self.citation_reference]):
            raise ValueError(
                "provenance_required: at least one of evidence_text, citation_text, "
                "or citation_reference must be provided"
            )
        return self


class ProvenanceItem(BaseModel):
    """Full provenance record for a single Chunk→Entity evidence link."""

    entity_id: str
    entity_type: str | None = None
    canonical_name: str | None = None
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


class ProvenanceResponse(BaseModel):
    document_id: str
    items: list[ProvenanceItem]
    total: int


class CitationDTO(BaseModel):
    """Citation-ready DTO for UI display in the answer citations panel."""

    entity_id: str
    canonical_name: str | None = None
    chunk_id: str
    source_document_id: str
    page_number: int | None = None
    source_connector: str | None = None
    external_url: str | None = None
    extraction_run_id: str | None = None
    confidence: float | None = None
    citation_text: str | None = None
    citation_reference: str | None = None


class CitationListResponse(BaseModel):
    entity_id: str
    items: list[CitationDTO]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/evidence", status_code=201, response_model=dict[str, Any])
async def create_evidence_link(
    body: CreateEvidenceRequest,
    principal: _AdminPrincipal,
    _: _RateLimit,
) -> dict[str, Any]:
    """Create an evidence link with full provenance (F282).

    Enforces the evidence-first contract: at least one citation field must be
    provided so graph facts are always traceable to source text.
    """
    _require_graph_enabled()
    svc = _graph_service()
    await svc.link_evidence(
        organization_id=principal.organization_id,
        entity_id=body.entity_id,
        chunk_id=body.chunk_id,
        source_document_id=body.source_document_id,
        confidence=body.confidence,
        workspace_id=body.workspace_id,
        document_version_id=body.document_version_id,
        page_number=body.page_number,
        source_connector=body.source_connector,
        external_url=body.external_url,
        extraction_run_id=body.extraction_run_id,
        evidence_text=body.evidence_text,
        citation_text=body.citation_text,
        citation_reference=body.citation_reference,
    )
    return {
        "linked": True,
        "entity_id": body.entity_id,
        "chunk_id": body.chunk_id,
        "source_document_id": body.source_document_id,
    }


@router.get(
    "/documents/{document_id}/provenance",
    response_model=ProvenanceResponse,
)
async def get_document_provenance(
    document_id: str,
    principal: _AdminPrincipal,
    _: _RateLimit,
    limit: int = Query(default=100, ge=1, le=500),
) -> ProvenanceResponse:
    """Return the full provenance chain for every entity extracted from a document.

    Allows the UI to display which graph facts came from which chunks and
    which extraction runs — linking source document → chunk → evidence → entity.
    """
    _require_graph_enabled()
    svc = _graph_service()
    items_raw = await svc.get_document_provenance(
        organization_id=principal.organization_id,
        document_id=document_id,
        limit=limit,
    )
    items = [
        ProvenanceItem(
            entity_id=r.get("entity_id", ""),
            entity_type=r.get("entity_type"),
            canonical_name=r.get("canonical_name"),
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
    return ProvenanceResponse(document_id=document_id, items=items, total=len(items))


@router.get(
    "/entities/{entity_id}/citations",
    response_model=CitationListResponse,
)
async def get_entity_citations(
    entity_id: str,
    principal: _AdminPrincipal,
    _: _RateLimit,
    limit: int = Query(default=50, ge=1, le=200),
) -> CitationListResponse:
    """Return citation-ready DTOs for all evidence backing an entity.

    The response is structured for direct consumption by the answer citations
    panel: chunk location, source connector, page number, and the verbatim
    citation text or formatted reference string.
    """
    _require_graph_enabled()
    svc = _graph_service()
    items_raw = await svc.get_entity_evidence(
        organization_id=principal.organization_id,
        entity_id=entity_id,
        limit=limit,
    )
    items = [
        CitationDTO(
            entity_id=entity_id,
            canonical_name=None,
            chunk_id=r.get("chunk_id", ""),
            source_document_id=r.get("source_document_id", ""),
            page_number=r.get("page_number"),
            source_connector=r.get("source_connector"),
            external_url=r.get("external_url"),
            extraction_run_id=r.get("extraction_run_id"),
            confidence=r.get("confidence"),
            citation_text=r.get("citation_text") or r.get("evidence_text"),
            citation_reference=r.get("citation_reference"),
        )
        for r in items_raw
    ]
    return CitationListResponse(entity_id=entity_id, items=items)
