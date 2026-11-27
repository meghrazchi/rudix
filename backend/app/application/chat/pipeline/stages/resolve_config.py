"""Stage 2: AI response policy, answer mode, RAG and model profiles, planner, routing,
tool orchestration, and answer language (R05-01). Order is exactly that of ``query_chat``.

Runs on the read session (R05-02). Only plain snapshots leave this stage: the RAG profile
config, the prompt version, the effective AI policy, the chat ``ResolvedTaskProfile``, and the
set of disabled tools; no ORM object is used after the read session is released.
"""

from time import perf_counter
from uuid import UUID

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.chat.pipeline.config_cache import (
    answer_prompt_version,
    effective_ai_policy,
    rag_profile_for_context,
)
from app.application.chat.pipeline.context import ChatContext
from app.application.chat.pipeline.controls import (
    _build_rerank_settings,
    _resolve_planner_critic_controls,
)
from app.application.chat.pipeline.stages._embedding import start_embedding_prefetch
from app.application.chat.scope_inventory import _is_scope_inventory_question
from app.core.config import settings
from app.core.logging import log_query_event
from app.domains.ai.profile.schemas import TaskType
from app.domains.ai.profile.service import resolve_task_profile_cached
from app.domains.chat.services.answer_planner_service import STRATEGY_LABELS
from app.domains.chat.services.language_service import detect_language, resolve_answer_language
from app.domains.chat.services.retrieval_strategy_router import FeatureAvailability
from app.domains.rag_profiles.schemas.rag_profiles import RagProfileConfig


