"""Usage-event, audit, and trace metadata of a chat run (R05-01).

Operational metadata only: ids, counts, flags, models, and timings. The question and the
answer go to the trace exporter only, which redacts and samples them (F271).
"""

from typing import Any

from fastapi import status

from app.application.chat.pipeline.context import ChatContext
from app.core.langfuse_tracer import ChatTraceMetadata
from app.domains.chat.services.chat_values import _decimal_to_float_or_none, _list_or_empty
from app.models.enums import PromptTemplateKey


def _prompt_template_meta(ctx: ChatContext) -> dict[str, Any] | None:
    version = ctx.config.answer_prompt_version
    if version is None:
        return None
    return {
        "key": PromptTemplateKey.answer_generation.value,
        "version_number": version.version_number,
        "version_id": str(version.id),
    }


def usage_metadata(ctx: ChatContext) -> dict[str, Any]:
    ret = ctx.retrieval
    gen = ctx.generation
    ver = ctx.verification
    out = ctx.persist
    graph = ret.graph_context_result
    conflict = ret.conflict_detection_result
    rerank = out.rerank_diagnostics
    rerank_settings = ctx.config.rerank_settings
    assert ctx.scope.chat_session is not None and out.assistant_message is not None
    assert rerank_settings is not None
    document_ids = ctx.scope.document_ids
    return {
        "chat_session_id": str(ctx.scope.chat_session.id),
        "assistant_message_id": str(out.assistant_message.id),
        "document_ids": [str(d) for d in document_ids] if document_ids is not None else [],
        "confidence_score": ver.confidence_score,
        "confidence_category": ver.confidence_category,
        "not_found": gen.not_found,
        "citation_count": len(gen.citations),
        "latencies_ms": ctx.latencies_ms,
        "answer_latency_ms": out.answer_latency_ms,
        "retrieval_count": len(ret.retrieved_chunks),
        "selected_count": len(ret.selected_chunks),
        "graph_context_enabled": graph.graph_context_enabled,
        "graph_context_used": graph.graph_context_used,
        "graph_context_unavailable": graph.graph_context_unavailable,
        "graph_context_reason": graph.graph_context_reason,
        "graph_seed_entity_count": graph.graph_seed_entity_count,
        "graph_related_entity_count": graph.graph_related_entity_count,
        "graph_chunk_count": graph.graph_chunk_count,
        "graph_max_hops_used": graph.graph_max_hops_used,
        "graph_relation_types_used": _list_or_empty(graph.graph_relation_types_used),
        "conflict_detection_enabled": ret.conflict_detection_enabled,
        "conflict_detection_applied": ret.conflict_detection_applied,
        "conflict_detection_latency_ms": ret.conflict_detection_latency_ms,
        "conflict_detection_agreement_level": conflict.agreement_level,
        "conflict_detection_conflict_count": len(conflict.conflict_pairs),
        "conflict_detection_conflicting_document_ids": _list_or_empty(
            conflict.conflicting_document_ids
        ),
        "conflict_detection_preferred_document_ids": _list_or_empty(
            conflict.preferred_document_ids
        ),
        "rerank_applied": ret.rerank_applied,
        "rerank_enabled": rerank_settings.enabled,
        "rerank_provider": rerank.provider_key if rerank else None,
        "rerank_model": rerank.model_name if rerank else None,
        "rerank_fallback_used": rerank.fallback_used if rerank else False,
        "rerank_fallback_reason": rerank.fallback_reason if rerank else None,
        "rerank_input_count": rerank.requested_count if rerank else 0,
        "rerank_batch_count": rerank.batch_count if rerank else 0,
        "rerank_prompt_tokens": rerank.prompt_tokens if rerank else 0,
        "rerank_completion_tokens": rerank.completion_tokens if rerank else 0,
        "rerank_total_tokens": rerank.total_tokens if rerank else 0,
        "rerank_cost_usd": _decimal_to_float_or_none(rerank.approximate_cost_usd)
        if rerank
        else None,
        "embedding_model": ret.embedding_model,
        "llm_model": gen.llm_model,
        "llm_provider": gen.llm_provider,
        "fallback_used": gen.llm_fallback_used,
        "fallback_from": gen.llm_fallback_from,
        "fallback_to": gen.llm_fallback_to,
        "fallback_reason": gen.llm_fallback_reason,
        "prompt_template": _prompt_template_meta(ctx),
    }


