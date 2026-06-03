from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AuthenticatedPrincipal
from app.core.logging import log_evaluation_event
from app.domains.admin.services.audit_service import AuditLogService
from app.domains.safety_evals.repositories.safety_evals import SafetyEvalRepository
from app.domains.safety_evals.schemas.safety_evals import (
    TriggerSafetyEvalRunRequest,
    TriggerSafetyEvalRunResponse,
)


async def trigger_safety_eval_workflow(
    *,
    request_id: str | None,
    payload: TriggerSafetyEvalRunRequest,
    principal: AuthenticatedPrincipal,
    organization_id: UUID,
    user_id: UUID,
    db_session: AsyncSession,
    safety_eval_repository: SafetyEvalRepository,
    audit_log_service: AuditLogService,
    run_safety_eval_task: Any,
) -> TriggerSafetyEvalRunResponse:
    regression_threshold = payload.regression_threshold
    model_version = payload.model_version
    retrieval_settings = payload.retrieval_settings or {}

    run = await safety_eval_repository.create_run(
        db_session,
        organization_id=organization_id,
        suite_name=payload.suite_name,
        config={
            "model_version": model_version,
            "retrieval_settings": retrieval_settings,
            "regression_threshold": regression_threshold,
            "triggered_by": principal.user_id,
            "request_id": request_id,
        },
    )
    await db_session.commit()
    await db_session.refresh(run)

    wrote_audit = await audit_log_service.record(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        action="safety_eval.run.requested",
        resource_type="safety_eval_run",
        resource_id=run.id,
        request_id=request_id,
        metadata={
            "suite_name": payload.suite_name,
            "model_version": model_version,
            "regression_threshold": regression_threshold,
        },
    )
    if wrote_audit:
        await db_session.commit()

    log_evaluation_event(
        event="safety_eval.run.queued",
        job_id=str(run.id),
        organization_id=str(organization_id),
        user_id=str(user_id),
        request_id=request_id,
        suite_name=payload.suite_name,
        status_code=status.HTTP_202_ACCEPTED,
    )

    task_result = run_safety_eval_task.delay(
        str(run.id),
        request_id=request_id,
        organization_id=str(organization_id),
        user_id=str(user_id),
    )

    return TriggerSafetyEvalRunResponse(
        run_id=str(run.id),
        status=run.status,
        message=f"Safety evaluation run queued (task_id={task_result.id})",
    )
