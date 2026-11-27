"""Feature flags and agent runtime settings."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import (
    BaseModel,
    Field,
)

from app.core.settings.enums import (
    Environment,
)

if TYPE_CHECKING:
    from app.core.config import Settings


class FeaturesSettings(BaseModel):
    agent_max_steps: int = Field(default=12, ge=1, le=200)
    agent_max_parallel_tool_calls: int = Field(default=4, ge=1, le=50)
    agent_tool_max_calls_per_run: int = Field(default=30, ge=1, le=500)
    agent_tool_timeout_ms: int = Field(default=8000, ge=100, le=300000)
    agent_tool_max_input_bytes: int = Field(default=32768, ge=512, le=10000000)
    agent_tool_max_output_bytes: int = Field(default=65536, ge=512, le=10000000)
    agent_tool_max_retry_attempts: int = Field(default=1, ge=0, le=10)
    agent_prompt_injection_guard_enabled: bool = True
    agent_document_instruction_guard_enabled: bool = True
    # F220: Model profiles and provider policy
    # feature_enable_local_llm_profiles — show local provider in admin model profile UI/API.
    # feature_enable_local_embedding_profiles — same for embedding task profiles.
    # feature_enable_provider_fallback — allow routing to a cloud fallback on local failure.
    #   WARNING: when True, private document context may be sent to the cloud provider on
    #   fallback. Requires explicit governance acknowledgment before enabling in production.
    #   See docs/19_LOCAL_LLM_PROVIDER_INTEGRATION.md — Security and Privacy section.
    feature_enable_local_llm_profiles: bool = False
    feature_enable_local_embedding_profiles: bool = False
    feature_enable_provider_fallback: bool = False
    feature_allow_request_model_override: bool = False
    feature_enable_experimental_profiles: bool = False
    feature_enable_pipeline_explorer: bool = True
    feature_enable_agents: bool | None = None
    # Authorization enforcement mode (F336).
    # True (default): policy denies block access and return 403/404.
    # False: soft/canary mode — denials are logged but access is allowed.
    # Disable only during staged rollout on existing deployments; re-enable before GA.
    feature_enable_authorization_enforcement: bool = True
    feature_expose_config_snapshot: bool = True
    # WebSocket chat transport (F277).
    feature_chat_websocket_enabled: bool = True
    ws_chat_max_connections_per_user: int = Field(default=3, ge=1, le=20)
    ws_chat_idle_timeout_seconds: int = Field(default=300, ge=30, le=3600)
    ws_chat_heartbeat_interval_seconds: int = Field(default=30, ge=10, le=120)
    # WebSocket chat auth (R02-10): single-use handshake tickets from POST /chat/ws-ticket.
    # chat_ws_allow_query_token keeps the legacy ?token= handshake working; it defaults
    # to true in 0.2.0, flips to false in 0.5.0, and is removed in 1.0.0.
    chat_ws_ticket_ttl_seconds: int = Field(default=30, ge=5, le=300)
    chat_ws_allow_query_token: bool = True
    # R05-01/R05-02: deprecated in 0.5.0. POST /chat and the chat WebSocket always run the
    # staged chat pipeline (the legacy bodies are gone); false only logs the startup warning
    # chat.pipeline_v2_ignored. Kept for one milestone, removed in 0.6.0.
    chat_pipeline_v2: bool = True
    # Table-aware retrieval (F298): boost table chunks when the query looks tabular.
    # feature_enable_table_aware_retrieval gates the entire feature.
    # table_retrieval_boost_multiplier: score multiplier applied to table chunks on table-like queries.
    feature_enable_table_aware_retrieval: bool = True
    table_retrieval_boost_multiplier: float = Field(default=1.25, ge=1.0, le=5.0)
    # OCR quality downranking (F299): penalise retrieval scores for low-confidence OCR chunks.
    feature_enable_ocr_quality_downranking: bool = True
    # Parent-context expansion (F300): replace child-chunk text with parent section text in the
    # LLM prompt while keeping citations on the precise child chunk.
    # parent_context_max_tokens_per_chunk: estimated-token cap per expanded parent text.
    feature_enable_parent_context_expansion: bool = True
    parent_context_max_tokens_per_chunk: int = Field(default=512, ge=64, le=8192)
    # Strict context packing (F340): priority scoring, rejection rules, and global token budget
    # applied after reranking.  Disabled by default; enable per RAG profile via
    # context_packing_enabled.  This system flag gates the feature entirely.
    feature_enable_context_packing: bool = False
    # Dynamic retrieval strategy routing (F341).
    # When True, the RetrievalStrategyRouter auto-selects a retrieval method
    # (vector / keyword / hybrid / table_aware / parent_child / graph_rag /
    # connector_aware) based on the question's planner strategy.
    feature_enable_dynamic_retrieval_routing: bool = False
    # When True, API callers may pass retrieval_strategy_override in the request
    # body to force a specific retrieval method for that query.
    feature_enable_retrieval_strategy_user_override: bool = False
    # Permission-aware adaptive tool orchestration (F342): selects and authorizes
    # chat-pipeline tools based on planner strategy, feature flags, principal roles,
    # and org-level policy overrides. Tool call decisions are logged and surfaced in
    # the trust panel. Default off — enable after baseline pipeline is validated.
    feature_enable_chat_tool_orchestration: bool = False
    # Tree-search reasoning (F346): fan out multiple candidate answers for high-risk,
    # multi-source questions and select the safest supported answer. Disabled by
    # default so simple questions keep the single-pass path.
    feature_enable_tree_search_reasoning: bool = False
    tree_search_max_candidates: int = Field(default=3, ge=1, le=10)
    tree_search_timeout_seconds: float = Field(default=6.0, ge=0.5, le=60.0)
    tree_search_max_total_tokens: int = Field(default=6000, ge=256, le=100_000)
    tree_search_max_total_cost_usd: float = Field(default=0.03, ge=0.0, le=1000.0)
    tree_search_min_selected_score: float = Field(default=0.45, ge=0.0, le=1.0)
    tree_search_min_context_chunks: int = Field(default=2, ge=1, le=10)
    # Org workflow memory and user preferences (F343). Off by default; enable once
    # permission-scoping and redaction are validated for the target org.
    feature_enable_org_memory: bool = False
    # PDF extraction pipeline (F237).
    feature_enable_advanced_pdf_extraction: bool = True
    pdf_extraction_enable_tables: bool = True
    pdf_extraction_enable_images: bool = True
    pdf_extraction_max_pages: int = Field(default=500, ge=1, le=5000)
    pdf_extraction_scanned_coverage_threshold: float = Field(default=0.05, ge=0.0, le=1.0)
    pdf_extraction_mixed_coverage_threshold: float = Field(default=0.50, ge=0.0, le=1.0)
    answer_language_workspace_default: str = Field(
        default="en",
        pattern=r"^(en|de|es|fr)$",
    )


def validate_agents_default(settings: Settings) -> None:
    if settings.feature_enable_agents is None:
        settings.feature_enable_agents = settings.environment in {
            Environment.development,
            Environment.test,
        }
