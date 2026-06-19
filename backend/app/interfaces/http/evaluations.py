import csv
import io
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.evaluations.workflows import trigger_evaluation_workflow
from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.core.logging import log_evaluation_event
from app.db.session import get_db_session
from app.domains.admin.services.audit_service import AuditLogService
from app.domains.evaluations.benchmark_suites import (
    get_benchmark_suite,
    list_benchmark_suites,
)
from app.domains.evaluations.repositories.evaluations import EvaluationRepository
from app.domains.evaluations.schemas.evaluations import (
    _MIN_COVERAGE_WARNING_THRESHOLD,
    BenchmarkSuiteListResponse,
    BenchmarkSuiteResponse,
    CaseComparisonRow,
    EvaluationRunDetailResponse,
    EvaluationRunListResponse,
    EvaluationRunResultListResponse,
    EvaluationRunResultResponse,
    EvaluationRunSummaryResponse,
    LanguageBreakdownItem,
    LanguageBreakdownResponse,
    LocalModelMetrics,
    MetricDelta,
    ModelProfileComparisonReport,
    ProviderProfileSummary,
    RunComparisonResponse,
    RunEvaluationRequest,
    RunEvaluationResponse,
    TriggerBenchmarkRunRequest,
    TriggerBenchmarkRunResponse,
    _build_release_gate_recommendation,
)
from app.domains.evaluations.services.evaluation_metrics_service import score_language_adherence
from app.domains.quota.services.plan_enforcement_service import plan_enforcement_service
from app.models.enums import EvaluationRunStatus, OrganizationRole
from app.models.evaluation import EvaluationQuestion, EvaluationResult, EvaluationRun
from app.rate_limit import RateLimitScope, enforce_rate_limit
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


def _parse_evaluation_run_id(evaluation_run_id: str) -> UUID:
    try:
        return UUID(evaluation_run_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Evaluation run not found"
        ) from exc


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
    return await trigger_evaluation_workflow(
        request_id=request_id,
        payload=payload,
        principal=principal,
        organization_id=organization_id,
        user_id=user_id,
        db_session=db_session,
        evaluation_repository=evaluation_repository,
        audit_log_service=audit_log_service,
        plan_enforcement_service=plan_enforcement_service,
        run_evaluation_task=run_evaluation_task,
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Evaluation run not found"
        )

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
                detected_answer_language=evaluation_result.detected_answer_language,
                language_match_score=evaluation_result.language_match_score,
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
            run_failure_reason = (
                "Evaluation run failed. Inspect question-level results for details."
            )
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
        model_profile_key=evaluation_run.model_profile_key,
        provider_type=evaluation_run.provider_type,
        provider_profile=evaluation_run.provider_profile,
    )


# ---------------------------------------------------------------------------
# Run listing
# ---------------------------------------------------------------------------


