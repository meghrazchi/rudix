"""Stage 5: query rewriting and decomposition (F295, R05-01).

Runs before the direct answers, exactly where ``query_chat`` ran it. Scope filters (document
ids, organisation) are applied in retrieval and never altered here, so rewriting cannot widen
access. The log carries the strategy and counts only, never the rewritten text.
"""

from app.application.chat.pipeline.context import ChatContext
from app.application.chat.pipeline.controls import _resolve_query_rewrite_preview_enabled
from app.application.chat.pipeline.stages._ledger import record_aux_usage
from app.application.chat.pipeline.stages.policies import run_with_budget
from app.core.config import settings
from app.core.logging import log_query_event
from app.domains.rag_profiles.schemas.rag_profiles import RagProfileConfig


class RewriteStage:
    name = "rewrite"
    runs_when_terminal = True
    optional = False

    async def run(self, ctx: ChatContext) -> None:
        req = ctx.request
        cfg = ctx.config
        assert cfg.answer_mode_result is not None
        if not (
            settings.feature_enable_query_rewriting
            and not cfg.injection_blocked
            and cfg.answer_mode_result.mode == "grounded"
            and not cfg.scope_inventory_requested
        ):
            return
        profile_rewriting = True
        profile_decomposition = True
        profile_max_sub_queries: int | None = None
        if cfg.rag_profile is not None:
            profile_cfg = RagProfileConfig.model_validate(dict(cfg.rag_profile.config))
            profile_rewriting = profile_cfg.query_rewriting_enabled
            profile_decomposition = profile_cfg.query_decomposition_enabled
            profile_max_sub_queries = profile_cfg.query_rewriting_max_sub_queries
        async with ctx.sessions.short() as db_session:
            cfg.query_rewrite_preview_enabled = await _resolve_query_rewrite_preview_enabled(
                db_session,
                organization_id=req.organization_id,
            )
        # R05-04: an exhausted rewrite budget retrieves with the original question.
        outcome = await run_with_budget(
            ctx,
            "rewrite",
            lambda: ctx.deps.query_rewriting_service.rewrite(
                req.payload.question,
                profile_rewriting_enabled=profile_rewriting,
                profile_decomposition_enabled=profile_decomposition,
                max_sub_queries=profile_max_sub_queries,
                resolved_profile=cfg.chat_profile,
            ),
        )
        if not outcome.completed or outcome.value is None:
            return
        result = outcome.value
        cfg.query_rewrite_result = result
        record_aux_usage(ctx, "rewrite", result.usage)
        if result.rewriting_applied or result.decomposition_applied:
            log_query_event(
                event="query.rewriting.applied",
                organization_id=req.principal.organization_id,
                user_id=req.principal.user_id,
                strategy=result.strategy,
                rewriting_applied=result.rewriting_applied,
                decomposition_applied=result.decomposition_applied,
                sub_query_count=len(result.sub_queries),
            )
