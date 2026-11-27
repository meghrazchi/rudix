"""Stage 6: vector, keyword, and graph retrieval with access filtering (R05-01).

Every branch is scoped to the organisation and the authorised document ids; chunks the
principal may not cite are removed before anything reaches a prompt. Retrieved text stays
untrusted data. Any failure is reported as ``retrieval_failed`` without details.
"""

from time import perf_counter

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.chat.citation_access import filter_chunks_by_cite_access
from app.application.chat.pipeline.context import ChatContext
from app.application.chat.pipeline.controls import (
    _augment_retrieval_with_graph_context,
    _resolve_graph_rag_enabled,
)
from app.application.chat.pipeline.errors import ChatPipelineError
from app.application.chat.pipeline.events import plural
from app.application.chat.pipeline.request_helpers import _get_qdrant_client
from app.application.chat.pipeline.stages._evidence import (
    apply_freshness,
    apply_ocr_quality,
    apply_table_boost,
)
from app.core.config import settings
from app.core.logging import log_query_event
from app.domains.chat.services.parallel_retrieval_optimizer import ParallelRetrievalBudget
from app.domains.chat.services.retrieved_chunk import (
    RetrievedChunk,
    _hybrid_to_retrieved_chunk,
    _to_retrieved_chunk,
    _with_original_ranks,
)


