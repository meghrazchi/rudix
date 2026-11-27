"""Service singletons and collaborators of the chat pipeline (R05-01).

``default_deps`` holds the one instance of every service the chat transports use.
``app.interfaces.http.chat`` binds its legacy module names to these objects (contract 4.2.2),
so a test that patches an attribute of ``chat_api._llm_service`` patches the pipeline too.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from app.application.chat.quota import ensure_chat_quota
from app.auth.authorization_service import AuthorizationService
from app.core.safety_guardrails import PromptInjectionGuard
from app.db.session import SessionLocal
from app.domains.admin.repositories.usage import UsageRepository
from app.domains.admin.services.audit_service import AuditLogService
from app.domains.admin.services.feature_flag_service import FeatureFlagService
from app.domains.agents.repositories.agent_policy import AgentToolPolicyRepository
from app.domains.ai_response_policy.repositories.ai_response_policy import (
    AiResponsePolicyRepository,
)
from app.domains.ai_response_policy.services.policy_engine import AiResponsePolicyEngine
from app.domains.chat.repositories.chat import ChatRepository
from app.domains.chat.services import citation_enrichment
from app.domains.chat.services.answer_critic_service import AnswerCriticService
from app.domains.chat.services.answer_mode_service import AnswerModeService
from app.domains.chat.services.answer_planner_service import AnswerPlannerService
from app.domains.chat.services.answer_refiner_service import AnswerRefinerService
from app.domains.chat.services.citation_service import CitationService
from app.domains.chat.services.confidence_service import ConfidenceService
from app.domains.chat.services.conflict_detection_service import ConflictDetectionService
from app.domains.chat.services.context_packer_service import ContextPackerService
from app.domains.chat.services.graph_retrieval_service import GraphRetrievalService
from app.domains.chat.services.grounded_answer_verifier import GroundedAnswerVerifier
from app.domains.chat.services.hybrid_retrieval_service import HybridRetrievalService
from app.domains.chat.services.keyword_retrieval_service import KeywordRetrievalService
from app.domains.chat.services.llm_service import LLMService
from app.domains.chat.services.parallel_retrieval_optimizer import ParallelRetrievalOptimizer
from app.domains.chat.services.parent_context_expansion_service import (
    ParentContextExpansionService,
)
from app.domains.chat.services.prompt_service import PromptService
from app.domains.chat.services.query_retrieval_service import QueryRetrievalService
from app.domains.chat.services.query_rewriting_service import QueryRewritingService
from app.domains.chat.services.rerank_service import RerankService
from app.domains.chat.services.retrieval_strategy_router import RetrievalStrategyRouter
from app.domains.chat.services.source_freshness_service import SourceFreshnessService
from app.domains.chat.services.source_scope_service import SourceScopeService
from app.domains.chat.services.table_retrieval_service import TableRetrievalService
from app.domains.chat.services.tool_orchestrator import ChatToolOrchestrator
from app.domains.chat.services.tree_search_service import TreeSearchService
from app.domains.connectors.services.source_provenance import SourceProvenanceService
from app.domains.documents.repositories.documents import DocumentRepository
from app.domains.documents.services.ocr_quality_service import OcrQualityService
from app.domains.prompt_templates.services.prompt_template_service import PromptTemplateService

EnsureQuota = Callable[..., Awaitable[None]]
SessionFactory = Callable[[], Any]


@dataclass
class ChatPipelineDeps:
    """Everything the pipeline calls out to; transports may override per run."""

    chat_repository: ChatRepository = field(default_factory=ChatRepository)
    usage_repository: UsageRepository = field(default_factory=UsageRepository)
    audit_log_service: AuditLogService = field(default_factory=AuditLogService)
    query_retrieval_service: QueryRetrievalService = field(default_factory=QueryRetrievalService)
    keyword_retrieval_service: KeywordRetrievalService = field(
        default_factory=KeywordRetrievalService
    )
    hybrid_retrieval_service: HybridRetrievalService = field(default_factory=HybridRetrievalService)
    source_scope_service: SourceScopeService = field(default_factory=SourceScopeService)
    rerank_service: RerankService = field(default_factory=RerankService)
    prompt_service: PromptService = field(default_factory=PromptService)
    prompt_template_service: PromptTemplateService = field(default_factory=PromptTemplateService)
    citation_service: CitationService = field(default_factory=CitationService)
    source_provenance_service: SourceProvenanceService = field(
        default_factory=SourceProvenanceService
    )
    confidence_service: ConfidenceService = field(default_factory=ConfidenceService)
    conflict_detection_service: ConflictDetectionService = field(
        default_factory=ConflictDetectionService
    )
    graph_retrieval_service: GraphRetrievalService = field(default_factory=GraphRetrievalService)
    feature_flag_service: FeatureFlagService = field(default_factory=FeatureFlagService)
    llm_service: LLMService = field(default_factory=LLMService)
    injection_guard: PromptInjectionGuard = field(default_factory=PromptInjectionGuard)
    query_rewriting_service: QueryRewritingService = field(default_factory=QueryRewritingService)
    grounded_verifier: GroundedAnswerVerifier = field(default_factory=GroundedAnswerVerifier)
    answer_mode_service: AnswerModeService = field(default_factory=AnswerModeService)
    answer_planner: AnswerPlannerService = field(default_factory=AnswerPlannerService)
    answer_critic: AnswerCriticService = field(default_factory=AnswerCriticService)
    answer_refiner: AnswerRefinerService = field(default_factory=AnswerRefinerService)
    authorization_service: AuthorizationService = field(default_factory=AuthorizationService)
    source_freshness_service: SourceFreshnessService = field(
        default_factory=lambda: citation_enrichment._source_freshness_service
    )
    table_retrieval_service: TableRetrievalService = field(default_factory=TableRetrievalService)
    ocr_quality_service: OcrQualityService = field(
        default_factory=lambda: citation_enrichment._ocr_quality_service
    )
    parent_context_expansion_service: ParentContextExpansionService = field(
        default_factory=ParentContextExpansionService
    )
    parallel_retrieval_optimizer: ParallelRetrievalOptimizer = field(
        default_factory=ParallelRetrievalOptimizer
    )
    context_packer_service: ContextPackerService = field(default_factory=ContextPackerService)
    retrieval_strategy_router: RetrievalStrategyRouter = field(
        default_factory=RetrievalStrategyRouter
    )
    chat_tool_orchestrator: ChatToolOrchestrator = field(default_factory=ChatToolOrchestrator)
    tree_search_service: TreeSearchService = field(default_factory=TreeSearchService)
    chat_tool_policy_repo: AgentToolPolicyRepository = field(
        default_factory=AgentToolPolicyRepository
    )
    document_repository_for_trust: DocumentRepository = field(default_factory=DocumentRepository)
    ai_policy_repo: AiResponsePolicyRepository = field(default_factory=AiResponsePolicyRepository)
    ai_policy_engine: AiResponsePolicyEngine = field(default_factory=AiResponsePolicyEngine)
    # Read at call time by the transports so tests that rebind the chat module globals
    # (``SessionLocal``, ``ensure_chat_quota``) reach the pipeline.
    session_factory: SessionFactory = SessionLocal
    ensure_quota: EnsureQuota = ensure_chat_quota


default_deps = ChatPipelineDeps()
