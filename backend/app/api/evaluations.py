from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.dependencies import get_current_principal, require_roles
from app.auth.models import AuthenticatedPrincipal
from app.core.logging import log_evaluation_event
from app.models.enums import OrganizationRole
from app.schemas.evaluations import (
    EvaluationStatusResponse,
    TriggerEvaluationRequest,
    TriggerEvaluationResponse,
)

router = APIRouter(prefix="/evaluations", tags=["evaluations"])


@router.post("", response_model=TriggerEvaluationResponse)
async def trigger_evaluation(
    _: TriggerEvaluationRequest,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
) -> TriggerEvaluationResponse:
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
