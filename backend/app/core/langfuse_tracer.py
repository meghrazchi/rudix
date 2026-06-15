"""Langfuse LLM observability tracer for Rudix AI/RAG workflows (F271).

Langfuse is an *optional* dependency. When LANGFUSE_ENABLED is False or
the package is not installed, every public function in this module is a
safe no-op and Rudix continues normally.

Privacy rules enforced here:
  - User IDs are one-way hashed before being sent (sha-256, first 16 hex chars).
  - LANGFUSE_CAPTURE_INPUT_OUTPUT=false disables prompt/answer capture entirely.
  - LANGFUSE_REDACTION_MODE=inputs  redacts question/prompt text.
  - LANGFUSE_REDACTION_MODE=all     redacts question, answer, and chunk text.
  - Secrets, JWTs, API keys, connector tokens are never included in traces.
  - LANGFUSE_SAMPLE_RATE controls the fraction of requests that are traced.
"""

from __future__ import annotations

import hashlib
import logging
import os
import random
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal

_logger = logging.getLogger("observability.langfuse")

_langfuse_client: Any | None = None
_initialized_pids: set[tuple[str, int]] = set()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _hash_user_id(user_id: str) -> str:
    """One-way hash so user identity cannot be reconstructed from traces."""
    return "u_" + hashlib.sha256(user_id.encode()).hexdigest()[:16]


def _should_sample(sample_rate: float) -> bool:
    if sample_rate >= 1.0:
        return True
    if sample_rate <= 0.0:
        return False
    return random.random() < sample_rate


def _is_enabled() -> bool:
    return _langfuse_client is not None


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


def init_langfuse(*, runtime: Literal["api", "worker"]) -> bool:
    """Initialize the Langfuse client. Safe to call multiple times.

    Returns True when the client initialised successfully.
    """
    global _langfuse_client

    cache_key = (runtime, os.getpid())
    if cache_key in _initialized_pids:
        return _is_enabled()

    # Import settings lazily to avoid circular imports during testing.
    from app.core.config import settings

    _initialized_pids.add(cache_key)

    if not settings.langfuse_enabled:
        _logger.info("langfuse.disabled runtime=%s reason=not_enabled", runtime)
        return False

    if settings.langfuse_public_key is None or settings.langfuse_secret_key is None:
        _logger.warning(
            "langfuse.disabled runtime=%s reason=keys_missing langfuse_enabled=True",
            runtime,
        )
        return False

    if settings.langfuse_base_url is None:
        _logger.warning(
            "langfuse.disabled runtime=%s reason=base_url_missing langfuse_enabled=True",
            runtime,
        )
        return False

    try:
        from langfuse import Langfuse  # type: ignore[import-untyped]

        _langfuse_client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key.get_secret_value(),
            host=str(settings.langfuse_base_url),
        )
        _logger.info(
            "langfuse.enabled runtime=%s base_url=%s sample_rate=%.3f redaction=%s",
            runtime,
            str(settings.langfuse_base_url),
            settings.langfuse_sample_rate,
            settings.langfuse_redaction_mode.value,
        )
        return True
    except ImportError:
        _logger.warning("langfuse.disabled runtime=%s reason=package_not_installed", runtime)
        return False
    except Exception as exc:
        _logger.warning(
            "langfuse.disabled runtime=%s reason=init_failed error=%s",
            runtime,
            exc.__class__.__name__,
        )
        return False


def shutdown_langfuse() -> None:
    """Flush the background queue and close the Langfuse client."""
    if _langfuse_client is not None:
        try:
            _langfuse_client.flush()
        except Exception as exc:
            _logger.debug("langfuse.flush_failed error=%s", exc.__class__.__name__)


# ---------------------------------------------------------------------------
# Trace schema
# ---------------------------------------------------------------------------


@dataclass
class ChatTraceMetadata:
    """All observable fields from a completed chat/RAG request.

    Pass this to `trace_chat_query()` after the pipeline has finished and
    all data has been persisted. Nothing here should contain raw secrets.
    """

    organization_id: str
    user_id: str
    session_id: str
    message_id: str
    question: str
    answer: str
    scope_mode: str
    # Optional fields — default to safe empty values
    request_id: str | None = None
    source_scope_label: str | None = None
    feature_area: str = "chat"
    # Retrieval
    retrieved_count: int = 0
    selected_count: int = 0
    rerank_applied: bool = False
    rerank_enabled: bool = False
    rerank_provider: str | None = None
    rerank_model: str | None = None
    rerank_fallback_used: bool = False
    rerank_fallback_reason: str | None = None
    rerank_input_count: int = 0
    rerank_batch_count: int = 0
    rerank_prompt_tokens: int = 0
    rerank_completion_tokens: int = 0
    rerank_total_tokens: int = 0
    rerank_cost_usd: Decimal | None = None
    # Answer quality
    cited_count: int = 0
    not_found: bool = False
    citation_validation_failed: bool = False
    conflict_detection_enabled: bool = False
    conflict_detection_applied: bool = False
    conflict_detection_agreement_level: str | None = None
    conflict_detection_conflict_count: int = 0
    conflict_detection_latency_ms: int = 0
    confidence_score: float | None = None
    confidence_category: str | None = None
    # Models and provider routing
    llm_model: str | None = None
    llm_provider: str | None = None
    embedding_model: str | None = None
    fallback_used: bool = False
    fallback_reason: str | None = None
    # Tokens / cost
    embedding_prompt_tokens: int = 0
    llm_prompt_tokens: int = 0
    llm_completion_tokens: int = 0
    llm_total_tokens: int = 0
    estimated_cost_usd: Decimal | None = None
    # Latencies
    latencies_ms: dict[str, int] = field(default_factory=dict)
    answer_latency_ms: int = 0
    # Language
    detected_language: str | None = None
    answer_language_used: str | None = None
    # Prompt template
    prompt_template_key: str | None = None
    prompt_template_version: int | None = None


