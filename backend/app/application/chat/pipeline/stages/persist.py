"""Stage 10: messages, trust metadata, citations, usage, audit, and quota in one transaction
(R05-01). Any failure rolls the whole write back and is reported as
``chat_persistence_failed``. Logs and audit metadata never carry question or answer text.
"""

from time import perf_counter
from typing import Any
from uuid import UUID

from fastapi import status

from app.application.chat.message_citations import persist_answer_citations
from app.application.chat.pipeline.context import ChatContext
from app.application.chat.pipeline.errors import ChatPipelineError
from app.application.chat.pipeline.stages._usage import (
    audit_metadata,
    build_trace_metadata,
    usage_metadata,
)
from app.application.chat.quota import record_chat_usage
from app.core.langfuse_tracer import trace_chat_query
from app.core.logging import log_query_event
from app.domains.chat.services.trust_metadata_builder import _build_trust_metadata
from app.domains.chat.services.trust_records import _build_retrieval_diagnostics_payload
from app.models.enums import ChatRole


class PersistStage:
    name = "persist"
    runs_when_terminal = True
    optional = False

    async def run(self, ctx: ChatContext) -> None:
        ret = ctx.retrieval
        out = ctx.persist
        cfg = ctx.config
        assert ctx.scope.source_scope_result is not None
        out.answer_latency_ms = int((perf_counter() - ctx.total_started) * 1000)
        out.rerank_diagnostics = (
            ret.rerank_result.diagnostics if ret.rerank_result is not None else None
        )
        out.retrieval_diagnostics_payload = _build_retrieval_diagnostics_payload(
            request_id=ctx.request.request_id,
            rag_profile=cfg.rag_profile,
            rag_profile_source=cfg.rag_profile_source,
            payload=ctx.request.payload,
            source_scope_result=ctx.scope.source_scope_result,
            retrieved_chunks=ret.retrieved_chunks,
            selected_chunks=ret.selected_chunks,
            rerank_applied=ret.rerank_applied,
            rerank_diagnostics=out.rerank_diagnostics,
            parallel_result=ret.parallel_result,
            hybrid_retrieval_enabled=ret.hybrid_retrieval_enabled,
            hybrid_vector_hit_count=ret.hybrid_vector_hit_count,
            hybrid_keyword_hit_count=ret.hybrid_keyword_hit_count,
            query_rewrite_result=cfg.query_rewrite_result,
            graph_context_result=ret.graph_context_result,
            document_ids=ctx.scope.document_ids,
            final_top_k=ret.final_top_k,
        )

        persist_started = perf_counter()
        async with ctx.sessions.write() as db_session:
            try:
                await self._write(ctx, db_session)
                await db_session.commit()
            except Exception as exc:
                await db_session.rollback()
                log_query_event(
                    event="query.failed.persist",
                    organization_id=ctx.request.principal.organization_id,
                    user_id=ctx.request.principal.user_id,
                    job_id=ctx.job_id,
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    error=exc.__class__.__name__,
                )
                raise ChatPipelineError(
                    code="chat_persistence_failed",
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    message="Failed to persist chat response",
                ) from exc
        ctx.latencies_ms["persist"] = int((perf_counter() - persist_started) * 1000)
        ctx.latencies_ms["total"] = int((perf_counter() - ctx.total_started) * 1000)

        trace_chat_query(build_trace_metadata(ctx))
        self._log_completed(ctx)
        await ctx.emit_step("preparing_final_answer", "Preparing final answer", "success")

    @staticmethod
    async def _write(ctx: ChatContext, db_session: Any) -> None:
        req = ctx.request
        deps = ctx.deps
        cfg = ctx.config
        ret = ctx.retrieval
        gen = ctx.generation
        ver = ctx.verification
        out = ctx.persist
        chat_session = ctx.scope.chat_session
        assert chat_session is not None and cfg.answer_mode_result is not None
        assert cfg.ai_effective_policy is not None
        assert ver.confidence_explanation is not None
        await deps.chat_repository.create_chat_message(
            db_session,
            chat_session_id=chat_session.id,
            role=ChatRole.user.value,
            content=req.payload.question,
        )
        assistant_message = await deps.chat_repository.create_chat_message(
            db_session,
            chat_session_id=chat_session.id,
            role=ChatRole.assistant.value,
            content=gen.answer,
            confidence_score=ver.confidence_score,
            latency_ms=out.answer_latency_ms,
            model_name=gen.llm_model,
            token_input_count=ret.embedding_prompt_tokens + gen.llm_prompt_tokens,
            token_output_count=gen.llm_completion_tokens,
            cost_usd=gen.llm_cost_usd,
            prompt_template_version_id=cfg.answer_prompt_version.id
            if cfg.answer_prompt_version is not None
            else None,
        )
        out.assistant_message = assistant_message

        trust_metadata = _build_trust_metadata(
            organization_id=req.organization_id,
            message_id=str(assistant_message.id),
            question=req.payload.question,
            query_rewrite_preview_enabled=cfg.query_rewrite_preview_enabled,
            not_found=gen.not_found,
            citation_validation_failed=ver.citation_validation_failed,
            verification_failed=ver.verification_failed,
            confidence_score=ver.confidence_score,
            confidence_category=ver.confidence_category,
            confidence_explanation=ver.confidence_explanation,
            citations=gen.citations,
            retrieval_diagnostics_payload=out.retrieval_diagnostics_payload,
            retrieved_chunks=ret.retrieved_chunks,
            selected_chunks=ret.selected_chunks,
            rerank_applied=ret.rerank_applied,
            rerank_diagnostics=out.rerank_diagnostics,
            hybrid_vector_hit_count=ret.hybrid_vector_hit_count,
            hybrid_keyword_hit_count=ret.hybrid_keyword_hit_count,
            query_rewrite_result=cfg.query_rewrite_result,
            parent_context_expanded_count=ret.parent_context_expanded_count,
            graph_context_result=ret.graph_context_result,
            freshness_excluded_count=ret.freshness_excluded_count,
            freshness_boosted_count=ret.freshness_boosted_count,
            freshness_stale_count=ret.freshness_stale_count,
            freshness_unreviewed_count=ret.freshness_unreviewed_count,
            freshness_deprecated_count=ret.freshness_deprecated_count,
            freshness_draft_count=ret.freshness_draft_count,
            freshness_all_excluded_fallback=ret.freshness_all_excluded_fallback,
            grounded_verifier_result=ver.grounded_verifier_result,
            answer_mode_result=cfg.answer_mode_result,
            llm_model=gen.llm_model,
            llm_provider=gen.llm_provider,
            embedding_model=ret.embedding_model,
            llm_fallback_used=gen.llm_fallback_used,
            llm_fallback_from=gen.llm_fallback_from,
            llm_fallback_to=gen.llm_fallback_to,
            llm_fallback_reason=gen.llm_fallback_reason,
            answer_prompt_version=cfg.answer_prompt_version,
            conflict_detection_result=ret.conflict_detection_result,
            ai_policy_applied=cfg.ai_effective_policy.source != "none",
            ai_policy_result=ver.ai_policy_result,
            generated_at=assistant_message.created_at,
            planner_result=cfg.planner_result,
            critic_result=ver.critic_result,
            refiner_result=ver.refiner_result,
            route_result=cfg.route_result,
            orchestration_result=cfg.orchestration_result,
        )
        out.trust_metadata = trust_metadata
        assistant_message.trust_metadata_json = trust_metadata.model_dump(mode="json")
        db_session.add(assistant_message)
        await db_session.flush()

        out.response_citations = await persist_answer_citations(
            db_session,
            chat_message_id=assistant_message.id,
            citations=gen.citations,
            rerank_applied=ret.rerank_applied,
            repository=deps.chat_repository,
        )

        await deps.usage_repository.create_usage_event(
            db_session,
            organization_id=req.organization_id,
            user_id=req.user_id,
            event_type="chat.completion",
            model_name=gen.llm_model,
            input_tokens=ret.embedding_prompt_tokens + gen.llm_prompt_tokens,
            output_tokens=gen.llm_completion_tokens,
            cost_usd=gen.llm_cost_usd,
            provider_key=gen.llm_provider,
            task_type="chat",
            retry_count=gen.llm_retry_count,
            fallback_used=gen.llm_fallback_used,
            request_id=req.request_id,
            metadata=usage_metadata(ctx),
        )
        await deps.audit_log_service.record(
            db_session,
            organization_id=req.organization_id,
            user_id=req.user_id,
            action="chat.query.completed",
            resource_type="chat_session",
            resource_id=chat_session.id,
            request_id=req.request_id,
            metadata=audit_metadata(ctx),
        )

        # Persist the policy evaluation log for audit and observability (F268).
        effective_policy = cfg.ai_effective_policy
        if effective_policy.source != "none":
            await deps.ai_policy_repo.create_eval_log(
                db_session,
                organization_id=req.organization_id,
                user_id=req.user_id,
                org_policy_id=UUID(effective_policy.policy_id)
                if effective_policy.policy_id
                else None,
                collection_id=cfg.ai_policy_collection_id,
                chat_session_id=chat_session.id,
                chat_message_id=assistant_message.id,
                outcome=ver.ai_policy_result.outcome,
                policy_source=ver.ai_policy_result.policy_source,
                violated_rules=ver.ai_policy_result.violated_rules,
                warning_flags=ver.ai_policy_result.warning_flags,
                question_preview=req.payload.question[:256],
                confidence_score=ver.confidence_score,
                citation_count=len(gen.citations),
                stale_source_count=ret.freshness_stale_count,
                is_preview_run=False,
            )

        await record_chat_usage(db_session, organization_id=req.organization_id)

    @staticmethod
    def _log_completed(ctx: ChatContext) -> None:
        req = ctx.request
        ret = ctx.retrieval
        ver = ctx.verification
        cfg = ctx.config
        assert ctx.scope.source_scope_result is not None
        log_query_event(
            event="query.completed",
            organization_id=req.principal.organization_id,
            user_id=req.principal.user_id,
            job_id=ctx.job_id,
            status_code=status.HTTP_200_OK,
            not_found=ctx.generation.not_found,
            confidence_score=ver.confidence_score,
            confidence_category=ver.confidence_category,
            retrieval_count=len(ret.retrieved_chunks),
            selected_count=len(ret.selected_chunks),
            graph_context_used=ret.graph_context_result.graph_context_used,
            graph_context_reason=ret.graph_context_result.graph_context_reason,
            source_scope=ctx.scope.source_scope_result.label,
            detected_language=cfg.detected_language,
            answer_language_mode=req.payload.answer_language,
            answer_language_used=cfg.answer_language_used,
        )
