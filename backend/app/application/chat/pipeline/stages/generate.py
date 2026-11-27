"""Stage 8: prompt building and answer generation (R05-01).

The prompt carries retrieved text as untrusted context inside the template's delimiters; the
model answers in JSON. A provider failure is reported as ``generation_failed`` only.
"""

from time import perf_counter

from fastapi import status

from app.application.chat.pipeline.context import NOT_FOUND_ANSWER, ChatContext
from app.application.chat.pipeline.controls import _build_prompt
from app.application.chat.pipeline.errors import ChatPipelineError
from app.application.chat.pipeline.stages._llm import apply_llm_result
from app.application.chat.pipeline.stages._tree_search import run_tree_search
from app.core.logging import log_query_event
from app.domains.chat.services.citation_enrichment import _build_conflict_context
from app.domains.chat.services.llm_service import (
    PermanentLLMServiceError,
    TransientLLMServiceError,
)


class GenerateStage:
    name = "generate"
    runs_when_terminal = False
    optional = False

    async def run(self, ctx: ChatContext) -> None:
        ret = ctx.retrieval
        gen = ctx.generation
        prompt_started = perf_counter()
        gen.prompt = (
            _build_prompt(
                question=ctx.request.payload.question,
                chunks=ret.selected_chunks,
                parent_context_map=ret.parent_context_map if ret.parent_context_map else None,
                conflict_context=_build_conflict_context(ret.conflict_detection_result),
                answer_language=ctx.config.answer_language_used,
                template=ctx.config.answer_prompt_template,
            )
            if not gen.not_found
            else ""
        )
        ctx.latencies_ms["prompt"] = int((perf_counter() - prompt_started) * 1000)

        gen.citation_result = None
        if gen.not_found:
            return
        gen.answer_block_ran = True
        await run_tree_search(ctx)
        if gen.citation_result is not None:
            return
        gen.llm_call_ran = True
        await self._generate(ctx)

    @staticmethod
    async def _generate(ctx: ChatContext) -> None:
        req = ctx.request
        gen = ctx.generation
        await ctx.emit_step("drafting_answer", "Drafting answer", "running")
        try:
            llm_result = await ctx.deps.llm_service.generate_answer(
                prompt=gen.prompt,
                resolved_profile=ctx.config.chat_profile,
            )
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

        gen.llm_result = llm_result
        apply_llm_result(ctx, llm_result, stage="generate")
        gen.answer = llm_result.answer
        if llm_result.not_found:
            gen.answer = NOT_FOUND_ANSWER
            gen.not_found = True
        elif not gen.answer.strip() or gen.answer.strip() == NOT_FOUND_ANSWER:
            gen.answer = NOT_FOUND_ANSWER
            gen.not_found = True
        await ctx.emit_step(
            "drafting_answer",
            "Drafting answer",
            "warning" if gen.not_found else "success",
            detail="No relevant answer found" if gen.not_found else None,
        )
