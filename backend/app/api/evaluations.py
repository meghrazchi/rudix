from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import ensure_document_ids_access, require_roles
from app.auth.models import AuthenticatedPrincipal
from app.core.config import settings
from app.core.logging import log_evaluation_event
from app.db.session import get_db_session
from app.models.enums import EvaluationRunStatus, OrganizationRole
from app.rate_limit import RateLimitScope, enforce_rate_limit
from app.repositories.evaluations import EvaluationRepository
from app.schemas.evaluations import (
    EvaluationRunDetailResponse,
    EvaluationRunResultListResponse,
    EvaluationRunResultResponse,
    RunEvaluationRequest,
    RunEvaluationResponse,
)
from app.services.audit_service import AuditLogService
from app.workers.evaluation_tasks import run_evaluation as run_evaluation_task

router = APIRouter(prefix="/evaluations", tags=["evaluations"])
evaluation_repository = EvaluationRepository()
audit_log_service = AuditLogService()


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


def _user_id_from_principal(principal: AuthenticatedPrincipal) -> UUID:
    try:
        return UUID(principal.user_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Principal user context is invalid",
        ) from exc


def _parse_evaluation_set_id(evaluation_set_id: str) -> UUID:
    try:
        return UUID(evaluation_set_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evaluation set not found") from exc


def _parse_evaluation_run_id(evaluation_run_id: str) -> UUID:
    try:
        return UUID(evaluation_run_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evaluation run not found") from exc


def _normalize_mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}


def _extract_failure_fields(details: dict[str, object]) -> tuple[str | None, str | None]:
    reason_raw = details.get("error")
    type_raw = details.get("error_type")
    reason = reason_raw.strip() if isinstance(reason_raw, str) and reason_raw.strip() else None
    failure_type = type_raw.strip() if isinstance(type_raw, str) and type_raw.strip() else None
    return reason, failure_type


def _request_id_from_request(request: Request) -> str | None:
    request_id = getattr(request.state, "request_id", None)
    if isinstance(request_id, str) and request_id.strip():
        return request_id
    return request.headers.get("x-request-id")


async def _safe_commit_audit_only(db_session: AsyncSession, *, wrote_audit: bool) -> None:
    if not wrote_audit:
        return
    try:
        await db_session.commit()
    except Exception:
        await db_session.rollback()


@router.post("/run", response_model=RunEvaluationResponse, status_code=status.HTTP_202_ACCEPTED)
async def trigger_evaluation(
    request: Request,
    payload: RunEvaluationRequest,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    _: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.evaluation))],
    __: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> RunEvaluationResponse:
    request_id = _request_id_from_request(request)
    organization_id = _organization_id_from_principal(principal)
    user_id = _user_id_from_principal(principal)
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
    await audit_log_service.record(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        action="evaluation.run.requested",
        resource_type="evaluation_run",
        resource_id=evaluation_run.id,
        request_id=request_id,
        metadata={
            "evaluation_set_id": str(evaluation_set_id),
            "top_k": config_payload["top_k"],
            "rerank": config_payload["rerank"],
            "selected_document_count": len(selected_document_ids_as_strings),
            "status_code": status.HTTP_202_ACCEPTED,
        },
    )
    await db_session.commit()
    await db_session.refresh(evaluation_run)

    try:
        task_result = run_evaluation_task.delay(
            str(evaluation_run.id),
            request_id=request_id,
            organization_id=str(organization_id),
            user_id=str(user_id),
        )
    except Exception as exc:
        _ = await evaluation_repository.update_evaluation_run_status(
            db_session,
            evaluation_run_id=evaluation_run.id,
            status="failed",
            mark_completed=True,
        )
        await audit_log_service.record(
            db_session,
            organization_id=organization_id,
            user_id=user_id,
            action="evaluation.run.enqueue_failed",
            resource_type="evaluation_run",
            resource_id=evaluation_run.id,
            request_id=request_id,
            metadata={
                "status_code": status.HTTP_503_SERVICE_UNAVAILABLE,
                "error_type": exc.__class__.__name__,
            },
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

    wrote_audit = await audit_log_service.record(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        action="evaluation.run.queued",
        resource_type="evaluation_run",
        resource_id=evaluation_run.id,
        request_id=request_id,
        metadata={
            "task_id": str(task_result.id),
            "status_code": status.HTTP_202_ACCEPTED,
        },
    )
    await _safe_commit_audit_only(db_session, wrote_audit=wrote_audit)

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


@router.get("/runs/{evaluation_run_id}", response_model=EvaluationRunDetailResponse)
async def get_evaluation_run_detail(
    evaluation_run_id: str,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(
            require_roles(
                OrganizationRole.owner.value,
                OrganizationRole.admin.value,
                OrganizationRole.member.value,
                OrganizationRole.viewer.value,
            )
        ),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> EvaluationRunDetailResponse:
    organization_id = _organization_id_from_principal(principal)
    parsed_run_id = _parse_evaluation_run_id(evaluation_run_id)
    evaluation_run = await evaluation_repository.get_evaluation_run_for_organization(
        db_session,
        evaluation_run_id=parsed_run_id,
        organization_id=organization_id,
    )
    if evaluation_run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evaluation run not found")

    rows = await evaluation_repository.list_evaluation_results_for_run(
        db_session,
        evaluation_run_id=evaluation_run.id,
        limit=limit,
        offset=offset,
    )
    total = await evaluation_repository.count_evaluation_results_for_run(
        db_session,
        evaluation_run_id=evaluation_run.id,
    )

    items: list[EvaluationRunResultResponse] = []
    for evaluation_result, evaluation_question in rows:
        details = _normalize_mapping(evaluation_result.details)
        metrics = _normalize_mapping(details.get("metrics"))
        status_value = details.get("status")
        if isinstance(status_value, str) and status_value.strip():
            normalized_status = status_value.strip()
        else:
            normalized_status = "failed" if details.get("error") else "completed"
        failure_reason, failure_type = _extract_failure_fields(details)
        items.append(
            EvaluationRunResultResponse(
                evaluation_result_id=str(evaluation_result.id),
                evaluation_question_id=str(evaluation_result.evaluation_question_id),
                question=evaluation_question.question,
                status=normalized_status,
                generated_answer=evaluation_result.generated_answer,
                retrieval_score=evaluation_result.retrieval_score,
                faithfulness_score=evaluation_result.faithfulness_score,
                citation_accuracy_score=evaluation_result.citation_accuracy_score,
                answer_relevance_score=evaluation_result.answer_relevance_score,
                latency_ms=evaluation_result.latency_ms,
                metrics=metrics,
                failure_reason=failure_reason,
                failure_type=failure_type,
                details=details,
                created_at=evaluation_result.created_at,
                updated_at=evaluation_result.updated_at,
            )
        )

    raw_config = _normalize_mapping(evaluation_run.config)
    summary_value = raw_config.get("metrics_summary")
    summary = _normalize_mapping(summary_value) if isinstance(summary_value, dict) else None
    config_payload = dict(raw_config)
    config_payload.pop("metrics_summary", None)

    run_failure_reason: str | None = None
    run_failure_type: str | None = None
    if evaluation_run.status == EvaluationRunStatus.failed.value:
        for item in items:
            if item.status == "failed" and item.failure_reason is not None:
                run_failure_reason = item.failure_reason
                run_failure_type = item.failure_type
                break
        if run_failure_reason is None:
            run_failure_reason = "Evaluation run failed. Inspect question-level results for details."
            run_failure_type = "EvaluationRunFailed"

    log_evaluation_event(
        event="evaluation.run.detail.requested",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        job_id=str(evaluation_run.id),
        status_code=status.HTTP_200_OK,
        limit=limit,
        offset=offset,
        total=total,
        returned=len(items),
    )
    return EvaluationRunDetailResponse(
        evaluation_run_id=str(evaluation_run.id),
        evaluation_set_id=str(evaluation_run.evaluation_set_id),
        status=evaluation_run.status,
        config=config_payload,
        summary=summary,
        failure_reason=run_failure_reason,
        failure_type=run_failure_type,
        started_at=evaluation_run.started_at,
        completed_at=evaluation_run.completed_at,
        created_at=evaluation_run.created_at,
        updated_at=evaluation_run.updated_at,
        results=EvaluationRunResultListResponse(
            items=items,
            total=total,
            limit=limit,
            offset=offset,
        ),
    )