class ResolveConfigStage:
    name = "resolve_config"
    runs_when_terminal = True
    optional = False

    async def run(self, ctx: ChatContext) -> None:
        async with ctx.sessions.read() as db_session:
            await self._resolve_policy(ctx, db_session)
            await self._resolve_profiles(ctx, db_session)
            # R05-04: the original question's embedding overlaps the rest of stage 2 to 4
            # when no later stage can change the retrieval query (stages/_embedding.py).
            start_embedding_prefetch(ctx)
            await self._plan(ctx, db_session)
        self._resolve_language(ctx)
        await self._emit_steps(ctx)

    async def _resolve_policy(self, ctx: ChatContext, db_session: AsyncSession) -> None:
        req = ctx.request
        deps = ctx.deps
        cfg = ctx.config
        payload = req.payload
        injection_blocked = cfg.injection_blocked
        # AI response policy pre-generation check — topic blocking (F268).
        # Resolve the collection override when the query is scoped to a single collection
        # (source_scope may be a collection-id string). The merged policy is a plain
        # dataclass, cached per organisation and collection (R05-05); no row is kept.
        policy_collection_id = _collection_id_or_none(payload.source_scope)
        cfg.ai_effective_policy = await effective_ai_policy(
            db_session,
            deps,
            organization_id=req.organization_id,
            collection_id=policy_collection_id,
        )
        if cfg.ai_effective_policy.source != "none":
            cfg.ai_policy_collection_id = policy_collection_id
        ai_pre_result = deps.ai_policy_engine.evaluate_pre_generation(
            payload.question, cfg.ai_effective_policy
        )
        cfg.ai_pre_result = ai_pre_result
        if ai_pre_result.blocked and not injection_blocked:
            log_query_event(
                event="query.rejected.policy_topic_blocked",
                organization_id=req.principal.organization_id,
                user_id=req.principal.user_id,
                job_id=ctx.job_id,
                status_code=status.HTTP_200_OK,
                violated_rules=ai_pre_result.violated_rules,
            )

        cfg.answer_mode_result = deps.answer_mode_service.classify(question=payload.question)
        cfg.scope_inventory_requested = _is_scope_inventory_question(payload.question)
        if cfg.answer_mode_result.mode == "grounded" and not cfg.scope_inventory_requested:
            cfg.answer_prompt_version = await answer_prompt_version(
                db_session, organization_id=req.organization_id
            )
            cfg.answer_prompt_template = cfg.answer_prompt_version.content

    async def _resolve_profiles(self, ctx: ChatContext, db_session: AsyncSession) -> None:
        req = ctx.request
        cfg = ctx.config
        ctx.latencies_ms = {}
        ctx.total_started = perf_counter()
        ctx.retrieval.embedding_model = ctx.deps.query_retrieval_service.embedding_model
        resolved_rag = await rag_profile_for_context(
            db_session, organization_id=req.organization_id, collection_id=None
        )
        cfg.rag_profile = resolved_rag.profile
        cfg.rag_profile_source = resolved_rag.source
        cfg.rerank_settings = _build_rerank_settings(
            dict(cfg.rag_profile.config) if cfg.rag_profile is not None else None
        )
        ctx.generation.not_found = cfg.blocked
        ctx.retrieval.final_top_k = req.payload.top_k or settings.retrieval_final_top_k
        cfg.query_rewrite_preview_enabled = settings.feature_enable_query_rewrite_preview

        # Resolve the effective model profile for this organisation (F223).
        cfg.chat_profile = await resolve_task_profile_cached(
            db_session,
            organization_id=req.organization_id,
            task_type=TaskType.chat,
        )

    async def _plan(self, ctx: ChatContext, db_session: AsyncSession) -> None:
        req = ctx.request
        deps = ctx.deps
        cfg = ctx.config
        payload = req.payload
        assert cfg.answer_mode_result is not None
        rag_profile = cfg.rag_profile
        grounded_question = (
            not cfg.injection_blocked
            and not ctx.generation.not_found
            and cfg.answer_mode_result.mode == "grounded"
            and not cfg.scope_inventory_requested
        )
        # Planner: classify question strategy and flag high-risk answers (F339).
        # Keyword heuristics only; also runs for dynamic routing (F341).
        cfg.pcr_enabled, cfg.pcr_mode, cfg.pcr_high_risk = _resolve_planner_critic_controls(
            RagProfileConfig.model_validate(dict(rag_profile.config))
            if rag_profile is not None
            else None,
        )
        cfg.routing_enabled = settings.feature_enable_dynamic_retrieval_routing
        if (cfg.pcr_enabled or cfg.routing_enabled) and grounded_question:
            cfg.planner_result = deps.answer_planner.classify(
                question=payload.question,
                graph_context_available=settings.feature_enable_graph_rag,
                connector_search_scope=False,
                high_risk_strategies_override=cfg.pcr_high_risk,
            )
        planner_strategy = (
            cfg.planner_result.strategy if cfg.planner_result is not None else "standard"
        )

        # Dynamic retrieval strategy routing (F341).
        if cfg.routing_enabled and grounded_question:
            profile_cfg_for_routing = (
                RagProfileConfig.model_validate(dict(rag_profile.config))
                if rag_profile is not None
                else None
            )
            cfg.route_result = deps.retrieval_strategy_router.route(
                planner_strategy=planner_strategy,
                features=FeatureAvailability(
                    hybrid_retrieval_enabled=settings.feature_enable_hybrid_retrieval,
                    graph_rag_enabled=settings.feature_enable_graph_rag,
                    parent_context_expansion_enabled=settings.feature_enable_parent_context_expansion,
                    keyword_retrieval_enabled=settings.feature_enable_hybrid_retrieval,
                ),
                profile_override=(
                    profile_cfg_for_routing.retrieval_strategy_override
                    if profile_cfg_for_routing is not None
                    else None
                ),
                request_override=payload.retrieval_strategy_override,
                allow_user_override=settings.feature_enable_retrieval_strategy_user_override,
            )

        # Adaptive tool orchestration (F342): authorize pipeline tools for this query.
        if settings.feature_enable_chat_tool_orchestration and grounded_question:
            feature_availability: dict[str, bool] = {
                "feature_enable_connectors": settings.feature_enable_connectors,
                "feature_enable_graph_rag": settings.feature_enable_graph_rag,
            }
            cfg.tool_policy_disabled = await deps.chat_tool_policy_repo.disabled_tool_names_cached(
                db_session,
                organization_id=req.organization_id,
            )
            cfg.orchestration_result = deps.chat_tool_orchestrator.orchestrate(
                planner_strategy=planner_strategy,
                principal=req.principal,
                feature_availability=feature_availability,
                disabled_tool_names=cfg.tool_policy_disabled,
                source_scope_mode=payload.scope_mode,
            )

    @staticmethod
    def _resolve_language(ctx: ChatContext) -> None:
        # Language detection and answer language resolution (F231).
        req = ctx.request
        cfg = ctx.config
        if settings.feature_enable_language_aware_rag and not cfg.injection_blocked:
            cfg.detected_language = detect_language(req.payload.question)
            cfg.answer_language_used = resolve_answer_language(
                mode=req.payload.answer_language,
                detected_language=cfg.detected_language,
                workspace_default=settings.answer_language_workspace_default,
            )
            log_query_event(
                event="query.language.detected",
                organization_id=req.principal.organization_id,
                user_id=req.principal.user_id,
                detected_language=cfg.detected_language,
                answer_language_mode=req.payload.answer_language,
                answer_language_used=cfg.answer_language_used,
            )

    @staticmethod
    async def _emit_steps(ctx: ChatContext) -> None:
        cfg = ctx.config
        await ctx.emit_step("understanding_question", "Understanding your question", "success")
        if cfg.pcr_enabled and cfg.planner_result is not None:
            await ctx.emit_step(
                "planning_answer",
                "Planning answer strategy",
                "success",
                detail=STRATEGY_LABELS.get(
                    cfg.planner_result.strategy, cfg.planner_result.strategy
                ),
            )
        if cfg.routing_enabled and cfg.route_result is not None:
            await ctx.emit_step(
                "selecting_strategy",
                "Selecting search strategy",
                "success",
                detail=cfg.route_result.method_label,
            )
        if settings.feature_enable_chat_tool_orchestration and cfg.orchestration_result is not None:
            await ctx.emit_step(
                "tool_orchestration",
                "Orchestrating available tools",
                "success",
                detail=(
                    f"{cfg.orchestration_result.authorized_count} of "
                    f"{cfg.orchestration_result.tool_count} tools authorized"
                ),
            )
        await ctx.emit_step("checking_sources", "Checking accessible sources", "running")


def _collection_id_or_none(source_scope: object) -> UUID | None:
    """The collection id when ``source_scope`` is a collection-id string (F268 rule)."""
    if source_scope is None:
        return None
    try:
        return UUID(str(source_scope))
    except (ValueError, AttributeError):
        return None