@router.get("/runs", response_model=EvaluationRunListResponse)
async def list_evaluation_runs(
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
    evaluation_set_id: Annotated[str | None, Query()] = None,
    run_status: Annotated[str | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> EvaluationRunListResponse:
    organization_id = _organization_id_from_principal(principal)

    set_id_parsed: UUID | None = None
    if evaluation_set_id is not None:
        try:
            set_id_parsed = UUID(evaluation_set_id)
        except ValueError:
            pass

    valid_statuses = {s.value for s in EvaluationRunStatus}
    status_filter = run_status if run_status in valid_statuses else None

    runs = await evaluation_repository.list_evaluation_runs_for_organization(
        db_session,
        organization_id=organization_id,
        evaluation_set_id=set_id_parsed,
        status_filter=status_filter,
        limit=limit,
        offset=offset,
    )
    total = await evaluation_repository.count_evaluation_runs_for_organization(
        db_session,
        organization_id=organization_id,
        evaluation_set_id=set_id_parsed,
        status_filter=status_filter,
    )

    items = [_to_run_summary_response(run) for run in runs]
    log_evaluation_event(
        event="evaluation.runs.listed",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        status_code=status.HTTP_200_OK,
        total=total,
        returned=len(items),
        limit=limit,
        offset=offset,
    )
    return EvaluationRunListResponse(items=items, total=total, limit=limit, offset=offset)


# ---------------------------------------------------------------------------
# Comparison helpers
# ---------------------------------------------------------------------------

_COMPARISON_METRICS: list[tuple[str, str, bool]] = [
    ("retrieval_hit_rate", "Retrieval Hit Rate", True),
    ("citation_accuracy_score", "Citation Accuracy", True),
    ("faithfulness_score", "Faithfulness", True),
    ("answer_relevance_score", "Answer Relevance", True),
    ("not_found_rate", "Not-Found Rate", False),
    ("latency_ms_average", "Avg Latency (ms)", False),
    ("cost_usd_total", "Total Cost (USD)", False),
]

_METRIC_REGRESSION_THRESHOLD = 0.01
_CASE_SCORE_THRESHOLD = 0.1


def _extract_run_summary(run: EvaluationRun) -> dict[str, object]:
    raw_config = _normalize_mapping(run.config)
    summary_value = raw_config.get("metrics_summary")
    return _normalize_mapping(summary_value) if isinstance(summary_value, dict) else {}


def _extract_run_name(run: EvaluationRun) -> str | None:
    raw_config = _normalize_mapping(run.config)
    run_name = raw_config.get("run_name")
    return str(run_name).strip() if isinstance(run_name, str) and run_name.strip() else None


def _to_run_summary_response(run: EvaluationRun) -> EvaluationRunSummaryResponse:
    summary = _extract_run_summary(run)
    return EvaluationRunSummaryResponse(
        evaluation_run_id=str(run.id),
        evaluation_set_id=str(run.evaluation_set_id),
        run_name=_extract_run_name(run),
        status=run.status,
        summary=summary if summary else None,
        started_at=run.started_at,
        completed_at=run.completed_at,
        created_at=run.created_at,
        updated_at=run.updated_at,
        model_profile_key=run.model_profile_key,
        provider_type=run.provider_type,
        provider_profile=run.provider_profile,
    )


def _metric_float(summary: dict[str, object], key: str) -> float | None:
    value = summary.get(key)
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _compute_metric_deltas(
    summary_a: dict[str, object],
    summary_b: dict[str, object],
) -> list[MetricDelta]:
    deltas: list[MetricDelta] = []
    for metric_key, metric_label, higher_is_better in _COMPARISON_METRICS:
        val_a = _metric_float(summary_a, metric_key)
        val_b = _metric_float(summary_b, metric_key)
        if val_a is None and val_b is None:
            continue

        delta: float | None = None
        is_regression = False
        is_improvement = False
        if val_a is not None and val_b is not None:
            delta = val_b - val_a
            if abs(delta) > 1e-10:
                if higher_is_better:
                    is_regression = delta < -_METRIC_REGRESSION_THRESHOLD
                    is_improvement = delta > _METRIC_REGRESSION_THRESHOLD
                else:
                    is_regression = delta > _METRIC_REGRESSION_THRESHOLD
                    is_improvement = delta < -_METRIC_REGRESSION_THRESHOLD

        deltas.append(
            MetricDelta(
                metric=metric_key,
                label=metric_label,
                run_a_value=val_a,
                run_b_value=val_b,
                delta=delta,
                is_regression=is_regression,
                is_improvement=is_improvement,
            )
        )
    return deltas


def _result_pair_to_response(
    evaluation_result: EvaluationResult,
    evaluation_question: EvaluationQuestion,
) -> EvaluationRunResultResponse:
    details = _normalize_mapping(evaluation_result.details)
    metrics = _normalize_mapping(details.get("metrics"))
    status_value = details.get("status")
    if isinstance(status_value, str) and status_value.strip():
        normalized_status = status_value.strip()
    else:
        normalized_status = "failed" if details.get("error") else "completed"
    failure_reason, failure_type = _extract_failure_fields(details)
    return EvaluationRunResultResponse(
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


def _is_case_regression(
    resp_a: EvaluationRunResultResponse,
    resp_b: EvaluationRunResultResponse,
) -> bool:
    if resp_a.status == "completed" and resp_b.status == "failed":
        return True
    for attr in (
        "retrieval_score",
        "faithfulness_score",
        "citation_accuracy_score",
        "answer_relevance_score",
    ):
        val_a = getattr(resp_a, attr)
        val_b = getattr(resp_b, attr)
        if val_a is not None and val_b is not None and val_a - val_b > _CASE_SCORE_THRESHOLD:
            return True
    return False


def _is_case_improvement(
    resp_a: EvaluationRunResultResponse,
    resp_b: EvaluationRunResultResponse,
) -> bool:
    if resp_a.status == "failed" and resp_b.status == "completed":
        return True
    for attr in (
        "retrieval_score",
        "faithfulness_score",
        "citation_accuracy_score",
        "answer_relevance_score",
    ):
        val_a = getattr(resp_a, attr)
        val_b = getattr(resp_b, attr)
        if val_a is not None and val_b is not None and val_b - val_a > _CASE_SCORE_THRESHOLD:
            return True
    return False


def _build_case_rows(
    results_a: list[tuple[EvaluationResult, EvaluationQuestion]],
    results_b: list[tuple[EvaluationResult, EvaluationQuestion]],
    *,
    difficulty_filter: str | None,
    tags_filter: list[str],
    case_status_filter: str,
    failure_type_filter: str | None,
) -> list[CaseComparisonRow]:
    map_a: dict[str, tuple[EvaluationResult, EvaluationQuestion]] = {
        str(r.evaluation_question_id): (r, q) for r, q in results_a
    }
    map_b: dict[str, tuple[EvaluationResult, EvaluationQuestion]] = {
        str(r.evaluation_question_id): (r, q) for r, q in results_b
    }
    all_qids = sorted(set(map_a) | set(map_b))

    rows: list[CaseComparisonRow] = []
    for qid in all_qids:
        entry_a = map_a.get(qid)
        entry_b = map_b.get(qid)
        question_obj = (entry_a or entry_b)[1]  # type: ignore[index]

        raw_metadata = dict(question_obj.metadata_json or {})
        raw_tags = raw_metadata.get("tags", [])
        tags = [str(t).strip() for t in raw_tags if isinstance(t, str) and t.strip()]

        if difficulty_filter and question_obj.difficulty != difficulty_filter:
            continue
        if tags_filter and not any(tag in tags for tag in tags_filter):
            continue

        resp_a = _result_pair_to_response(*entry_a) if entry_a else None
        resp_b = _result_pair_to_response(*entry_b) if entry_b else None

        regression = False
        improvement = False
        if resp_a is not None and resp_b is not None:
            regression = _is_case_regression(resp_a, resp_b)
            improvement = _is_case_improvement(resp_a, resp_b)
        elif resp_a is None and resp_b is not None:
            improvement = True
        elif resp_a is not None and resp_b is None:
            regression = True

        if case_status_filter == "regression" and not regression:
            continue
        if case_status_filter == "improvement" and not improvement:
            continue
        if case_status_filter == "failed_any":
            a_failed = resp_a is not None and resp_a.status == "failed"
            b_failed = resp_b is not None and resp_b.status == "failed"
            if not (a_failed or b_failed):
                continue

        if failure_type_filter:
            a_type = resp_a.failure_type if resp_a else None
            b_type = resp_b.failure_type if resp_b else None
            if a_type != failure_type_filter and b_type != failure_type_filter:
                continue

        rows.append(
            CaseComparisonRow(
                evaluation_question_id=qid,
                question=question_obj.question,
                difficulty=question_obj.difficulty,
                tags=tags,
                run_a=resp_a,
                run_b=resp_b,
                regression=regression,
                improvement=improvement,
            )
        )
    return rows


async def _resolve_comparison(
    *,
    run_a_id_str: str,
    run_b_id_str: str,
    organization_id: UUID,
    db_session: AsyncSession,
    difficulty_filter: str | None,
    tags_filter: list[str],
    case_status_filter: str,
    failure_type_filter: str | None,
) -> RunComparisonResponse:
    try:
        parsed_a = UUID(run_a_id_str)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Baseline run not found"
        ) from exc
    try:
        parsed_b = UUID(run_b_id_str)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Comparison run not found"
        ) from exc

    run_a_obj = await evaluation_repository.get_evaluation_run_for_organization(
        db_session, evaluation_run_id=parsed_a, organization_id=organization_id
    )
    if run_a_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Baseline run not found")

    run_b_obj = await evaluation_repository.get_evaluation_run_for_organization(
        db_session, evaluation_run_id=parsed_b, organization_id=organization_id
    )
    if run_b_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Comparison run not found"
        )

    results_a = await evaluation_repository.list_all_evaluation_results_for_run(
        db_session, evaluation_run_id=run_a_obj.id
    )
    results_b = await evaluation_repository.list_all_evaluation_results_for_run(
        db_session, evaluation_run_id=run_b_obj.id
    )

    summary_a = _extract_run_summary(run_a_obj)
    summary_b = _extract_run_summary(run_b_obj)
    metric_deltas = _compute_metric_deltas(summary_a, summary_b)

    cases = _build_case_rows(
        results_a,
        results_b,
        difficulty_filter=difficulty_filter,
        tags_filter=tags_filter,
        case_status_filter=case_status_filter,
        failure_type_filter=failure_type_filter,
    )

    regression_count = sum(1 for c in cases if c.regression)
    improvement_count = sum(1 for c in cases if c.improvement)

    filters_applied: dict[str, object] = {}
    if difficulty_filter:
        filters_applied["difficulty"] = difficulty_filter
    if tags_filter:
        filters_applied["tags"] = tags_filter
    if case_status_filter != "all":
        filters_applied["case_status"] = case_status_filter
    if failure_type_filter:
        filters_applied["failure_type"] = failure_type_filter

    return RunComparisonResponse(
        run_a=_to_run_summary_response(run_a_obj),
        run_b=_to_run_summary_response(run_b_obj),
        metric_deltas=metric_deltas,
        regression_count=regression_count,
        improvement_count=improvement_count,
        cases=cases,
        total_cases=len(cases),
        filters_applied=filters_applied,
    )


