from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import ensure_document_ids_access, get_current_principal, require_roles
from app.auth.models import AuthenticatedPrincipal
from app.core.logging import log_evaluation_event
from app.db.session import get_db_session
from app.models.enums import OrganizationRole
from app.rate_limit import RateLimitScope, enforce_rate_limit
from app.schemas.evaluations import (
    EvaluationStatusResponse,
    TriggerEvaluationRequest,
    TriggerEvaluationResponse,
)

router = APIRouter(prefix="/evaluations", tags=["evaluations"])


@router.post("", response_model=TriggerEvaluationResponse)
async def trigger_evaluation(
    payload: TriggerEvaluationRequest,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    _: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.evaluation))],
    __: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> TriggerEvaluationResponse:
    await ensure_document_ids_access(
        document_ids=[payload.document_id],
        principal=principal,
        db_session=db_session,
    )

    log_evaluation_event(
        event="evaluation.requested",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
    )
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Evaluation enqueue is not implemented in scaffold.",
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
