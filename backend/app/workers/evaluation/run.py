"""``_run_evaluation_async``: load the run, evaluate each target, persist the summary.

Sessions are short: one to load the run, one to clear stale results, one per question
result (``target.py``), and one for the summary. None is held across a provider call.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import log_evaluation_event
from app.domains.ai.profile.schemas import ResolvedTaskProfile, TaskType
from app.domains.ai.profile.service import (
    _profile_to_resolved,
    get_profile_by_id,
    resolve_task_profile,
)
from app.models.document import Document
from app.workers.base_task import PermanentTaskError, TransientTaskError
from app.workers.evaluation import facade
from app.workers.evaluation.comparison import (
    _build_best_target_by_dimension,
    apply_regression_flags,
    build_comparison_payload,
    model_profile_summary,
)
from app.workers.evaluation.config import (
    EvaluationRunConfig,
    _parse_run_config,
    _parse_uuid,
    _resolve_corpus_document_ids,
    resolve_comparison_targets,
)
from app.workers.evaluation.target import RunContext, evaluate_target


async def _load_prompt_template(
    session: AsyncSession, evaluation_run: Any
) -> tuple[str | None, dict[str, Any] | None]:
    if evaluation_run.prompt_template_version_id is None:
        return None, None
    prompt_version = await facade()._prompt_template_repository.get_version_by_id(
        session,
        version_id=evaluation_run.prompt_template_version_id,
    )
    if prompt_version is None:
        return None, None
    raw_config = evaluation_run.config if isinstance(evaluation_run.config, dict) else {}
    config_prompt_template = raw_config.get("prompt_template")
    metadata = (
        dict(config_prompt_template)
        if isinstance(config_prompt_template, dict)
        else {
            "version_id": str(prompt_version.id),
            "version_number": prompt_version.version_number,
        }
    )
    return prompt_version.content, metadata


async def _resolve_profile(
    session: AsyncSession, run_config: EvaluationRunConfig, organization_id: UUID
) -> ResolvedTaskProfile | None:
    if run_config.model_profile_id is None:
        return await resolve_task_profile(
            session,
            organization_id=organization_id,
            task_type=TaskType.evaluations,
        )
    try:
        profile_uuid = UUID(run_config.model_profile_id)
    except ValueError as exc:
        raise PermanentTaskError(
            f"Invalid model_profile_id in run config: {run_config.model_profile_id}"
        ) from exc
    profile_row = await get_profile_by_id(
        session,
        profile_id=profile_uuid,
        organization_id=organization_id,
    )
    if profile_row is None:
        raise PermanentTaskError(
            f"Model profile not found or inaccessible: {run_config.model_profile_id}"
        )
    return _profile_to_resolved(profile_row)


async def _load_context(
    evaluation_run_id: str,
    parsed_run_id: UUID,
    *,
    request_id: str | None,
    organization_id: str | None,
    user_id: str | None,
) -> tuple[RunContext, dict[UUID, Document]]:
    f = facade()
    repository = f._evaluation_repository
    async with f.SessionLocal() as session:
        evaluation_run = await repository.get_evaluation_run(
            session, evaluation_run_id=parsed_run_id
        )
        if evaluation_run is None:
            raise PermanentTaskError(f"Evaluation run not found: {evaluation_run_id}")
        evaluation_set = await repository.get_evaluation_set_by_id(
            session, evaluation_set_id=evaluation_run.evaluation_set_id
        )
        if evaluation_set is None:
            raise PermanentTaskError(
                f"Evaluation set not found for run: {evaluation_run.evaluation_set_id}"
            )
        questions = await repository.list_all_evaluation_questions(
            session, evaluation_set_id=evaluation_set.id
        )
        run_config = _parse_run_config(
            evaluation_run.config if isinstance(evaluation_run.config, dict) else {}
        )
        template_content, template_metadata = await _load_prompt_template(session, evaluation_run)
        llm_service = f.LLMService(model_name=run_config.model_name)
        owner_id = evaluation_set.organization_id
        resolved_profile = await _resolve_profile(session, run_config, owner_id)
        documents_by_id: dict[UUID, Document] = {}
        for document_id in _resolve_corpus_document_ids(
            selected_document_ids=run_config.selected_document_ids, questions=questions
        ):
            document = await f._document_repository.get_document_by_id(
                session, document_id=document_id
            )
            # Only the evaluation set's own organisation's documents are ever re-ingested.
            if document is None or document.organization_id != owner_id:
                continue
            documents_by_id[document_id] = document
    ctx = RunContext(
        parsed_run_id=parsed_run_id,
        evaluation_run_id=evaluation_run_id,
        owner_organization_id=owner_id,
        request_id=request_id,
        organization_id=organization_id,
        user_id=user_id,
        run_config=run_config,
        llm_service=llm_service,
        questions=list(questions),
        document_ids=list(documents_by_id),
        prompt_template_content=template_content,
        prompt_template_metadata=template_metadata,
        resolved_profile=resolved_profile,
    )
    return ctx, documents_by_id


async def _clear_stale_results(parsed_run_id: UUID, evaluation_run_id: str) -> None:
    """Idempotent retry behaviour: replace previous results for this run."""
    f = facade()
    async with f.SessionLocal() as session:
        try:
            _ = await f._evaluation_repository.delete_evaluation_results_for_run(
                session, evaluation_run_id=parsed_run_id
            )
            await session.commit()
        except Exception as exc:
            await session.rollback()
            raise TransientTaskError(
                f"Unable to clear stale evaluation results for run: {evaluation_run_id}"
            ) from exc


async def _persist_summary(
    parsed_run_id: UUID, evaluation_run_id: str, config_patch: dict[str, Any]
) -> None:
    f = facade()
    async with f.SessionLocal() as session:
        try:
            updated_run = await f._evaluation_repository.update_evaluation_run_config(
                session, evaluation_run_id=parsed_run_id, config_patch=config_patch
            )
            if updated_run is None:
                raise RuntimeError("evaluation run not found while updating summary")
            await session.commit()
        except Exception as exc:
            await session.rollback()
            raise TransientTaskError(
                f"Unable to persist evaluation summary for run: {evaluation_run_id}"
            ) from exc


async def _run_evaluation_async(
    evaluation_run_id: str,
    *,
    request_id: str | None = None,
    organization_id: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    try:
        parsed_run_id = _parse_uuid(evaluation_run_id)
    except ValueError as exc:
        raise PermanentTaskError(f"Invalid evaluation_run_id: {evaluation_run_id}") from exc

    ctx, documents_by_id = await _load_context(
        evaluation_run_id,
        parsed_run_id,
        request_id=request_id,
        organization_id=organization_id,
        user_id=user_id,
    )
    run_config = ctx.run_config
    await _clear_stale_results(parsed_run_id, evaluation_run_id)

    target_summaries: list[dict[str, Any]] = []
    per_target_question_scores: dict[str, dict[str, float | None]] = {}
    primary_success_count = 0
    primary_failure_count = 0
    for target_index, target in enumerate(resolve_comparison_targets(run_config)):
        outcome = await evaluate_target(ctx, target_index=target_index, target=target)
        if target_index == 0:
            primary_success_count = outcome.success_count
            primary_failure_count = outcome.failure_count
        target_summaries.append(outcome.summary)
        per_target_question_scores[target.label] = outcome.question_scores

    total_questions = len(ctx.questions)
    primary_summary = (
        dict(target_summaries[0])
        if target_summaries
        else facade()._evaluation_metrics_service.summarize_run(
            metrics=[], total_questions=total_questions, success_count=0, failure_count=0
        )
    )
    comparison_payload = build_comparison_payload(target_summaries)
    regression_count, regression_failed = apply_regression_flags(
        target_summaries, run_config.regression_thresholds
    )
    best_by_document_type, best_by_use_case = _build_best_target_by_dimension(
        documents_by_id=documents_by_id,
        questions=ctx.questions,
        per_target_question_scores=per_target_question_scores,
    )

    metrics_summary = dict(primary_summary)
    metrics_summary["comparison_targets"] = target_summaries
    metrics_summary["best_by_document_type"] = best_by_document_type
    metrics_summary["best_by_use_case"] = best_by_use_case
    metrics_summary["regressions_count"] = regression_count
    metrics_summary["regression_failed"] = regression_failed
    metrics_summary["eval_index_cleanup"] = ctx.cleanup_results
    if ctx.prompt_template_metadata is not None:
        metrics_summary["prompt_template"] = dict(ctx.prompt_template_metadata)
    if comparison_payload is not None:
        metrics_summary["comparison"] = comparison_payload
    if ctx.resolved_profile is not None:
        metrics_summary["model_profile"] = model_profile_summary(ctx.resolved_profile)

    await _persist_summary(
        parsed_run_id,
        evaluation_run_id,
        {
            "metrics_summary": metrics_summary,
            "metric_options_effective": run_config.metric_options.as_dict(),
        },
    )
    log_evaluation_event(
        event="evaluation.run.metrics_computed",
        organization_id=ctx.log_organization_id,
        user_id=user_id,
        job_id=evaluation_run_id,
        request_id=request_id,
        metrics_summary=metrics_summary,
    )
    return {
        "evaluation_run_id": evaluation_run_id,
        "question_total_count": total_questions,
        "question_success_count": primary_success_count,
        "question_failure_count": primary_failure_count,
        "all_questions_failed": total_questions > 0 and primary_success_count == 0,
        "metrics_summary": metrics_summary,
    }
