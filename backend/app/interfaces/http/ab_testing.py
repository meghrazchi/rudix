"""A/B experiment HTTP interface — prompt and retrieval profile comparison (F304)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.core.logging import log_evaluation_event
from app.db.session import get_db_session
from app.domains.ab_testing.repositories.ab_testing import AbTestingRepository
from app.domains.ab_testing.schemas.ab_testing import (
    AbExperimentListResponse,
    AbExperimentResponse,
    AbExperimentRunListResponse,
    AbExperimentRunResponse,
    AbVariantResponse,
    ApproveVariantRequest,
    CreateAbExperimentRequest,
    CreateAbVariantRequest,
    RejectVariantRequest,
    StartAbExperimentRunRequest,
    UpdateAbExperimentRequest,
)
from app.domains.ab_testing.services.ab_testing_service import (
    build_comparison_report,
    build_variant_summaries,
    extract_metrics_from_eval_config,
)
from app.domains.admin.services.audit_service import AuditLogService
from app.domains.evaluations.repositories.evaluations import EvaluationRepository
from app.domains.rag_profiles.repositories.rag_profiles import RagProfileRepository
from app.models.ab_experiment import AbExperiment, AbExperimentRun, AbExperimentVariant
from app.models.enums import AbExperimentStatus, AbVariantApprovalStatus, OrganizationRole

router = APIRouter(prefix="/ab-experiments", tags=["ab-experiments"])

_repo = AbTestingRepository()
_eval_repo = EvaluationRepository()
_rag_repo = RagProfileRepository()
_audit = AuditLogService()

_ADMIN_ROLES = (OrganizationRole.owner.value, OrganizationRole.admin.value)
_READ_ROLES = (
    OrganizationRole.owner.value,
    OrganizationRole.admin.value,
    OrganizationRole.member.value,
    OrganizationRole.viewer.value,
    OrganizationRole.developer.value,
)


def _org_id(principal: AuthenticatedPrincipal) -> UUID:
    if principal.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="No active organization context"
        )
    try:
        return UUID(principal.organization_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Invalid organization context"
        ) from exc


def _user_id(principal: AuthenticatedPrincipal) -> UUID:
    try:
        return UUID(principal.user_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Invalid user context"
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


def _variant_to_response(variant: AbExperimentVariant) -> AbVariantResponse:
    return AbVariantResponse(
        variant_id=str(variant.id),
        experiment_id=str(variant.experiment_id),
        label=variant.label,
        description=variant.description,
        rag_profile_id=str(variant.rag_profile_id) if variant.rag_profile_id else None,
        rag_profile_version=variant.rag_profile_version,
        prompt_template_version_id=(
            str(variant.prompt_template_version_id) if variant.prompt_template_version_id else None
        ),
        model_profile_key=variant.model_profile_key,
        config_snapshot=dict(variant.config_snapshot or {}),
        approval_status=variant.approval_status,  # type: ignore[arg-type]
        approved_by_id=str(variant.approved_by_id) if variant.approved_by_id else None,
        approval_note=variant.approval_note,
        approved_at=variant.approved_at,
        created_at=variant.created_at,
        updated_at=variant.updated_at,
    )


def _experiment_to_response(exp: AbExperiment) -> AbExperimentResponse:
    return AbExperimentResponse(
        experiment_id=str(exp.id),
        name=exp.name,
        description=exp.description,
        evaluation_set_id=str(exp.evaluation_set_id),
        status=exp.status,  # type: ignore[arg-type]
        metrics_config=dict(exp.metrics_config or {}),
        created_by_id=str(exp.created_by_id) if exp.created_by_id else None,
        created_at=exp.created_at,
        updated_at=exp.updated_at,
        variants=[_variant_to_response(v) for v in (exp.variants or [])],
    )


def _run_to_response(run: AbExperimentRun, experiment_name: str = "") -> AbExperimentRunResponse:
    variant_runs = list(run.variant_runs or [])
    variant_labels: dict[str, str] = {}
    for vr in variant_runs:
        if vr.variant is not None:
            variant_labels[str(vr.variant_id)] = vr.variant.label

    summaries = build_variant_summaries(variant_runs, variant_labels)
    return AbExperimentRunResponse(
        experiment_run_id=str(run.id),
        experiment_id=str(run.experiment_id),
        status=run.status,  # type: ignore[arg-type]
        triggered_by_id=str(run.triggered_by_id) if run.triggered_by_id else None,
        started_at=run.started_at,
        completed_at=run.completed_at,
        created_at=run.created_at,
        updated_at=run.updated_at,
        variant_summaries=summaries,
        comparison_report=dict(run.comparison_report or {}),
    )


# ---------------------------------------------------------------------------
# Experiment CRUD
# ---------------------------------------------------------------------------


@router.post("", response_model=AbExperimentResponse, status_code=status.HTTP_201_CREATED)
async def create_ab_experiment(
    request: Request,
    payload: CreateAbExperimentRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> AbExperimentResponse:
    org_id = _org_id(principal)
    user_id = _user_id(principal)
    eval_set_uuid = _parse_uuid(payload.evaluation_set_id, "Evaluation set")
    eval_set = await _eval_repo.get_evaluation_set(
        db, evaluation_set_id=eval_set_uuid, organization_id=org_id
    )
    if eval_set is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Evaluation set not found"
        )

    exp = await _repo.create_experiment(
        db,
        organization_id=org_id,
        name=payload.name,
        description=payload.description,
        evaluation_set_id=eval_set_uuid,
        metrics_config=payload.metrics_config,
        created_by_id=user_id,
    )
    await db.commit()
    await db.refresh(exp)

    await _audit.record(
        db,
        organization_id=org_id,
        user_id=user_id,
        action="ab_experiment.created",
        resource_type="ab_experiment",
        resource_id=exp.id,
        request_id=_request_id(request),
        metadata={"name": exp.name},
    )
    await db.commit()
    return _experiment_to_response(exp)


@router.get("", response_model=AbExperimentListResponse)
async def list_ab_experiments(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_READ_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AbExperimentListResponse:
    org_id = _org_id(principal)
    experiments = await _repo.list_experiments(
        db, organization_id=org_id, limit=limit, offset=offset
    )
    total = await _repo.count_experiments(db, organization_id=org_id)
    return AbExperimentListResponse(
        items=[_experiment_to_response(e) for e in experiments],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{experiment_id}", response_model=AbExperimentResponse)
async def get_ab_experiment(
    experiment_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_READ_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> AbExperimentResponse:
    org_id = _org_id(principal)
    exp_uuid = _parse_uuid(experiment_id, "Experiment")
    exp = await _repo.get_experiment(db, experiment_id=exp_uuid, organization_id=org_id)
    if exp is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Experiment not found")
    return _experiment_to_response(exp)


@router.patch("/{experiment_id}", response_model=AbExperimentResponse)
async def update_ab_experiment(
    experiment_id: str,
    request: Request,
    payload: UpdateAbExperimentRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> AbExperimentResponse:
    org_id = _org_id(principal)
    user_id = _user_id(principal)
    exp_uuid = _parse_uuid(experiment_id, "Experiment")
    exp = await _repo.get_experiment(db, experiment_id=exp_uuid, organization_id=org_id)
    if exp is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Experiment not found")
    if exp.status == AbExperimentStatus.running.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot update an experiment that is currently running",
        )

    await _repo.update_experiment(
        db,
        exp,
        name=payload.name,
        description=payload.description,
        metrics_config=payload.metrics_config,
    )
    await db.commit()
    await db.refresh(exp)

    await _audit.record(
        db,
        organization_id=org_id,
        user_id=user_id,
        action="ab_experiment.updated",
        resource_type="ab_experiment",
        resource_id=exp.id,
        request_id=_request_id(request),
        metadata={"name": exp.name},
    )
    await db.commit()
    return _experiment_to_response(exp)


@router.delete("/{experiment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_ab_experiment(
    experiment_id: str,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> None:
    org_id = _org_id(principal)
    user_id = _user_id(principal)
    exp_uuid = _parse_uuid(experiment_id, "Experiment")
    exp = await _repo.get_experiment(db, experiment_id=exp_uuid, organization_id=org_id)
    if exp is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Experiment not found")
    if exp.status == AbExperimentStatus.running.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete an experiment that is currently running",
        )

    exp_id_copy = exp.id
    exp_name = exp.name
    await _repo.delete_experiment(db, exp)
    await db.commit()

    await _audit.record(
        db,
        organization_id=org_id,
        user_id=user_id,
        action="ab_experiment.deleted",
        resource_type="ab_experiment",
        resource_id=exp_id_copy,
        request_id=_request_id(request),
        metadata={"name": exp_name},
    )
    await db.commit()


# ---------------------------------------------------------------------------
# Variant CRUD
# ---------------------------------------------------------------------------


@router.post(
    "/{experiment_id}/variants",
    response_model=AbVariantResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_variant(
    experiment_id: str,
    request: Request,
    payload: CreateAbVariantRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> AbVariantResponse:
    org_id = _org_id(principal)
    user_id = _user_id(principal)
    exp_uuid = _parse_uuid(experiment_id, "Experiment")
    exp = await _repo.get_experiment(db, experiment_id=exp_uuid, organization_id=org_id)
    if exp is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Experiment not found")
    if exp.status == AbExperimentStatus.running.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot add variants to a running experiment",
        )

    rag_profile_uuid: UUID | None = None
    if payload.rag_profile_id:
        rag_profile_uuid = _parse_uuid(payload.rag_profile_id, "RAG profile")
        profile = await _rag_repo.get_profile(
            db, profile_id=rag_profile_uuid, organization_id=org_id
        )
        if profile is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="RAG profile not found"
            )

    prompt_version_uuid: UUID | None = None
    if payload.prompt_template_version_id:
        prompt_version_uuid = _parse_uuid(
            payload.prompt_template_version_id, "Prompt template version"
        )

    variant = await _repo.create_variant(
        db,
        experiment_id=exp_uuid,
        label=payload.label,
        description=payload.description,
        rag_profile_id=rag_profile_uuid,
        rag_profile_version=payload.rag_profile_version,
        prompt_template_version_id=prompt_version_uuid,
        model_profile_key=payload.model_profile_key,
        config_snapshot=payload.config_snapshot,
    )
    await db.commit()
    await db.refresh(variant)

    await _audit.record(
        db,
        organization_id=org_id,
        user_id=user_id,
        action="ab_experiment.variant.added",
        resource_type="ab_experiment_variant",
        resource_id=variant.id,
        request_id=_request_id(request),
        metadata={"experiment_id": experiment_id, "label": variant.label},
    )
    await db.commit()
    return _variant_to_response(variant)


@router.delete(
    "/{experiment_id}/variants/{variant_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_variant(
    experiment_id: str,
    variant_id: str,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> None:
    org_id = _org_id(principal)
    user_id = _user_id(principal)
    exp_uuid = _parse_uuid(experiment_id, "Experiment")
    variant_uuid = _parse_uuid(variant_id, "Variant")

    exp = await _repo.get_experiment(db, experiment_id=exp_uuid, organization_id=org_id)
    if exp is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Experiment not found")
    if exp.status == AbExperimentStatus.running.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot remove variants from a running experiment",
        )

    variant = await _repo.get_variant(db, variant_id=variant_uuid, experiment_id=exp_uuid)
    if variant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Variant not found")

    var_id_copy = variant.id
    await _repo.delete_variant(db, variant)
    await db.commit()

    await _audit.record(
        db,
        organization_id=org_id,
        user_id=user_id,
        action="ab_experiment.variant.removed",
        resource_type="ab_experiment_variant",
        resource_id=var_id_copy,
        request_id=_request_id(request),
        metadata={"experiment_id": experiment_id},
    )
    await db.commit()


# ---------------------------------------------------------------------------
# Experiment runs
# ---------------------------------------------------------------------------


@router.post(
    "/{experiment_id}/runs",
    response_model=AbExperimentRunResponse,
    status_code=status.HTTP_201_CREATED,
)
async def start_experiment_run(
    experiment_id: str,
    request: Request,
    payload: StartAbExperimentRunRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> AbExperimentRunResponse:
    org_id = _org_id(principal)
    user_id = _user_id(principal)
    exp_uuid = _parse_uuid(experiment_id, "Experiment")
    exp = await _repo.get_experiment(db, experiment_id=exp_uuid, organization_id=org_id)
    if exp is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Experiment not found")
    if not exp.variants:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Experiment must have at least one variant before running",
        )
    if exp.status == AbExperimentStatus.running.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Experiment is already running",
        )

    now = datetime.now(UTC)
    exp_run = await _repo.create_experiment_run(
        db,
        experiment_id=exp_uuid,
        status=AbExperimentStatus.running.value,
        triggered_by_id=user_id,
        started_at=now,
    )
    await _repo.update_experiment(db, exp, status=AbExperimentStatus.running.value)

    # Create a variant run stub for each variant (evaluation runs are submitted
    # asynchronously via the existing evaluation pipeline; stubs track status)
    for variant in exp.variants:
        await _repo.create_variant_run(
            db,
            experiment_run_id=exp_run.id,
            variant_id=variant.id,
            evaluation_run_id=None,
            status="queued",
        )

    await db.commit()
    await db.refresh(exp_run)

    await _audit.record(
        db,
        organization_id=org_id,
        user_id=user_id,
        action="ab_experiment.run.started",
        resource_type="ab_experiment_run",
        resource_id=exp_run.id,
        request_id=_request_id(request),
        metadata={"experiment_id": experiment_id, "variant_count": len(exp.variants)},
    )
    await db.commit()

    log_evaluation_event(
        event="ab_experiment.run.started",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        job_id=str(exp_run.id),
        status_code=status.HTTP_201_CREATED,
    )
    return _run_to_response(exp_run, exp.name)


@router.get("/{experiment_id}/runs", response_model=AbExperimentRunListResponse)
async def list_experiment_runs(
    experiment_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_READ_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AbExperimentRunListResponse:
    org_id = _org_id(principal)
    exp_uuid = _parse_uuid(experiment_id, "Experiment")
    exp = await _repo.get_experiment(db, experiment_id=exp_uuid, organization_id=org_id)
    if exp is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Experiment not found")

    runs = await _repo.list_experiment_runs(
        db,
        experiment_id=exp_uuid,
        organization_id=org_id,
        limit=limit,
        offset=offset,
    )
    total = await _repo.count_experiment_runs(db, experiment_id=exp_uuid, organization_id=org_id)
    return AbExperimentRunListResponse(
        items=[_run_to_response(r, exp.name) for r in runs],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{experiment_id}/runs/{run_id}", response_model=AbExperimentRunResponse)
async def get_experiment_run(
    experiment_id: str,
    run_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_READ_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> AbExperimentRunResponse:
    org_id = _org_id(principal)
    _parse_uuid(experiment_id, "Experiment")
    run_uuid = _parse_uuid(run_id, "Experiment run")
    run = await _repo.get_experiment_run(db, run_id=run_uuid, organization_id=org_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Experiment run not found"
        )
    return _run_to_response(run)


@router.post(
    "/{experiment_id}/runs/{run_id}/finalize",
    response_model=AbExperimentRunResponse,
)
async def finalize_experiment_run(
    experiment_id: str,
    run_id: str,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> AbExperimentRunResponse:
    """Compute comparison report and mark run completed.

    Called after variant evaluation runs have completed and metrics are available.
    Reads evaluation run metrics from linked EvaluationRun.config.metrics_summary.
    """
    org_id = _org_id(principal)
    user_id = _user_id(principal)
    exp_uuid = _parse_uuid(experiment_id, "Experiment")
    run_uuid = _parse_uuid(run_id, "Experiment run")

    exp = await _repo.get_experiment(db, experiment_id=exp_uuid, organization_id=org_id)
    if exp is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Experiment not found")

    run = await _repo.get_experiment_run(db, run_id=run_uuid, organization_id=org_id)
    if run is None or run.experiment_id != exp_uuid:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Experiment run not found"
        )
    if run.status == AbExperimentStatus.completed.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Experiment run already finalized"
        )

    # Pull metrics from linked evaluation runs
    for vr in run.variant_runs or []:
        if vr.evaluation_run_id and vr.status != "completed":
            eval_run = await _eval_repo.get_evaluation_run_for_organization(
                db, evaluation_run_id=vr.evaluation_run_id, organization_id=org_id
            )
            if eval_run is not None:
                metrics = extract_metrics_from_eval_config(dict(eval_run.config or {}))
                await _repo.update_variant_run(
                    db,
                    vr,
                    status="completed" if eval_run.status == "completed" else eval_run.status,
                    metrics_summary=metrics,
                )

    await db.flush()

    # Reload variant runs to build summaries with fresh metrics
    refreshed_run = await _repo.get_experiment_run(db, run_id=run_uuid, organization_id=org_id)
    assert refreshed_run is not None

    variant_labels = {
        str(vr.variant_id): (vr.variant.label if vr.variant else "Unknown")
        for vr in (refreshed_run.variant_runs or [])
    }
    summaries = build_variant_summaries(list(refreshed_run.variant_runs or []), variant_labels)
    report = build_comparison_report(
        experiment_run_id=str(run_uuid),
        experiment_id=experiment_id,
        experiment_name=exp.name,
        evaluation_set_id=str(exp.evaluation_set_id),
        variant_summaries=summaries,
    )

    now = datetime.now(UTC)
    await _repo.update_experiment_run(
        db,
        refreshed_run,
        status=AbExperimentStatus.completed.value,
        comparison_report=report,
        completed_at=now,
    )
    await _repo.update_experiment(db, exp, status=AbExperimentStatus.completed.value)
    await db.commit()
    await db.refresh(refreshed_run)

    await _audit.record(
        db,
        organization_id=org_id,
        user_id=user_id,
        action="ab_experiment.run.finalized",
        resource_type="ab_experiment_run",
        resource_id=run_uuid,
        request_id=_request_id(request),
        metadata={"experiment_id": experiment_id},
    )
    await db.commit()

    log_evaluation_event(
        event="ab_experiment.run.finalized",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        job_id=str(run_uuid),
        status_code=status.HTTP_200_OK,
    )
    return _run_to_response(refreshed_run, exp.name)


# ---------------------------------------------------------------------------
# Variant approval / rejection
# ---------------------------------------------------------------------------


@router.post(
    "/{experiment_id}/variants/{variant_id}/approve",
    response_model=AbVariantResponse,
)
async def approve_variant(
    experiment_id: str,
    variant_id: str,
    request: Request,
    payload: ApproveVariantRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> AbVariantResponse:
    """Approve a variant and optionally promote its RAG profile to the org default."""
    org_id = _org_id(principal)
    user_id = _user_id(principal)
    exp_uuid = _parse_uuid(experiment_id, "Experiment")
    variant_uuid = _parse_uuid(variant_id, "Variant")

    exp = await _repo.get_experiment(db, experiment_id=exp_uuid, organization_id=org_id)
    if exp is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Experiment not found")
    if exp.status not in (AbExperimentStatus.completed.value, AbExperimentStatus.draft.value):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Variant approval requires experiment to be completed or draft",
        )

    variant = await _repo.get_variant(db, variant_id=variant_uuid, experiment_id=exp_uuid)
    if variant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Variant not found")
    if variant.approval_status == AbVariantApprovalStatus.approved.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Variant is already approved"
        )

    now = datetime.now(UTC)
    await _repo.set_variant_approval(
        db,
        variant,
        approval_status=AbVariantApprovalStatus.approved.value,
        approved_by_id=user_id,
        approval_note=payload.note,
        approved_at=now,
    )

    # Optionally promote the RAG profile to default
    if payload.set_as_default_profile and variant.rag_profile_id:
        rag_profile = await _rag_repo.get_profile(
            db, profile_id=variant.rag_profile_id, organization_id=org_id
        )
        if rag_profile is not None and not rag_profile.is_default:
            await _rag_repo.clear_default_flag(
                db, organization_id=org_id, exclude_id=rag_profile.id
            )
            await _rag_repo.update_profile(db, rag_profile, is_default=True)

    await db.commit()
    await db.refresh(variant)

    await _audit.record(
        db,
        organization_id=org_id,
        user_id=user_id,
        action="ab_experiment.variant.approved",
        resource_type="ab_experiment_variant",
        resource_id=variant.id,
        request_id=_request_id(request),
        metadata={
            "experiment_id": experiment_id,
            "label": variant.label,
            "set_as_default_profile": payload.set_as_default_profile,
        },
    )
    await db.commit()

    log_evaluation_event(
        event="ab_experiment.variant.approved",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        job_id=str(variant.id),
        status_code=status.HTTP_200_OK,
    )
    return _variant_to_response(variant)


@router.post(
    "/{experiment_id}/variants/{variant_id}/reject",
    response_model=AbVariantResponse,
)
async def reject_variant(
    experiment_id: str,
    variant_id: str,
    request: Request,
    payload: RejectVariantRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> AbVariantResponse:
    org_id = _org_id(principal)
    user_id = _user_id(principal)
    exp_uuid = _parse_uuid(experiment_id, "Experiment")
    variant_uuid = _parse_uuid(variant_id, "Variant")

    exp = await _repo.get_experiment(db, experiment_id=exp_uuid, organization_id=org_id)
    if exp is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Experiment not found")

    variant = await _repo.get_variant(db, variant_id=variant_uuid, experiment_id=exp_uuid)
    if variant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Variant not found")
    if variant.approval_status == AbVariantApprovalStatus.approved.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot reject an already-approved variant",
        )

    now = datetime.now(UTC)
    await _repo.set_variant_approval(
        db,
        variant,
        approval_status=AbVariantApprovalStatus.rejected.value,
        approved_by_id=user_id,
        approval_note=payload.note,
        approved_at=now,
    )
    await db.commit()
    await db.refresh(variant)

    await _audit.record(
        db,
        organization_id=org_id,
        user_id=user_id,
        action="ab_experiment.variant.rejected",
        resource_type="ab_experiment_variant",
        resource_id=variant.id,
        request_id=_request_id(request),
        metadata={"experiment_id": experiment_id, "label": variant.label},
    )
    await db.commit()
    return _variant_to_response(variant)
