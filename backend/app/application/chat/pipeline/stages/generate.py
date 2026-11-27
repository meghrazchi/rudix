"""Stage 8: prompt building and answer generation (R05-01, R05-03).

The prompt carries retrieved text as untrusted context inside the template's delimiters; the
model answers in JSON. A provider failure is reported as ``generation_failed`` only.

R05-03: the answer is generated through ``LLMService.stream_answer``. The stream mode is
chosen once per run (``resolve_stream_mode``): ``buffered`` when strict grounded
verification applies, when the effective AI response policy has a post-generation rule that
can block the answer, when tree search runs, or when ``CHAT_STREAM_MODE=buffered``;
otherwise ``live`` and the decoded answer text goes out as ``generation.delta`` while the
model writes it. Deltas carry text only; the verify stage sends ``generation.final``.
"""

from time import perf_counter

from app.application.chat.pipeline.context import NOT_FOUND_ANSWER, ChatContext
from app.application.chat.pipeline.controls import (
    _build_prompt,
    _resolve_grounded_verification_controls,
)
from app.application.chat.pipeline.stages._llm import (
    apply_llm_result,
    generation_error,
    start_drafting,
    stream_llm_answer,
)
from app.application.chat.pipeline.stages._tree_search import run_tree_search
from app.application.chat.pipeline.stream_state import StreamMode
from app.core.config import settings
from app.core.logging import log_query_event
from app.domains.ai_response_policy.services.policy_engine import EffectivePolicy
from app.domains.chat.services.citation_enrichment import _build_conflict_context
from app.domains.chat.services.llm_service import (
    PermanentLLMServiceError,
    TransientLLMServiceError,
)
from app.domains.rag_profiles.schemas.rag_profiles import RagProfileConfig


def policy_can_block_after_generation(policy: EffectivePolicy | None) -> bool:
    """True when ``evaluate_post_generation`` may refuse the answer under ``policy``:
    required citations, a minimum source count, a confidence floor, refusing not-found
    answers, or refusing stale sources. A disclaimer only decorates the answer, so it
    streams and is applied with ``generation.replace``."""
    if policy is None or policy.source == "none":
        return False
    return (
        policy.citation_mode == "required"
        or policy.min_sources_required is not None
        or policy.min_confidence_threshold is not None
        or policy.no_answer_behavior == "refuse"
        or policy.stale_source_behavior == "refuse"
    )


def strict_verification_applies(ctx: ChatContext) -> bool:
    cfg = ctx.config
    enabled, mode, _ = _resolve_grounded_verification_controls(
        effective_policy=cfg.ai_effective_policy,
        rag_profile=RagProfileConfig.model_validate(dict(cfg.rag_profile.config))
        if cfg.rag_profile is not None
        else None,
    )
    return enabled and mode == "strict"


def resolve_stream_mode(ctx: ChatContext, *, verification: bool = True) -> StreamMode:
    """``buffered`` when streamed text could be withheld or rewritten wholesale after
    generation; ``verification=False`` for answers the grounded verifier never checks."""
    if settings.chat_stream_mode == "buffered":
        return "buffered"
    if policy_can_block_after_generation(ctx.config.ai_effective_policy):
        return "buffered"
    if verification and strict_verification_applies(ctx):
        return "buffered"
    return "live"


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
            # Tree search selected (or rejected) a candidate: that is the generated answer.
            # Tree search always buffers; the verify stage sends the verified text.
            assert gen.llm_result is not None
            ctx.stream.answer_after_generation = gen.answer
            await self._drafting_done(ctx)
            return
        gen.llm_call_ran = True
        await self._generate(ctx)

    @staticmethod
    async def _generate(ctx: ChatContext) -> None:
        req = ctx.request
        gen = ctx.generation
        await start_drafting(ctx, resolve_stream_mode(ctx))
        try:
            llm_result = await stream_llm_answer(ctx, gen.prompt)
        except (TransientLLMServiceError, PermanentLLMServiceError) as exc:
            failure = generation_error(exc)
            log_query_event(
                event="query.failed.generate",
                organization_id=req.principal.organization_id,
                user_id=req.principal.user_id,
                job_id=ctx.job_id,
                status_code=failure.status_code,
                error=exc.__class__.__name__,
            )
            await ctx.emit_step("drafting_answer", "Drafting answer", "failed")
            raise failure from exc

        gen.llm_result = llm_result
        apply_llm_result(ctx, llm_result, stage="generate")
        gen.answer = llm_result.answer
        if llm_result.not_found:
            gen.answer = NOT_FOUND_ANSWER
            gen.not_found = True
        elif not gen.answer.strip() or gen.answer.strip() == NOT_FOUND_ANSWER:
            gen.answer = NOT_FOUND_ANSWER
            gen.not_found = True
        ctx.stream.answer_after_generation = gen.answer
        await GenerateStage._drafting_done(ctx)

    @staticmethod
    async def _drafting_done(ctx: ChatContext) -> None:
        not_found = ctx.generation.not_found
        await ctx.emit_step(
            "drafting_answer",
            "Drafting answer",
            "warning" if not_found else "success",
            detail="No relevant answer found" if not_found else None,
        )