# ---------------------------------------------------------------------------
# Tracing
# ---------------------------------------------------------------------------


def trace_chat_query(metadata: ChatTraceMetadata) -> None:
    """Emit a structured Langfuse trace for a completed chat/RAG query.

    This is a fire-and-forget call — failures are logged at DEBUG level and
    never propagate to callers.
    """
    if not _is_enabled():
        return

    from app.core.config import settings

    if not _should_sample(settings.langfuse_sample_rate):
        return

    try:
        _emit_chat_trace(metadata)
    except Exception as exc:
        _logger.debug(
            "langfuse.trace_failed error=%s session_id=%s",
            exc.__class__.__name__,
            metadata.session_id,
        )


def _emit_chat_trace(metadata: ChatTraceMetadata) -> None:
    from app.core.config import LangfuseRedactionMode, settings

    redact_mode = settings.langfuse_redaction_mode
    capture_io = settings.langfuse_capture_input_output

    # Sanitize user identifier — never send the raw user ID.
    safe_user_id = _hash_user_id(metadata.user_id) if metadata.user_id else None

    # Apply redaction to user-supplied text.
    if not capture_io or redact_mode == LangfuseRedactionMode.all:
        trace_input: str = "<redacted:question>"
        trace_output: str = "<redacted:answer>"
    elif redact_mode == LangfuseRedactionMode.inputs:
        trace_input = "<redacted:question>"
        trace_output = metadata.answer
    else:
        trace_input = metadata.question
        trace_output = metadata.answer

    tags = [
        settings.environment.value,
        metadata.feature_area,
        f"scope:{metadata.scope_mode}",
    ]
    if metadata.llm_model:
        tags.append(f"model:{metadata.llm_model}")
    if metadata.llm_provider:
        tags.append(f"provider:{metadata.llm_provider}")
    if metadata.fallback_used:
        tags.append("fallback_used")
    if metadata.not_found:
        tags.append("not_found")
    if metadata.citation_validation_failed:
        tags.append("citation_validation_failed")

    trace_meta = {
        "request_id": metadata.request_id,
        "organization_id": metadata.organization_id,
        "feature_area": metadata.feature_area,
        "scope_mode": metadata.scope_mode,
        "source_scope": metadata.source_scope_label,
        "environment": settings.environment.value,
        "release_version": settings.api_version,
        "service": "rudix-api",
        "rerank_applied": metadata.rerank_applied,
        "rerank_enabled": metadata.rerank_enabled,
        "rerank_provider": metadata.rerank_provider,
        "rerank_model": metadata.rerank_model,
        "rerank_fallback_used": metadata.rerank_fallback_used,
        "rerank_fallback_reason": metadata.rerank_fallback_reason,
        "rerank_input_count": metadata.rerank_input_count,
        "rerank_batch_count": metadata.rerank_batch_count,
        "rerank_prompt_tokens": metadata.rerank_prompt_tokens,
        "rerank_completion_tokens": metadata.rerank_completion_tokens,
        "rerank_total_tokens": metadata.rerank_total_tokens,
        "rerank_cost_usd": str(metadata.rerank_cost_usd)
        if metadata.rerank_cost_usd is not None
        else None,
        "retrieved_count": metadata.retrieved_count,
        "selected_count": metadata.selected_count,
        "cited_count": metadata.cited_count,
        "not_found": metadata.not_found,
        "citation_validation_failed": metadata.citation_validation_failed,
        "conflict_detection_enabled": metadata.conflict_detection_enabled,
        "conflict_detection_applied": metadata.conflict_detection_applied,
        "conflict_detection_agreement_level": metadata.conflict_detection_agreement_level,
        "conflict_detection_conflict_count": metadata.conflict_detection_conflict_count,
        "conflict_detection_latency_ms": metadata.conflict_detection_latency_ms,
        "confidence_score": metadata.confidence_score,
        "confidence_category": metadata.confidence_category,
        "embedding_model": metadata.embedding_model,
        "llm_provider": metadata.llm_provider,
        "fallback_used": metadata.fallback_used,
        "fallback_reason": metadata.fallback_reason,
        "detected_language": metadata.detected_language,
        "answer_language_used": metadata.answer_language_used,
        "prompt_template_key": metadata.prompt_template_key,
        "prompt_template_version": metadata.prompt_template_version,
        "answer_latency_ms": metadata.answer_latency_ms,
    }

    trace = _langfuse_client.trace(
        name=f"rag.{metadata.feature_area}",
        input=trace_input,
        output=trace_output,
        user_id=safe_user_id,
        session_id=metadata.session_id,
        metadata=trace_meta,
        tags=tags,
    )

    # --- Embedding span ---
    if metadata.embedding_model and metadata.latencies_ms.get("embed") is not None:
        embed_span = trace.span(
            name="embedding.query",
            metadata={
                "model": metadata.embedding_model,
                "prompt_tokens": metadata.embedding_prompt_tokens,
                "latency_ms": metadata.latencies_ms.get("embed"),
            },
        )
        embed_span.end()

    # --- Vector retrieval span ---
    if metadata.latencies_ms.get("retrieve") is not None:
        retrieve_span = trace.span(
            name="retrieval.vector_search",
            metadata={
                "retrieved_count": metadata.retrieved_count,
                "latency_ms": metadata.latencies_ms.get("retrieve"),
            },
        )
        retrieve_span.end()

    # --- Rerank span ---
    if metadata.rerank_enabled and metadata.latencies_ms.get("rerank") is not None:
        rerank_span = trace.span(
            name="retrieval.rerank",
            metadata={
                "selected_count": metadata.selected_count,
                "latency_ms": metadata.latencies_ms.get("rerank"),
                "provider": metadata.rerank_provider,
                "model": metadata.rerank_model,
                "fallback_used": metadata.rerank_fallback_used,
                "fallback_reason": metadata.rerank_fallback_reason,
                "input_count": metadata.rerank_input_count,
                "batch_count": metadata.rerank_batch_count,
                "prompt_tokens": metadata.rerank_prompt_tokens,
                "completion_tokens": metadata.rerank_completion_tokens,
                "total_tokens": metadata.rerank_total_tokens,
                "estimated_cost_usd": str(metadata.rerank_cost_usd)
                if metadata.rerank_cost_usd is not None
                else None,
            },
        )
        rerank_span.end()

    # --- LLM generation span ---
    if metadata.llm_model:
        gen_usage: dict[str, object] = {}
        if metadata.llm_prompt_tokens or metadata.llm_completion_tokens:
            gen_usage = {
                "input": metadata.llm_prompt_tokens,
                "output": metadata.llm_completion_tokens,
                "total": metadata.llm_total_tokens,
                "unit": "TOKENS",
            }

        gen_meta: dict[str, object] = {
            "latency_ms": metadata.latencies_ms.get("llm"),
            "not_found": metadata.not_found,
            "provider": metadata.llm_provider,
            "fallback_used": metadata.fallback_used,
            "fallback_reason": metadata.fallback_reason,
        }
        if metadata.estimated_cost_usd is not None:
            gen_meta["estimated_cost_usd"] = str(metadata.estimated_cost_usd)

        gen = trace.generation(
            name="llm.generate_answer",
            model=metadata.llm_model,
            input=trace_input,
            usage=gen_usage if gen_usage else None,
            metadata=gen_meta,
        )
        gen.end(output=trace_output)

    # --- Citation span ---
    if not metadata.not_found and metadata.scope_mode != "none":
        cite_span = trace.span(
            name="citations.validate",
            metadata={
                "cited_count": metadata.cited_count,
                "citation_validation_failed": metadata.citation_validation_failed,
                "latency_ms": metadata.latencies_ms.get("citations"),
            },
        )
        cite_span.end()


# ---------------------------------------------------------------------------
# Health / diagnostics
# ---------------------------------------------------------------------------


async def check_langfuse_health() -> dict[str, object]:
    """Probe the Langfuse service health endpoint.

    Returns a dict with: enabled, base_url_configured, reachable, last_error.
    Never raises.
    """
    from app.core.config import settings

    result: dict[str, object] = {
        "enabled": settings.langfuse_enabled,
        "base_url_configured": settings.langfuse_base_url is not None,
        "keys_configured": (
            settings.langfuse_public_key is not None and settings.langfuse_secret_key is not None
        ),
        "client_initialized": _is_enabled(),
        "reachable": False,
        "last_error": None,
    }

    if not settings.langfuse_enabled or settings.langfuse_base_url is None:
        return result

    try:
        import httpx

        health_url = str(settings.langfuse_base_url).rstrip("/") + "/api/public/health"
        async with httpx.AsyncClient(timeout=5.0) as http:
            response = await http.get(health_url)
        result["reachable"] = response.status_code < 500
    except Exception as exc:
        result["last_error"] = exc.__class__.__name__

    return result
