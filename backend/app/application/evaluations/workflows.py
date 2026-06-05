from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import ensure_document_ids_access
from app.auth.models import AuthenticatedPrincipal
from app.core.config import settings
from app.core.logging import log_evaluation_event
from app.domains.admin.services.audit_service import AuditLogService
from app.domains.admin.services.chunking_profile_service import ChunkingProfileService
from app.domains.evaluations.repositories.evaluations import EvaluationRepository
from app.domains.evaluations.schemas.evaluations import RunEvaluationRequest, RunEvaluationResponse
from app.domains.prompt_templates.services.prompt_template_service import PromptTemplateService
from app.domains.prompt_templates.services.rendering import PromptTemplateValidationError
from app.models.enums import PromptTemplateKey

_chunking_profile_service = ChunkingProfileService()
_prompt_template_service = PromptTemplateService()


async def _safe_commit_audit_only(db_session: AsyncSession, *, wrote_audit: bool) -> None:
    if not wrote_audit:
        return
    try:
        await db_session.commit()
    except Exception:
        await db_session.rollback()


async def trigger_evaluation_workflow(
    *,
    request_id: str | None,
    payload: RunEvaluationRequest,
    principal: AuthenticatedPrincipal,
    organization_id: UUID,
    user_id: UUID,
    db_session: AsyncSession,
    evaluation_repository: EvaluationRepository,
    audit_log_service: AuditLogService,
    run_evaluation_task: Any,
) -> RunEvaluationResponse:
    try:
        evaluation_set_id = UUID(payload.evaluation_set_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Evaluation set not found"
        ) from exc

    evaluation_set = await evaluation_repository.get_evaluation_set(
        db_session,
        evaluation_set_id=evaluation_set_id,
        organization_id=organization_id,
    )
    if evaluation_set is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Evaluation set not found"
        )

    selected_document_ids = await ensure_document_ids_access(
        document_ids=payload.config.selected_document_ids,
        principal=principal,
        db_session=db_session,
    )
    selected_document_ids_as_strings = [str(document_id) for document_id in selected_document_ids]

    normalized_comparison_targets: list[dict[str, object]] = []
    if payload.config.comparison_targets:
        for target in payload.config.comparison_targets:
            normalized_comparison_targets.append(
                await _chunking_profile_service.resolve_profile_target_for_evaluation(
                    db_session,
                    profile_id=target.chunking_profile_id,
                    inline_config=target.chunking_profile_config,
                    organization_id=organization_id,
                    label=target.label,
                )
            )
    elif (
        payload.config.chunking_profile_id is not None
        or payload.config.chunking_profile_config is not None
    ):
        normalized_comparison_targets.append(
            await _chunking_profile_service.resolve_profile_target_for_evaluation(
                db_session,
                profile_id=payload.config.chunking_profile_id,
                inline_config=payload.config.chunking_profile_config,
                organization_id=organization_id,
                label=payload.config.run_name,
            )
        )

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

    try:
        prompt_version = await _prompt_template_service.resolve_active_version(
            db_session,
            organization_id=organization_id,
            template_key=PromptTemplateKey.answer_generation.value,
        )
    except PromptTemplateValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Answer prompt template is unavailable",
        ) from exc

    config_payload: dict[str, object] = {
        "run_name": payload.config.run_name,
        "top_k": payload.config.top_k
        if payload.config.top_k is not None
        else settings.retrieval_final_top_k,
        "rerank": payload.config.rerank,
        "model_name": payload.config.model_name or settings.openai_llm_model,
        "selected_document_ids": selected_document_ids_as_strings,
        "metric_options": dict(payload.config.metric_options),
        "comparison_targets": normalized_comparison_targets,
        "regression_thresholds": (
            payload.config.regression_thresholds.model_dump(exclude_none=True)
            if payload.config.regression_thresholds is not None
            else None
        ),
        "prompt_template": {
            "key": PromptTemplateKey.answer_generation.value,
            "version_number": prompt_version.version_number,
            "version_id": str(prompt_version.id),
        },
    }
    if len(normalized_comparison_targets) == 1:
        single_target = normalized_comparison_targets[0]
        config_payload["chunking_profile_id"] = single_target.get("chunking_profile_id")
        config_payload["chunking_profile_config"] = single_target.get("chunking_profile_config")
        config_payload["chunking_strategy"] = single_target.get("chunking_strategy")
        config_payload["profile_version"] = single_target.get("profile_version")

    evaluation_run = await evaluation_repository.create_evaluation_run(
        db_session,
        evaluation_set_id=evaluation_set_id,
        config=config_payload,
        prompt_template_version_id=prompt_version.id,
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
            "comparison_target_count": len(normalized_comparison_targets),
            "chunking_strategy": config_payload.get("chunking_strategy"),
            "prompt_template_key": PromptTemplateKey.answer_generation.value,
            "prompt_template_version": prompt_version.version_number,
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
            organization_id=str(organization_id),
            user_id=str(user_id),
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
        organization_id=str(organization_id),
        user_id=str(user_id),
        job_id=str(evaluation_run.id),
        task_id=str(task_result.id),
        status_code=status.HTTP_202_ACCEPTED,
    )
    return RunEvaluationResponse(
        evaluation_run_id=str(evaluation_run.id),
        status="queued",
    )
