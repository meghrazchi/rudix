from __future__ import annotations

import logging
from time import perf_counter
from typing import Any

from fastapi import FastAPI, Request, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

from app.core.config import settings

logger = logging.getLogger("observability.metrics")

# Central Prometheus metrics registry
registry = CollectorRegistry(auto_describe=True)

# ---------------------------------------------------------------------------
# Metric Definitions
# ---------------------------------------------------------------------------

# HTTP RED Metrics
HTTP_REQUESTS_TOTAL = Counter(
    "rudix_http_requests_total",
    "Total HTTP requests by normalized route template and status code",
    ["method", "route", "status_code"],
    registry=registry,
)

HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "rudix_http_request_duration_seconds",
    "End-to-end HTTP request latency in seconds",
    ["method", "route"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
    registry=registry,
)

HTTP_REQUESTS_IN_PROGRESS = Gauge(
    "rudix_http_requests_in_progress",
    "Concurrent in-flight HTTP requests",
    ["method", "route"],
    registry=registry,
)

RATE_LIMIT_DECISIONS_TOTAL = Counter(
    "rudix_rate_limit_decisions_total",
    "Rate limiting decisions by scope, decision, and failure mode",
    ["scope", "decision", "failure_mode"],
    registry=registry,
)

AUTH_VERIFICATIONS_TOTAL = Counter(
    "rudix_auth_verifications_total",
    "Authentication token verification outcomes",
    ["provider", "outcome"],
    registry=registry,
)

AUTHZ_DECISIONS_TOTAL = Counter(
    "rudix_authz_decisions_total",
    "Authorization policy decisions by resource, action, decision, and deny reason",
    ["resource_type", "action", "decision", "deny_reason"],
    registry=registry,
)

# RAG & LLM Metrics
RAG_QUERY_DURATION_SECONDS = Histogram(
    "rudix_rag_query_duration_seconds",
    "Total RAG chat query execution latency in seconds",
    ["scope_mode", "status"],
    buckets=(0.1, 0.25, 0.5, 1.0, 2.0, 3.0, 5.0, 8.0, 15.0, 30.0),
    registry=registry,
)