def audit_metadata(ctx: ChatContext) -> dict[str, Any]:
    ret = ctx.retrieval
    out = ctx.persist
    conflict = ret.conflict_detection_result
    rerank = out.rerank_diagnostics
    version = ctx.config.answer_prompt_version
    rerank_settings = ctx.config.rerank_settings
    assert out.assistant_message is not None and rerank_settings is not None
    return {
        "assistant_message_id": str(out.assistant_message.id),
        "not_found": ctx.generation.not_found,
        "confidence_category": ctx.verification.confidence_category,
        "citation_count": len(ctx.generation.citations),
        "retrieval_count": len(ret.retrieved_chunks),
        "selected_count": len(ret.selected_chunks),
        "graph_context_used": ret.graph_context_result.graph_context_used,
        "graph_context_reason": ret.graph_context_result.graph_context_reason,
        "conflict_detection_enabled": ret.conflict_detection_enabled,
        "conflict_detection_applied": ret.conflict_detection_applied,
        "conflict_detection_agreement_level": conflict.agreement_level,
        "conflict_detection_conflict_count": len(conflict.conflict_pairs),
        "conflict_detection_latency_ms": ret.conflict_detection_latency_ms,
        "conflict_detection_conflicting_document_ids": _list_or_empty(
            conflict.conflicting_document_ids
        ),
        "conflict_detection_preferred_document_ids": _list_or_empty(
            conflict.preferred_document_ids
        ),
        "rerank_applied": ret.rerank_applied,
        "rerank_enabled": rerank_settings.enabled,
        "rerank_provider": rerank.provider_key if rerank else None,
        "rerank_model": rerank.model_name if rerank else None,
        "prompt_template_key": PromptTemplateKey.answer_generation.value
        if version is not None
        else None,
        "prompt_template_version": version.version_number if version is not None else None,
        "status_code": status.HTTP_200_OK,
    }


def build_trace_metadata(ctx: ChatContext) -> ChatTraceMetadata:
    req = ctx.request
    ret = ctx.retrieval
    gen = ctx.generation
    ver = ctx.verification
    out = ctx.persist
    rerank = out.rerank_diagnostics
    version = ctx.config.answer_prompt_version
    rerank_settings = ctx.config.rerank_settings
    assert ctx.scope.chat_session is not None and out.assistant_message is not None
    assert ctx.scope.source_scope_result is not None and rerank_settings is not None
    return ChatTraceMetadata(
        request_id=req.request_id,
        organization_id=str(req.organization_id),
        user_id=str(req.user_id) if req.user_id is not None else "",
        session_id=str(ctx.scope.chat_session.id),
        message_id=str(out.assistant_message.id),
        question=req.payload.question,
        answer=gen.answer,
        scope_mode=req.payload.scope_mode,  # type: ignore[arg-type]  # None as today
        source_scope_label=ctx.scope.source_scope_result.label,
        feature_area="chat",
        retrieved_count=len(ret.retrieved_chunks),
        selected_count=len(ret.selected_chunks),
        rerank_applied=ret.rerank_applied,
        rerank_enabled=rerank_settings.enabled,
        rerank_provider=rerank.provider_key if rerank else None,
        rerank_model=rerank.model_name if rerank else None,
        rerank_fallback_used=rerank.fallback_used if rerank else False,
        rerank_fallback_reason=rerank.fallback_reason if rerank else None,
        rerank_input_count=rerank.requested_count if rerank else 0,
        rerank_batch_count=rerank.batch_count if rerank else 0,
        rerank_prompt_tokens=rerank.prompt_tokens if rerank else 0,
        rerank_completion_tokens=rerank.completion_tokens if rerank else 0,
        rerank_total_tokens=rerank.total_tokens if rerank else 0,
        rerank_cost_usd=rerank.approximate_cost_usd if rerank else None,
        cited_count=len(gen.citations),
        not_found=gen.not_found,
        citation_validation_failed=ver.citation_validation_failed,
        confidence_score=ver.confidence_score,
        confidence_category=ver.confidence_category,
        llm_model=gen.llm_model,
        llm_provider=gen.llm_provider,
        embedding_model=ret.embedding_model,
        fallback_used=gen.llm_fallback_used,
        fallback_reason=gen.llm_fallback_reason,
        embedding_prompt_tokens=ret.embedding_prompt_tokens,
        llm_prompt_tokens=gen.llm_prompt_tokens,
        llm_completion_tokens=gen.llm_completion_tokens,
        llm_total_tokens=ret.embedding_prompt_tokens
        + gen.llm_prompt_tokens
        + gen.llm_completion_tokens,
        estimated_cost_usd=gen.llm_cost_usd,
        latencies_ms=dict(ctx.latencies_ms),
        answer_latency_ms=out.answer_latency_ms,
        detected_language=ctx.config.detected_language,
        answer_language_used=ctx.config.answer_language_used,
        prompt_template_key=PromptTemplateKey.answer_generation.value
        if version is not None
        else None,
        prompt_template_version=version.version_number if version is not None else None,
    )
