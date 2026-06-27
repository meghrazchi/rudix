"""HTTP interface for plan-before-execute agent workflows (F344)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.auth.dependencies import require_roles
from app.core.config import settings
from app.domains.agents.schemas import AgentPlanPreviewResponse, AgentRuntimeRequest
from app.domains.agents.services import WorkflowPlannerService
from app.domains.agents.services.workflow_planner_service import (
    WorkflowAction,
    WorkflowType,
)
from app.models.enums import OrganizationRole

router = APIRouter(prefix="/agent/workflows", tags=["agent-workflows"])

_workflow_planner = WorkflowPlannerService()


class WorkflowPlanRequest(BaseModel):
    workflow_type: WorkflowType
    request: AgentRuntimeRequest | None = None
    requested_actions: list[WorkflowAction] = Field(default_factory=list)


def _feature_enabled() -> None:
    if not settings.feature_enable_agents:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "feature_not_available",
                "message": "Agentic workflows are not enabled for this deployment.",
            },
        )


@router.post("/preview", response_model=AgentPlanPreviewResponse)
async def preview_workflow_plan(
    payload: WorkflowPlanRequest,
    _: Annotated[
        None,
        Depends(
            require_roles(
                OrganizationRole.owner.value,
                OrganizationRole.admin.value,
                OrganizationRole.member.value,
                OrganizationRole.viewer.value,
            )
        ),
    ],
) -> AgentPlanPreviewResponse:
    _feature_enabled()
    return _workflow_planner.preview(
        workflow_type=payload.workflow_type,
        request=payload.request,
        requested_actions=payload.requested_actions,
    )
