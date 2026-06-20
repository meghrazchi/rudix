from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.core.logging import log_evaluation_event
from app.db.session import get_db_session
from app.domains.admin.services.audit_service import AuditLogService
from app.domains.evaluations.repositories.evaluations import EvaluationRepository
from app.domains.quality_gates.repositories.quality_gates import QualityGateRepository
from app.domains.quality_gates.schemas.quality_gates import (
    BaselineMetricDelta,
    CreateQualityGateRequest,
    GateCheckResult,
    QualityGateListResponse,
    QualityGateOverrideRequest,
    QualityGateReportResponse,
    QualityGateResponse,
    QualityGateRunListResponse,
    QualityGateRunResponse,
    QualityGateThresholds,
    TriggerQualityGateRunRequest,
    UpdateQualityGateRequest,
)
from app.domains.quality_gates.services.quality_gate_service import (
    build_gate_report,
    evaluate_gate,
    evaluate_regression,
)
from app.domains.safety_evals.repositories.safety_evals import SafetyEvalRepository
from app.models.enums import OrganizationRole, QualityGateVerdict
from app.models.quality_gate import QualityGate, QualityGateRun

router = APIRouter(prefix="/quality-gates", tags=["quality-gates"])

_gate_repo = QualityGateRepository()
_eval_repo = EvaluationRepository()
_safety_repo = SafetyEvalRepository()
_audit_service = AuditLogService()


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


def _parse_uuid(value: str, label: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"{label} not found"
        ) from exc


def _request_id(request: Request) -> str | None:
    rid = getattr(request.state, "request_id", None)
    if isinstance(rid, str) and rid.strip():
        return rid
    return request.headers.get("x-request-id")


def _gate_to_response(gate: QualityGate) -> QualityGateResponse:
    return QualityGateResponse(
        quality_gate_id=str(gate.id),
        name=gate.name,
        description=gate.description,
        thresholds=dict(gate.thresholds or {}),
        baseline_evaluation_run_id=(
            str(gate.baseline_evaluation_run_id) if gate.baseline_evaluation_run_id else None
        ),
        baseline_safety_run_id=(
            str(gate.baseline_safety_run_id) if gate.baseline_safety_run_id else None
        ),
        created_by_id=str(gate.created_by_id) if gate.created_by_id else None,
        created_at=gate.created_at,
        updated_at=gate.updated_at,
    )


def _gate_run_to_response(gate_run: QualityGateRun) -> QualityGateRunResponse:
    report = dict(gate_run.report or {})
    passed_checks = [GateCheckResult(**c) for c in report.get("passed_checks", [])]
    failed_checks = [GateCheckResult(**c) for c in report.get("failed_checks", [])]
    return QualityGateRunResponse(
        gate_run_id=str(gate_run.id),
        quality_gate_id=str(gate_run.quality_gate_id),
        evaluation_run_id=(str(gate_run.evaluation_run_id) if gate_run.evaluation_run_id else None),
        safety_eval_run_id=(
            str(gate_run.safety_eval_run_id) if gate_run.safety_eval_run_id else None
        ),
        verdict=gate_run.verdict,  # type: ignore[arg-type]
        passed_checks=passed_checks,
        failed_checks=failed_checks,
        override_reason=gate_run.override_reason,
        overridden_by_id=(str(gate_run.overridden_by_id) if gate_run.overridden_by_id else None),
        overridden_at=gate_run.overridden_at,
        created_at=gate_run.created_at,
        updated_at=gate_run.updated_at,
    )


# ---------------------------------------------------------------------------
# CRUD endpoints
# ---------------------------------------------------------------------------


