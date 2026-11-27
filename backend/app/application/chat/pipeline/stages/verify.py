"""Stage 9: citations, grounded verifier, critic and refiner, AI policy post-check, and the
final confidence (R05-01). Verifier and refiner see validated citation snippets only.
"""

from time import perf_counter
from typing import Literal, cast

from fastapi import status

from app.application.chat.pipeline.context import NOT_FOUND_ANSWER, ChatContext
from app.application.chat.pipeline.controls import _resolve_grounded_verification_controls
from app.application.chat.pipeline.events import ChatEvent, plural
from app.application.chat.pipeline.stages._confidence import (
    build_answer_citations,
    enrich_citations_and_score,
    score_not_found,
)
from app.core.logging import log_query_event
from app.domains.chat.services.confidence_calibration import _build_evidence_quality_inputs
from app.domains.chat.services.grounded_answer_verifier import VerifierChunk
from app.domains.chat.services.trust_records import _build_verifier_citations
from app.domains.rag_profiles.schemas.rag_profiles import RagProfileConfig


class VerifyStage:
    name = "verify"
    runs_when_terminal = True
    optional = False

    async def run(self, ctx: ChatContext) -> None:
        gen = ctx.generation
        if not ctx.terminal:
            if gen.answer_block_ran:
                # Citation events and steps only describe an answer the model gave; tree
                # search validated its candidate's citations already.
                answered = not gen.not_found
                if answered:
                    await ctx.emit(ChatEvent(type="citation.validation.started"))
                    await ctx.emit_step(
                        "verifying_citations", "Verifying source citations", "running"
                    )
                if gen.llm_call_ran:
                    build_answer_citations(ctx)
                    await enrich_citations_and_score(ctx)
                if answered:
                    await ctx.emit(
                        ChatEvent(
                            type="citation.validation.completed",
                            payload={"citation_count": len(gen.citations)},
                        )
                    )
                    await ctx.emit_step(
                        "verifying_citations",
                        "Verifying source citations",
                        "warning" if ctx.verification.citation_validation_failed else "success",
                        detail=f"Linked {plural(len(gen.citations), 'citation')}",
                    )
                if gen.llm_call_ran:
                    await self._grounded_verification(ctx)
            if gen.answer_block_ran and gen.not_found:
                score_not_found(ctx)
            await self._critic_and_refiner(ctx)

        ctx.latencies_ms["llm"] = gen.llm_latency_ms
        self._policy_post_check(ctx)
        # The answer, citations, and confidence are final from here on.
        # anchor: A1 final event

    @staticmethod
    async def _grounded_verification(ctx: ChatContext) -> None:
        """Grounded-answer verification (F296/F309); strict mode refuses weak evidence."""
        req = ctx.request
        cfg = ctx.config
        gen = ctx.generation
        ver = ctx.verification
        citation_result = gen.citation_result
        assert citation_result is not None
        gv_enabled, gv_mode, gv_threshold = _resolve_grounded_verification_controls(
            effective_policy=cfg.ai_effective_policy,
            rag_profile=RagProfileConfig.model_validate(dict(cfg.rag_profile.config))
            if cfg.rag_profile is not None
            else None,
        )
        ver.grounded_verification_enabled = gv_enabled
        ver.grounded_verification_mode = gv_mode
        ver.grounded_verification_threshold = gv_threshold
        if not gv_enabled:
            return
        started = perf_counter()
        result = await ctx.deps.grounded_verifier.verify(
            answer=gen.answer,
            chunks=[
                VerifierChunk(
                    chunk_id=str(chunk.chunk_id),
                    text=chunk.text,
                    similarity_score=chunk.similarity_score,
                )
                for chunk in ctx.retrieval.selected_chunks
            ],
            citations=_build_verifier_citations(gen.citations),
            mode=cast(Literal["strict", "standard"], gv_mode),
            threshold=gv_threshold,
        )
        ver.grounded_verifier_result = result
        ctx.latencies_ms["grounded_verification"] = int((perf_counter() - started) * 1000)
        if not result.applied:
            return
        gen.answer = result.final_answer
        if not gen.answer.strip():
            gen.not_found = True
            ver.verification_failed = True
        elif gv_mode == "strict" and result.verification_score < gv_threshold:
            gen.not_found = True
            ver.verification_failed = True
        elif gv_mode == "strict" and result.conflicting_claim_count > 0:
            # Conflicting sources in strict mode: refuse rather than show contradicted content.
            gen.not_found = True
            ver.verification_failed = True
        elif result.unsupported_claim_count > 0 or result.conflicting_claim_count > 0:
            ver.verification_failed = True
        if gen.not_found:
            gen.answer = NOT_FOUND_ANSWER
        principal = req.principal
        log_query_event(
            event="query.grounded_verification.completed",
            organization_id=principal.organization_id,
            user_id=principal.user_id,
            job_id=ctx.job_id,
            verdict=result.verdict,
            verification_score=result.verification_score,
            claim_count=result.claim_count,
            supported_count=result.supported_claim_count,
            partial_count=result.partially_supported_claim_count,
            unsupported_count=result.unsupported_claim_count,
            unverifiable_count=result.unverifiable_claim_count,
            removed_count=len(result.removed_claims),
            mode=gv_mode,
            threshold=gv_threshold,
            latency_ms=result.latency_ms,
        )
        if ver.verification_failed:
            log_query_event(
                event="query.grounded_verification.failed",
                organization_id=principal.organization_id,
                user_id=principal.user_id,
                job_id=ctx.job_id,
                verdict=result.verdict,
                removed_count=len(result.removed_claims),
                reason_codes=result.reason_codes,
                mode=gv_mode,
                threshold=gv_threshold,
            )
        elif gen.citations:
            confidence = ctx.deps.confidence_service.score(
                chunks=ver.confidence_signals,
                citation_count=len(gen.citations),
                citation_validation_score=citation_result.validation_score,
                citation_support_score_override=result.aggregate_support_score,
                not_found_signal=False,
                freshness_multiplier=ver.freshness_multiplier,
                ocr_quality_multiplier=ver.ocr_quality_multiplier,
                conflict_multiplier=ver.conflict_multiplier,
                graph_context_used=ctx.retrieval.graph_context_result.graph_context_used,
                verification_support_score=result.aggregate_support_score,
            )
            ver.confidence_score = confidence.score
            ver.confidence_category = confidence.category
            ver.confidence_explanation = confidence.explanation

    @staticmethod
    async def _critic_and_refiner(ctx: ChatContext) -> None:
        """Critic (no LLM) on high-risk questions; refiner on medium/high severity (F339)."""
        cfg = ctx.config
        gen = ctx.generation
        ver = ctx.verification
        ret = ctx.retrieval
        planner_result = cfg.planner_result
        if not (cfg.pcr_enabled and planner_result is not None and not cfg.injection_blocked):
            return
        run_critic = cfg.pcr_mode == "always" or (
            cfg.pcr_mode == "high_risk_only" and planner_result.high_risk
        )
        if not run_critic:
            return
        gv = ver.grounded_verifier_result
        evidence_quality = _build_evidence_quality_inputs(gen.citations)
        critic = ctx.deps.answer_critic.evaluate(
            not_found=gen.not_found,
            selected_chunk_count=len(ret.selected_chunks),
            citation_count=len(gen.citations),
            gv_applied=bool(gv and gv.applied),
            gv_unsupported_count=(gv.unsupported_claim_count if gv else 0),
            gv_conflicting_count=(gv.conflicting_claim_count if gv else 0),
            gv_not_enough_evidence_count=(gv.not_enough_evidence_claim_count if gv else 0),
            conflict_detected=ret.conflict_detection_result.conflict_detected,
            freshness_stale_count=ret.freshness_stale_count,
            freshness_excluded_count=ret.freshness_excluded_count,
            freshness_all_excluded_fallback=ret.freshness_all_excluded_fallback,
            ocr_low_confidence_chunk_count=ret.ocr_low_confidence_chunk_count,
            table_low_confidence_count=evidence_quality["table_low_confidence_count"],
            extraction_warning_count=evidence_quality["extraction_warning_count"],
        )
        ver.critic_result = critic
        principal = ctx.request.principal
        log_query_event(
            event="query.planner_critic.evaluated",
            organization_id=principal.organization_id,
            user_id=principal.user_id,
            job_id=ctx.job_id,
            strategy=planner_result.strategy,
            high_risk=planner_result.high_risk,
            critic_severity=critic.severity,
            warning_count=len(critic.warnings),
            requires_refiner=critic.requires_refiner,
        )
        await ctx.emit_step(
            "reviewing_answer",
            "Reviewing answer quality",
            "warning" if critic.severity in ("medium", "high") else "success",
            detail=(
                f"{len(critic.warnings)} quality warning(s) found"
                if critic.warnings
                else "No quality issues found"
            ),
        )
        if not (critic.requires_refiner and not gen.not_found and gen.answer.strip()):
            return
        await ctx.emit_step("refining_answer", "Refining with verified claims", "running")
        snippets = cast(
            list[str],
            [c.text_snippet for c in gen.citations if getattr(c, "text_snippet", None)][:10],
        )
        started = perf_counter()
        refiner = await ctx.deps.answer_refiner.refine(
            draft_answer=gen.answer,
            critic_instruction=critic.refiner_instruction,
            citation_snippets=snippets,
        )
        ver.refiner_result = refiner
        ctx.latencies_ms["refiner"] = int((perf_counter() - started) * 1000)
        if not refiner.applied:
            await ctx.emit_step("refining_answer", "Refining with verified claims", "skipped")
            return
        refined = refiner.refined_answer.strip()
        if not refined:
            gen.answer = NOT_FOUND_ANSWER
            gen.not_found = True
            ver.verification_failed = True
        else:
            gen.answer = refined
            if refiner.draft_changed:
                ver.verification_failed = True
        log_query_event(
            event="query.planner_critic.refined",
            organization_id=principal.organization_id,
            user_id=principal.user_id,
            job_id=ctx.job_id,
            draft_changed=refiner.draft_changed,
            unsupported_removed=refiner.unsupported_claims_removed,
            latency_ms=refiner.latency_ms,
        )
        await ctx.emit_step(
            "refining_answer",
            "Refining with verified claims",
            "warning" if gen.not_found else "success",
            detail="Unsupported claims removed" if refiner.draft_changed else "No changes needed",
        )

    @staticmethod
    def _policy_post_check(ctx: ChatContext) -> None:
        """AI response policy post-generation check (F268) and the disclaimer."""
        cfg = ctx.config
        gen = ctx.generation
        ver = ctx.verification
        assert cfg.ai_pre_result is not None and cfg.ai_effective_policy is not None
        engine = ctx.deps.ai_policy_engine
        if not cfg.ai_pre_result.blocked and not cfg.injection_blocked:
            post = engine.evaluate_post_generation(
                confidence_score=ver.confidence_score,
                citation_count=len(gen.citations),
                stale_source_count=ctx.retrieval.freshness_stale_count,
                not_found=gen.not_found,
                effective_policy=cfg.ai_effective_policy,
            )
            if post.blocked:
                ver.ai_policy_result = post
                gen.answer = post.refusal_message or NOT_FOUND_ANSWER
                gen.not_found = True
                gen.citations = []
                log_query_event(
                    event="query.rejected.policy_post_generation",
                    organization_id=ctx.request.principal.organization_id,
                    user_id=ctx.request.principal.user_id,
                    job_id=ctx.job_id,
                    status_code=status.HTTP_200_OK,
                    violated_rules=post.violated_rules,
                )
            elif post.warned:
                ver.ai_policy_result = post
        # Apply the disclaimer when a policy is active and the answer is not blocked.
        if not gen.not_found and cfg.ai_effective_policy.source != "none":
            gen.answer = engine.apply_disclaimer(gen.answer, ver.ai_policy_result)