# ---------------------------------------------------------------------------
# Comparison endpoints
# ---------------------------------------------------------------------------


@router.get("/compare", response_model=RunComparisonResponse)
async def compare_evaluation_runs(
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
    run_a: Annotated[str, Query(description="Baseline run ID")],
    run_b: Annotated[str, Query(description="Comparison run ID")],
    difficulty: Annotated[str | None, Query()] = None,
    tags: Annotated[str | None, Query(description="Comma-separated tag filter")] = None,
    case_status: Annotated[
        str,
        Query(description="all | regression | improvement | failed_any"),
    ] = "all",
    failure_type: Annotated[str | None, Query()] = None,
) -> RunComparisonResponse:
    organization_id = _organization_id_from_principal(principal)
    tags_filter = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    valid_case_statuses = {"all", "regression", "improvement", "failed_any"}
    resolved_case_status = case_status if case_status in valid_case_statuses else "all"

    comparison = await _resolve_comparison(
        run_a_id_str=run_a,
        run_b_id_str=run_b,
        organization_id=organization_id,
        db_session=db_session,
        difficulty_filter=difficulty,
        tags_filter=tags_filter,
        case_status_filter=resolved_case_status,
        failure_type_filter=failure_type,
    )
    log_evaluation_event(
        event="evaluation.comparison.requested",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        status_code=status.HTTP_200_OK,
        regression_count=comparison.regression_count,
        improvement_count=comparison.improvement_count,
        total_cases=comparison.total_cases,
    )
    return comparison


