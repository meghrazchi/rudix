from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.safety_evals.workflows import trigger_safety_eval_workflow
from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.core.logging import log_evaluation_event
from app.db.session import get_db_session
from app.domains.admin.services.audit_service import AuditLogService
from app.domains.safety_evals.repositories.safety_evals import SafetyEvalRepository
from app.domains.safety_evals.schemas.safety_evals import (
    CreateSafetyEvalCaseRequest,
    SafetyEvalCaseListResponse,
    SafetyEvalCaseResponse,
    SafetyEvalReportResponse,
    SafetyEvalResultListResponse,
    SafetyEvalResultResponse,
    SafetyEvalRunDetailResponse,
    SafetyEvalRunListResponse,
    SafetyEvalRunResponse,
    TriggerSafetyEvalRunRequest,
    TriggerSafetyEvalRunResponse,
)
from app.models.enums import OrganizationRole
from app.models.safety_eval import SafetyEvalCase, SafetyEvalRun
from app.rate_limit import RateLimitScope, enforce_rate_limit
from app.workers.safety_eval_tasks import run_safety_eval as run_safety_eval_task

router = APIRouter(prefix="/safety-evals", tags=["safety-evals"])
_safety_eval_repository = SafetyEvalRepository()
_audit_log_service = AuditLogService()


def _org_id(principal: AuthenticatedPrincipal) -> UUID:
    if principal.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No active organization context",
        )
    try:
        return UUID(principal.organization_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid organization context",
        ) from exc


def _user_id(principal: AuthenticatedPrincipal) -> UUID:
    try:
        return UUID(principal.user_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid user context",
        ) from exc


def _parse_run_id(run_id: str) -> UUID:
    try:
        return UUID(run_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Safety eval run not found",
        ) from exc


def _request_id(request: Request) -> str | None:
    rid = getattr(request.state, "request_id", None)
    if isinstance(rid, str) and rid.strip():
        return rid
    return request.headers.get("x-request-id")


def _case_response(case: SafetyEvalCase) -> SafetyEvalCaseResponse:
    return SafetyEvalCaseResponse(
        case_id=str(case.id),
        suite_name=case.suite_name,
        violation_type=case.violation_type,
        name=case.name,
        description=case.description,
        prompt_text=case.prompt_text,
        severity=case.severity,
        metadata=case.metadata_json if isinstance(case.metadata_json, dict) else {},
        created_at=case.created_at,
        updated_at=case.updated_at,
    )