class RetrieveStage:
    name = "retrieve"
    runs_when_terminal = False
    optional = False

    async def run(self, ctx: ChatContext) -> None:
        req = ctx.request
        ret = ctx.retrieval
        rerank_settings = ctx.config.rerank_settings
        assert rerank_settings is not None
        ret.final_top_k = req.payload.top_k or settings.retrieval_final_top_k
        ret.rerank_applied = bool(req.payload.rerank and rerank_settings.enabled)
        rerank_input_limit = (
            rerank_settings.max_input_candidates or settings.rerank_default_input_candidates
        )
        ret.retrieval_top_k = max(
            ret.final_top_k, rerank_input_limit if ret.rerank_applied else ret.final_top_k
        )

        # Retrieval queries: the decomposed set, the single rewritten query, or the question.
        rewrite = ctx.config.query_rewrite_result
        if rewrite is not None and rewrite.decomposition_applied:
            ret.retrieval_queries = [rewrite.primary_query, *list(rewrite.sub_queries)]
        elif rewrite is not None and rewrite.rewriting_applied:
            ret.retrieval_queries = [rewrite.primary_query]
        else:
            ret.retrieval_queries = [req.payload.question]

        document_ids = ctx.scope.document_ids
        source_count = len(document_ids) if document_ids is not None else 0
        await ctx.emit_step(
            "checking_sources",
            "Checking accessible sources",
            "success",
            detail=f"Searching {plural(source_count, 'source')}",
        )
        await ctx.emit_step("searching_documents", "Searching knowledge base", "running")
        retrieve_started = perf_counter()
        try:
            async with ctx.sessions.short() as db_session:
                await self._retrieve(ctx, db_session)
                await apply_freshness(ctx, db_session)
                apply_table_boost(ctx)
                await apply_ocr_quality(ctx, db_session)
        except Exception as exc:
            log_query_event(
                event="query.failed.retrieve",
                organization_id=req.principal.organization_id,
                user_id=req.principal.user_id,
                job_id=ctx.job_id,
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                error=exc.__class__.__name__,
                initial_top_k=ret.retrieval_top_k,
            )
            await ctx.emit_step("searching_documents", "Searching knowledge base", "failed")
            raise ChatPipelineError(
                code="retrieval_failed",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                message="Retrieval is unavailable",
            ) from exc
        ctx.latencies_ms["retrieve"] = int((perf_counter() - retrieve_started) * 1000)
        ctx.ledger.record(
            "retrieve",
            None,
            ret.embedding_model,
            ret.embedding_prompt_tokens,
            0,
        )
        count = len(ret.retrieved_chunks)
        await ctx.emit_step(
            "searching_documents",
            "Searching knowledge base",
            "warning" if count == 0 else "success",
            detail=f"Found {plural(count, 'relevant passage')}",
            duration_ms=ctx.latencies_ms["retrieve"],
        )

    @staticmethod
    async def _retrieve(ctx: ChatContext, db_session: AsyncSession) -> None:
        req = ctx.request
        deps = ctx.deps
        ret = ctx.retrieval
        document_ids = ctx.scope.document_ids
        ret.graph_enabled = await _resolve_graph_rag_enabled(
            db_session,
            organization_id=req.organization_id,
        )
        route_result = ctx.config.route_result
        route_wants_vector_only = route_result is not None and route_result.method == "vector"
        effective_hybrid = settings.feature_enable_hybrid_retrieval and not route_wants_vector_only
        budget = ParallelRetrievalBudget(
            max_parallel_calls=settings.retrieval_parallel_max_calls,
            timeout_ms=settings.retrieval_parallel_timeout_ms,
            max_retry_attempts=settings.retrieval_parallel_max_retry_attempts,
            max_total_tokens=settings.retrieval_parallel_max_total_tokens,
            max_total_cost_usd=(
                None
                if settings.retrieval_parallel_max_total_cost_usd is None
                else settings.retrieval_parallel_max_total_cost_usd  # type: ignore[arg-type]
            ),
        )
        parallel_result = await deps.parallel_retrieval_optimizer.execute(
            session=db_session,
            organization_id=req.organization_id,
            document_ids=document_ids,
            queries=ret.retrieval_queries,
            query_retrieval_service=deps.query_retrieval_service,
            keyword_retrieval_service=deps.keyword_retrieval_service,
            graph_retrieval_service=deps.graph_retrieval_service,
            graph_enabled=ret.graph_enabled,
            keyword_enabled=effective_hybrid,
            qdrant_client=_get_qdrant_client(),
            top_k=ret.retrieval_top_k,
            exact_match_boost=settings.hybrid_retrieval_exact_match_boost,
            budget=budget,
            index_versions=settings.active_index_versions,
        )
        ret.parallel_result = parallel_result
        ret.embedding_model = parallel_result.embedding_model or ret.embedding_model
        ret.embedding_prompt_tokens = parallel_result.total_embedding_prompt_tokens
        ret.graph_context_result = parallel_result.graph_result

        merged: dict[str, RetrievedChunk] = {}
        primary_query = ret.retrieval_queries[0]
        for record in parallel_result.query_records:
            if effective_hybrid and record.keyword_candidates is not None:
                hybrid_result = deps.hybrid_retrieval_service.merge(
                    vector_candidates=record.vector_candidates,
                    keyword_candidates=record.keyword_candidates.candidates,
                    exact_match_tokens=record.keyword_candidates.exact_match_tokens,
                    vector_weight=settings.hybrid_retrieval_vector_weight,
                    rrf_k=settings.hybrid_retrieval_rrf_k,
                    exact_match_boost=settings.hybrid_retrieval_exact_match_boost,
                )
                batch_chunks = [_hybrid_to_retrieved_chunk(c) for c in hybrid_result.candidates]
                if record.query == primary_query:
                    ret.hybrid_retrieval_enabled = True
                    ret.hybrid_vector_hit_count = hybrid_result.vector_hit_count
                    ret.hybrid_keyword_hit_count = hybrid_result.keyword_hit_count
                    ret.hybrid_exact_match_tokens = hybrid_result.exact_match_tokens
            else:
                batch_chunks = [_to_retrieved_chunk(c) for c in record.vector_candidates]
            for chunk in batch_chunks:
                key = str(chunk.chunk_id)
                if key not in merged or chunk.similarity_score > merged[key].similarity_score:
                    merged[key] = chunk

        retrieved = sorted(merged.values(), key=lambda c: c.similarity_score, reverse=True)
        retrieved = await deps.source_provenance_service.filter_active_chunks(
            db_session,
            organization_id=req.organization_id,
            chunks=retrieved,
        )
        # Citation-level authorization: remove chunks the principal cannot cite.
        retrieved = await filter_chunks_by_cite_access(
            db_session,
            principal=req.principal,
            organization_id=req.organization_id,
            user_id=req.user_id,
            user_roles=req.user_roles,
            chunks=retrieved,
        )
        retrieved, ret.graph_context_result = await _augment_retrieval_with_graph_context(
            db_session,
            organization_id=req.organization_id,
            question=req.payload.question,
            vector_chunks=retrieved,
            allowed_document_ids=document_ids,
            graph_enabled=ret.graph_enabled,
            graph_result=ret.graph_context_result,
        )
        ret.retrieved_chunks = _with_original_ranks(retrieved)
