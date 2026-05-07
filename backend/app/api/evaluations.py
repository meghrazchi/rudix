from fastapi import APIRouter, HTTPException, status

from app.core.logging import log_evaluation_event
from app.schemas.evaluations import (
    EvaluationStatusResponse,
    TriggerEvaluationRequest,
    TriggerEvaluationResponse,
)

router = APIRouter(prefix="/evaluations", tags=["evaluations"])


@router.post("", response_model=TriggerEvaluationResponse)
async def trigger_evaluation(_: TriggerEvaluationRequest) -> TriggerEvaluationResponse:
    log_evaluation_event(
        event="evaluation.requested",
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
    )
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Evaluation enqueue is not implemented in scaffold.",
    )


@router.get("/{evaluation_run_id}", response_model=EvaluationStatusResponse)
async def get_evaluation_status(evaluation_run_id: str) -> EvaluationStatusResponse:
    log_evaluation_event(
        event="evaluation.status.requested",
        job_id=evaluation_run_id,
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
    )
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=f"Evaluation status for {evaluation_run_id} is not implemented in scaffold.",
    )