def _run_response(run: SafetyEvalRun) -> SafetyEvalRunResponse:
    pass_count = run.pass_count
    total_count = run.total_count
    pass_rate = (
        round(pass_count / total_count, 4)
        if pass_count is not None and total_count is not None and total_count > 0
        else None
    )
    return SafetyEvalRunResponse(
        run_id=str(run.id),
        status=run.status,
        suite_name=run.suite_name,
        pass_count=run.pass_count,
        fail_count=run.fail_count,
        total_count=run.total_count,
        pass_rate=pass_rate,
        started_at=run.started_at,
        completed_at=run.completed_at,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------


@router.post(
    "/cases",
    response_model=SafetyEvalCaseResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_safety_eval_case(
    request: Request,
    payload: CreateSafetyEvalCaseRequest,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    _: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> SafetyEvalCaseResponse:
    organization_id = _org_id(principal)
    user_id = _user_id(principal)
    case = await _safety_eval_repository.create_case(
        db_session,
        organization_id=organization_id,
        suite_name=payload.suite_name,
        violation_type=payload.violation_type,
        name=payload.name,
        prompt_text=payload.prompt_text,
        severity=payload.severity,
        description=payload.description,
        metadata=dict(payload.metadata),
    )
    await db_session.commit()
    await db_session.refresh(case)

    wrote_audit = await _audit_log_service.record(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        action="safety_eval.case.created",
        resource_type="safety_eval_case",
        resource_id=case.id,
        request_id=_request_id(request),
        metadata={"suite_name": payload.suite_name, "violation_type": payload.violation_type},
    )
    if wrote_audit:
        await db_session.commit()

    log_evaluation_event(
        event="safety_eval.case.created",
        organization_id=str(organization_id),
        user_id=str(user_id),
        job_id=str(case.id),
        status_code=status.HTTP_201_CREATED,
    )
    return _case_response(case)


@router.get("/cases", response_model=SafetyEvalCaseListResponse)
async def list_safety_eval_cases(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(
            require_roles(
                OrganizationRole.owner.value,
                OrganizationRole.admin.value,
                OrganizationRole.member.value,
            )
        ),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    suite_name: Annotated[str | None, Query(max_length=255)] = None,
    violation_type: Annotated[str | None, Query(max_length=64)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SafetyEvalCaseListResponse:
    organization_id = _org_id(principal)
    cases = await _safety_eval_repository.list_cases(
        db_session,
        organization_id=organization_id,
        suite_name=suite_name,
        violation_type=violation_type,
        limit=limit,
        offset=offset,
    )
    total = await _safety_eval_repository.count_cases(
        db_session,
        organization_id=organization_id,
        suite_name=suite_name,
        violation_type=violation_type,
    )
    return SafetyEvalCaseListResponse(
        items=[_case_response(c) for c in cases],
        total=total,
        limit=limit,
        offset=offset,
    )


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


@router.post(
    "/runs",
    response_model=TriggerSafetyEvalRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_safety_eval_run(
    request: Request,
    payload: TriggerSafetyEvalRunRequest,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    _: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.evaluation))],
    __: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> TriggerSafetyEvalRunResponse:
    organization_id = _org_id(principal)
    user_id = _user_id(principal)
    return await trigger_safety_eval_workflow(
        request_id=_request_id(request),
        payload=payload,
        principal=principal,
        organization_id=organization_id,
        user_id=user_id,
        db_session=db_session,
        safety_eval_repository=_safety_eval_repository,
        audit_log_service=_audit_log_service,
        run_safety_eval_task=run_safety_eval_task,
    )


@router.get("/runs", response_model=SafetyEvalRunListResponse)
async def list_safety_eval_runs(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(
            require_roles(
                OrganizationRole.owner.value,
                OrganizationRole.admin.value,
                OrganizationRole.member.value,
            )
        ),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    suite_name: Annotated[str | None, Query(max_length=255)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SafetyEvalRunListResponse:
    organization_id = _org_id(principal)
    runs = await _safety_eval_repository.list_runs(
        db_session,
        organization_id=organization_id,
        suite_name=suite_name,
        limit=limit,
        offset=offset,
    )
    total = await _safety_eval_repository.count_runs(
        db_session,
        organization_id=organization_id,
        suite_name=suite_name,
    )
    return SafetyEvalRunListResponse(
        items=[_run_response(r) for r in runs],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/runs/{run_id}", response_model=SafetyEvalRunDetailResponse)
async def get_safety_eval_run_detail(
    run_id: str,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(
            require_roles(
                OrganizationRole.owner.value,
                OrganizationRole.admin.value,
                OrganizationRole.member.value,
            )
        ),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SafetyEvalRunDetailResponse:
    organization_id = _org_id(principal)
    parsed_run_id = _parse_run_id(run_id)
    run = await _safety_eval_repository.get_run_by_id(
        db_session,
        run_id=parsed_run_id,
        organization_id=organization_id,
    )
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Safety eval run not found",
        )

    raw_results = await _safety_eval_repository.list_results_for_run(
        db_session,
        run_id=parsed_run_id,
        limit=limit,
        offset=offset,
    )
    total_results = await _safety_eval_repository.count_results_for_run(
        db_session,
        run_id=parsed_run_id,
    )

    result_items: list[SafetyEvalResultResponse] = []
    for r in raw_results:
        details = r.details if isinstance(r.details, dict) else {}
        result_items.append(
            SafetyEvalResultResponse(
                result_id=str(r.id),
                case_id=str(r.safety_eval_case_id),
                case_name=details.get("case_name", ""),
                suite_name=details.get("case_suite", ""),
                violation_type=r.violation_type or "",
                severity=details.get("case_severity", ""),
                passed=r.passed,
                violation_detected=r.violation_detected,
                violation_type_detected=r.violation_type,
                score=r.score,
                latency_ms=r.latency_ms,
                details=details,
                created_at=r.created_at,
            )
        )

    pass_count = run.pass_count
    total_count = run.total_count
    pass_rate = (
        round(pass_count / total_count, 4)
        if pass_count is not None and total_count is not None and total_count > 0
        else None
    )
    return SafetyEvalRunDetailResponse(
        run_id=str(run.id),
        status=run.status,
        suite_name=run.suite_name,
        config=run.config if isinstance(run.config, dict) else {},
        pass_count=run.pass_count,
        fail_count=run.fail_count,
        total_count=run.total_count,
        pass_rate=pass_rate,
        summary=run.summary if isinstance(run.summary, dict) else {},
        started_at=run.started_at,
        completed_at=run.completed_at,
        created_at=run.created_at,
        updated_at=run.updated_at,
        results=SafetyEvalResultListResponse(
            items=result_items,
            total=total_results,
            limit=limit,
            offset=offset,
        ),
    )


@router.get("/runs/{run_id}/report", response_model=SafetyEvalReportResponse)
async def get_safety_eval_report(
    run_id: str,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(
            require_roles(
                OrganizationRole.owner.value,
                OrganizationRole.admin.value,
                OrganizationRole.member.value,
            )
        ),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> SafetyEvalReportResponse:
    organization_id = _org_id(principal)
    parsed_run_id = _parse_run_id(run_id)
    run = await _safety_eval_repository.get_run_by_id(
        db_session,
        run_id=parsed_run_id,
        organization_id=organization_id,
    )
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Safety eval run not found",
        )
    if run.status not in ("completed", "failed"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Safety eval run has not completed yet",
        )

    summary = run.summary if isinstance(run.summary, dict) else {}
    pass_count = run.pass_count or 0
    fail_count = run.fail_count or 0
    total_count = run.total_count or 0
    pass_rate = round(pass_count / total_count, 4) if total_count > 0 else 0.0
    baseline_pass_rate = summary.get("baseline_pass_rate")
    regression_threshold = summary.get("regression_threshold")
    regression_detected = bool(summary.get("regression_detected", False))

    by_violation_type = summary.get("by_violation_type", {})
    by_severity = summary.get("by_severity", {})
    failed_cases = summary.get("failed_cases", [])

    if not isinstance(baseline_pass_rate, (int, float)):
        baseline_pass_rate = None
    if not isinstance(regression_threshold, (int, float)):
        regression_threshold = None

    return SafetyEvalReportResponse(
        run_id=str(run.id),
        status=run.status,
        generated_at=datetime.now(tz=UTC),
        suite_name=run.suite_name,
        total_cases=total_count,
        pass_count=pass_count,
        fail_count=fail_count,
        pass_rate=pass_rate,
        baseline_pass_rate=baseline_pass_rate,
        regression_detected=regression_detected,
        regression_threshold=regression_threshold,
        by_violation_type=by_violation_type if isinstance(by_violation_type, dict) else {},
        by_severity=by_severity if isinstance(by_severity, dict) else {},
        failed_cases=failed_cases if isinstance(failed_cases, list) else [],
        summary=summary,
    )