@router.post("", response_model=QualityGateResponse, status_code=status.HTTP_201_CREATED)
async def create_quality_gate(
    request: Request,
    payload: CreateQualityGateRequest,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> QualityGateResponse:
    organization_id = _org_id(principal)
    user_id = _user_id(principal)
    request_id = _request_id(request)

    baseline_eval_run_uuid: UUID | None = None
    if payload.baseline_evaluation_run_id:
        baseline_eval_run_uuid = _parse_uuid(
            payload.baseline_evaluation_run_id, "Baseline evaluation run"
        )
        run = await _eval_repo.get_evaluation_run_for_organization(
            db_session,
            evaluation_run_id=baseline_eval_run_uuid,
            organization_id=organization_id,
        )
        if run is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Baseline evaluation run not found",
            )

    baseline_safety_uuid: UUID | None = None
    if payload.baseline_safety_run_id:
        baseline_safety_uuid = _parse_uuid(
            payload.baseline_safety_run_id, "Baseline safety eval run"
        )
        safety_run = await _safety_repo.get_run_by_id(
            db_session,
            run_id=baseline_safety_uuid,
            organization_id=organization_id,
        )
        if safety_run is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Baseline safety eval run not found",
            )

    gate = await _gate_repo.create_gate(
        db_session,
        organization_id=organization_id,
        name=payload.name,
        description=payload.description,
        thresholds=payload.thresholds.model_dump(exclude_none=True),
        baseline_evaluation_run_id=baseline_eval_run_uuid,
        baseline_safety_run_id=baseline_safety_uuid,
        created_by_id=user_id,
    )
    await db_session.commit()
    await db_session.refresh(gate)

    await _audit_service.record(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        action="quality_gate.created",
        resource_type="quality_gate",
        resource_id=gate.id,
        request_id=request_id,
        metadata={"name": gate.name},
    )
    await db_session.commit()

    log_evaluation_event(
        event="quality_gate.created",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        job_id=str(gate.id),
        status_code=status.HTTP_201_CREATED,
    )
    return _gate_to_response(gate)


