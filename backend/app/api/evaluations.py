from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import ensure_document_ids_access, get_current_principal, require_roles
from app.auth.models import AuthenticatedPrincipal
from app.core.config import settings
from app.core.logging import log_evaluation_event
from app.db.session import get_db_session
from app.models.enums import OrganizationRole
from app.rate_limit import RateLimitScope, enforce_rate_limit
from app.repositories.evaluations import EvaluationRepository
from app.schemas.evaluations import (
    EvaluationStatusResponse,
    RunEvaluationRequest,
    RunEvaluationResponse,
)
from app.workers.evaluation_tasks import run_evaluation as run_evaluation_task

router = APIRouter(prefix="/evaluations", tags=["evaluations"])
evaluation_repository = EvaluationRepository()


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


def _parse_evaluation_set_id(evaluation_set_id: str) -> UUID:
    try:
        return UUID(evaluation_set_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evaluation set not found") from exc


@router.post("/run", response_model=RunEvaluationResponse, status_code=status.HTTP_202_ACCEPTED)
async def trigger_evaluation(
    payload: RunEvaluationRequest,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    _: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.evaluation))],
    __: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> RunEvaluationResponse:
    organization_id = _organization_id_from_principal(principal)
    evaluation_set_id = _parse_evaluation_set_id(payload.evaluation_set_id)

    evaluation_set = await evaluation_repository.get_evaluation_set(
        db_session,
        evaluation_set_id=evaluation_set_id,
        organization_id=organization_id,
    )
    if evaluation_set is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evaluation set not found")

    selected_document_ids = await ensure_document_ids_access(
        document_ids=payload.config.selected_document_ids,
        principal=principal,
        db_session=db_session,
    )
    selected_document_ids_as_strings = [str(document_id) for document_id in selected_document_ids]

    if settings.evaluation_prevent_duplicate_active_runs:
        active_runs = await evaluation_repository.count_active_runs_for_set(
            db_session,
            evaluation_set_id=evaluation_set_id,
        )
        if active_runs > 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An evaluation run is already active for this evaluation set",
            )

    config_payload: dict[str, object] = {
        "top_k": payload.config.top_k if payload.config.top_k is not None else settings.retrieval_final_top_k,
        "rerank": payload.config.rerank,
        "model_name": payload.config.model_name or settings.openai_llm_model,
        "selected_document_ids": selected_document_ids_as_strings,
        "metric_options": dict(payload.config.metric_options),
    }

    evaluation_run = await evaluation_repository.create_evaluation_run(
        db_session,
        evaluation_set_id=evaluation_set_id,
        config=config_payload,
    )
    await db_session.commit()
    await db_session.refresh(evaluation_run)

    try:
        task_result = run_evaluation_task.delay(
            str(evaluation_run.id),
            request_id=None,
            organization_id=str(organization_id),
            user_id=principal.user_id,
        )
    except Exception as exc:
        _ = await evaluation_repository.update_evaluation_run_status(
            db_session,
            evaluation_run_id=evaluation_run.id,
            status="failed",
            mark_completed=True,
        )
        await db_session.commit()

        log_evaluation_event(
            event="evaluation.run.enqueue_failed",
            organization_id=principal.organization_id,
            user_id=principal.user_id,
            job_id=str(evaluation_run.id),
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            error=exc.__class__.__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Evaluation run could not be queued",
        ) from exc

    log_evaluation_event(
        event="evaluation.run.queued",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        job_id=str(evaluation_run.id),
        task_id=str(task_result.id),
        status_code=status.HTTP_202_ACCEPTED,
    )
    return RunEvaluationResponse(
        evaluation_run_id=str(evaluation_run.id),
        status="queued",
    )


@router.get("/{evaluation_run_id}", response_model=EvaluationStatusResponse)
async def get_evaluation_status(
    evaluation_run_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
) -> EvaluationStatusResponse:
    log_evaluation_event(
        event="evaluation.status.requested",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        job_id=evaluation_run_id,
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
    )
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=f"Evaluation status for {evaluation_run_id} is not implemented in scaffold.",
    )