@router.get("/compare/export")
async def export_comparison_report(
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
    run_a: Annotated[str, Query(description="Baseline run ID")],
    run_b: Annotated[str, Query(description="Comparison run ID")],
    export_format: Annotated[Literal["csv", "json"], Query(alias="format")] = "csv",
) -> Response:
    organization_id = _organization_id_from_principal(principal)
    comparison = await _resolve_comparison(
        run_a_id_str=run_a,
        run_b_id_str=run_b,
        organization_id=organization_id,
        db_session=db_session,
        difficulty_filter=None,
        tags_filter=[],
        case_status_filter="all",
        failure_type_filter=None,
    )

    if export_format == "json":
        log_evaluation_event(
            event="evaluation.comparison.exported",
            organization_id=principal.organization_id,
            user_id=principal.user_id,
            status_code=status.HTTP_200_OK,
            format="json",
        )
        return Response(
            content=comparison.model_dump_json(indent=2),
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=comparison.json"},
        )

    run_a_label = comparison.run_a.run_name or comparison.run_a.evaluation_run_id[:8]
    run_b_label = comparison.run_b.run_name or comparison.run_b.evaluation_run_id[:8]

    buffer = io.StringIO()
    writer = csv.writer(buffer)

    writer.writerow(["# Evaluation Run Comparison Report"])
    writer.writerow(["Run A", run_a_label, comparison.run_a.evaluation_run_id])
    writer.writerow(["Run B", run_b_label, comparison.run_b.evaluation_run_id])
    writer.writerow([])

    writer.writerow(["## Metric Summary"])
    writer.writerow(
        ["Metric", f"Run A ({run_a_label})", f"Run B ({run_b_label})", "Delta", "Status"]
    )
    for delta in comparison.metric_deltas:
        if delta.is_regression:
            delta_status = "regression"
        elif delta.is_improvement:
            delta_status = "improvement"
        else:
            delta_status = "unchanged"
        val_a = f"{delta.run_a_value:.4f}" if delta.run_a_value is not None else ""
        val_b = f"{delta.run_b_value:.4f}" if delta.run_b_value is not None else ""
        delta_str = f"{delta.delta:+.4f}" if delta.delta is not None else ""
        writer.writerow([delta.label, val_a, val_b, delta_str, delta_status])

    writer.writerow([])
    writer.writerow(
        [
            f"Regressions: {comparison.regression_count}",
            f"Improvements: {comparison.improvement_count}",
        ]
    )
    writer.writerow([])

    writer.writerow(["## Case Comparison"])
    writer.writerow(
        [
            "Question",
            "Difficulty",
            "Tags",
            f"Run A Status ({run_a_label})",
            "Run A Score",
            f"Run B Status ({run_b_label})",
            "Run B Score",
            "Status",
        ]
    )
    for case in comparison.cases:
        if case.regression:
            case_status_str = "regression"
        elif case.improvement:
            case_status_str = "improvement"
        else:
            case_status_str = "unchanged"

        a_status = case.run_a.status if case.run_a else ""
        a_score = (
            f"{case.run_a.retrieval_score:.3f}"
            if case.run_a and case.run_a.retrieval_score is not None
            else ""
        )
        b_status = case.run_b.status if case.run_b else ""
        b_score = (
            f"{case.run_b.retrieval_score:.3f}"
            if case.run_b and case.run_b.retrieval_score is not None
            else ""
        )
        writer.writerow(
            [
                case.question[:120],
                case.difficulty or "",
                ",".join(case.tags),
                a_status,
                a_score,
                b_status,
                b_score,
                case_status_str,
            ]
        )

    log_evaluation_event(
        event="evaluation.comparison.exported",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        status_code=status.HTTP_200_OK,
        format="csv",
    )
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=comparison.csv"},
    )


