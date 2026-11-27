"""Stage 7: rerank, context packing, the not-found decision, parent context, and source
conflict detection (R05-01)."""

from time import perf_counter

from app.application.chat.pipeline.context import ChatContext
from app.application.chat.pipeline.controls import (
    _build_conflict_detection_chunks,
    _rerank_chunks,
)
from app.application.chat.pipeline.events import ChatEvent, plural
from app.application.chat.pipeline.stages._packing import (
    apply_context_packing,
    apply_parent_context_expansion,
)
from app.core.config import settings
from app.core.logging import log_query_event
from app.domains.chat.services.confidence_calibration import (
    _compute_freshness_multiplier,
    _to_confidence_signals,
)
from app.domains.rag_profiles.schemas.rag_profiles import RagProfileConfig


class RerankPackStage:
    name = "rerank_pack"
    runs_when_terminal = False
    optional = False

    async def run(self, ctx: ChatContext) -> None:
        ret = ctx.retrieval
        if ret.rerank_applied:
            await ctx.emit(ChatEvent(type="rerank.started"))
            await ctx.emit_step("reranking_evidence", "Ranking evidence by relevance", "running")
        else:
            await ctx.emit_step("reranking_evidence", "Ranking evidence by relevance", "skipped")
        rerank_started = perf_counter()
        ret.selected_chunks, ret.rerank_result = await _rerank_chunks(
            query=ctx.request.payload.question,
            chunks=ret.retrieved_chunks,
            enabled=ret.rerank_applied,
            final_top_k=ret.final_top_k,
            settings_override=ctx.config.rerank_settings,
        )
        ctx.latencies_ms["rerank"] = int((perf_counter() - rerank_started) * 1000)
        if ret.rerank_applied:
            await ctx.emit(
                ChatEvent(
                    type="rerank.completed",
                    payload={"selected_count": len(ret.selected_chunks)},
                )
            )
            await ctx.emit_step(
                "reranking_evidence",
                "Ranking evidence by relevance",
                "success",
                detail=f"Selected {plural(len(ret.selected_chunks), 'top source')}",
                duration_ms=ctx.latencies_ms["rerank"],
            )

        apply_context_packing(ctx)
        self._decide_not_found(ctx)
        apply_parent_context_expansion(ctx)
        if ret.selected_chunks and not ctx.generation.not_found:
            await self._detect_conflicts(ctx)

    @staticmethod
    def _decide_not_found(ctx: ChatContext) -> None:
        ret = ctx.retrieval
        ver = ctx.verification
        confidence = ctx.deps.confidence_service
        ver.confidence_signals = _to_confidence_signals(
            chunks=ret.selected_chunks, rerank_applied=ret.rerank_applied
        )
        pre_freshness_multiplier = _compute_freshness_multiplier(
            ret.freshness_stale_count, len(ret.selected_chunks)
        )
        result = confidence.score(
            chunks=ver.confidence_signals,
            citation_count=0,
            citation_validation_score=1.0,
            not_found_signal=False,
            freshness_multiplier=pre_freshness_multiplier,
        )
        ver.confidence_score = result.score
        ver.confidence_category = result.category
        ver.confidence_explanation = result.explanation
        min_chunks_for_answer = (
            ret.context_pack_result.not_found_min_chunks
            if ret.context_pack_result is not None
            else 1
        )
        ctx.generation.not_found = (
            len(ret.selected_chunks) < min_chunks_for_answer
            or ver.confidence_score < settings.confidence_not_found_threshold
        )
        if ctx.generation.not_found:
            result = confidence.score(
                chunks=ver.confidence_signals,
                citation_count=0,
                citation_validation_score=1.0,
                not_found_signal=True,
                freshness_multiplier=pre_freshness_multiplier,
            )
            ver.confidence_score = result.score
            ver.confidence_category = result.category
            ver.confidence_explanation = result.explanation

    @staticmethod
    async def _detect_conflicts(ctx: ChatContext) -> None:
        ret = ctx.retrieval
        enabled = settings.feature_enable_conflict_detection
        min_docs = settings.conflict_detection_min_source_docs
        rag_profile = ctx.config.rag_profile
        if rag_profile is not None:
            conflict_cfg = RagProfileConfig.model_validate(dict(rag_profile.config))
            enabled = conflict_cfg.conflict_detection_enabled
        ret.conflict_detection_enabled = enabled
        if not enabled:
            return
        started = perf_counter()
        result = await ctx.deps.conflict_detection_service.detect(
            chunks=_build_conflict_detection_chunks(
                chunks=ret.selected_chunks,
                parent_context_map=ret.parent_context_map if ret.parent_context_map else None,
                trust_map=ret.freshness_trust_map,
                org_stale_threshold_days=ret.freshness_stale_threshold_days,
            ),
            min_source_docs=min_docs,
        )
        ret.conflict_detection_result = result
        ret.conflict_detection_applied = result.applied
        ret.conflict_detection_latency_ms = int((perf_counter() - started) * 1000)
        ctx.latencies_ms["conflict_detection"] = ret.conflict_detection_latency_ms
        if ret.conflict_detection_applied:
            log_query_event(
                event="query.conflict_detection.completed",
                organization_id=ctx.request.principal.organization_id,
                user_id=ctx.request.principal.user_id,
                job_id=ctx.job_id,
                agreement_level=result.agreement_level,
                conflict_detected=result.conflict_detected,
                conflict_count=len(result.conflict_pairs),
                preferred_document_ids=result.preferred_document_ids,
                conflicting_document_ids=result.conflicting_document_ids,
                latency_ms=ret.conflict_detection_latency_ms,
            )
