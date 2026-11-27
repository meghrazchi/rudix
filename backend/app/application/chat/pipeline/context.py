"""State of one chat run, passed through every pipeline stage (R05-01).

The fields are exactly the locals of the pre-pipeline ``query_chat``, grouped by phase.
Later packages add fields only directly after their anchor comment (plan section 4.1).
"""

import asyncio
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from app.application.chat.pipeline.controls import _NOT_FOUND_ANSWER
from app.application.chat.pipeline.deps import ChatPipelineDeps
from app.application.chat.pipeline.events import ActivityStepEmitter, ChatEvent, Emitter
from app.application.chat.pipeline.ledger import TokenLedger
from app.application.chat.pipeline.sessions import ChatSessionScope
from app.application.chat.pipeline.snapshots import PromptVersionSnapshot, RagProfileSnapshot
from app.application.chat.pipeline.stream_state import StreamState
from app.auth.models import AuthenticatedPrincipal
from app.core.safety_guardrails import InjectionCheckResult
from app.domains.ai.profile.schemas import ResolvedTaskProfile
from app.domains.ai_response_policy.services.policy_engine import EffectivePolicy
from app.domains.ai_response_policy.services.policy_engine import (
    PolicyEvaluationResult as AiPolicyEvaluationResult,
)
from app.domains.chat.schemas.chat import ChatCitationResponse, ChatQueryRequest
from app.domains.chat.schemas.trust_metadata import AnswerTrustMetadataResponse
from app.domains.chat.services.answer_critic_service import CriticResult
from app.domains.chat.services.answer_mode_service import AnswerModeResult
from app.domains.chat.services.answer_planner_service import PlannerResult
from app.domains.chat.services.answer_refiner_service import RefinerResult
from app.domains.chat.services.citation_service import CitationBuildResult
from app.domains.chat.services.confidence_service import (
    ConfidenceChunkSignal,
    ConfidenceExplanation,
)
from app.domains.chat.services.conflict_detection_service import ConflictDetectionResult
from app.domains.chat.services.context_injection_scan import ContextInjectionScanResult
from app.domains.chat.services.context_packer_service import ContextPackResult
from app.domains.chat.services.graph_retrieval_service import GraphRetrievalResult
from app.domains.chat.services.grounded_answer_verifier import GroundedVerifierResult
from app.domains.chat.services.llm_service import LLMAnswerResult
from app.domains.chat.services.parallel_retrieval_optimizer import ParallelRetrievalResult
from app.domains.chat.services.parent_context_expansion_service import ParentExpansionResult
from app.domains.chat.services.query_rewriting_service import QueryRewritingResult
from app.domains.chat.services.rerank_service import RerankDiagnostics, RerankResult, RerankSettings
from app.domains.chat.services.retrieval_strategy_router import RetrievalRouteResult
from app.domains.chat.services.retrieved_chunk import RetrievedChunk
from app.domains.chat.services.source_freshness_service import DocumentTrustData
from app.domains.chat.services.source_scope_service import ResolvedSourceScope
from app.domains.chat.services.table_retrieval_service import TableBoostResult
from app.domains.chat.services.tool_orchestrator import ToolOrchestrationResult
from app.domains.chat.services.untrusted_context import new_context_boundary
from app.models.chat import ChatMessage

NOT_FOUND_ANSWER = _NOT_FOUND_ANSWER


@dataclass
class RequestState:
    payload: ChatQueryRequest
    principal: AuthenticatedPrincipal
    transport: str
    request_id: str | None
    user_id: UUID
    organization_id: UUID
    user_roles: list[str]


@dataclass
class RunIds:
    """Ids fixed for one run (R05-02). The assistant message id is pre-assigned; the chat
    session id is pre-assigned for a new session (the row is written by stage 10) or set
    by stage 1 once an existing session passed the ownership check."""

    assistant_message_id: UUID = field(default_factory=uuid4)
    chat_session_id: UUID | None = None
    new_chat_session: bool = False


@dataclass
class ScopeState:
    explicit_document_ids: list[UUID] | None = None
    source_scope_result: ResolvedSourceScope | None = None
    document_ids: list[UUID] | None = None