# ---------------------------------------------------------------------------
# F226 — Benchmark suites and model-profile comparison
# ---------------------------------------------------------------------------


@router.get("/benchmark-suites", response_model=BenchmarkSuiteListResponse)
async def list_benchmark_suite_catalog(
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
) -> BenchmarkSuiteListResponse:
    suites = list_benchmark_suites()
    items = [
        BenchmarkSuiteResponse(
            suite_id=s.suite_id,
            name=s.name,
            description=s.description,
            quality_dimension=s.quality_dimension,
            case_count=len(s.cases),
        )
        for s in suites
    ]
    return BenchmarkSuiteListResponse(items=items, total=len(items))


@router.post(
    "/benchmark-suites/{suite_id}/run",
    response_model=TriggerBenchmarkRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_benchmark_run(
    suite_id: str,
    payload: TriggerBenchmarkRunRequest,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    _: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.evaluation))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> TriggerBenchmarkRunResponse:
    suite = get_benchmark_suite(suite_id)
    if suite is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Benchmark suite not found"
        )

    organization_id = _organization_id_from_principal(principal)
    user_id = _user_id_from_principal(principal)

    # Resolve or create the evaluation set for this benchmark suite.
    set_id_str = payload.evaluation_set_id
    if set_id_str is not None:
        try:
            set_uuid = UUID(set_id_str)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="evaluation_set_id is not a valid UUID",
            ) from exc
        eval_set = await evaluation_repository.get_evaluation_set(
            db_session, evaluation_set_id=set_uuid, organization_id=organization_id
        )
        if eval_set is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Evaluation set not found"
            )
    else:
        eval_set = await evaluation_repository.create_evaluation_set(
            db_session,
            organization_id=organization_id,
            name=f"[Benchmark] {suite.name}",
            description=suite.description,
            owner_id=user_id,
        )
        for case in suite.cases:
            await evaluation_repository.create_evaluation_question(
                db_session,
                evaluation_set_id=eval_set.id,
                question=case.question,
                expected_answer=case.expected_answer,
                difficulty=case.difficulty,
                metadata={"tags": case.tags},
                question_language=case.question_language,
                expected_answer_language=case.expected_answer_language,
                source_language=case.source_language,
            )
        await db_session.flush()

    active = await evaluation_repository.count_active_runs_for_set(
        db_session, evaluation_set_id=eval_set.id
    )
    if active > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An active evaluation run already exists for this set. Wait for it to complete.",
        )

    run_config: dict = {
        "run_name": f"[{payload.provider_profile}] {suite.name}",
        "top_k": payload.top_k,
        "rerank": payload.rerank,
        "benchmark_suite_id": suite_id,
        "provider_profile_label": payload.provider_profile,
    }
    evaluation_run = await evaluation_repository.create_evaluation_run(
        db_session,
        evaluation_set_id=eval_set.id,
        config=run_config,
    )
    evaluation_run.provider_profile = payload.provider_profile
    await db_session.flush()

    run_evaluation_task.delay(str(evaluation_run.id))

    log_evaluation_event(
        event="evaluation.benchmark.triggered",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        job_id=str(evaluation_run.id),
        status_code=status.HTTP_202_ACCEPTED,
        suite_id=suite_id,
        provider_profile=payload.provider_profile,
    )
    return TriggerBenchmarkRunResponse(
        evaluation_run_id=str(evaluation_run.id),
        suite_id=suite_id,
        provider_profile=payload.provider_profile,
    )


