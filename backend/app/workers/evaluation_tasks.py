"""Facade of the evaluation worker (R06-12).

The implementation lives in ``app.workers.evaluation`` (one module per concern). This
module keeps the task ``evaluations.run`` with its signature, every name callers and tests
import, and the collaborators they rebind: ``SessionLocal``, ``LLMService``,
``QueryRetrievalService``, ``_query_retrieval_service``, the repository and service
singletons, ``default_provider_factory``, ``set_evaluation_status``,
``get_evaluation_status``, ``cleanup_eval_index_version_async``,
``_prepare_chunking_target_corpus_async``, ``_evaluate_question_pipeline_async``,
``_evaluate_with_llm_judge_async``, ``_run_evaluation_async``, ``_record_worker_audit``,
``_record_worker_audit_async`` and ``_run``. The modules read them from here at call time
(``app.workers.evaluation.facade()``), so a ``monkeypatch.setattr(evaluation_tasks, ...)``
reaches every caller. ``REBINDABLE_FACADE_NAMES`` lists them.
"""

from __future__ import annotations

from collections.abc import Coroutine
from typing import Any

from app.db.session import SessionLocal
from app.domains.admin.services.audit_service import AuditLogService
from app.domains.ai.providers.factory import default_provider_factory
from app.domains.chat.services.citation_service import CitationService
from app.domains.chat.services.confidence_service import ConfidenceService
from app.domains.chat.services.llm_service import LLMService
from app.domains.chat.services.prompt_service import PromptService
from app.domains.chat.services.query_retrieval_service import QueryRetrievalService
from app.domains.chat.services.rerank_service import RerankService
from app.domains.documents.repositories.documents import DocumentRepository
from app.domains.evaluations.repositories.evaluations import EvaluationRepository
from app.domains.evaluations.services.evaluation_metrics_service import EvaluationMetricsService
from app.domains.prompt_templates.repositories.prompt_templates import PromptTemplateRepository
from app.workers import document_tasks
from app.workers.async_runtime import run_async
from app.workers.base_task import PermanentTaskError, RudixTask, TransientTaskError
from app.workers.evaluation.comparison import (
    _build_best_target_by_dimension,
    _build_regression_flags,
    _build_target_summary,
    _derive_target_score,
    _question_use_case,
)
from app.workers.evaluation.config import (
    ChunkingComparisonTarget,
    EvaluationRegressionThresholds,
    EvaluationRunConfig,
    _coerce_score,
    _normalize_optional_label,
    _normalize_score,
    _parse_comparison_targets,
    _parse_optional_uuid,
    _parse_regression_thresholds,
    _parse_run_config,
    _parse_uuid,
    _resolve_corpus_document_ids,
)
from app.workers.evaluation.corpus import (
    ChunkingCorpusStats,
    _build_target_index_version,
    _cleanup_target_index_async,
    _collect_chunking_corpus_stats_async,
    _prepare_chunking_target_corpus_async,
)
from app.workers.evaluation.judge import _evaluate_with_llm_judge_async
from app.workers.evaluation.question import (
    _NOT_FOUND_ANSWER,
    EvaluationQuestionComputation,
    RetrievedChunk,
    _build_prompt,
    _evaluate_question_pipeline_async,
    _rerank_chunks,
    _serialize_chunk,
    _to_confidence_signals,
    _to_retrieved_chunk,
    _with_original_ranks,
)
from app.workers.evaluation.run import _run_evaluation_async
from app.workers.evaluation.tasks import (
    EvaluationTask,
    _record_worker_audit,
    _record_worker_audit_async,
    run_evaluation,
)
from app.workers.evaluation_index_cleanup import (
    cleanup_eval_index_version_async,
    is_eval_index_version,
)
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


def _run[T](coro: Coroutine[Any, Any, T]) -> T:
    return run_async(coro)


# Names the evaluation modules read from this module at call time.
REBINDABLE_FACADE_NAMES: tuple[str, ...] = (
    "SessionLocal",
    "LLMService",
    "QueryRetrievalService",
    "default_provider_factory",
    "_evaluation_repository",
    "_query_retrieval_service",
    "_rerank_service",
    "_prompt_service",
    "_prompt_template_repository",
    "_citation_service",
    "_confidence_service",
    "_evaluation_metrics_service",
    "_audit_log_service",
    "_document_repository",
    "set_evaluation_status",
    "get_evaluation_status",
    "cleanup_eval_index_version_async",
    "_prepare_chunking_target_corpus_async",
    "_evaluate_question_pipeline_async",
    "_evaluate_with_llm_judge_async",
    "_run_evaluation_async",
    "_record_worker_audit",
    "_record_worker_audit_async",
    "_run",
)

__all__ = [
    "REBINDABLE_FACADE_NAMES",
    "_NOT_FOUND_ANSWER",
    "ChunkingComparisonTarget",
    "ChunkingCorpusStats",
    "EvaluationQuestionComputation",
    "EvaluationRegressionThresholds",
    "EvaluationRunConfig",
    "EvaluationTask",
    "LLMService",
    "PermanentTaskError",
    "QueryRetrievalService",
    "RetrievedChunk",
    "RudixTask",
    # REBINDABLE_FACADE_NAMES
    "SessionLocal",
    "TransientTaskError",
    "_audit_log_service",
    "_build_best_target_by_dimension",
    "_build_prompt",
    "_build_regression_flags",
    "_build_target_index_version",
    "_build_target_summary",
    "_citation_service",
    "_cleanup_target_index_async",
    "_coerce_score",
    "_collect_chunking_corpus_stats_async",
    "_confidence_service",
    "_derive_target_score",
    "_document_repository",
    "_evaluate_question_pipeline_async",
    "_evaluate_with_llm_judge_async",
    "_evaluation_metrics_service",
    "_evaluation_repository",
    "_normalize_optional_label",
    "_normalize_score",
    "_parse_comparison_targets",
    "_parse_optional_uuid",
    "_parse_regression_thresholds",
    "_parse_run_config",
    "_parse_uuid",
    "_prepare_chunking_target_corpus_async",
    "_prompt_service",
    "_prompt_template_repository",
    "_query_retrieval_service",
    "_question_use_case",
    "_record_worker_audit",
    "_record_worker_audit_async",
    "_rerank_chunks",
    "_rerank_service",
    "_resolve_corpus_document_ids",
    "_run",
    "_run_evaluation_async",
    "_serialize_chunk",
    "_to_confidence_signals",
    "_to_retrieved_chunk",
    "_with_original_ranks",
    "cleanup_eval_index_version_async",
    "default_provider_factory",
    "document_tasks",
    "get_evaluation_status",
    "is_eval_index_version",
    "run_evaluation",
    "set_evaluation_status",
]
