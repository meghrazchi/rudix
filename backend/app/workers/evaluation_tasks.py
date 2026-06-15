from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Coroutine
from dataclasses import asdict, dataclass
from decimal import Decimal
from time import perf_counter
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import log_evaluation_event
from app.db.session import SessionLocal
from app.domains.admin.services.audit_service import AuditLogService
from app.domains.ai.profile.schemas import ResolvedTaskProfile, TaskType
from app.domains.ai.profile.service import (
    _profile_to_resolved,
    get_profile_by_id,
    resolve_task_profile,
)
from app.domains.chat.services.citation_service import CitationContextChunk, CitationService
from app.domains.chat.services.confidence_service import ConfidenceChunkSignal, ConfidenceService
from app.domains.chat.services.llm_service import (
    LLMService,
    PermanentLLMServiceError,
    TransientLLMServiceError,
)
from app.domains.chat.services.prompt_service import PromptContextChunk, PromptService
from app.domains.chat.services.query_retrieval_service import (
    QueryRetrievalService,
    RetrievedCandidate,
)
from app.domains.chat.services.rerank_service import (
    RerankCandidate,
    RerankResult,
    RerankService,
)
from app.domains.documents.repositories.documents import DocumentRepository
from app.domains.evaluations.repositories.evaluations import EvaluationRepository
from app.domains.evaluations.services.evaluation_metrics_service import (
    EvaluationJudgeScores,
    EvaluationMetricOptions,
    EvaluationMetricsService,
    EvaluationQuestionMetrics,
    RetrievedMetricChunk,
)
from app.domains.prompt_templates.repositories.prompt_templates import PromptTemplateRepository
from app.models.document import Document
from app.models.enums import EvaluationRunStatus
from app.models.evaluation import EvaluationQuestion
from app.workers import document_tasks
from app.workers.async_runtime import run_async
from app.workers.base_task import PermanentTaskError, RudixTask, TransientTaskError
from app.workers.celery_app import celery_app
from app.workers.status_tracking import get_evaluation_status, set_evaluation_status

_evaluation_repository = EvaluationRepository()
_query_retrieval_service = QueryRetrievalService()
_rerank_service = RerankService()
_prompt_service = PromptService()
_prompt_template_repository = PromptTemplateRepository()
_citation_service = CitationService()
_confidence_service = ConfidenceService()
_evaluation_metrics_service = EvaluationMetricsService()
_audit_log_service = AuditLogService()
_document_repository = DocumentRepository()
_NOT_FOUND_ANSWER = "I could not find this information in the uploaded documents."


@dataclass(frozen=True)
class RetrievedChunk:
    document_id: UUID
    chunk_id: UUID
    filename: str
    page_number: int | None
    text: str
    similarity_score: float
    original_rank: int | None = None
    rerank_score: float | None = None
    rerank_rank: int | None = None
    final_rank: int | None = None


@dataclass(frozen=True)
class EvaluationRunConfig:
    run_name: str | None
    top_k: int
    rerank: bool
    model_name: str
    selected_document_ids: list[UUID]
    metric_options: EvaluationMetricOptions
    chunking_profile_id: str | None
    chunking_profile_config: dict[str, Any] | None
    chunking_strategy: str | None
    profile_version: str | None
    comparison_targets: list[ChunkingComparisonTarget]
    regression_thresholds: EvaluationRegressionThresholds
    # Optional: pin a specific OrgModelProfile UUID for this run.
    # When None the org's evaluations task profile is resolved at runtime.
    model_profile_id: str | None = None


@dataclass(frozen=True)
class EvaluationQuestionComputation:
    generated_answer: str
    retrieval_score: float | None
    faithfulness_score: float | None
    citation_accuracy_score: float | None
    answer_relevance_score: float | None
    metrics: EvaluationQuestionMetrics
    latency_ms: int
    details: dict[str, Any]


@dataclass(frozen=True)
class ChunkingComparisonTarget:
    label: str
    profile_source: str
    chunking_profile_id: str | None
    chunking_profile_config: dict[str, Any] | None
    chunking_strategy: str | None
    profile_version: str | None


@dataclass(frozen=True)
class EvaluationRegressionThresholds:
    retrieval_hit_rate_min: float | None = None
    citation_accuracy_score_min: float | None = None
    faithfulness_score_min: float | None = None
    max_not_found_rate: float | None = None


@dataclass(frozen=True)
class ChunkingCorpusStats:
    chunk_count_total: int
    chunk_tokens_average: float | None
    chunk_tokens_variance: float | None
    chunk_tokens_min: int | None
    chunk_tokens_max: int | None
    document_type_breakdown: dict[str, int]
    language_breakdown: dict[str, int]
    ocr_breakdown: dict[str, int]


def _parse_uuid(value: str) -> UUID:
    return UUID(value)


def _run[T](coro: Coroutine[Any, Any, T]) -> T:
    return run_async(coro)


def _parse_optional_uuid(value: str | None) -> UUID | None:
    if value is None:
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


def _normalize_score(value: object) -> float | None:
    if isinstance(value, (int, float)):
        numeric = float(value)
    elif isinstance(value, str):
        try:
            numeric = float(value.strip())
        except ValueError:
            return None
    else:
        return None
    return max(0.0, min(1.0, numeric))