def _extract_local_model_metrics(summary: dict[str, object]) -> LocalModelMetrics:
    def _f(key: str) -> float | None:
        v = summary.get(key)
        if v is None or isinstance(v, bool):
            return None
        if isinstance(v, (int, float)):
            return float(v)
        return None

    return LocalModelMetrics(
        invalid_json_rate=_f("invalid_json_rate"),
        timeout_rate=_f("timeout_rate"),
        fallback_frequency=_f("fallback_frequency"),
        estimated_compute_latency_ms=_f("estimated_compute_latency_ms"),
        tokens_per_second=_f("tokens_per_second"),
    )


def _aggregate_provider_profile_summary(
    runs: list[EvaluationRun],
    profile_label: str,
) -> ProviderProfileSummary:
    profile_runs = [r for r in runs if r.provider_profile == profile_label]
    if not profile_runs:
        return ProviderProfileSummary(
            provider_profile=profile_label,
            run_count=0,
        )

    metrics_keys = [
        "retrieval_hit_rate",
        "citation_accuracy_score",
        "faithfulness_score",
        "answer_relevance_score",
        "not_found_rate",
        "latency_ms_average",
        "cost_usd_total",
    ]

    accum: dict[str, list[float]] = {k: [] for k in metrics_keys}
    local_accum: dict[str, list[float]] = {
        "invalid_json_rate": [],
        "timeout_rate": [],
        "fallback_frequency": [],
        "estimated_compute_latency_ms": [],
        "tokens_per_second": [],
    }
    latest_run_id: str | None = None
    provider_type: str | None = None

    for run in profile_runs:
        if latest_run_id is None:
            latest_run_id = str(run.id)
            provider_type = run.provider_type
        raw_config = run.config if isinstance(run.config, dict) else {}
        summary_value = raw_config.get("metrics_summary")
        summary = summary_value if isinstance(summary_value, dict) else {}

        for k in metrics_keys:
            v = summary.get(k)
            if v is not None and not isinstance(v, bool) and isinstance(v, (int, float)):
                accum[k].append(float(v))

        for k in local_accum:
            v = summary.get(k)
            if v is not None and not isinstance(v, bool) and isinstance(v, (int, float)):
                local_accum[k].append(float(v))

    def _avg(values: list[float]) -> float | None:
        return sum(values) / len(values) if values else None

    local_metrics_obj = LocalModelMetrics(
        invalid_json_rate=_avg(local_accum["invalid_json_rate"]),
        timeout_rate=_avg(local_accum["timeout_rate"]),
        fallback_frequency=_avg(local_accum["fallback_frequency"]),
        estimated_compute_latency_ms=_avg(local_accum["estimated_compute_latency_ms"]),
        tokens_per_second=_avg(local_accum["tokens_per_second"]),
    )
    has_local = any(
        v is not None
        for v in [
            local_metrics_obj.invalid_json_rate,
            local_metrics_obj.timeout_rate,
            local_metrics_obj.fallback_frequency,
        ]
    )

    return ProviderProfileSummary(
        provider_profile=profile_label,
        provider_type=provider_type,
        run_count=len(profile_runs),
        latest_run_id=latest_run_id,
        retrieval_hit_rate=_avg(accum["retrieval_hit_rate"]),
        citation_accuracy_score=_avg(accum["citation_accuracy_score"]),
        faithfulness_score=_avg(accum["faithfulness_score"]),
        answer_relevance_score=_avg(accum["answer_relevance_score"]),
        not_found_rate=_avg(accum["not_found_rate"]),
        latency_ms_average=_avg(accum["latency_ms_average"]),
        cost_usd_total=_avg(accum["cost_usd_total"]),
        local_model_metrics=local_metrics_obj if has_local else None,
    )


