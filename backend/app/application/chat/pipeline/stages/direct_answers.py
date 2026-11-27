"""Answers that skip retrieval and generation over documents (R05-01).

Three branches, in ``query_chat`` order: a blocked question (injection guard or AI policy
topic), a scope-inventory question, and a product-guidance question. Each sets
``ctx.terminal`` so retrieval, packing, and generation are skipped; verification and
persistence still run.
"""

from time import perf_counter

from fastapi import status

from app.application.chat.pipeline.context import NOT_FOUND_ANSWER, ChatContext
from app.application.chat.pipeline.errors import ChatPipelineError
from app.application.chat.pipeline.events import ChatEvent, plural
from app.application.chat.pipeline.stages._llm import (
    apply_llm_result,
    emit_delta,
    start_drafting,
    stream_llm_answer,
)
from app.application.chat.pipeline.stages.generate import resolve_stream_mode
from app.application.chat.scope_inventory import (
    _build_scope_inventory_answer,
    _build_scope_inventory_result,
)
from app.core.logging import log_query_event
from app.domains.chat.services.confidence_calibration import _to_confidence_signals
from app.domains.chat.services.confidence_service import ConfidenceResult
from app.domains.chat.services.llm_service import (
    PermanentLLMServiceError,
    TransientLLMServiceError,
)


def _apply_confidence(ctx: ChatContext, result: ConfidenceResult) -> None:
    ctx.verification.confidence_score = result.score
    ctx.verification.confidence_category = result.category
    ctx.verification.confidence_explanation = result.explanation