@dataclass
class ConfigState:
    injection_check: InjectionCheckResult | None = None
    ai_policy_collection_id: UUID | None = None
    ai_effective_policy: EffectivePolicy | None = None
    ai_pre_result: AiPolicyEvaluationResult | None = None
    answer_mode_result: AnswerModeResult | None = None
    scope_inventory_requested: bool = False
    answer_prompt_version: PromptVersionSnapshot | None = None
    answer_prompt_template: str | None = None
    rag_profile: RagProfileSnapshot | None = None
    rag_profile_source: str = "system_default"
    rerank_settings: RerankSettings | None = None
    chat_profile: ResolvedTaskProfile | None = None
    pcr_enabled: bool = False
    pcr_mode: str = "high_risk_only"
    pcr_high_risk: frozenset[str] = frozenset()
    routing_enabled: bool = False
    planner_result: PlannerResult | None = None
    route_result: RetrievalRouteResult | None = None
    orchestration_result: ToolOrchestrationResult | None = None
    tool_policy_disabled: frozenset[str] = frozenset()
    detected_language: str | None = None
    answer_language_used: str | None = None
    query_rewrite_preview_enabled: bool = False
    query_rewrite_result: QueryRewritingResult | None = None

    @property
    def blocked(self) -> bool:
        """The question was refused by the injection guard or the AI policy topic check."""
        injection = self.injection_check is not None and self.injection_check.blocked
        policy = self.ai_pre_result is not None and self.ai_pre_result.blocked
        return injection or policy

    @property
    def injection_blocked(self) -> bool:
        return self.injection_check is not None and self.injection_check.blocked


@dataclass
class RetrievalState:
    embedding_model: str | None = None
    final_top_k: int = 0
    rerank_applied: bool = False
    retrieval_top_k: int = 0
    retrieval_queries: list[str] = field(default_factory=list)
    graph_enabled: bool = False
    retrieved_chunks: list[RetrievedChunk] = field(default_factory=list)
    selected_chunks: list[RetrievedChunk] = field(default_factory=list)
    embedding_prompt_tokens: int = 0
    hybrid_retrieval_enabled: bool = False
    hybrid_vector_hit_count: int = 0
    hybrid_keyword_hit_count: int = 0
    hybrid_exact_match_tokens: list[str] = field(default_factory=list)
    graph_context_result: GraphRetrievalResult = field(default_factory=GraphRetrievalResult)
    parallel_result: ParallelRetrievalResult | None = None
    rerank_result: RerankResult | None = None
    freshness_trust_map: dict[str, DocumentTrustData] = field(default_factory=dict)
    freshness_stale_ids: frozenset[str] = frozenset()
    freshness_stale_threshold_days: int | None = None
    freshness_filter_enabled: bool = False
    freshness_excluded_count: int = 0
    freshness_boosted_count: int = 0
    freshness_stale_count: int = 0
    freshness_unreviewed_count: int = 0
    freshness_deprecated_count: int = 0
    freshness_draft_count: int = 0
    freshness_all_excluded_fallback: bool = False
    table_boost_enabled: bool = False
    table_boost_applied: bool = False
    table_boost_count: int = 0
    table_chunk_count: int = 0
    table_query_detected: bool = False
    table_boost_result: TableBoostResult | None = None
    ocr_docs: list[Any] = field(default_factory=list)
    ocr_quality_map: dict[str, str] = field(default_factory=dict)
    ocr_quality_downranking_enabled: bool = False
    ocr_low_confidence_chunk_count: int = 0
    parent_expansion_result: ParentExpansionResult | None = None
    parent_context_map: dict[str, str] = field(default_factory=dict)
    parent_context_expansion_enabled: bool = False
    parent_context_child_hit_count: int = 0
    parent_context_expanded_count: int = 0
    parent_context_tokens_used: int = 0
    context_pack_result: ContextPackResult | None = None
    context_packing_rejected_count: int = 0
    conflict_detection_enabled: bool = False
    conflict_detection_applied: bool = False
    conflict_detection_latency_ms: int = 0
    conflict_detection_result: ConflictDetectionResult = field(
        default_factory=lambda: ConflictDetectionResult(
            conflict_detected=False,
            agreement_level="full",
        )
    )


