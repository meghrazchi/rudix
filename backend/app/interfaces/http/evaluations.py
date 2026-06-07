import csv
import io
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
from app.domains.evaluations.repositories.evaluations import EvaluationRepository
from app.domains.evaluations.schemas.evaluations import (
    CaseComparisonRow,
    EvaluationRunDetailResponse,
    EvaluationRunListResponse,
    EvaluationRunResultListResponse,
    EvaluationRunResultResponse,
    EvaluationRunSummaryResponse,
    MetricDelta,
    RunComparisonResponse,
    RunEvaluationRequest,
    RunEvaluationResponse,
)
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