class DirectAnswersStage:
    name = "direct_answers"
    runs_when_terminal = True
    optional = False

    async def run(self, ctx: ChatContext) -> None:
        cfg = ctx.config
        assert cfg.answer_mode_result is not None
        if cfg.blocked:
            await ctx.emit_step(
                "checking_sources",
                "Checking accessible sources",
                "failed",
                detail="Request could not be processed",
            )
            self._blocked(ctx)
        elif cfg.scope_inventory_requested:
            await self._scope_inventory(ctx)
        elif cfg.answer_mode_result.mode == "guidance":
            await self._guidance(ctx)
        else:
            return
        ctx.terminal = True

    @staticmethod
    def _blocked(ctx: ChatContext) -> None:
        # Question blocked by injection heuristics or AI response policy topic check.
        cfg = ctx.config
        assert cfg.ai_pre_result is not None
        ctx.retrieval.embedding_model = None
        if cfg.ai_pre_result.blocked and not cfg.injection_blocked:
            ctx.verification.ai_policy_result = cfg.ai_pre_result
            ctx.generation.answer = cfg.ai_pre_result.refusal_message or NOT_FOUND_ANSWER
        signals = _to_confidence_signals(chunks=[], rerank_applied=False)
        ctx.verification.confidence_signals = signals
        _apply_confidence(
            ctx,
            ctx.deps.confidence_service.score(
                chunks=signals,
                citation_count=0,
                citation_validation_score=1.0,
                not_found_signal=True,
            ),
        )

    @staticmethod
    async def _scope_inventory(ctx: ChatContext) -> None:
        req = ctx.request
        ctx.retrieval.embedding_model = None
        retrieve_started = perf_counter()
        async with ctx.sessions.short() as db_session:
            inventory_result = await _build_scope_inventory_result(
                db_session,
                principal=req.principal,
                organization_id=req.organization_id,
                user_id=req.user_id,
                user_roles=req.user_roles,
                document_ids=ctx.scope.document_ids,
            )
        ctx.latencies_ms["retrieve"] = int((perf_counter() - retrieve_started) * 1000)
        assert ctx.scope.source_scope_result is not None
        ctx.retrieval.retrieved_chunks = inventory_result.retrieved_chunks
        ctx.retrieval.selected_chunks = inventory_result.retrieved_chunks
        gen = ctx.generation
        gen.citations = inventory_result.citations
        gen.answer = _build_scope_inventory_answer(
            inventory=inventory_result,
            source_scope_result=ctx.scope.source_scope_result,
        )
        gen.not_found = inventory_result.total_count == 0
        signals = _to_confidence_signals(
            chunks=ctx.retrieval.selected_chunks,
            rerank_applied=False,
        )
        ctx.verification.confidence_signals = signals
        _apply_confidence(
            ctx,
            ctx.deps.confidence_service.score(
                chunks=signals,
                citation_count=len(gen.citations),
                citation_validation_score=1.0,
                not_found_signal=gen.not_found,
            ),
        )
        detail = (
            "No indexed files found"
            if gen.not_found
            else f"Found {plural(inventory_result.total_count, 'indexed file')}"
        )
        state = "warning" if gen.not_found else "success"
        await ctx.emit_step("checking_sources", "Checking accessible sources", state, detail)
        await ctx.emit(ChatEvent(type="retrieval.started"))
        await ctx.emit(
            ChatEvent(
                type="retrieval.completed",
                payload={"chunk_count": len(ctx.retrieval.retrieved_chunks)},
            )
        )
        await ctx.emit_step("searching_documents", "Searching knowledge base", state, detail)
        await ctx.emit_step("reranking_evidence", "Ranking evidence by relevance", "skipped")
        # The inventory text is built here, not by a model: one delta, as before streaming.
        await start_drafting(ctx, "live")
        await emit_delta(ctx, gen.answer)
        ctx.stream.answer_after_generation = gen.answer
        await ctx.emit_step("drafting_answer", "Drafting answer", state)
        await ctx.emit(
            ChatEvent(
                type="citation.validation.completed",
                payload={"citation_count": len(gen.citations)},
            )
        )
        if gen.citations:
            await ctx.emit_step(
                "verifying_citations",
                "Verifying source citations",
                "success",
                detail=f"Linked {plural(len(gen.citations), 'citation')}",
            )

    @staticmethod
    async def _guidance(ctx: ChatContext) -> None:
        # Guidance mode: skip retrieval and answer with safe Rudix product help only.
        req = ctx.request
        gen = ctx.generation
        ctx.retrieval.embedding_model = None
        await ctx.emit_step("checking_sources", "Checking accessible sources", "skipped")
        await ctx.emit_step("searching_documents", "Searching knowledge base", "skipped")
        # R05-03: guidance streams too (the grounded verifier never checks it).
        await start_drafting(ctx, resolve_stream_mode(ctx, verification=False))
        gen.prompt = ctx.deps.prompt_service.build_guidance_prompt(
            question=req.payload.question,
            answer_language=ctx.config.answer_language_used,
        )
        try:
            llm_result = await stream_llm_answer(ctx, gen.prompt)
        except (TransientLLMServiceError, PermanentLLMServiceError) as exc:
            log_query_event(
                event="query.failed.generate",
                organization_id=req.principal.organization_id,
                user_id=req.principal.user_id,
                job_id=ctx.job_id,
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                error=exc.__class__.__name__,
            )
            await ctx.emit_step("drafting_answer", "Drafting answer", "failed")
            raise ChatPipelineError(
                code="generation_failed",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                message="Answer generation is unavailable",
            ) from exc
        apply_llm_result(ctx, llm_result, stage="generate")
        gen.answer = llm_result.answer if llm_result.answer.strip() else NOT_FOUND_ANSWER
        gen.not_found = llm_result.not_found or not gen.answer.strip()
        gen.citations = []
        ctx.stream.answer_after_generation = gen.answer
        signals = _to_confidence_signals(chunks=[], rerank_applied=False)
        ctx.verification.confidence_signals = signals
        _apply_confidence(
            ctx,
            ctx.deps.confidence_service.score(
                chunks=signals,
                citation_count=0,
                citation_validation_score=1.0,
                not_found_signal=gen.not_found,
            ),
        )
        await ctx.emit_step(
            "drafting_answer",
            "Drafting answer",
            "warning" if gen.not_found else "success",
            detail="No relevant answer found" if gen.not_found else None,
        )