@router.get("/model-profile-report", response_model=ModelProfileComparisonReport)
async def get_model_profile_comparison_report(
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
    evaluation_set_id: Annotated[str | None, Query()] = None,
) -> ModelProfileComparisonReport:
    organization_id = _organization_id_from_principal(principal)

    set_uuid: UUID | None = None
    if evaluation_set_id is not None:
        try:
            set_uuid = UUID(evaluation_set_id)
        except ValueError:
            pass

    runs = await evaluation_repository.list_runs_by_provider_profile_for_org(
        db_session,
        organization_id=organization_id,
        evaluation_set_id=set_uuid,
    )

    profile_labels = ["cloud_baseline", "local_profile", "fallback_profile"]
    profiles = [
        _aggregate_provider_profile_summary(runs, label)
        for label in profile_labels
        if any(r.provider_profile == label for r in runs)
        or label in ("cloud_baseline", "local_profile")
    ]

    recommendations = [
        _build_release_gate_recommendation(p)
        for p in profiles
        if p.provider_profile != "cloud_baseline" and p.run_count > 0
    ]

    log_evaluation_event(
        event="evaluation.model_profile_report.requested",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        status_code=status.HTTP_200_OK,
        profile_count=len(profiles),
    )
    return ModelProfileComparisonReport(
        organization_id=principal.organization_id or "",
        evaluation_set_id=evaluation_set_id,
        profiles=profiles,
        release_gate_recommendations=recommendations,
        generated_at=datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# F234 — Language breakdown endpoint
# ---------------------------------------------------------------------------


def _mean_floats(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


@router.get(
    "/runs/{evaluation_run_id}/language-breakdown", response_model=LanguageBreakdownResponse
)
async def get_language_breakdown(
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
) -> LanguageBreakdownResponse:
    organization_id = _organization_id_from_principal(principal)
    parsed_run_id = _parse_evaluation_run_id(evaluation_run_id)

    evaluation_run = await evaluation_repository.get_evaluation_run_for_organization(
        db_session,
        evaluation_run_id=parsed_run_id,
        organization_id=organization_id,
    )
    if evaluation_run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Evaluation run not found"
        )

    pairs = await evaluation_repository.get_results_with_questions_for_run(
        db_session,
        evaluation_run_id=parsed_run_id,
    )

    # Group result-question pairs by question_language.
    buckets: dict[str, list[tuple]] = {}
    for result, question in pairs:
        lang = question.question_language or "unlabelled"
        buckets.setdefault(lang, []).append((result, question))

    items: list[LanguageBreakdownItem] = []
    coverage_warning_languages: list[str] = []

    for lang, rows in sorted(buckets.items()):
        total = len(rows)
        successes = [
            (r, q) for r, q in rows if not (isinstance(r.details, dict) and r.details.get("error"))
        ]
        success_count = len(successes)

        retrieval_vals: list[float] = []
        citation_vals: list[float] = []
        faithfulness_vals: list[float] = []
        relevance_vals: list[float] = []
        latency_vals: list[float] = []
        cost_vals: list[float] = []
        not_found_flags: list[float] = []
        lang_match_vals: list[float] = []

        for result, question in successes:
            if result.retrieval_score is not None:
                retrieval_vals.append(result.retrieval_score)
            if result.citation_accuracy_score is not None:
                citation_vals.append(result.citation_accuracy_score)
            if result.faithfulness_score is not None:
                faithfulness_vals.append(result.faithfulness_score)
            if result.answer_relevance_score is not None:
                relevance_vals.append(result.answer_relevance_score)
            if result.latency_ms is not None:
                latency_vals.append(float(result.latency_ms))
            details = result.details if isinstance(result.details, dict) else {}
            cost = details.get("cost_usd")
            if cost is not None and isinstance(cost, (int, float)):
                cost_vals.append(float(cost))
            not_found = details.get("not_found")
            not_found_flags.append(1.0 if not_found else 0.0)

            # Language adherence: use stored column if available, else compute.
            if result.language_match_score is not None:
                lang_match_vals.append(result.language_match_score)
            elif result.detected_answer_language is not None and question.expected_answer_language:
                score = (
                    1.0
                    if result.detected_answer_language == question.expected_answer_language
                    else 0.0
                )
                lang_match_vals.append(score)
            elif question.expected_answer_language and result.generated_answer:
                _, match_score = score_language_adherence(
                    result.generated_answer, question.expected_answer_language
                )
                if match_score is not None:
                    lang_match_vals.append(match_score)

        insufficient = lang != "unlabelled" and total < _MIN_COVERAGE_WARNING_THRESHOLD
        if insufficient:
            coverage_warning_languages.append(lang)

        items.append(
            LanguageBreakdownItem(
                language=lang,
                question_count=total,
                success_count=success_count,
                retrieval_hit_rate=_mean_floats(retrieval_vals),
                citation_accuracy_score=_mean_floats(citation_vals),
                faithfulness_score=_mean_floats(faithfulness_vals),
                answer_relevance_score=_mean_floats(relevance_vals),
                not_found_rate=_mean_floats(not_found_flags),
                language_adherence_score=_mean_floats(lang_match_vals),
                latency_ms_average=_mean_floats(latency_vals),
                cost_usd_total=round(sum(cost_vals), 6) if cost_vals else None,
                has_insufficient_coverage=insufficient,
            )
        )

    log_evaluation_event(
        event="evaluation.language_breakdown.requested",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        job_id=evaluation_run_id,
        status_code=status.HTTP_200_OK,
        language_count=len(items),
    )
    return LanguageBreakdownResponse(
        evaluation_run_id=evaluation_run_id,
        items=items,
        coverage_warning_languages=sorted(coverage_warning_languages),
    )