RAG_STAGE_DURATION_SECONDS = Histogram(
    "rudix_rag_stage_duration_seconds",
    "Latency of individual RAG stages in seconds",
    ["stage", "provider"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    registry=registry,
)

RAG_ANSWERS_TOTAL = Counter(
    "rudix_rag_answers_total",
    "Completed RAG answers by grounding and fallback outcomes",
    ["scope_mode", "confidence_category", "not_found", "fallback_used"],
    registry=registry,
)

RAG_CONFIDENCE_SCORE = Histogram(
    "rudix_rag_confidence_score",
    "Distribution of answer confidence scores",
    ["scope_mode"],
    buckets=(0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0),
    registry=registry,
)

RAG_CITATION_VALIDATION_FAILURES_TOTAL = Counter(
    "rudix_rag_citation_validation_failures_total",
    "Responses where citation validation failed by reason",
    ["reason"],
    registry=registry,
)

LLM_REQUESTS_TOTAL = Counter(
    "rudix_llm_requests_total",
    "LLM and embedding provider API calls by operation and status",
    ["provider", "model", "operation", "status"],
    registry=registry,
)

LLM_TOKENS_TOTAL = Counter(
    "rudix_llm_tokens_total",
    "LLM and embedding token consumption by provider, model, and direction",
    ["provider", "model", "direction"],
    registry=registry,
)

LLM_ESTIMATED_COST_USD_TOTAL = Counter(
    "rudix_llm_estimated_cost_usd_total",
    "Cumulative estimated USD spend by provider and model",
    ["provider", "model"],
    registry=registry,
)

LLM_RETRIES_TOTAL = Counter(
    "rudix_llm_retries_total",
    "LLM provider retry events by reason",
    ["provider", "model", "reason"],
    registry=registry,
)

# Chat token ledger (R05-07): tokens of every provider call in a chat run, by pipeline
# stage and kind (prompt, completion, cached). Counted once the run is persisted.
CHAT_TOKENS_TOTAL = Counter(
    "rudix_chat_tokens_total",
    "Chat pipeline tokens by stage and kind (prompt, completion, cached)",
    ["stage", "kind"],
    registry=registry,
)

# Retrieved chunks matching prompt-injection patterns (R05-09), by configured action.
CHAT_CONTEXT_INJECTION_FLAGGED_TOTAL = Counter(
    "rudix_chat_context_injection_flagged_total",
    "Retrieved chunks flagged by the context injection scan, by action",
    ["action"],
    registry=registry,
)

# Document Ingestion & Chunking Metrics
DOCUMENT_UPLOADS_TOTAL = Counter(
    "rudix_document_uploads_total",
    "Document upload outcomes by file type, status, and malware scan result",
    ["file_type", "status", "malware_scan_result"],
    registry=registry,
)

DOCUMENT_INDEXING_JOBS_TOTAL = Counter(
    "rudix_document_indexing_jobs_total",
    "Document indexing job executions by task type, file type, and status",
    ["task_type", "file_type", "status"],
    registry=registry,
)

DOCUMENT_INDEXING_DURATION_SECONDS = Histogram(
    "rudix_document_indexing_duration_seconds",
    "Duration of document indexing stages in seconds",
    ["stage", "file_type"],
    buckets=(0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0),
    registry=registry,
)

DOCUMENT_CHUNKS_GENERATED = Histogram(
    "rudix_document_chunks_generated",
    "Number of chunks produced per document",
    ["strategy", "file_type"],
    buckets=(1.0, 5.0, 10.0, 25.0, 50.0, 100.0, 250.0, 500.0, 1000.0),
    registry=registry,
)

DOCUMENTS_REAPED_TOTAL = Counter(
    "rudix_documents_reaped_total",
    "Stale processing documents handled by the reaper",
    ["outcome"],
    registry=registry,
)

OCR_PAGES_PROCESSED_TOTAL = Counter(
    "rudix_ocr_pages_processed_total",
    "OCR pages processed by language and status",
    ["language", "status"],
    registry=registry,
)

# Celery Workers, Agents, Connectors, Bots & Readiness
CELERY_TASKS_TOTAL = Counter(
    "rudix_celery_tasks_total",
    "Celery task executions by task name, queue, and status",
    ["task_name", "queue", "status"],
    registry=registry,
)

CELERY_TASK_DURATION_SECONDS = Histogram(
    "rudix_celery_task_duration_seconds",
    "Celery task duration in seconds",
    ["task_name", "queue"],
    buckets=(0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0),
    registry=registry,
)

AGENT_RUNS_TOTAL = Counter(
    "rudix_agent_runs_total",
    "Agentic workflow runs by status",
    ["status"],
    registry=registry,
)

AGENT_TOOL_CALLS_TOTAL = Counter(
    "rudix_agent_tool_calls_total",
    "Agent and MCP tool calls by surface, effect policy, and status",
    ["tool_name", "surface", "effect", "status"],
    registry=registry,
)

CONNECTOR_SYNC_RUNS_TOTAL = Counter(
    "rudix_connector_sync_runs_total",
    "Connector synchronization runs by provider and status",
    ["provider_key", "status"],
    registry=registry,
)

BOT_ASKS_TOTAL = Counter(
    "rudix_bot_asks_total",
    "Chat bot ask invocations by provider and outcome",
    ["provider", "outcome"],
    registry=registry,
)

RETRIEVAL_BRANCH_FAILURES_TOTAL = Counter(
    "rudix_retrieval_branch_failures_total",
    "Retrieval branch attempts that failed or timed out and were degraded",
    ["branch", "error"],
    registry=registry,
)

EVAL_INDEX_CLEANUP_FAILURES_TOTAL = Counter(
    "rudix_eval_index_cleanup_failures_total",
    "Per-document evaluation index cleanup steps that failed (store: qdrant or postgres)",
    ["store"],
    registry=registry,
)

CHAT_QUOTA_DENIED_TOTAL = Counter(
    "rudix_chat_quota_denied_total",
    "Chat questions refused because the plan question quota is exhausted",
    ["transport"],
    registry=registry,
)

# R05-01: one observation per chat pipeline stage run (CHAT_PIPELINE_V2); labels are the
# fixed stage names, never request data.
CHAT_STAGE_SECONDS = Histogram(
    "rudix_chat_stage_seconds",
    "Duration of one chat pipeline stage in seconds",
    ["stage"],
    buckets=(0.005, 0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
    registry=registry,
)

# R05-02: how long the chat pipeline holds a database session per phase (read, short,
# write). Labels are the fixed phase names; no session is held while the model generates.
CHAT_DB_SESSION_SECONDS = Histogram(
    "rudix_chat_db_session_seconds",
    "Time one chat pipeline database session was held, by phase",
    ["phase"],
    buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
    registry=registry,
)

CHAT_WS_AUTH_TOTAL = Counter(
    "rudix_chat_ws_auth_total",
    "Chat WebSocket handshake authentication attempts by method and outcome",
    ["method", "outcome"],
    registry=registry,
)

# R05-03: pipeline start to the first answer text sent (first delta; in buffered mode the
# first verified delta; generation.final when no delta was sent). Observed once per answer.
CHAT_TTFT_SECONDS = Histogram(
    "rudix_chat_ttft_seconds",
    "Chat time to first answer token in seconds, by transport",
    ["transport"],
    buckets=(0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 7.5, 10.0, 20.0),
    registry=registry,
)

CHAT_STREAM_CANCELLED_TOTAL = Counter(
    "rudix_chat_stream_cancelled_total",
    "Chat answers cancelled before completion (chat.cancel or client disconnect)",
    ["transport"],
    registry=registry,
)

# R05-06: provider circuit breaker (0 closed, 1 half-open, 2 open) and its transitions.
LLM_BREAKER_STATE = Gauge(
    "rudix_llm_breaker_state",
    "LLM provider circuit breaker state (0 closed, 1 half-open, 2 open)",
    ["provider", "model"],
    registry=registry,
)

LLM_BREAKER_TRANSITIONS_TOTAL = Counter(
    "rudix_llm_breaker_transitions_total",
    "LLM provider circuit breaker transitions, by the state entered",
    ["provider", "model", "state"],
    registry=registry,
)

# R05-06: per-organisation concurrency (Redis semaphore). No organisation label (cardinality).
LLM_ORG_CONCURRENCY_REJECTED_TOTAL = Counter(
    "rudix_llm_org_concurrency_rejected_total",
    "LLM calls rejected because the organisation concurrency limit stayed reached",
    registry=registry,
)

LLM_ORG_SEMAPHORE_UNAVAILABLE_TOTAL = Counter(
    "rudix_llm_org_semaphore_unavailable_total",
    "LLM calls admitted without a lease because Redis was missing or failing",
    registry=registry,
)

LLM_CACHED_PROMPT_TOKENS_TOTAL = Counter(
    "rudix_llm_cached_prompt_tokens_total",
    "Prompt tokens the provider reported as served from its prompt cache",
    ["provider", "model"],
    registry=registry,
)

# R05-13: resumable WebSocket runs.
CHAT_WS_RESUME_TOTAL = Counter(
    "rudix_chat_ws_resume_total",
    "chat.resume commands by outcome (replayed, rebuilt, unavailable, redis_unavailable)",
    ["outcome"],
    registry=registry,
)

CHAT_WS_DROP_TOTAL = Counter(
    "rudix_chat_ws_drop_total",
    "WebSocket runs whose socket dropped mid-run, by outcome "
    "(completed, cancelled, cancelled_no_grace)",
    ["outcome"],
    registry=registry,
)

CHAT_RESUME_BUFFER_ERRORS_TOTAL = Counter(
    "rudix_chat_resume_buffer_errors_total",
    "Resume buffer writes that failed (Redis error); the run continues unbuffered",
    registry=registry,
)

DEPENDENCY_READINESS = Gauge(
    "rudix_dependency_readiness",
    "Health and readiness status of backing dependencies (1 = healthy, 0 = degraded)",
    ["dependency"],
    registry=registry,
)


# ---------------------------------------------------------------------------
# Recording Helpers (Safe No-Ops When METRICS_ENABLED=False)
# ---------------------------------------------------------------------------


def is_metrics_enabled() -> bool:
    return bool(settings.metrics_enabled)


def record_rate_limit(scope: str, decision: str, failure_mode: str = "none") -> None:
    if not is_metrics_enabled():
        return
    try:
        RATE_LIMIT_DECISIONS_TOTAL.labels(
            scope=scope, decision=decision, failure_mode=failure_mode
        ).inc()
    except Exception as exc:
        logger.debug("metrics.record_rate_limit_failed: %s", exc)


def record_auth_verification(provider: str, outcome: str) -> None:
    if not is_metrics_enabled():
        return
    try:
        AUTH_VERIFICATIONS_TOTAL.labels(provider=provider, outcome=outcome).inc()
    except Exception as exc:
        logger.debug("metrics.record_auth_verification_failed: %s", exc)


def record_authz_decision(
    resource_type: str, action: str, decision: str, deny_reason: str = "none"
) -> None:
    if not is_metrics_enabled():
        return
    try:
        AUTHZ_DECISIONS_TOTAL.labels(
            resource_type=resource_type,
            action=action,
            decision=decision,
            deny_reason=deny_reason,
        ).inc()
    except Exception as exc:
        logger.debug("metrics.record_authz_decision_failed: %s", exc)


def record_rag_query(
    *,
    scope_mode: str,
    status: str,
    duration_seconds: float,
    confidence_score: float | None = None,
    confidence_category: str = "none",
    not_found: bool = False,
    fallback_used: bool = False,
    citation_validation_failed: bool = False,
    citation_failure_reason: str | None = None,
) -> None:
    if not is_metrics_enabled():
        return
    try:
        RAG_QUERY_DURATION_SECONDS.labels(scope_mode=scope_mode, status=status).observe(
            duration_seconds
        )
        RAG_ANSWERS_TOTAL.labels(
            scope_mode=scope_mode,
            confidence_category=confidence_category or "none",
            not_found=str(not_found).lower(),
            fallback_used=str(fallback_used).lower(),
        ).inc()
        if confidence_score is not None:
            RAG_CONFIDENCE_SCORE.labels(scope_mode=scope_mode).observe(confidence_score)
        if citation_validation_failed:
            RAG_CITATION_VALIDATION_FAILURES_TOTAL.labels(
                reason=citation_failure_reason or "unknown"
            ).inc()
    except Exception as exc:
        logger.debug("metrics.record_rag_query_failed: %s", exc)


def record_rag_stage(stage: str, provider: str, duration_seconds: float) -> None:
    if not is_metrics_enabled():
        return
    try:
        RAG_STAGE_DURATION_SECONDS.labels(stage=stage, provider=provider).observe(duration_seconds)
    except Exception as exc:
        logger.debug("metrics.record_rag_stage_failed: %s", exc)


def record_llm_request(
    *,
    provider: str,
    model: str,
    operation: str,
    status: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    estimated_cost_usd: float | None = None,
) -> None:
    if not is_metrics_enabled():
        return
    try:
        LLM_REQUESTS_TOTAL.labels(
            provider=provider, model=model, operation=operation, status=status
        ).inc()
        if input_tokens > 0:
            LLM_TOKENS_TOTAL.labels(provider=provider, model=model, direction="input").inc(
                input_tokens
            )
        if output_tokens > 0:
            LLM_TOKENS_TOTAL.labels(provider=provider, model=model, direction="output").inc(
                output_tokens
            )
        if estimated_cost_usd is not None and estimated_cost_usd > 0:
            LLM_ESTIMATED_COST_USD_TOTAL.labels(provider=provider, model=model).inc(
                estimated_cost_usd
            )
    except Exception as exc:
        logger.debug("metrics.record_llm_request_failed: %s", exc)


def record_llm_retry(provider: str, model: str, reason: str) -> None:
    if not is_metrics_enabled():
        return
    try:
        LLM_RETRIES_TOTAL.labels(provider=provider, model=model, reason=reason).inc()
    except Exception as exc:
        logger.debug("metrics.record_llm_retry_failed: %s", exc)


def record_chat_tokens(stage: str, kind: str, amount: int) -> None:
    if not is_metrics_enabled() or amount <= 0:
        return
    try:
        CHAT_TOKENS_TOTAL.labels(stage=stage, kind=kind).inc(amount)
    except Exception as exc:
        logger.debug("metrics.record_chat_tokens_failed: %s", exc)


def record_chat_context_injection_flagged(action: str, count: int) -> None:
    if not is_metrics_enabled() or count <= 0:
        return
    try:
        CHAT_CONTEXT_INJECTION_FLAGGED_TOTAL.labels(action=action).inc(count)
    except Exception as exc:
        logger.debug("metrics.record_chat_context_injection_flagged_failed: %s", exc)


def record_document_upload(file_type: str, status: str, malware_scan_result: str) -> None:
    if not is_metrics_enabled():
        return
    try:
        DOCUMENT_UPLOADS_TOTAL.labels(
            file_type=file_type,
            status=status,
            malware_scan_result=malware_scan_result,
        ).inc()
    except Exception as exc:
        logger.debug("metrics.record_document_upload_failed: %s", exc)


def record_document_indexing_job(
    *,
    task_type: str,
    file_type: str,
    status: str,
    duration_seconds: float | None = None,
    stage: str | None = None,
    chunk_count: int | None = None,
    strategy: str | None = None,
) -> None:
    if not is_metrics_enabled():
        return
    try:
        DOCUMENT_INDEXING_JOBS_TOTAL.labels(
            task_type=task_type, file_type=file_type, status=status
        ).inc()
        if duration_seconds is not None and stage is not None:
            DOCUMENT_INDEXING_DURATION_SECONDS.labels(stage=stage, file_type=file_type).observe(
                duration_seconds
            )
        if chunk_count is not None and strategy is not None:
            DOCUMENT_CHUNKS_GENERATED.labels(strategy=strategy, file_type=file_type).observe(
                float(chunk_count)
            )
    except Exception as exc:
        logger.debug("metrics.record_document_indexing_job_failed: %s", exc)


def record_document_reaped(outcome: str) -> None:
    if not is_metrics_enabled():
        return
    try:
        DOCUMENTS_REAPED_TOTAL.labels(outcome=outcome).inc()
    except Exception as exc:
        logger.debug("metrics.record_document_reaped_failed: %s", exc)


def record_celery_task(
    task_name: str, queue: str, status: str, duration_seconds: float | None = None
) -> None:
    if not is_metrics_enabled():
        return
    try:
        CELERY_TASKS_TOTAL.labels(task_name=task_name, queue=queue, status=status).inc()
        if duration_seconds is not None and duration_seconds >= 0:
            CELERY_TASK_DURATION_SECONDS.labels(task_name=task_name, queue=queue).observe(
                duration_seconds
            )
    except Exception as exc:
        logger.debug("metrics.record_celery_task_failed: %s", exc)


def record_agent_run(status: str) -> None:
    if not is_metrics_enabled():
        return
    try:
        AGENT_RUNS_TOTAL.labels(status=status).inc()
    except Exception as exc:
        logger.debug("metrics.record_agent_run_failed: %s", exc)


def record_agent_tool_call(tool_name: str, surface: str, effect: str, status: str) -> None:
    if not is_metrics_enabled():
        return
    try:
        AGENT_TOOL_CALLS_TOTAL.labels(
            tool_name=tool_name, surface=surface, effect=effect, status=status
        ).inc()
    except Exception as exc:
        logger.debug("metrics.record_agent_tool_call_failed: %s", exc)


def record_connector_sync(provider_key: str, status: str) -> None:
    if not is_metrics_enabled():
        return
    try:
        CONNECTOR_SYNC_RUNS_TOTAL.labels(provider_key=provider_key, status=status).inc()
    except Exception as exc:
        logger.debug("metrics.record_connector_sync_failed: %s", exc)


def record_bot_ask(provider: str, outcome: str) -> None:
    if not is_metrics_enabled():
        return
    try:
        BOT_ASKS_TOTAL.labels(provider=provider, outcome=outcome).inc()
    except Exception as exc:
        logger.debug("metrics.record_bot_ask_failed: %s", exc)


def record_retrieval_branch_failure(branch: str, error: str) -> None:
    if not is_metrics_enabled():
        return
    try:
        RETRIEVAL_BRANCH_FAILURES_TOTAL.labels(branch=branch, error=error).inc()
    except Exception as exc:
        logger.debug("metrics.record_retrieval_branch_failure_failed: %s", exc)


def record_eval_index_cleanup_failure(store: str) -> None:
    if not is_metrics_enabled():
        return
    try:
        EVAL_INDEX_CLEANUP_FAILURES_TOTAL.labels(store=store).inc()
    except Exception as exc:
        logger.debug("metrics.record_eval_index_cleanup_failure_failed: %s", exc)


def record_chat_quota_denied(transport: str) -> None:
    if not is_metrics_enabled():
        return
    try:
        CHAT_QUOTA_DENIED_TOTAL.labels(transport=transport).inc()
    except Exception as exc:
        logger.debug("metrics.record_chat_quota_denied_failed: %s", exc)


def record_chat_ws_auth(method: str, outcome: str) -> None:
    if not is_metrics_enabled():
        return
    try:
        CHAT_WS_AUTH_TOTAL.labels(method=method, outcome=outcome).inc()
    except Exception as exc:
        logger.debug("metrics.record_chat_ws_auth_failed: %s", exc)


def set_dependency_readiness(dependency: str, is_ready: bool) -> None:
    if not is_metrics_enabled():
        return
    try:
        DEPENDENCY_READINESS.labels(dependency=dependency).set(1.0 if is_ready else 0.0)
    except Exception as exc:
        logger.debug("metrics.set_dependency_readiness_failed: %s", exc)


# ---------------------------------------------------------------------------
# HTTP Middleware and Metric Scraping
# ---------------------------------------------------------------------------


def attach_metrics_middleware(app: FastAPI) -> None:
    """Attach low-overhead Prometheus metrics middleware to FastAPI."""
    from app.core.db_metrics import begin_request_query_count, end_request_query_count

    @app.middleware("http")
    async def prometheus_metrics_middleware(request: Request, call_next: Any) -> Any:
        if not is_metrics_enabled():
            return await call_next(request)

        method = request.method
        route = request.scope.get("route")
        route_template = getattr(route, "path", None)
        if not route_template:
            route_template = (
                request.url.path
                if request.url.path in {"/metrics", "/health", "/healthz", "/ready", "/readyz"}
                else "unmatched"
            )

        HTTP_REQUESTS_IN_PROGRESS.labels(method=method, route=route_template).inc()
        started_at = perf_counter()
        status_code = 500
        query_scope = begin_request_query_count()

        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            duration = perf_counter() - started_at
            # If route was populated after routing
            if route_template == "unmatched":
                route = request.scope.get("route")
                post_route = getattr(route, "path", None)
                if post_route:
                    route_template = post_route

            HTTP_REQUEST_DURATION_SECONDS.labels(method=method, route=route_template).observe(
                duration
            )
            HTTP_REQUESTS_TOTAL.labels(
                method=method, route=route_template, status_code=str(status_code)
            ).inc()
            HTTP_REQUESTS_IN_PROGRESS.labels(method=method, route=route_template).dec()
            end_request_query_count(query_scope, method, route_template)


def generate_prometheus_metrics() -> Response:
    """Generate metrics in Prometheus text format."""
    data = generate_latest(registry)
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)
