from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_principal
from app.auth.models import AuthenticatedPrincipal
from app.db.session import get_db_session
from app.domains.pipeline.repositories.pipeline import PipelineRepository
from app.domains.pipeline.schemas.pipeline import (
    PipelineEdgeResponse,
    PipelineNodeDetailResponse,
    PipelineNodeResponse,
    PipelineRunGraphResponse,
    PipelineRunResolveResponse,
    PipelineStepListResponse,
)
from app.domains.pipeline.services.pipeline_graph_service import (
    aggregate_pipeline_nodes,
    build_pipeline_edges,
    build_pipeline_node_detail,
    canonical_pipeline_type,
)

router = APIRouter(prefix="/pipeline", tags=["pipeline"])
pipeline_repository = PipelineRepository()
_CANONICAL_PIPELINE_TYPES: dict[str, list[str]] = {
    "document.process": ["document.process", "document.reindex", "document.delete"],
    "chat.answer": ["chat.query"],
    "evaluation.run": ["evaluation.run"],
}


def _organization_id_from_principal(principal: AuthenticatedPrincipal) -> UUID:
    if principal.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No active organization context for principal",
        )
    try:
        return UUID(principal.organization_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Principal organization context is invalid",
        ) from exc


def _parse_pipeline_run_id(pipeline_run_id: str) -> UUID:
    try:
        return UUID(pipeline_run_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pipeline run not found") from exc


def _resolve_pipeline_type_filters(run_type: str | None) -> list[str] | None:
    if run_type is None:
        return None
    normalized = canonical_pipeline_type(run_type)
    resolved = _CANONICAL_PIPELINE_TYPES.get(normalized)
    if resolved is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "invalid_pipeline_type",
                "message": "run_type must be one of document.process, chat.answer, evaluation.run",
            },
        )
    return resolved


@router.get("/steps", response_model=PipelineStepListResponse)
async def list_pipeline_steps() -> PipelineStepListResponse:
    return PipelineStepListResponse(
        steps=[
            "extract",
            "clean",
            "chunk",
            "embed",
            "index",
            "retrieve",
            "rerank",
            "generate",
            "evaluate",
        ]
    )


@router.get("/runs/resolve", response_model=PipelineRunResolveResponse)
async def resolve_pipeline_run(
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    run_type: str | None = Query(default=None),
    document_id: UUID | None = Query(default=None),
    chat_message_id: UUID | None = Query(default=None),
    evaluation_run_id: UUID | None = Query(default=None),
) -> PipelineRunResolveResponse:
    if document_id is None and chat_message_id is None and evaluation_run_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "pipeline_context_required",
                "message": "Provide at least one of document_id, chat_message_id, or evaluation_run_id",
            },
        )

    organization_id = _organization_id_from_principal(principal)
    pipeline_types = _resolve_pipeline_type_filters(run_type)
    pipeline_run = await pipeline_repository.resolve_latest_pipeline_run(
        db_session,
        organization_id=organization_id,
        pipeline_types=pipeline_types,
        document_id=document_id,
        chat_message_id=chat_message_id,
        evaluation_run_id=evaluation_run_id,
    )
    if pipeline_run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pipeline run not found")

    return PipelineRunResolveResponse(
        pipeline_run_id=str(pipeline_run.id),
        pipeline_type=canonical_pipeline_type(pipeline_run.pipeline_type),
        status=pipeline_run.status,
    )


@router.get("/runs/{run_id}", response_model=PipelineRunGraphResponse)
async def get_pipeline_run_graph(
    run_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PipelineRunGraphResponse:
    organization_id = _organization_id_from_principal(principal)
    parsed_run_id = _parse_pipeline_run_id(run_id)
    pipeline_run = await pipeline_repository.get_pipeline_run_for_organization(
        db_session,
        pipeline_run_id=parsed_run_id,
        organization_id=organization_id,
    )
    if pipeline_run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pipeline run not found")

    events = await pipeline_repository.list_pipeline_events_for_run(
        db_session,
        pipeline_run_id=pipeline_run.id,
    )
    nodes = aggregate_pipeline_nodes(
        pipeline_type=pipeline_run.pipeline_type,
        events=events,
    )
    node_ids_in_order = [node.node_id for node in nodes]
    edges = build_pipeline_edges(node_ids_in_order)

    return PipelineRunGraphResponse(
        pipeline_run_id=str(pipeline_run.id),
        pipeline_type=canonical_pipeline_type(pipeline_run.pipeline_type),
        status=pipeline_run.status,
        nodes=[
            PipelineNodeResponse(
                id=node.node_id,
                label=node.label,
                section=node.section,
                description=node.description,
                status=node.status,
                started_at=node.started_at,
                completed_at=node.completed_at,
                duration_ms=node.duration_ms,
                metrics=node.metrics,
            )
            for node in nodes
        ],
        edges=[PipelineEdgeResponse(**edge) for edge in edges],
    )


@router.get("/runs/{run_id}/nodes/{node_id}", response_model=PipelineNodeDetailResponse)
async def get_pipeline_node_detail(
    run_id: str,
    node_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PipelineNodeDetailResponse:
    organization_id = _organization_id_from_principal(principal)
    parsed_run_id = _parse_pipeline_run_id(run_id)
    pipeline_run = await pipeline_repository.get_pipeline_run_for_organization(
        db_session,
        pipeline_run_id=parsed_run_id,
        organization_id=organization_id,
    )
    if pipeline_run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pipeline run not found")

    events = await pipeline_repository.list_pipeline_events_for_node(
        db_session,
        pipeline_run_id=pipeline_run.id,
        node_name=node_id,
    )
    if not events:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pipeline node not found")

    detail_payload = build_pipeline_node_detail(events=events)
    return PipelineNodeDetailResponse(**detail_payload)