@dataclass
class GenerationState:
    prompt: str = ""
    answer: str = NOT_FOUND_ANSWER
    not_found: bool = False
    citations: list[ChatCitationResponse] = field(default_factory=list)
    citation_result: CitationBuildResult | None = None
    llm_result: LLMAnswerResult | None = None
    # True when the grounded path reached generation (``not not_found`` after packing).
    answer_block_ran: bool = False
    # True when the single LLM call ran (tree search did not select a candidate).
    llm_call_ran: bool = False
    # True once generation.started and the running drafting step were emitted.
    drafting_started: bool = False
    llm_prompt_tokens: int = 0
    llm_completion_tokens: int = 0
    llm_model: str | None = None
    llm_provider: str | None = None
    llm_fallback_used: bool = False
    llm_fallback_from: str | None = None
    llm_fallback_to: str | None = None
    llm_fallback_reason: str | None = None
    llm_retry_count: int | None = None
    llm_cost_usd: Decimal | None = None
    llm_latency_ms: int = 0


@dataclass
class VerificationState:
    citation_validation_failed: bool = False
    verification_failed: bool = False
    grounded_verifier_result: GroundedVerifierResult | None = None
    grounded_verification_enabled: bool = False
    grounded_verification_mode: str | None = None
    grounded_verification_threshold: float | None = None
    freshness_multiplier: float = 1.0
    ocr_quality_multiplier: float = 1.0
    conflict_multiplier: float = 1.0
    confidence_signals: list[ConfidenceChunkSignal] = field(default_factory=list)
    confidence_score: float = 0.0
    confidence_category: str = "low"
    confidence_explanation: ConfidenceExplanation | None = None
    critic_result: CriticResult | None = None
    refiner_result: RefinerResult | None = None
    ai_policy_result: AiPolicyEvaluationResult = field(default_factory=AiPolicyEvaluationResult)


@dataclass
class PersistState:
    answer_latency_ms: int = 0
    rerank_diagnostics: RerankDiagnostics | None = None
    retrieval_diagnostics_payload: dict[str, Any] = field(default_factory=dict)
    assistant_message: ChatMessage | None = None
    trust_metadata: AnswerTrustMetadataResponse | None = None
    response_citations: list[ChatCitationResponse] = field(default_factory=list)


@dataclass
class ChatContext:
    request: RequestState
    deps: ChatPipelineDeps
    emitter: Emitter
    sessions: ChatSessionScope
    steps: ActivityStepEmitter
    ids: RunIds = field(default_factory=RunIds)
    scope: ScopeState = field(default_factory=ScopeState)
    config: ConfigState = field(default_factory=ConfigState)
    retrieval: RetrievalState = field(default_factory=RetrievalState)
    generation: GenerationState = field(default_factory=GenerationState)
    verification: VerificationState = field(default_factory=VerificationState)
    persist: PersistState = field(default_factory=PersistState)
    latencies_ms: dict[str, int] = field(default_factory=dict)
    total_started: float = 0.0
    ledger: TokenLedger = field(default_factory=TokenLedger)
    # Absolute ``perf_counter`` deadline of the run; ``None`` means no budget (B2 sets it).
    deadline: float | None = None
    # Stages that were skipped or degraded, recorded by the runner (names and reasons only).
    degradations: list[dict[str, str]] = field(default_factory=list)
    # Tasks started by stages; the runner cancels the unfinished ones when the run ends.
    background_tasks: list[asyncio.Task[Any]] = field(default_factory=list)
    # Set by a stage that produced the final answer (blocked, scope inventory, guidance).
    terminal: bool = False
    # anchor: A1 streaming
    stream: StreamState = field(default_factory=StreamState)
    # anchor: A2 resilience
    # anchor: B1 ledger routing injection
    # Random boundary of the context markers, shared by every prompt of this run (R05-09).
    context_boundary: str = field(default_factory=new_context_boundary)
    # Prompt-injection scan of the reranked chunks (R05-09); ``None`` when no scan ran.
    context_injection: ContextInjectionScanResult | None = None
    # anchor: B2 budget caches

    async def emit(self, event: ChatEvent) -> None:
        await self.emitter.emit(event)

    async def emit_step(
        self,
        step_key: str,
        label: str,
        state: str,
        detail: str | None = None,
        duration_ms: int | None = None,
    ) -> None:
        await self.steps.emit_step(step_key, label, state, detail, duration_ms)

    @property
    def job_id(self) -> str:
        chat_session_id = self.ids.chat_session_id
        return str(chat_session_id) if chat_session_id is not None else ""