def _normalize_optional_label(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _build_target_index_version(*, evaluation_run_id: UUID, target_index: int) -> str:
    return f"eval-{evaluation_run_id.hex[:10]}-{target_index + 1}"


def _derive_target_score(summary: dict[str, Any]) -> float | None:
    candidates = [
        summary.get("citation_accuracy_score"),
        summary.get("faithfulness_score"),
        summary.get("retrieval_hit_rate"),
        summary.get("retrieval_mrr"),
        summary.get("context_precision"),
        summary.get("context_recall"),
    ]
    normalized = [_normalize_score(value) for value in candidates]
    usable = [value for value in normalized if value is not None]
    if not usable:
        return None
    return round(sum(usable) / len(usable), 4)


def _parse_regression_thresholds(raw_thresholds: object) -> EvaluationRegressionThresholds:
    if not isinstance(raw_thresholds, dict):
        return EvaluationRegressionThresholds()
    return EvaluationRegressionThresholds(
        retrieval_hit_rate_min=_normalize_score(raw_thresholds.get("retrieval_hit_rate_min")),
        citation_accuracy_score_min=_normalize_score(
            raw_thresholds.get("citation_accuracy_score_min")
        ),
        faithfulness_score_min=_normalize_score(raw_thresholds.get("faithfulness_score_min")),
        max_not_found_rate=_normalize_score(raw_thresholds.get("max_not_found_rate")),
    )


def _parse_comparison_targets(raw_targets: object) -> list[ChunkingComparisonTarget]:
    if not isinstance(raw_targets, list):
        return []
    targets: list[ChunkingComparisonTarget] = []
    for index, raw_target in enumerate(raw_targets, start=1):
        if not isinstance(raw_target, dict):
            continue
        label = _normalize_optional_label(raw_target.get("label")) or f"Target {index}"
        raw_config = raw_target.get("chunking_profile_config")
        config = dict(raw_config) if isinstance(raw_config, dict) else None
        targets.append(
            ChunkingComparisonTarget(
                label=label,
                profile_source=(
                    _normalize_optional_label(raw_target.get("profile_source")) or "system_default"
                ),
                chunking_profile_id=_normalize_optional_label(
                    raw_target.get("chunking_profile_id")
                ),
                chunking_profile_config=config,
                chunking_strategy=_normalize_optional_label(raw_target.get("chunking_strategy")),
                profile_version=_normalize_optional_label(raw_target.get("profile_version")),
            )
        )
    return targets


async def _record_worker_audit_async(
    *,
    action: str,
    resource_type: str,
    resource_id: str | None,
    organization_id: str | None,
    user_id: str | None,
    request_id: str | None,
    metadata: dict[str, Any] | None = None,
) -> None:
    organization_uuid = _parse_optional_uuid(organization_id)
    if organization_uuid is None:
        return
    user_uuid = _parse_optional_uuid(user_id)
    parsed_resource_id = _parse_optional_uuid(resource_id)
    try:
        async with SessionLocal() as audit_session:
            wrote_audit = await _audit_log_service.record(
                audit_session,
                organization_id=organization_uuid,
                user_id=user_uuid,
                action=action,
                resource_type=resource_type,
                resource_id=parsed_resource_id,
                request_id=request_id,
                metadata=metadata or {},
            )
            if wrote_audit:
                await audit_session.commit()
    except Exception:
        return


def _record_worker_audit(
    *,
    action: str,
    resource_type: str,
    resource_id: str | None,
    organization_id: str | None,
    user_id: str | None,
    request_id: str | None,
    metadata: dict[str, Any] | None = None,
) -> None:
    _run(
        _record_worker_audit_async(
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            organization_id=organization_id,
            user_id=user_id,
            request_id=request_id,
            metadata=metadata,
        )
    )


def _coerce_score(value: object) -> float | None:
    if isinstance(value, (int, float)):
        numeric = float(value)
    elif isinstance(value, str):
        try:
            numeric = float(value.strip())
        except ValueError:
            return None
    else:
        return None
    return max(0.0, min(1.0, numeric))


async def _evaluate_with_llm_judge_async(
    *,
    model_name: str,
    question: str,
    expected_answer: str | None,
    generated_answer: str,
    retrieved_chunks: list[RetrievedChunk],
    resolved_profile: ResolvedTaskProfile | None = None,
) -> EvaluationJudgeScores:
    from app.domains.ai.providers.factory import default_provider_factory
    from app.domains.ai.providers.protocols import ChatCompletionRequest

    context_lines: list[str] = []
    for index, chunk in enumerate(retrieved_chunks[:6], start=1):
        context_lines.append(
            f"[{index}] document_id={chunk.document_id} "
            f"chunk_id={chunk.chunk_id} filename={chunk.filename} page={chunk.page_number}\n"
            f"{chunk.text[:1200]}"
        )
    context_block = "\n\n".join(context_lines) if context_lines else "(no context)"
    expected_block = (
        expected_answer.strip()
        if isinstance(expected_answer, str) and expected_answer.strip()
        else "(none)"
    )
    prompt = (
        "Score the assistant answer for a RAG evaluation.\n"
        "Return strict JSON with keys: faithfulness_score, answer_relevance_score.\n"
        "Scores must be floats between 0 and 1.\n\n"
        f"Question:\n{question}\n\n"
        f"Expected answer (optional):\n{expected_block}\n\n"
        f"Assistant answer:\n{generated_answer}\n\n"
        f"Retrieved context:\n{context_block}\n"
    )
    if resolved_profile is not None:
        provider = default_provider_factory.get_chat_provider(resolved_profile.provider_type)
        judge_model = resolved_profile.base_model
    else:
        provider = default_provider_factory.get_chat_provider()
        judge_model = model_name
    response = await provider.complete(
        ChatCompletionRequest(
            prompt=prompt,
            model=judge_model,
            temperature=0.0,
            json_mode=True,
            system_message=(
                "You are an evaluation judge. Score only groundedness and relevance. "
                "Do not return any keys except faithfulness_score and answer_relevance_score."
            ),
        )
    )
    payload = json.loads(response.content)
    faithfulness_score = _coerce_score(payload.get("faithfulness_score"))
    answer_relevance_score = _coerce_score(payload.get("answer_relevance_score"))
    return EvaluationJudgeScores(
        faithfulness_score=faithfulness_score,
        answer_relevance_score=answer_relevance_score,
        provider=resolved_profile.provider_type if resolved_profile is not None else "llm_judge",
    )


def _to_retrieved_chunk(candidate: RetrievedCandidate) -> RetrievedChunk:
    return RetrievedChunk(
        document_id=candidate.document_id,
        chunk_id=candidate.chunk_id,
        filename=candidate.filename,
        page_number=candidate.page_number,
        text=candidate.text,
        similarity_score=candidate.similarity_score,
    )


def _with_original_ranks(chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    ranked_chunks: list[RetrievedChunk] = []
    for index, chunk in enumerate(chunks, start=1):
        ranked_chunks.append(
            RetrievedChunk(
                document_id=chunk.document_id,
                chunk_id=chunk.chunk_id,
                filename=chunk.filename,
                page_number=chunk.page_number,
                text=chunk.text,
                similarity_score=chunk.similarity_score,
                original_rank=index,
                rerank_score=chunk.rerank_score,
                rerank_rank=chunk.rerank_rank,
                final_rank=chunk.final_rank,
            )
        )
    return ranked_chunks


async def _rerank_chunks(
    *,
    query: str,
    chunks: list[RetrievedChunk],
    enabled: bool,
    final_top_k: int,
) -> tuple[list[RetrievedChunk], RerankResult]:
    if final_top_k < 1 or not chunks:
        empty_result = await _rerank_service.rerank(
            query=query,
            candidates=[],
            enabled=enabled,
            final_top_k=final_top_k,
        )
        return [], empty_result

    chunk_by_key = {str(chunk.chunk_id): chunk for chunk in chunks}
    rerank_inputs = [
        RerankCandidate(
            key=str(chunk.chunk_id),
            text=chunk.text,
            similarity_score=chunk.similarity_score,
            original_rank=chunk.original_rank,
        )
        for chunk in chunks
    ]
    rerank_result = await _rerank_service.rerank(
        query=query,
        candidates=rerank_inputs,
        enabled=enabled,
        final_top_k=final_top_k,
    )

    selected_chunks: list[RetrievedChunk] = []
    for reranked in rerank_result.candidates:
        source_chunk = chunk_by_key.get(reranked.key)
        if source_chunk is None:
            continue
        selected_chunks.append(
            RetrievedChunk(
                document_id=source_chunk.document_id,
                chunk_id=source_chunk.chunk_id,
                filename=source_chunk.filename,
                page_number=source_chunk.page_number,
                text=source_chunk.text,
                similarity_score=source_chunk.similarity_score,
                original_rank=reranked.original_rank,
                rerank_score=reranked.rerank_score,
                rerank_rank=reranked.rerank_rank,
                final_rank=reranked.final_rank,
            )
        )
    return selected_chunks, rerank_result


def _build_prompt(
    *,
    question: str,
    chunks: list[RetrievedChunk],
    template: str | None = None,
) -> str:
    return _prompt_service.build_prompt(
        question=question,
        not_found_answer=_NOT_FOUND_ANSWER,
        template=template,
        chunks=[
            PromptContextChunk(
                document_id=str(chunk.document_id),
                chunk_id=str(chunk.chunk_id),
                filename=chunk.filename,
                page_number=chunk.page_number,
                text=chunk.text,
                similarity_score=chunk.similarity_score,
                original_rank=chunk.original_rank,
                rerank_score=chunk.rerank_score,
                rerank_rank=chunk.rerank_rank,
                final_rank=chunk.final_rank,
            )
            for chunk in chunks
        ],
    )


def _to_confidence_signals(
    *, chunks: list[RetrievedChunk], rerank_applied: bool
) -> list[ConfidenceChunkSignal]:
    return [
        ConfidenceChunkSignal(
            similarity_score=chunk.similarity_score,
            rerank_score=chunk.rerank_score if rerank_applied else None,
        )
        for chunk in chunks
    ]


def _serialize_chunk(chunk: RetrievedChunk) -> dict[str, Any]:
    return {
        "document_id": str(chunk.document_id),
        "chunk_id": str(chunk.chunk_id),
        "filename": chunk.filename,
        "page_number": chunk.page_number,
        "similarity_score": round(float(chunk.similarity_score), 6),
        "original_rank": chunk.original_rank,
        "rerank_score": round(float(chunk.rerank_score), 6)
        if chunk.rerank_score is not None
        else None,
        "rerank_rank": chunk.rerank_rank,
        "final_rank": chunk.final_rank,
        "text_snippet": chunk.text[:400],
    }


def _parse_run_config(raw_config: dict[str, Any]) -> EvaluationRunConfig:
    run_name = _normalize_optional_label(raw_config.get("run_name"))
    raw_top_k = raw_config.get("top_k")
    if raw_top_k is None:
        top_k = settings.retrieval_final_top_k
    elif isinstance(raw_top_k, int) and 1 <= raw_top_k <= 200:
        top_k = raw_top_k
    else:
        raise PermanentTaskError("Invalid evaluation run config: top_k")

    raw_rerank = raw_config.get("rerank")
    if raw_rerank is None:
        rerank = True
    elif isinstance(raw_rerank, bool):
        rerank = raw_rerank
    else:
        raise PermanentTaskError("Invalid evaluation run config: rerank")

    raw_model_name = raw_config.get("model_name")
    if raw_model_name is None:
        model_name = settings.openai_llm_model
    elif isinstance(raw_model_name, str) and raw_model_name.strip():
        model_name = raw_model_name.strip()
    else:
        raise PermanentTaskError("Invalid evaluation run config: model_name")

    raw_selected_document_ids = raw_config.get("selected_document_ids", [])
    if not isinstance(raw_selected_document_ids, list):
        raise PermanentTaskError("Invalid evaluation run config: selected_document_ids")
    selected_document_ids: list[UUID] = []
    seen_document_ids: set[UUID] = set()
    for raw_document_id in raw_selected_document_ids:
        if not isinstance(raw_document_id, str) or not raw_document_id.strip():
            raise PermanentTaskError("Invalid evaluation run config: selected_document_ids")
        try:
            parsed_document_id = UUID(raw_document_id.strip())
        except ValueError as exc:
            raise PermanentTaskError(
                "Invalid evaluation run config: selected_document_ids"
            ) from exc
        if parsed_document_id in seen_document_ids:
            continue
        seen_document_ids.add(parsed_document_id)
        selected_document_ids.append(parsed_document_id)

    raw_metric_options = raw_config.get("metric_options", {})
    if not isinstance(raw_metric_options, dict):
        raise PermanentTaskError("Invalid evaluation run config: metric_options")

    raw_chunking_profile_id = raw_config.get("chunking_profile_id")
    if raw_chunking_profile_id is not None and not isinstance(raw_chunking_profile_id, str):
        raise PermanentTaskError("Invalid evaluation run config: chunking_profile_id")
    raw_chunking_profile_config = raw_config.get("chunking_profile_config")
    if raw_chunking_profile_config is not None and not isinstance(
        raw_chunking_profile_config, dict
    ):
        raise PermanentTaskError("Invalid evaluation run config: chunking_profile_config")
    raw_chunking_strategy = raw_config.get("chunking_strategy")
    if raw_chunking_strategy is not None and not isinstance(raw_chunking_strategy, str):
        raise PermanentTaskError("Invalid evaluation run config: chunking_strategy")
    raw_profile_version = raw_config.get("profile_version")
    if raw_profile_version is not None and not isinstance(raw_profile_version, str):
        raise PermanentTaskError("Invalid evaluation run config: profile_version")

    raw_model_profile_id = raw_config.get("model_profile_id")
    if raw_model_profile_id is not None and not isinstance(raw_model_profile_id, str):
        raise PermanentTaskError("Invalid evaluation run config: model_profile_id")

    return EvaluationRunConfig(
        run_name=run_name,
        top_k=top_k,
        rerank=rerank,
        model_name=model_name,
        selected_document_ids=selected_document_ids,
        metric_options=_evaluation_metrics_service.parse_metric_options(dict(raw_metric_options)),
        chunking_profile_id=_normalize_optional_label(raw_chunking_profile_id),
        chunking_profile_config=(
            dict(raw_chunking_profile_config)
            if isinstance(raw_chunking_profile_config, dict)
            else None
        ),
        chunking_strategy=_normalize_optional_label(raw_chunking_strategy),
        profile_version=_normalize_optional_label(raw_profile_version),
        comparison_targets=_parse_comparison_targets(raw_config.get("comparison_targets", [])),
        regression_thresholds=_parse_regression_thresholds(raw_config.get("regression_thresholds")),
        model_profile_id=_normalize_optional_label(raw_model_profile_id),
    )


def _resolve_corpus_document_ids(
    *,
    selected_document_ids: list[UUID],
    questions: list[EvaluationQuestion],
) -> list[UUID]:
    if selected_document_ids:
        return selected_document_ids
    derived: list[UUID] = []
    seen: set[UUID] = set()
    for question in questions:
        if question.expected_document_id is None or question.expected_document_id in seen:
            continue
        seen.add(question.expected_document_id)
        derived.append(question.expected_document_id)
    return derived


async def _collect_chunking_corpus_stats_async(
    *,
    session: AsyncSession,
    document_ids: list[UUID],
    index_version: str,
) -> ChunkingCorpusStats:
    token_counts: list[int] = []
    document_type_counter: Counter[str] = Counter()
    language_counter: Counter[str] = Counter()
    ocr_counter: Counter[str] = Counter()

    for document_id in document_ids:
        document = await _document_repository.get_document_by_id(session, document_id=document_id)
        if document is not None:
            document_type_counter[document.file_type or "unknown"] += 1
            language_counter[document.language or "unknown"] += 1
            snapshot = (
                document.chunking_config_snapshot
                if isinstance(document.chunking_config_snapshot, dict)
                else {}
            )
            if snapshot.get("ocr_applied") is True:
                ocr_counter["ocr_applied"] += 1
            elif snapshot.get("ocr_applied") is False:
                ocr_counter["native_text"] += 1
            else:
                ocr_counter["unknown"] += 1

        chunks = await _document_repository.list_document_chunks(
            session,
            document_id=document_id,
            index_version=index_version,
        )
        token_counts.extend(chunk.token_count for chunk in chunks)

    if not token_counts:
        return ChunkingCorpusStats(
            chunk_count_total=0,
            chunk_tokens_average=None,
            chunk_tokens_variance=None,
            chunk_tokens_min=None,
            chunk_tokens_max=None,
            document_type_breakdown=dict(document_type_counter),
            language_breakdown=dict(language_counter),
            ocr_breakdown=dict(ocr_counter),
        )

    average = sum(token_counts) / len(token_counts)
    variance = sum((count - average) ** 2 for count in token_counts) / len(token_counts)
    return ChunkingCorpusStats(
        chunk_count_total=len(token_counts),
        chunk_tokens_average=round(average, 2),
        chunk_tokens_variance=round(variance, 2),
        chunk_tokens_min=min(token_counts),
        chunk_tokens_max=max(token_counts),
        document_type_breakdown=dict(document_type_counter),
        language_breakdown=dict(language_counter),
        ocr_breakdown=dict(ocr_counter),
    )


async def _prepare_chunking_target_corpus_async(
    *,
    evaluation_run_id: UUID,
    target_index: int,
    target: ChunkingComparisonTarget,
    document_ids: list[UUID],
    request_id: str | None,
    organization_id: str | None,
    user_id: str | None,
) -> tuple[str, ChunkingCorpusStats]:
    if target.chunking_profile_config is None:
        async with SessionLocal() as session:
            stats = await _collect_chunking_corpus_stats_async(
                session=session,
                document_ids=document_ids,
                index_version=settings.document_index_version,
            )
        return settings.document_index_version, stats

    index_version = _build_target_index_version(
        evaluation_run_id=evaluation_run_id,
        target_index=target_index,
    )
    chunking_service = document_tasks._make_chunking_service(
        target.chunking_profile_config,
        index_version=index_version,
    )
    for document_id in document_ids:
        await document_tasks._extract_and_store_document_pages_async(
            str(document_id),
            request_id=request_id,
            organization_id=organization_id,
            user_id=user_id,
            pipeline_type="evaluation.run",
            chunking_service=chunking_service,
            profile_source=target.profile_source,
            persist_document_state=False,
            persist_document_pages=False,
            record_usage_event=False,
        )

    async with SessionLocal() as session:
        stats = await _collect_chunking_corpus_stats_async(
            session=session,
            document_ids=document_ids,
            index_version=index_version,
        )
    return index_version, stats


def _build_regression_flags(
    *,
    baseline_summary: dict[str, Any] | None,
    candidate_summary: dict[str, Any],
    thresholds: EvaluationRegressionThresholds,
) -> list[dict[str, Any]]:
    flags: list[dict[str, Any]] = []

    def maybe_flag(metric: str, value: float | None, minimum: float | None) -> None:
        if value is None or minimum is None or value >= minimum:
            return
        flags.append(
            {
                "metric": metric,
                "status": "failed",
                "threshold": minimum,
                "value": value,
                "message": f"{metric} dropped below the configured threshold",
            }
        )

    maybe_flag(
        "retrieval_hit_rate",
        _normalize_score(candidate_summary.get("retrieval_hit_rate")),
        thresholds.retrieval_hit_rate_min,
    )
    maybe_flag(
        "citation_accuracy_score",
        _normalize_score(candidate_summary.get("citation_accuracy_score")),
        thresholds.citation_accuracy_score_min,
    )
    maybe_flag(
        "faithfulness_score",
        _normalize_score(candidate_summary.get("faithfulness_score")),
        thresholds.faithfulness_score_min,
    )

    not_found_rate = _normalize_score(candidate_summary.get("not_found_rate"))
    if (
        not_found_rate is not None
        and thresholds.max_not_found_rate is not None
        and not_found_rate > thresholds.max_not_found_rate
    ):
        flags.append(
            {
                "metric": "not_found_rate",
                "status": "failed",
                "threshold": thresholds.max_not_found_rate,
                "value": not_found_rate,
                "message": "not_found_rate exceeded the configured threshold",
            }
        )

    baseline_score = _derive_target_score(baseline_summary or {})
    candidate_score = _derive_target_score(candidate_summary)
    if baseline_score is not None and candidate_score is not None:
        candidate_summary["baseline_score"] = baseline_score
        candidate_summary["latest_score"] = candidate_score
        candidate_summary["score_delta"] = round(candidate_score - baseline_score, 4)

    return flags


def _question_use_case(question: EvaluationQuestion) -> str:
    metadata = question.metadata_json if isinstance(question.metadata_json, dict) else {}
    raw_use_case = metadata.get("use_case")
    if isinstance(raw_use_case, str) and raw_use_case.strip():
        return raw_use_case.strip()
    raw_tags = metadata.get("tags")
    if isinstance(raw_tags, list):
        for tag in raw_tags:
            if isinstance(tag, str) and tag.strip():
                return tag.strip()
    return "unlabeled"


def _build_best_target_by_dimension(
    *,
    documents_by_id: dict[UUID, Document],
    questions: list[EvaluationQuestion],
    per_target_question_scores: dict[str, dict[str, float | None]],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    document_type_scores: defaultdict[str, list[tuple[str, float]]] = defaultdict(list)
    use_case_scores: defaultdict[str, list[tuple[str, float]]] = defaultdict(list)

    for question in questions:
        expected_document = (
            documents_by_id.get(question.expected_document_id)
            if question.expected_document_id is not None
            else None
        )
        document_type = expected_document.file_type if expected_document is not None else "unknown"
        use_case = _question_use_case(question)
        for target_label, question_scores in per_target_question_scores.items():
            score = question_scores.get(str(question.id))
            if score is None:
                continue
            document_type_scores[document_type].append((target_label, score))
            use_case_scores[use_case].append((target_label, score))

    def summarize_dimension(
        buckets: defaultdict[str, list[tuple[str, float]]],
    ) -> dict[str, dict[str, Any]]:
        summarized: dict[str, dict[str, Any]] = {}
        for key, values in buckets.items():
            grouped: defaultdict[str, list[float]] = defaultdict(list)
            for label, score in values:
                grouped[label].append(score)
            ranked = sorted(
                (
                    (label, round(sum(scores) / len(scores), 4), len(scores))
                    for label, scores in grouped.items()
                    if scores
                ),
                key=lambda item: (-item[1], item[0]),
            )
            if not ranked:
                continue
            winner = ranked[0]
            summarized[key] = {
                "label": winner[0],
                "score": winner[1],
                "question_count": winner[2],
            }
        return summarized

    return summarize_dimension(document_type_scores), summarize_dimension(use_case_scores)


def _build_target_summary(
    *,
    target: ChunkingComparisonTarget,
    index_version: str,
    corpus_stats: ChunkingCorpusStats,
    metrics: list[EvaluationQuestionMetrics],
    total_questions: int,
    success_count: int,
    failure_count: int,
) -> dict[str, Any]:
    summary = _evaluation_metrics_service.summarize_run(
        metrics=metrics,
        total_questions=total_questions,
        success_count=success_count,
        failure_count=failure_count,
    )
    summary.update(
        {
            "label": target.label,
            "chunking_strategy": target.chunking_strategy,
            "chunking_profile_id": target.chunking_profile_id,
            "profile_version": target.profile_version,
            "profile_source": target.profile_source,
            "index_version": index_version,
            "chunk_count_total": corpus_stats.chunk_count_total,
            "chunk_tokens_average": corpus_stats.chunk_tokens_average,
            "chunk_tokens_variance": corpus_stats.chunk_tokens_variance,
            "chunk_tokens_min": corpus_stats.chunk_tokens_min,
            "chunk_tokens_max": corpus_stats.chunk_tokens_max,
            "document_type_breakdown": corpus_stats.document_type_breakdown,
            "language_breakdown": corpus_stats.language_breakdown,
            "ocr_breakdown": corpus_stats.ocr_breakdown,
        }
    )
    summary["overall_score"] = _derive_target_score(summary)
    return summary


async def _evaluate_question_pipeline_async(
    *,
    question_text: str,
    expected_answer: str | None,
    expected_document_id: UUID | None,
    expected_page_number: int | None,
    organization_id: UUID,
    config: EvaluationRunConfig,
    llm_service: LLMService,
    index_version: str | None = None,
    prompt_template_content: str | None = None,
    prompt_template_metadata: dict[str, Any] | None = None,
    resolved_profile: ResolvedTaskProfile | None = None,
) -> EvaluationQuestionComputation:
    latencies_ms: dict[str, int] = {}
    total_started = perf_counter()
    embedding_model = _query_retrieval_service.embedding_model

    embed_started = perf_counter()
    query_vector, embedding_prompt_tokens = await _query_retrieval_service.embed_query(
        question=question_text,
    )
    latencies_ms["embed"] = int((perf_counter() - embed_started) * 1000)

    retrieval_top_k = max(
        config.top_k,
        _rerank_service.candidate_count if config.rerank else config.top_k,
    )
    retrieve_started = perf_counter()
    retrieved_candidates = _query_retrieval_service.retrieve_candidates(
        query_vector=query_vector,
        organization_id=organization_id,
        document_ids=config.selected_document_ids,
        initial_top_k=retrieval_top_k,
        index_version=index_version,
    )
    retrieved_chunks = [_to_retrieved_chunk(candidate) for candidate in retrieved_candidates]
    retrieved_chunks = _with_original_ranks(retrieved_chunks)
    latencies_ms["retrieve"] = int((perf_counter() - retrieve_started) * 1000)

    rerank_started = perf_counter()
    selected_chunks, _rerank_result = await _rerank_chunks(
        query=question_text,
        chunks=retrieved_chunks,
        enabled=config.rerank,
        final_top_k=config.top_k,
    )
    latencies_ms["rerank"] = int((perf_counter() - rerank_started) * 1000)

    llm_prompt_tokens = 0
    llm_completion_tokens = 0
    llm_model: str | None = None
    llm_cost_usd: Decimal | None = None
    embedding_cost_usd = (Decimal(embedding_prompt_tokens) / Decimal(1_000_000)) * Decimal(
        str(settings.openai_embedding_cost_per_million_tokens_usd)
    )
    citation_validation_score = 1.0

    confidence_signals = _to_confidence_signals(
        chunks=selected_chunks, rerank_applied=config.rerank
    )
    confidence_result = _confidence_service.score(
        chunks=confidence_signals,
        citation_count=0,
        citation_validation_score=1.0,
        not_found_signal=False,
    )
    confidence_score = confidence_result.score
    confidence_category = confidence_result.category
    confidence_explanation = confidence_result.explanation
    not_found = (
        len(selected_chunks) == 0 or confidence_score < settings.confidence_not_found_threshold
    )
    if not_found:
        confidence_result = _confidence_service.score(
            chunks=confidence_signals,
            citation_count=0,
            citation_validation_score=1.0,
            not_found_signal=True,
        )
        confidence_score = confidence_result.score
        confidence_category = confidence_result.category
        confidence_explanation = confidence_result.explanation

    prompt_started = perf_counter()
    prompt = (
        _build_prompt(
            question=question_text,
            chunks=selected_chunks,
            template=prompt_template_content,
        )
        if not not_found
        else ""
    )
    latencies_ms["prompt"] = int((perf_counter() - prompt_started) * 1000)

    answer = _NOT_FOUND_ANSWER
    citations: list[dict[str, Any]] = []
    judge_scores: EvaluationJudgeScores | None = None
    judge_error: str | None = None
    llm_latency_ms = 0
    if not not_found:
        try:
            llm_result = await llm_service.generate_answer(
                prompt=prompt,
                resolved_profile=resolved_profile,
            )
        except (TransientLLMServiceError, PermanentLLMServiceError) as exc:
            raise RuntimeError("llm_generation_failed") from exc

        llm_latency_ms = llm_result.latency_ms
        llm_model = llm_result.model_name
        llm_prompt_tokens = llm_result.prompt_tokens
        llm_completion_tokens = llm_result.completion_tokens
        llm_cost_usd = llm_result.approximate_cost_usd
        answer = llm_result.answer

        if llm_result.not_found or not answer.strip() or answer.strip() == _NOT_FOUND_ANSWER:
            answer = _NOT_FOUND_ANSWER
            not_found = True
        else:
            citation_result = _citation_service.build_citations(
                not_found=False,
                answer=answer,
                retrieved_chunks=[
                    CitationContextChunk(
                        document_id=chunk.document_id,
                        chunk_id=chunk.chunk_id,
                        filename=chunk.filename,
                        page_number=chunk.page_number,
                        text=chunk.text,
                        similarity_score=chunk.similarity_score,
                        rerank_score=chunk.rerank_score,
                        rerank_rank=chunk.rerank_rank,
                    )
                    for chunk in selected_chunks
                ],
                model_citations=llm_result.citations,
            )
            citations = [citation.model_dump() for citation in citation_result.citations]
            citation_validation_score = citation_result.validation_score
            confidence_result = _confidence_service.score(
                chunks=confidence_signals,
                citation_count=len(citations),
                citation_validation_score=citation_validation_score,
                not_found_signal=False,
            )
            confidence_score = confidence_result.score
            confidence_category = confidence_result.category
            confidence_explanation = confidence_result.explanation

        if not not_found and (
            config.metric_options.faithfulness_enabled
            or config.metric_options.answer_relevance_enabled
        ):
            judge_model_name = config.metric_options.judge_model_name or config.model_name
            try:
                judge_scores = await _evaluate_with_llm_judge_async(
                    model_name=judge_model_name,
                    question=question_text,
                    expected_answer=expected_answer,
                    generated_answer=answer,
                    retrieved_chunks=selected_chunks,
                    resolved_profile=resolved_profile,
                )
            except Exception as exc:
                judge_error = exc.__class__.__name__

        if not_found:
            confidence_result = _confidence_service.score(
                chunks=confidence_signals,
                citation_count=0,
                citation_validation_score=1.0,
                not_found_signal=True,
            )
            confidence_score = confidence_result.score
            confidence_category = confidence_result.category
            confidence_explanation = confidence_result.explanation
            citations = []
    latencies_ms["llm"] = llm_latency_ms

    total_latency_ms = int((perf_counter() - total_started) * 1000)
    latencies_ms["total"] = total_latency_ms
    citation_accuracy_score = citation_validation_score if citations else None
    total_cost_usd = (llm_cost_usd or Decimal("0")) + embedding_cost_usd
    question_metrics = _evaluation_metrics_service.score_question(
        expected_document_id=expected_document_id,
        expected_page_number=expected_page_number,
        expected_answer=expected_answer,
        generated_answer=answer,
        not_found=not_found,
        retrieved_chunks=[
            RetrievedMetricChunk(
                document_id=chunk.document_id,
                page_number=chunk.page_number,
            )
            for chunk in retrieved_chunks
        ],
        selected_chunk_count=len(selected_chunks),
        citation_count=len(citations),
        citation_accuracy_score=citation_accuracy_score,
        latency_ms=total_latency_ms,
        cost_usd=total_cost_usd,
        token_input_count=embedding_prompt_tokens + llm_prompt_tokens,
        token_output_count=llm_completion_tokens,
        options=config.metric_options,
        judge_scores=judge_scores,
        judge_error=judge_error,
    )
    retrieval_score = question_metrics.retrieval_hit_rate
    if retrieval_score is None:
        retrieval_score = retrieved_chunks[0].similarity_score if retrieved_chunks else None

    provider_key = resolved_profile.provider_type if resolved_profile is not None else settings.llm_default_provider
    details: dict[str, Any] = {
        "status": "completed",
        "question": question_text,
        "expected_answer": expected_answer,
        "expected_document_id": str(expected_document_id)
        if expected_document_id is not None
        else None,
        "expected_page_number": expected_page_number,
        "not_found": not_found,
        "confidence_score": confidence_score,
        "confidence_category": confidence_category,
        "confidence_explanation": asdict(confidence_explanation),
        "citation_validation_score": citation_validation_score,
        "latencies_ms": latencies_ms,
        "retrieval_count": len(retrieved_chunks),
        "selected_count": len(selected_chunks),
        "rerank_applied": config.rerank,
        "embedding_model": embedding_model,
        "llm_model": llm_model,
        "provider_key": provider_key,
        "provider_type": resolved_profile.provider_type if resolved_profile is not None else None,
        "base_model": resolved_profile.base_model if resolved_profile is not None else config.model_name,
        "token_input_count": embedding_prompt_tokens + llm_prompt_tokens,
        "token_output_count": llm_completion_tokens,
        "cost_usd": float(total_cost_usd),
        "embedding_cost_usd": float(embedding_cost_usd),
        "llm_cost_usd": float(llm_cost_usd) if llm_cost_usd is not None else 0.0,
        "citations": citations,
        "retrieved_chunks": [_serialize_chunk(chunk) for chunk in retrieved_chunks],
        "selected_chunks": [_serialize_chunk(chunk) for chunk in selected_chunks],
        "metric_options": config.metric_options.as_dict(),
        "metrics": question_metrics.as_dict(),
    }
    if prompt_template_metadata is not None:
        details["prompt_template"] = dict(prompt_template_metadata)
    return EvaluationQuestionComputation(
        generated_answer=answer,
        retrieval_score=retrieval_score,
        faithfulness_score=question_metrics.faithfulness_score,
        citation_accuracy_score=question_metrics.citation_accuracy_score,
        answer_relevance_score=question_metrics.answer_relevance_score,
        metrics=question_metrics,
        latency_ms=total_latency_ms,
        details=details,
    )


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

    async with SessionLocal() as session:
        evaluation_run = await _evaluation_repository.get_evaluation_run(
            session,
            evaluation_run_id=parsed_run_id,
        )
        if evaluation_run is None:
            raise PermanentTaskError(f"Evaluation run not found: {evaluation_run_id}")

        evaluation_set = await _evaluation_repository.get_evaluation_set_by_id(
            session,
            evaluation_set_id=evaluation_run.evaluation_set_id,
        )
        if evaluation_set is None:
            raise PermanentTaskError(
                f"Evaluation set not found for run: {evaluation_run.evaluation_set_id}"
            )

        questions = await _evaluation_repository.list_all_evaluation_questions(
            session,
            evaluation_set_id=evaluation_set.id,
        )
        run_config = _parse_run_config(
            evaluation_run.config if isinstance(evaluation_run.config, dict) else {}
        )
        prompt_template_content: str | None = None
        prompt_template_metadata: dict[str, Any] | None = None
        if evaluation_run.prompt_template_version_id is not None:
            prompt_version = await _prompt_template_repository.get_version_by_id(
                session,
                version_id=evaluation_run.prompt_template_version_id,
            )
            if prompt_version is not None:
                prompt_template_content = prompt_version.content
                raw_config = (
                    evaluation_run.config if isinstance(evaluation_run.config, dict) else {}
                )
                config_prompt_template = raw_config.get("prompt_template")
                prompt_template_metadata = (
                    dict(config_prompt_template)
                    if isinstance(config_prompt_template, dict)
                    else {
                        "version_id": str(prompt_version.id),
                        "version_number": prompt_version.version_number,
                    }
                )
        llm_service = LLMService(model_name=run_config.model_name)
        resolved_run_profile: ResolvedTaskProfile | None = None
        if run_config.model_profile_id is not None:
            try:
                profile_uuid = UUID(run_config.model_profile_id)
            except ValueError as exc:
                raise PermanentTaskError(
                    f"Invalid model_profile_id in run config: {run_config.model_profile_id}"
                ) from exc
            profile_row = await get_profile_by_id(
                session,
                profile_id=profile_uuid,
                organization_id=evaluation_set.organization_id,
            )
            if profile_row is None:
                raise PermanentTaskError(
                    f"Model profile not found or inaccessible: {run_config.model_profile_id}"
                )
            resolved_run_profile = _profile_to_resolved(profile_row)
        else:
            resolved_run_profile = await resolve_task_profile(
                session,
                organization_id=evaluation_set.organization_id,
                task_type=TaskType.evaluations,
            )
        corpus_document_ids = _resolve_corpus_document_ids(
            selected_document_ids=run_config.selected_document_ids,
            questions=questions,
        )
        documents_by_id: dict[UUID, Document] = {}
        resolved_corpus_document_ids: list[UUID] = []
        for document_id in corpus_document_ids:
            document = await _document_repository.get_document_by_id(
                session,
                document_id=document_id,
            )
            if document is None or document.organization_id != evaluation_set.organization_id:
                continue
            documents_by_id[document_id] = document
            resolved_corpus_document_ids.append(document_id)

        if run_config.comparison_targets:
            comparison_targets = run_config.comparison_targets
        elif (
            run_config.chunking_profile_id is not None
            or run_config.chunking_profile_config is not None
        ):
            comparison_targets = [
                ChunkingComparisonTarget(
                    label=run_config.run_name or "Pinned profile",
                    profile_source=(
                        "inline_profile"
                        if run_config.chunking_profile_id is None
                        else "organization_profile"
                    ),
                    chunking_profile_id=run_config.chunking_profile_id,
                    chunking_profile_config=run_config.chunking_profile_config,
                    chunking_strategy=run_config.chunking_strategy,
                    profile_version=run_config.profile_version,
                )
            ]
        else:
            comparison_targets = [
                ChunkingComparisonTarget(
                    label="Current index",
                    profile_source="system_default",
                    chunking_profile_id=None,
                    chunking_profile_config=None,
                    chunking_strategy="live_index",
                    profile_version=settings.document_index_version,
                )
            ]

        # Idempotent retry behavior: replace previous results for this run.
        try:
            _ = await _evaluation_repository.delete_evaluation_results_for_run(
                session,
                evaluation_run_id=parsed_run_id,
            )
            await session.commit()
        except Exception as exc:
            await session.rollback()
            raise TransientTaskError(
                f"Unable to clear stale evaluation results for run: {evaluation_run_id}"
            ) from exc

        target_summaries: list[dict[str, Any]] = []
        per_target_question_scores: dict[str, dict[str, float | None]] = {}
        primary_question_success_count = 0
        primary_question_failure_count = 0

        for target_index, target in enumerate(comparison_targets):
            target_index_version, corpus_stats = await _prepare_chunking_target_corpus_async(
                evaluation_run_id=parsed_run_id,
                target_index=target_index,
                target=target,
                document_ids=resolved_corpus_document_ids,
                request_id=request_id,
                organization_id=organization_id,
                user_id=user_id,
            )
            question_success_count = 0
            question_failure_count = 0
            successful_metrics: list[EvaluationQuestionMetrics] = []
            target_question_scores: dict[str, float | None] = {}

            for question in questions:
                question_started = perf_counter()
                try:
                    computed = await _evaluate_question_pipeline_async(
                        question_text=question.question,
                        expected_answer=question.expected_answer,
                        expected_document_id=question.expected_document_id,
                        expected_page_number=question.expected_page_number,
                        organization_id=evaluation_set.organization_id,
                        config=run_config,
                        llm_service=llm_service,
                        index_version=target_index_version,
                        prompt_template_content=prompt_template_content,
                        prompt_template_metadata=prompt_template_metadata,
                        resolved_profile=resolved_run_profile,
                    )
                except Exception as exc:
                    question_failure_count += 1
                    failed_metrics = _evaluation_metrics_service.score_question(
                        expected_document_id=question.expected_document_id,
                        expected_page_number=question.expected_page_number,
                        expected_answer=question.expected_answer,
                        generated_answer="",
                        not_found=True,
                        retrieved_chunks=[],
                        selected_chunk_count=0,
                        citation_count=0,
                        citation_accuracy_score=None,
                        latency_ms=int((perf_counter() - question_started) * 1000),
                        cost_usd=0.0,
                        token_input_count=0,
                        token_output_count=0,
                        options=run_config.metric_options,
                        judge_scores=None,
                        judge_error=exc.__class__.__name__,
                    )
                    computed = EvaluationQuestionComputation(
                        generated_answer="",
                        retrieval_score=None,
                        faithfulness_score=None,
                        citation_accuracy_score=None,
                        answer_relevance_score=None,
                        metrics=failed_metrics,
                        latency_ms=failed_metrics.latency_ms,
                        details={
                            "status": "failed",
                            "question": question.question,
                            "expected_answer": question.expected_answer,
                            "expected_document_id": (
                                str(question.expected_document_id)
                                if question.expected_document_id is not None
                                else None
                            ),
                            "expected_page_number": question.expected_page_number,
                            "metrics": failed_metrics.as_dict(),
                            "error": str(exc),
                            "error_type": exc.__class__.__name__,
                        },
                    )
                    log_evaluation_event(
                        event="evaluation.question.failed",
                        organization_id=organization_id or str(evaluation_set.organization_id),
                        user_id=user_id,
                        job_id=evaluation_run_id,
                        request_id=request_id,
                        question_id=str(question.id),
                        error=exc.__class__.__name__,
                        target_label=target.label,
                        index_version=target_index_version,
                    )
                else:
                    question_success_count += 1
                    successful_metrics.append(computed.metrics)
                    log_evaluation_event(
                        event="evaluation.question.completed",
                        organization_id=organization_id or str(evaluation_set.organization_id),
                        user_id=user_id,
                        job_id=evaluation_run_id,
                        request_id=request_id,
                        question_id=str(question.id),
                        not_found=computed.details.get("not_found"),
                        confidence_score=computed.answer_relevance_score,
                        target_label=target.label,
                        index_version=target_index_version,
                    )

                computed.details["chunking_target"] = {
                    "label": target.label,
                    "chunking_strategy": target.chunking_strategy,
                    "chunking_profile_id": target.chunking_profile_id,
                    "profile_version": target.profile_version,
                    "profile_source": target.profile_source,
                    "index_version": target_index_version,
                }
                target_question_scores[str(question.id)] = _derive_target_score(
                    computed.metrics.as_dict()
                )

                if target_index == 0:
                    try:
                        await _evaluation_repository.create_evaluation_result(
                            session,
                            evaluation_run_id=parsed_run_id,
                            evaluation_question_id=question.id,
                            generated_answer=computed.generated_answer or None,
                            retrieval_score=computed.retrieval_score,
                            faithfulness_score=computed.faithfulness_score,
                            citation_accuracy_score=computed.citation_accuracy_score,
                            answer_relevance_score=computed.answer_relevance_score,
                            latency_ms=computed.latency_ms,
                            details=computed.details,
                        )
                        await session.commit()
                    except Exception as exc:
                        await session.rollback()
                        raise TransientTaskError(
                            f"Unable to persist evaluation result for question: {question.id}"
                        ) from exc

            if target_index == 0:
                primary_question_success_count = question_success_count
                primary_question_failure_count = question_failure_count

            target_summary = _build_target_summary(
                target=target,
                index_version=target_index_version,
                corpus_stats=corpus_stats,
                metrics=successful_metrics,
                total_questions=len(questions),
                success_count=question_success_count,
                failure_count=question_failure_count,
            )
            target_summaries.append(target_summary)
            per_target_question_scores[target.label] = target_question_scores

        primary_summary = (
            dict(target_summaries[0])
            if target_summaries
            else _evaluation_metrics_service.summarize_run(
                metrics=[],
                total_questions=len(questions),
                success_count=0,
                failure_count=0,
            )
        )
        baseline_summary = target_summaries[0] if target_summaries else None
        comparison_payload: dict[str, Any] | None = None
        if baseline_summary is not None and len(target_summaries) > 1:
            ranked_candidates = sorted(
                target_summaries[1:],
                key=lambda item: (
                    item.get("overall_score") is None,
                    0.0 if item.get("overall_score") is None else -float(item["overall_score"]),
                    str(item.get("label") or ""),
                ),
            )
            latest_summary = ranked_candidates[0]
            baseline_score = _normalize_score(baseline_summary.get("overall_score"))
            latest_score = _normalize_score(latest_summary.get("overall_score"))
            comparison_payload = {
                "baseline_label": baseline_summary.get("label") or "Baseline",
                "baseline_score": baseline_score,
                "latest_label": latest_summary.get("label") or "Candidate",
                "latest_score": latest_score,
                "score_delta": (
                    round(latest_score - baseline_score, 4)
                    if baseline_score is not None and latest_score is not None
                    else None
                ),
            }

        regression_count = 0
        regression_failed = False
        for index, target_summary in enumerate(target_summaries):
            flags = _build_regression_flags(
                baseline_summary=baseline_summary if index > 0 else None,
                candidate_summary=target_summary,
                thresholds=run_config.regression_thresholds,
            )
            target_summary["regression_flags"] = flags
            target_summary["regression_failed"] = len(flags) > 0
            regression_count += len(flags)
            regression_failed = regression_failed or bool(flags)

        best_by_document_type, best_by_use_case = _build_best_target_by_dimension(
            documents_by_id=documents_by_id,
            questions=questions,
            per_target_question_scores=per_target_question_scores,
        )

        total_questions = len(questions)
        metrics_summary = dict(primary_summary)
        metrics_summary["comparison_targets"] = target_summaries
        metrics_summary["best_by_document_type"] = best_by_document_type
        metrics_summary["best_by_use_case"] = best_by_use_case
        metrics_summary["regressions_count"] = regression_count
        metrics_summary["regression_failed"] = regression_failed
        if prompt_template_metadata is not None:
            metrics_summary["prompt_template"] = dict(prompt_template_metadata)
        if comparison_payload is not None:
            metrics_summary["comparison"] = comparison_payload
        if resolved_run_profile is not None:
            metrics_summary["model_profile"] = {
                "provider_type": resolved_run_profile.provider_type,
                "base_model": resolved_run_profile.base_model,
                "source": resolved_run_profile.source.value,
                "task_type": resolved_run_profile.task_type.value,
                "version": resolved_run_profile.version,
                "is_local": resolved_run_profile.provider_type == "local",
            }

        try:
            updated_run = await _evaluation_repository.update_evaluation_run_config(
                session,
                evaluation_run_id=parsed_run_id,
                config_patch={
                    "metrics_summary": metrics_summary,
                    "metric_options_effective": run_config.metric_options.as_dict(),
                },
            )
            if updated_run is None:
                raise RuntimeError("evaluation run not found while updating summary")
            await session.commit()
        except Exception as exc:
            await session.rollback()
            raise TransientTaskError(
                f"Unable to persist evaluation summary for run: {evaluation_run_id}"
            ) from exc

        log_evaluation_event(
            event="evaluation.run.metrics_computed",
            organization_id=organization_id or str(evaluation_set.organization_id),
            user_id=user_id,
            job_id=evaluation_run_id,
            request_id=request_id,
            metrics_summary=metrics_summary,
        )
        return {
            "evaluation_run_id": evaluation_run_id,
            "question_total_count": total_questions,
            "question_success_count": primary_question_success_count,
            "question_failure_count": primary_question_failure_count,
            "all_questions_failed": total_questions > 0 and primary_question_success_count == 0,
            "metrics_summary": metrics_summary,
        }


class EvaluationTask(RudixTask):
    abstract = True

    def on_terminal_failure(
        self,
        *,
        exc: Exception,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> None:
        evaluation_run_id = kwargs.get("evaluation_run_id")
        if evaluation_run_id is None and args:
            evaluation_run_id = args[0]
        if not isinstance(evaluation_run_id, str):
            return
        try:
            set_evaluation_status(
                evaluation_run_id,
                status=EvaluationRunStatus.failed,
                mark_completed=True,
            )
            log_evaluation_event(
                event="evaluation.run.failed",
                job_id=evaluation_run_id,
                request_id=kwargs.get("request_id"),
                organization_id=kwargs.get("organization_id"),
                user_id=kwargs.get("user_id"),
                status_code=EvaluationRunStatus.failed.value,
                error=str(exc),
            )
            _record_worker_audit(
                action="evaluation.run.failed",
                resource_type="evaluation_run",
                resource_id=evaluation_run_id,
                organization_id=kwargs.get("organization_id"),
                user_id=kwargs.get("user_id"),
                request_id=kwargs.get("request_id"),
                metadata={
                    "status": EvaluationRunStatus.failed.value,
                    "task_name": self.name,
                    "error_type": exc.__class__.__name__,
                },
            )
            from app.workers.notification_helper import emit_notification

            emit_notification(
                organization_id=kwargs.get("organization_id"),
                user_id=kwargs.get("user_id"),
                event_type="evaluation_failed",
                severity="error",
                title="Evaluation run failed",
                message="The evaluation run could not be completed.",
                href=f"/evaluations/runs/{evaluation_run_id}",
                source_id=evaluation_run_id,
            )
        except Exception:
            return


@celery_app.task(name="evaluations.run", bind=True, base=EvaluationTask, ignore_result=True)
def run_evaluation(
    self: EvaluationTask,
    evaluation_run_id: str,
    *,
    request_id: str | None = None,
    organization_id: str | None = None,
    user_id: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Run evaluation questions through the query pipeline and persist per-question outcomes."""
    try:
        status = get_evaluation_status(evaluation_run_id)
    except ValueError as exc:
        raise PermanentTaskError(f"Invalid evaluation_run_id: {evaluation_run_id}") from exc
    if status is None:
        raise PermanentTaskError(f"Evaluation run not found: {evaluation_run_id}")

    if not force and status == EvaluationRunStatus.completed.value:
        log_evaluation_event(
            event="evaluation.run.skipped",
            job_id=evaluation_run_id,
            request_id=request_id,
            organization_id=organization_id,
            user_id=user_id,
            status_code=status,
        )
        return {"evaluation_run_id": evaluation_run_id, "status": "skipped"}

    running_updated = set_evaluation_status(
        evaluation_run_id,
        status=EvaluationRunStatus.running,
        mark_started=True,
    )
    if not running_updated:
        raise TransientTaskError(
            f"Unable to move evaluation run to running state: {evaluation_run_id}"
        )

    log_evaluation_event(
        event="evaluation.run.started",
        job_id=evaluation_run_id,
        request_id=request_id,
        organization_id=organization_id,
        user_id=user_id,
        status_code=EvaluationRunStatus.running.value,
    )

    summary = _run(
        _run_evaluation_async(
            evaluation_run_id,
            request_id=request_id,
            organization_id=organization_id,
            user_id=user_id,
        )
    )
    final_status = (
        EvaluationRunStatus.failed
        if summary["all_questions_failed"]
        else EvaluationRunStatus.completed
    )

    completed_updated = set_evaluation_status(
        evaluation_run_id,
        status=final_status,
        mark_completed=True,
    )
    if not completed_updated:
        raise TransientTaskError(
            f"Unable to move evaluation run to final state: {evaluation_run_id}"
        )

    log_evaluation_event(
        event="evaluation.run.completed",
        job_id=evaluation_run_id,
        request_id=request_id,
        organization_id=organization_id,
        user_id=user_id,
        status_code=final_status.value,
        question_total_count=summary["question_total_count"],
        question_success_count=summary["question_success_count"],
        question_failure_count=summary["question_failure_count"],
    )
    _record_worker_audit(
        action="evaluation.run.completed",
        resource_type="evaluation_run",
        resource_id=evaluation_run_id,
        organization_id=organization_id,
        user_id=user_id,
        request_id=request_id,
        metadata={
            "status": final_status.value,
            "question_total_count": summary["question_total_count"],
            "question_success_count": summary["question_success_count"],
            "question_failure_count": summary["question_failure_count"],
        },
    )
    from app.workers.notification_helper import emit_notification

    if final_status == EvaluationRunStatus.completed:
        emit_notification(
            organization_id=organization_id,
            user_id=user_id,
            event_type="evaluation_complete",
            severity="info",
            title="Evaluation run completed",
            message=(
                f"{summary['question_success_count']}/{summary['question_total_count']} "
                "question(s) passed."
            ),
            href=f"/evaluations/runs/{evaluation_run_id}",
            source_id=evaluation_run_id,
        )
    else:
        emit_notification(
            organization_id=organization_id,
            user_id=user_id,
            event_type="evaluation_failed",
            severity="error",
            title="Evaluation run failed",
            message="All questions failed during evaluation.",
            href=f"/evaluations/runs/{evaluation_run_id}",
            source_id=evaluation_run_id,
        )
    return {
        "evaluation_run_id": evaluation_run_id,
        "status": final_status.value,
        "question_total_count": summary["question_total_count"],
        "question_success_count": summary["question_success_count"],
        "question_failure_count": summary["question_failure_count"],
        "metrics_summary": summary.get("metrics_summary"),
    }