@router.get("", response_model=QualityGateListResponse)
async def list_quality_gates(
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
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> QualityGateListResponse:
    organization_id = _org_id(principal)
    gates = await _gate_repo.list_gates(
        db_session, organization_id=organization_id, limit=limit, offset=offset
    )
    total = await _gate_repo.count_gates(db_session, organization_id=organization_id)
    return QualityGateListResponse(
        items=[_gate_to_response(g) for g in gates],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{quality_gate_id}", response_model=QualityGateResponse)
async def get_quality_gate(
    quality_gate_id: str,
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
) -> QualityGateResponse:
    organization_id = _org_id(principal)
    gate_uuid = _parse_uuid(quality_gate_id, "Quality gate")
    gate = await _gate_repo.get_gate(db_session, gate_id=gate_uuid, organization_id=organization_id)
    if gate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quality gate not found")
    return _gate_to_response(gate)


@router.patch("/{quality_gate_id}", response_model=QualityGateResponse)
async def update_quality_gate(
    quality_gate_id: str,
    request: Request,
    payload: UpdateQualityGateRequest,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> QualityGateResponse:
    organization_id = _org_id(principal)
    user_id = _user_id(principal)
    request_id = _request_id(request)
    gate_uuid = _parse_uuid(quality_gate_id, "Quality gate")
    gate = await _gate_repo.get_gate(db_session, gate_id=gate_uuid, organization_id=organization_id)
    if gate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quality gate not found")

    new_thresholds: dict | None = None
    if payload.thresholds is not None:
        new_thresholds = payload.thresholds.model_dump(exclude_none=True)

    await _gate_repo.update_gate(
        db_session,
        gate,
        name=payload.name,
        description=payload.description,
        thresholds=new_thresholds,
    )
    await db_session.commit()
    await db_session.refresh(gate)

    await _audit_service.record(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        action="quality_gate.updated",
        resource_type="quality_gate",
        resource_id=gate.id,
        request_id=request_id,
        metadata={"name": gate.name},
    )
    await db_session.commit()
    return _gate_to_response(gate)


@router.delete("/{quality_gate_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_quality_gate(
    quality_gate_id: str,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> None:
    organization_id = _org_id(principal)
    user_id = _user_id(principal)
    request_id = _request_id(request)
    gate_uuid = _parse_uuid(quality_gate_id, "Quality gate")
    gate = await _gate_repo.get_gate(db_session, gate_id=gate_uuid, organization_id=organization_id)
    if gate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quality gate not found")

    gate_id_copy = gate.id
    gate_name = gate.name
    await _gate_repo.delete_gate(db_session, gate)
    await db_session.commit()

    await _audit_service.record(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        action="quality_gate.deleted",
        resource_type="quality_gate",
        resource_id=gate_id_copy,
        request_id=request_id,
        metadata={"name": gate_name},
    )
    await db_session.commit()


# ---------------------------------------------------------------------------
# Gate run endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/{quality_gate_id}/runs",
    response_model=QualityGateRunResponse,
    status_code=status.HTTP_201_CREATED,
)
async def trigger_quality_gate_run(
    quality_gate_id: str,
    request: Request,
    payload: TriggerQualityGateRunRequest,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> QualityGateRunResponse:
    organization_id = _org_id(principal)
    user_id = _user_id(principal)
    request_id = _request_id(request)
    gate_uuid = _parse_uuid(quality_gate_id, "Quality gate")
    gate = await _gate_repo.get_gate(db_session, gate_id=gate_uuid, organization_id=organization_id)
    if gate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quality gate not found")

    if payload.evaluation_run_id is None and payload.safety_eval_run_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide at least one of evaluation_run_id or safety_eval_run_id",
        )

    eval_summary: dict | None = None
    eval_run_uuid: UUID | None = None
    if payload.evaluation_run_id:
        eval_run_uuid = _parse_uuid(payload.evaluation_run_id, "Evaluation run")
        eval_run = await _eval_repo.get_evaluation_run_for_organization(
            db_session, evaluation_run_id=eval_run_uuid, organization_id=organization_id
        )
        if eval_run is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Evaluation run not found"
            )
        raw_config = dict(eval_run.config or {})
        summary_raw = raw_config.get("metrics_summary")
        eval_summary = dict(summary_raw) if isinstance(summary_raw, dict) else None

    safety_summary: dict | None = None
    safety_run_uuid: UUID | None = None
    if payload.safety_eval_run_id:
        safety_run_uuid = _parse_uuid(payload.safety_eval_run_id, "Safety eval run")
        safety_run = await _safety_repo.get_run_by_id(
            db_session, run_id=safety_run_uuid, organization_id=organization_id
        )
        if safety_run is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Safety eval run not found"
            )
        raw_summary = dict(safety_run.summary or {})
        pass_count = safety_run.pass_count or 0
        total_count = safety_run.total_count or 0
        pass_rate_value = raw_summary.get("pass_rate")
        if pass_rate_value is None and total_count > 0:
            pass_rate_value = pass_count / total_count
        safety_summary = {**raw_summary, "pass_rate": pass_rate_value}

    thresholds = QualityGateThresholds(
        **{
            k: v
            for k, v in (gate.thresholds or {}).items()
            if k in QualityGateThresholds.model_fields
        }
    )
    verdict, passed_checks, failed_checks = evaluate_gate(thresholds, eval_summary, safety_summary)

    # Baseline regression comparison — fetch baseline metrics when configured.
    baseline_summary: dict | None = None
    if gate.baseline_evaluation_run_id is not None:
        baseline_run = await _eval_repo.get_evaluation_run_for_organization(
            db_session,
            evaluation_run_id=gate.baseline_evaluation_run_id,
            organization_id=organization_id,
        )
        if baseline_run is not None:
            raw_baseline = dict(baseline_run.config or {})
            baseline_raw = raw_baseline.get("metrics_summary")
            baseline_summary = dict(baseline_raw) if isinstance(baseline_raw, dict) else None

    regression_failed, baseline_deltas = evaluate_regression(
        thresholds, eval_summary, baseline_summary
    )
    if regression_failed:
        failed_checks.extend(regression_failed)
        if verdict == QualityGateVerdict.passed.value:
            verdict = QualityGateVerdict.failed.value

    report = build_gate_report(
        gate_run_id="",
        quality_gate_id=str(gate.id),
        quality_gate_name=gate.name,
        verdict=verdict,
        evaluation_run_id=str(eval_run_uuid) if eval_run_uuid else None,
        safety_eval_run_id=str(safety_run_uuid) if safety_run_uuid else None,
        thresholds=thresholds,
        passed_checks=passed_checks,
        failed_checks=failed_checks,
        evaluation_summary=eval_summary,
        safety_summary=safety_summary,
        baseline_comparison=baseline_deltas if baseline_deltas else None,
    )

    gate_run = await _gate_repo.create_gate_run(
        db_session,
        quality_gate_id=gate.id,
        evaluation_run_id=eval_run_uuid,
        safety_eval_run_id=safety_run_uuid,
        verdict=verdict,
        report={**report, "gate_run_id": ""},
        triggered_by_id=user_id,
    )
    await db_session.commit()
    await db_session.refresh(gate_run)

    updated_report = {**gate_run.report, "gate_run_id": str(gate_run.id)}
    gate_run.report = updated_report
    await db_session.commit()

    await _audit_service.record(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        action="quality_gate.run.completed",
        resource_type="quality_gate_run",
        resource_id=gate_run.id,
        request_id=request_id,
        metadata={
            "quality_gate_id": str(gate.id),
            "verdict": verdict,
            "fail_count": len(failed_checks),
        },
    )
    await db_session.commit()

    log_evaluation_event(
        event="quality_gate.run.completed",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        job_id=str(gate_run.id),
        status_code=status.HTTP_201_CREATED,
        verdict=verdict,
    )
    await db_session.refresh(gate_run)
    return _gate_run_to_response(gate_run)


@router.get("/{quality_gate_id}/runs", response_model=QualityGateRunListResponse)
async def list_quality_gate_runs(
    quality_gate_id: str,
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
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> QualityGateRunListResponse:
    organization_id = _org_id(principal)
    gate_uuid = _parse_uuid(quality_gate_id, "Quality gate")
    gate = await _gate_repo.get_gate(db_session, gate_id=gate_uuid, organization_id=organization_id)
    if gate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quality gate not found")
    runs = await _gate_repo.list_gate_runs(
        db_session,
        quality_gate_id=gate_uuid,
        organization_id=organization_id,
        limit=limit,
        offset=offset,
    )
    total = await _gate_repo.count_gate_runs(
        db_session, quality_gate_id=gate_uuid, organization_id=organization_id
    )
    return QualityGateRunListResponse(
        items=[_gate_run_to_response(r) for r in runs],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/runs/{gate_run_id}", response_model=QualityGateRunResponse)
async def get_quality_gate_run(
    gate_run_id: str,
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
) -> QualityGateRunResponse:
    organization_id = _org_id(principal)
    run_uuid = _parse_uuid(gate_run_id, "Gate run")
    gate_run = await _gate_repo.get_gate_run(
        db_session, gate_run_id=run_uuid, organization_id=organization_id
    )
    if gate_run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gate run not found")
    return _gate_run_to_response(gate_run)


@router.get("/runs/{gate_run_id}/report", response_model=QualityGateReportResponse)
async def get_quality_gate_report(
    gate_run_id: str,
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
) -> QualityGateReportResponse:
    organization_id = _org_id(principal)
    run_uuid = _parse_uuid(gate_run_id, "Gate run")
    gate_run = await _gate_repo.get_gate_run(
        db_session, gate_run_id=run_uuid, organization_id=organization_id
    )
    if gate_run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gate run not found")

    gate = await _gate_repo.get_gate(
        db_session,
        gate_id=gate_run.quality_gate_id,
        organization_id=organization_id,
    )
    if gate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quality gate not found")

    report = dict(gate_run.report or {})
    passed_checks = [GateCheckResult(**c) for c in report.get("passed_checks", [])]
    failed_checks = [GateCheckResult(**c) for c in report.get("failed_checks", [])]

    raw_deltas = report.get("baseline_comparison")
    baseline_comparison = (
        [BaselineMetricDelta(**d) for d in raw_deltas] if isinstance(raw_deltas, list) else None
    )

    ci_exit_code = (
        0
        if gate_run.verdict
        in (
            QualityGateVerdict.passed.value,
            QualityGateVerdict.overridden.value,
        )
        else 1
    )

    overridden_at_str: str | None = None
    if gate_run.overridden_at is not None:
        overridden_at_str = gate_run.overridden_at.isoformat()

    return QualityGateReportResponse(
        gate_run_id=str(gate_run.id),
        quality_gate_id=str(gate.id),
        quality_gate_name=gate.name,
        verdict=gate_run.verdict,
        generated_at=report.get("generated_at", datetime.now(UTC).isoformat()),
        evaluation_run_id=(str(gate_run.evaluation_run_id) if gate_run.evaluation_run_id else None),
        safety_eval_run_id=(
            str(gate_run.safety_eval_run_id) if gate_run.safety_eval_run_id else None
        ),
        thresholds_applied=report.get("thresholds_applied", {}),
        passed_checks=passed_checks,
        failed_checks=failed_checks,
        total_checks=len(passed_checks) + len(failed_checks),
        pass_count=len(passed_checks),
        fail_count=len(failed_checks),
        override_reason=gate_run.override_reason,
        overridden_by_id=(str(gate_run.overridden_by_id) if gate_run.overridden_by_id else None),
        overridden_at=overridden_at_str,
        evaluation_summary=report.get("evaluation_summary"),
        safety_summary=report.get("safety_summary"),
        baseline_comparison=baseline_comparison,
        ci_exit_code=ci_exit_code,
    )


@router.get("/runs/{gate_run_id}/report/download")
async def download_quality_gate_report(
    gate_run_id: str,
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
) -> Response:
    """Return the gate report as a downloadable JSON file (for CI artifact upload)."""
    import json as _json

    organization_id = _org_id(principal)
    run_uuid = _parse_uuid(gate_run_id, "Gate run")
    gate_run = await _gate_repo.get_gate_run(
        db_session, gate_run_id=run_uuid, organization_id=organization_id
    )
    if gate_run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gate run not found")

    return Response(
        content=_json.dumps(gate_run.report, indent=2, default=str),
        media_type="application/json",
        headers={
            "Content-Disposition": f"attachment; filename=quality-gate-{gate_run_id[:8]}.json"
        },
    )


# ---------------------------------------------------------------------------
# Override endpoint (audited; owner/admin only)
# ---------------------------------------------------------------------------


@router.post("/runs/{gate_run_id}/override", response_model=QualityGateRunResponse)
async def override_quality_gate_run(
    gate_run_id: str,
    request: Request,
    payload: QualityGateOverrideRequest,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> QualityGateRunResponse:
    organization_id = _org_id(principal)
    user_id = _user_id(principal)
    request_id = _request_id(request)
    run_uuid = _parse_uuid(gate_run_id, "Gate run")
    gate_run = await _gate_repo.get_gate_run(
        db_session, gate_run_id=run_uuid, organization_id=organization_id
    )
    if gate_run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gate run not found")

    if gate_run.verdict == QualityGateVerdict.passed.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Gate run already passed — override is not applicable",
        )
    if gate_run.verdict == QualityGateVerdict.overridden.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Gate run is already overridden",
        )

    now = datetime.now(UTC)
    gate_run = await _gate_repo.apply_override(
        db_session,
        gate_run,
        overridden_by_id=user_id,
        override_reason=payload.reason,
        overridden_at=now,
    )
    await db_session.commit()
    await db_session.refresh(gate_run)

    await _audit_service.record(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        action="quality_gate.run.overridden",
        resource_type="quality_gate_run",
        resource_id=gate_run.id,
        request_id=request_id,
        metadata={
            "quality_gate_id": str(gate_run.quality_gate_id),
            "override_reason": payload.reason,
        },
    )
    await db_session.commit()

    log_evaluation_event(
        event="quality_gate.run.overridden",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        job_id=str(gate_run.id),
        status_code=status.HTTP_200_OK,
    )
    return _gate_run_to_response(gate_run)
