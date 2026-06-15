import json
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlsplit, urlunsplit

from pydantic import (
    AmqpDsn,
    AnyHttpUrl,
    AnyUrl,
    BaseModel,
    Field,
    PostgresDsn,
    RedisDsn,
    SecretStr,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT_DIR = BACKEND_DIR.parent
ENV_FILES = (
    str(BACKEND_DIR / ".env"),
    str(PROJECT_ROOT_DIR / ".env"),
)
_ALLOWED_ORG_ROLES = {"owner", "admin", "member", "viewer"}
_DEFAULT_MCP_VIEWER_CAPABILITIES = [
    "documents.read",
    "documents.chunks.read",
    "documents.summary.read",
    "documents.compare.read",
    "pipeline.read",
]
_DEFAULT_MCP_ELEVATED_CAPABILITIES = [
    *_DEFAULT_MCP_VIEWER_CAPABILITIES,
    "chat.answer",
]


class Environment(StrEnum):
    development = "development"
    test = "test"
    staging = "staging"
    production = "production"


class LogFormat(StrEnum):
    auto = "auto"
    json = "json"
    console = "console"


class AuthProvider(StrEnum):
    app = "app"
    clerk = "clerk"
    supabase = "supabase"
    internal_jwt = "internal_jwt"
    api_key = "api_key"


class RateLimitRedisFailureMode(StrEnum):
    open = "open"
    closed = "closed"


class QdrantDistance(StrEnum):
    cosine = "cosine"
    dot = "dot"
    euclid = "euclid"
    manhattan = "manhattan"


class MCPTransport(StrEnum):
    streamable_http = "streamable_http"
    stdio = "stdio"


class MCPExternalTransport(StrEnum):
    streamable_http = "streamable_http"


class MCPExternalAuthType(StrEnum):
    none = "none"
    bearer = "bearer"
    header = "header"


class RerankFallbackBehavior(StrEnum):
    original = "original"
    disabled = "disabled"


class ConnectorRolloutStage(StrEnum):
    off = "off"
    development = "development"
    staging = "staging"
    production = "production"
    all = "all"


class LangfuseRedactionMode(StrEnum):
    none = "none"
    inputs = "inputs"
    all = "all"


class MCPExternalServerSettings(BaseModel):
    server_id: str = Field(
        min_length=2,
        max_length=64,
        pattern=r"^[a-z0-9][a-z0-9._-]*$",
    )
    enabled: bool = True
    transport: MCPExternalTransport = MCPExternalTransport.streamable_http
    base_url: AnyHttpUrl
    timeout_seconds: float = Field(default=8.0, ge=0.1, le=120.0)
    auth_type: MCPExternalAuthType = MCPExternalAuthType.none
    auth_token: SecretStr | None = None
    auth_header_name: str | None = Field(default=None, min_length=1, max_length=100)
    auth_header_value: SecretStr | None = None
    allow_tools: list[str] = Field(default_factory=list, max_length=200)
    allow_resources: list[str] = Field(default_factory=list, max_length=200)
    read_only_tools: list[str] = Field(default_factory=list, max_length=200)
    side_effect_tools: list[str] = Field(default_factory=list, max_length=200)
    required_roles: list[str] = Field(
        default_factory=lambda: ["owner", "admin"],
        max_length=4,
    )
    capability_prefix: str = Field(
        default="external_mcp",
        min_length=2,
        max_length=64,
        pattern=r"^[a-z0-9][a-z0-9._-]*$",
    )
    expose_on_mcp_surface: bool = False
    approval_required_for_side_effect: bool = True
    budget_max_calls_per_run: int | None = Field(default=None, ge=1, le=500)
    budget_max_input_bytes: int | None = Field(default=None, ge=512, le=10_000_000)
    budget_max_output_bytes: int | None = Field(default=None, ge=512, le=10_000_000)
    budget_timeout_ms: int | None = Field(default=None, ge=100, le=300_000)
    budget_max_retry_attempts: int | None = Field(default=None, ge=0, le=10)

    @field_validator(
        "allow_tools",
        "allow_resources",
        "read_only_tools",
        "side_effect_tools",
        mode="before",
    )
    @classmethod
    def validate_string_list(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            raw_items = [item.strip() for item in value.split(",")]
        elif isinstance(value, list):
            raw_items = [str(item).strip() for item in value]
        else:
            raise ValueError("value must be a comma-separated string or list")

        normalized_values: list[str] = []
        for item in raw_items:
            if not item:
                continue
            if item not in normalized_values:
                normalized_values.append(item)
        return normalized_values

    @field_validator("required_roles", mode="before")
    @classmethod
    def validate_required_roles(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            raw_items = [item.strip() for item in value.split(",")]
        elif isinstance(value, list):
            raw_items = [str(item).strip() for item in value]
        else:
            raise ValueError("required_roles must be a comma-separated string or list")

        normalized_roles: list[str] = []
        for role in raw_items:
            if not role:
                continue
            normalized = role.lower()
            if normalized not in _ALLOWED_ORG_ROLES:
                raise ValueError(f"unsupported required role: {role}")
            if normalized not in normalized_roles:
                normalized_roles.append(normalized)
        if not normalized_roles:
            raise ValueError("required_roles must contain at least one role")
        return normalized_roles

    @model_validator(mode="after")
    def validate_consistency(self) -> "MCPExternalServerSettings":
        if self.auth_type == MCPExternalAuthType.bearer:
            if self.auth_token is None or not self.auth_token.get_secret_value().strip():
                raise ValueError("auth_token is required when auth_type=bearer")
        if self.auth_type == MCPExternalAuthType.header:
            if self.auth_header_name is None:
                raise ValueError("auth_header_name is required when auth_type=header")
            if (
                self.auth_header_value is None
                or not self.auth_header_value.get_secret_value().strip()
            ):
                raise ValueError("auth_header_value is required when auth_type=header")

        if self.read_only_tools and self.side_effect_tools:
            overlap = set(self.read_only_tools).intersection(self.side_effect_tools)
            if overlap:
                overlap_text = ", ".join(sorted(overlap))
                raise ValueError(
                    f"tool names cannot appear in both read_only_tools and side_effect_tools: {overlap_text}"
                )

        if self.read_only_tools or self.side_effect_tools:
            allowlist = set(self.allow_tools)
            out_of_scope = {
                *[name for name in self.read_only_tools if name not in allowlist],
                *[name for name in self.side_effect_tools if name not in allowlist],
            }
            if out_of_scope:
                out_of_scope_text = ", ".join(sorted(out_of_scope))
                raise ValueError(
                    f"policy tools must also exist in allow_tools allowlist: {out_of_scope_text}"
                )
        return self


class ConnectorOAuthClientSettings(BaseModel):
    provider_key: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9][a-z0-9_-]*$",
    )
    client_id: str = Field(min_length=1, max_length=255)
    client_secret: SecretStr
    redirect_uri: AnyHttpUrl | None = None

    @field_validator("provider_key")
    @classmethod
    def validate_provider_key(cls, value: str) -> str:
        return value.strip().lower()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILES,
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        case_sensitive=False,
        extra="ignore",
        validate_by_name=True,
    )

    environment: Environment = Environment.development
    log_level: str = Field(default="INFO", pattern=r"^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$")
    log_format: LogFormat = LogFormat.auto

    api_name: str = Field(default="AI Document Q&A Assistant API", min_length=3, max_length=120)
    api_version: str = Field(default="0.1.0", min_length=1, max_length=32)
    api_prefix: str = Field(default="/api/v1", pattern=r"^/[a-zA-Z0-9/_-]*$")
    api_base_url: AnyHttpUrl
    frontend_base_url: AnyHttpUrl
    cors_origins: Annotated[list[AnyHttpUrl], NoDecode] = Field(default_factory=list)

    database_url: PostgresDsn
    database_echo: bool = False

    qdrant_url: AnyHttpUrl
    qdrant_api_key: SecretStr | None = None
    qdrant_collection: str = Field(min_length=2, max_length=128)
    qdrant_vector_size: int = Field(default=1536, ge=8, le=8192)
    qdrant_distance: QdrantDistance = QdrantDistance.cosine
    qdrant_timeout_seconds: float = Field(default=2.0, ge=0.1, le=60.0)
    qdrant_bootstrap_collection: bool = True

    minio_endpoint: AnyHttpUrl
    minio_access_key: str = Field(min_length=3, max_length=128)
    minio_secret_key: SecretStr
    minio_bucket: str = Field(min_length=3, max_length=63)
    minio_bootstrap_bucket: bool = True

    rabbitmq_url: AmqpDsn
    rabbitmq_connect_timeout_seconds: float = Field(default=2.0, ge=0.1, le=30.0)
    celery_result_backend_enabled: bool = True
    celery_task_default_queue: str = Field(default="default", min_length=1, max_length=64)
    celery_queue_documents_processing: str = Field(
        default="documents.processing", min_length=1, max_length=64
    )
    celery_queue_documents_deletion: str = Field(
        default="documents.deletion", min_length=1, max_length=64
    )
    celery_queue_documents_reindex: str = Field(
        default="documents.reindex", min_length=1, max_length=64
    )
    celery_queue_evaluations: str = Field(default="evaluations", min_length=1, max_length=64)
    celery_queue_connector_sync: str = Field(default="connectors.sync", min_length=1, max_length=64)
    connector_sync_schedule_poll_interval_seconds: int = Field(default=60, ge=10, le=3600)
    celery_task_max_retries: int = Field(default=5, ge=0, le=20)
    celery_retry_backoff_seconds: int = Field(default=2, ge=1, le=300)
    celery_retry_backoff_max_seconds: int = Field(default=60, ge=1, le=3600)
    celery_retry_jitter: bool = True
    celery_worker_prefetch_multiplier: int = Field(default=1, ge=1, le=20)
    redis_url: RedisDsn
    redis_socket_connect_timeout_seconds: float = Field(default=2.0, ge=0.1, le=30.0)
    redis_socket_timeout_seconds: float = Field(default=2.0, ge=0.1, le=30.0)
    rate_limit_enabled: bool = True
    rate_limit_disable_in_development: bool = True
    rate_limit_disable_in_test: bool = True
    rate_limit_redis_failure_mode: RateLimitRedisFailureMode = RateLimitRedisFailureMode.open
    rate_limit_window_seconds: int = Field(default=60, ge=1, le=3600)
    rate_limit_upload_requests: int = Field(default=20, ge=1, le=10000)
    rate_limit_chat_requests: int = Field(default=30, ge=1, le=10000)
    rate_limit_evaluation_requests: int = Field(default=10, ge=1, le=10000)
    rate_limit_delete_requests: int = Field(default=20, ge=1, le=10000)
    rate_limit_admin_requests: int = Field(default=15, ge=1, le=10000)
    rate_limit_connector_requests: int = Field(default=15, ge=1, le=10000)
    rate_limit_bot_requests: int = Field(default=30, ge=1, le=10000)
    rate_limit_auth_login_requests: int = Field(default=10, ge=1, le=10000)
    rate_limit_auth_refresh_requests: int = Field(default=60, ge=1, le=10000)
    rate_limit_auth_logout_requests: int = Field(default=30, ge=1, le=10000)
    rate_limit_auth_password_requests: int = Field(default=10, ge=1, le=10000)
    evaluation_prevent_duplicate_active_runs: bool = True

    dependency_connect_timeout_seconds: float = Field(default=1.0, ge=0.1, le=30.0)
    dependency_read_timeout_seconds: float = Field(default=1.0, ge=0.1, le=120.0)
    dependency_max_retries: int = Field(default=0, ge=0, le=10)

    # Provider routing — new settings with backwards-compatible OpenAI defaults
    llm_default_provider: str = Field(default="openai", min_length=1, max_length=64)
    embedding_default_provider: str = Field(default="openai", min_length=1, max_length=64)

    openai_api_key: SecretStr | None = None
    openai_embedding_model: str = Field(
        default="text-embedding-3-small", min_length=3, max_length=128
    )
    openai_llm_model: str = Field(default="gpt-5.4-mini", min_length=3, max_length=128)
    llm_retry_max_attempts: int = Field(default=2, ge=1, le=10)
    llm_retry_base_seconds: float = Field(default=0.4, ge=0.1, le=30.0)
    llm_retry_max_seconds: float = Field(default=3.0, ge=0.1, le=120.0)
    openai_llm_input_cost_per_million_tokens_usd: float = Field(default=0.0, ge=0.0, le=1000.0)
    openai_llm_output_cost_per_million_tokens_usd: float = Field(default=0.0, ge=0.0, le=1000.0)

    # Local LLM (OpenAI-compatible) provider settings — F218
    # Active when LLM_DEFAULT_PROVIDER=local. Supports Ollama, vLLM, LiteLLM, and any
    # server that implements the OpenAI chat completions API. See .env.local-llm.example
    # and docs/19_LOCAL_LLM_PROVIDER_INTEGRATION.md for setup and security requirements.
    # WARNING: local_llm_api_key is sensitive — never log or return it in API responses.
    local_llm_base_url: AnyHttpUrl | None = None
    local_llm_api_key: SecretStr | None = None
    local_llm_model: str = Field(default="", min_length=0, max_length=128)
    # One of: ollama, vllm, litellm, generic — used for diagnostics and logging only.
    local_llm_provider_kind: str = Field(default="generic", min_length=1, max_length=64)
    local_llm_timeout_seconds: float = Field(default=30.0, ge=1.0, le=300.0)
    # Set False for providers that do not support response_format=json_object (e.g. Ollama).
    local_llm_json_mode_enabled: bool = True

    # Local embedding (OpenAI-compatible /v1/embeddings) provider settings — F219
    # Active when EMBEDDING_DEFAULT_PROVIDER=local. Changing the embedding model after
    # documents are indexed requires a full reindex — existing Qdrant vectors become
    # incompatible. See the "Embedding dimension mismatch" runbook in
    # docs/19_LOCAL_LLM_PROVIDER_INTEGRATION.md before changing local_embedding_model.
    local_embedding_base_url: AnyHttpUrl | None = None
    local_embedding_api_key: SecretStr | None = None
    local_embedding_model: str = Field(default="", min_length=0, max_length=128)
    local_embedding_timeout_seconds: float = Field(default=30.0, ge=1.0, le=300.0)

    auth_provider: AuthProvider = AuthProvider.app
    app_auth_secret: SecretStr = SecretStr("dev-insecure-change-me")
    app_auth_access_token_ttl_seconds: int = Field(default=3600, ge=60, le=604800)
    app_auth_refresh_token_ttl_seconds: int = Field(default=1209600, ge=300, le=7776000)
    app_auth_issuer: str = Field(default="rudix-app", min_length=3, max_length=120)
    app_auth_audience: str = Field(default="rudix-api", min_length=3, max_length=120)
    app_auth_clock_skew_seconds: int = Field(default=30, ge=0, le=300)
    app_auth_cookie_domain: str | None = Field(default=None, max_length=255)
    app_auth_cookie_secure: bool | None = None
    app_auth_cookie_same_site: str = Field(default="lax", min_length=3, max_length=16)
    app_auth_cookie_path: str = Field(default="/api/v1/auth", min_length=1, max_length=255)
    app_auth_login_password: SecretStr | None = None
    app_auth_auto_provision_users: bool = True
    app_auth_password_hash_memory_cost_kib: int = Field(default=65536, ge=8192, le=1048576)
    app_auth_password_hash_time_cost: int = Field(default=3, ge=1, le=10)
    app_auth_password_hash_parallelism: int = Field(default=1, ge=1, le=8)
    app_auth_password_hash_length: int = Field(default=32, ge=16, le=128)
    app_auth_password_salt_length: int = Field(default=16, ge=8, le=64)
    auth_jwks_cache_ttl_seconds: int = Field(default=300, ge=30, le=86400)
    clerk_jwks_url: AnyHttpUrl | None = None
    clerk_jwt_issuer: AnyHttpUrl | None = None
    clerk_jwt_audience: str | None = Field(default=None, min_length=1, max_length=255)
    supabase_jwks_url: AnyHttpUrl | None = None
    supabase_jwt_issuer: AnyHttpUrl | None = None
    supabase_jwt_audience: str | None = Field(default=None, min_length=1, max_length=255)

    sentry_dsn: AnyUrl | None = None
    sentry_release: str | None = Field(default=None, max_length=128)
    sentry_error_sample_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    sentry_traces_sample_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    sentry_profiles_sample_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    sentry_test_event_enabled: bool | None = None

    # Transactional email (F251)
    email_enabled: bool = False
    email_provider: str = Field(default="console", pattern=r"^(console|smtp|resend|postmark)$")
    email_from_address: str = Field(default="noreply@example.com", min_length=5, max_length=255)
    email_from_name: str = Field(default="Rudix", min_length=1, max_length=120)
    email_reply_to: str | None = Field(default=None, max_length=255)
    email_max_retries: int = Field(default=3, ge=0, le=10)
    smtp_host: str = Field(default="localhost", min_length=1, max_length=255)
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str | None = Field(default=None, max_length=255)
    smtp_password: SecretStr | None = None
    smtp_use_tls: bool = True
    smtp_timeout_seconds: float = Field(default=10.0, ge=1.0, le=60.0)
    resend_api_key: SecretStr | None = None
    postmark_server_token: SecretStr | None = None

    # Langfuse observability (optional, F271)
    langfuse_enabled: bool = False
    langfuse_base_url: AnyHttpUrl | None = None
    langfuse_public_key: str | None = Field(default=None, max_length=256)
    langfuse_secret_key: SecretStr | None = None
    langfuse_sample_rate: float = Field(default=1.0, ge=0.0, le=1.0)
    langfuse_capture_input_output: bool = True
    langfuse_redaction_mode: LangfuseRedactionMode = LangfuseRedactionMode.none

    max_upload_size_mb: int = Field(default=25, ge=1, le=512)
    malware_scan_enabled: bool = True
    malware_scan_required: bool = False
    malware_scan_bypass_on_unavailable: bool = False
    malware_scan_clamav_host: str = Field(default="localhost", min_length=1, max_length=255)
    malware_scan_clamav_port: int = Field(default=3310, ge=1, le=65535)
    malware_scan_timeout_seconds: float = Field(default=10.0, ge=0.1, le=120.0)
    malware_scan_max_bytes: int | None = Field(default=None, ge=1, le=536_870_912)
    malware_scan_stream_chunk_size_bytes: int = Field(default=65_536, ge=1024, le=4_194_304)
    duplicate_detection_enabled: bool = True
    duplicate_detection_action: str = Field(
        default="warn",
        pattern=r"^(allow|warn|reject)$",
    )
    dlp_enabled: bool = True
    dlp_action: str = Field(
        default="warn",
        pattern=r"^(allow|warn|quarantine|reject)$",
    )
    dlp_min_findings: int = Field(default=3, ge=1, le=1000)
    ocr_enabled: bool = True
    ocr_default_languages: str = Field(default="eng", min_length=1, max_length=255)
    ocr_allowed_languages: str = Field(
        default="eng,ara,fas,spa,fra,deu,ita,por,rus,chi_sim,chi_tra,jpn,kor",
        min_length=3,
        max_length=512,
    )
    ocr_max_pages: int = Field(default=100, ge=1, le=1000)
    ocr_page_timeout_seconds: int = Field(default=60, ge=5, le=300)
    ocr_min_text_chars_per_page: int = Field(default=30, ge=1, le=1000)
    ocr_min_text_chars_document: int = Field(default=300, ge=1, le=10000)
    ocr_image_dpi: int = Field(default=300, ge=72, le=600)
    retrieval_initial_top_k: int = Field(default=20, ge=1, le=200)
    retrieval_final_top_k: int = Field(default=5, ge=1, le=50)
    rerank_default_provider: str = Field(default="openai", min_length=1, max_length=64)
    rerank_default_model_name: str | None = Field(default=None, max_length=255)
    rerank_default_timeout_seconds: float = Field(default=6.0, ge=0.1, le=120.0)
    rerank_default_batch_size: int = Field(default=8, ge=1, le=200)
    rerank_default_input_candidates: int = Field(default=20, ge=1, le=200)
    rerank_default_candidate_chars: int = Field(default=2000, ge=128, le=20_000)
    rerank_default_fallback_behavior: RerankFallbackBehavior = RerankFallbackBehavior.original
    rerank_input_cost_per_million_tokens_usd: float = Field(default=0.0, ge=0.0, le=1000.0)
    rerank_output_cost_per_million_tokens_usd: float = Field(default=0.0, ge=0.0, le=1000.0)
    rerank_mmr_lambda: float = Field(default=0.7, ge=0.0, le=1.0)
    rerank_mmr_candidate_count: int = Field(default=20, ge=1, le=200)
    rerank_mmr_duplicate_similarity_threshold: float = Field(default=0.92, ge=0.0, le=1.0)
    confidence_weight_top_similarity: float = Field(default=0.35, ge=0.0, le=1.0)
    confidence_weight_average_similarity: float = Field(default=0.20, ge=0.0, le=1.0)
    confidence_weight_rerank_score: float = Field(default=0.20, ge=0.0, le=1.0)
    confidence_weight_citation_support: float = Field(default=0.15, ge=0.0, le=1.0)
    confidence_weight_agreement: float = Field(default=0.10, ge=0.0, le=1.0)
    confidence_medium_threshold: float = Field(default=0.50, ge=0.0, le=1.0)
    confidence_high_threshold: float = Field(default=0.80, ge=0.0, le=1.0)
    confidence_not_found_threshold: float = Field(default=0.20, ge=0.0, le=1.0)
    confidence_not_found_penalty_multiplier: float = Field(default=0.35, ge=0.0, le=1.0)
    confidence_citation_coverage_target: int = Field(default=2, ge=1, le=20)
    chunk_size_tokens: int = Field(default=700, ge=100, le=4000)
    chunk_overlap_tokens: int = Field(default=120, ge=0, le=2000)
    chunking_strategy: str = Field(default="token_recursive", min_length=1, max_length=64)
    document_index_version: str = Field(default="v1", min_length=1, max_length=64)
    embedding_batch_max_items: int = Field(default=96, ge=1, le=2048)
    embedding_batch_max_tokens: int = Field(default=100000, ge=100, le=300000)
    embedding_retry_max_attempts: int = Field(default=3, ge=1, le=10)
    embedding_retry_base_seconds: float = Field(default=0.5, ge=0.1, le=30.0)
    embedding_retry_max_seconds: float = Field(default=8.0, ge=0.1, le=120.0)
    openai_embedding_cost_per_million_tokens_usd: float = Field(default=0.02, ge=0.0, le=1000.0)
    request_timeout_seconds: int = Field(default=30, ge=1, le=300)
    agent_max_steps: int = Field(default=12, ge=1, le=200)
    agent_max_parallel_tool_calls: int = Field(default=4, ge=1, le=50)
    agent_tool_max_calls_per_run: int = Field(default=30, ge=1, le=500)
    agent_tool_timeout_ms: int = Field(default=8000, ge=100, le=300000)
    agent_tool_max_input_bytes: int = Field(default=32768, ge=512, le=10000000)
    agent_tool_max_output_bytes: int = Field(default=65536, ge=512, le=10000000)
    agent_tool_max_retry_attempts: int = Field(default=1, ge=0, le=10)
    agent_prompt_injection_guard_enabled: bool = True
    agent_document_instruction_guard_enabled: bool = True
    connector_credential_encryption_key: SecretStr | None = None
    connector_credential_encryption_key_id: str = Field(
        default="default",
        min_length=1,
        max_length=128,
        pattern=r"^[a-zA-Z0-9._:-]+$",
    )
    connector_oauth_state_ttl_seconds: int = Field(default=600, ge=60, le=3600)
    connector_oauth_clients: Annotated[list[ConnectorOAuthClientSettings], NoDecode] = Field(
        default_factory=list
    )
    feature_enable_connectors: bool = True
    connector_rollout_stage: ConnectorRolloutStage = ConnectorRolloutStage.all

    feature_enable_embeddings: bool = True
    feature_enable_llm: bool = True
    feature_enable_evaluations: bool = True
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
    feature_enable_chunking_profiles: bool = False
    feature_enable_adaptive_chunking: bool = False
    feature_enable_hybrid_retrieval: bool = False
    # Weight given to vector (semantic) scores when merging. keyword weight = 1 - vector_weight.
    hybrid_retrieval_vector_weight: float = Field(default=0.7, ge=0.0, le=1.0)
    # Constant k used in Reciprocal Rank Fusion: score = 1 / (k + rank).
    hybrid_retrieval_rrf_k: int = Field(default=60, ge=1, le=1000)
    # Multiplier applied to a chunk's RRF score when an exact-match token is found.
    hybrid_retrieval_exact_match_boost: float = Field(default=1.5, ge=1.0, le=10.0)
    # Query rewriting and decomposition (F295).
    # When enabled the LLM rewrites vague questions and decomposes multi-part questions
    # into focused sub-queries for parallel retrieval.
    # WARNING: each LLM rewriting call adds latency and token cost before retrieval.
    # Keep query_rewriting_timeout_seconds well below the overall request timeout.
    feature_enable_query_rewriting: bool = False
    query_rewriting_timeout_seconds: float = Field(default=5.0, ge=0.5, le=30.0)
    query_rewriting_max_sub_queries: int = Field(default=4, ge=1, le=8)
    # Grounded-answer verifier (F296): checks that generated answers are supported
    # by retrieved source chunks. Unsupported claims are removed (standard mode)
    # or the answer is refused (strict mode). Adds one LLM call after generation.
    # Keep grounded_verification_timeout_seconds well below the overall request timeout.
    feature_enable_grounded_answer_verification: bool = False
    grounded_verification_timeout_seconds: float = Field(default=12.0, ge=0.5, le=60.0)
    feature_enable_graph_rag: bool = False
    # graph_extraction gates the entity/relation extraction pipeline per org.
    # graph_explorer gates the read-only graph explorer UI per org.
    feature_enable_graph_extraction: bool = False
    feature_enable_graph_explorer: bool = True
    feature_enable_mcp: bool = False
    feature_enable_external_mcp_connectors: bool = False
    feature_expose_config_snapshot: bool = True
    feature_enable_language_aware_rag: bool = True
    # WebSocket chat transport (F277).
    feature_chat_websocket_enabled: bool = True
    # Slack / Microsoft Teams bot transport (F261).
    feature_enable_collaboration_bots: bool = True
    bot_slack_signing_secret: SecretStr | None = None
    bot_slack_client_id: str | None = Field(default=None, min_length=1, max_length=255)
    bot_slack_client_secret: SecretStr | None = None
    bot_slack_oauth_redirect_uri: AnyHttpUrl | None = None
    bot_slack_oauth_scopes: str = Field(
        default="app_mentions:read,chat:write,commands,users:read,users:read.email",
        min_length=1,
        max_length=512,
    )
    bot_teams_shared_secret: SecretStr | None = None
    bot_process_events_async: bool = True
    bot_delivery_timeout_seconds: float = Field(default=5.0, ge=0.1, le=30.0)

    # Enterprise Graph (Neo4j) — F279
    # Set ENTERPRISE_GRAPH_ENABLED=true and configure the bolt URI + credentials to activate.
    # When disabled, all upload/chat/RAG flows operate normally without Neo4j.
    # WARNING: neo4j_password is sensitive — never log or return it in API responses.
    enterprise_graph_enabled: bool = False
    neo4j_uri: str | None = Field(default=None, max_length=255)
    neo4j_username: str | None = Field(default=None, max_length=128)
    neo4j_password: SecretStr | None = None
    neo4j_database: str = Field(default="neo4j", min_length=1, max_length=128)
    neo4j_connection_timeout_seconds: float = Field(default=5.0, ge=0.1, le=60.0)
    neo4j_query_timeout_seconds: float = Field(default=10.0, ge=0.1, le=120.0)
    neo4j_max_connection_pool_size: int = Field(default=50, ge=1, le=500)
    # Entity extraction pipeline (F283): LLM-based entity extraction from document chunks.
    # Requires enterprise_graph_enabled=true. Set FEATURE_ENABLE_ENTITY_EXTRACTION=true to activate.
    # strict_mode=true aborts the document pipeline on extraction failure (default: continue).
    feature_enable_entity_extraction: bool = False
    entity_extraction_batch_size: int = Field(default=10, ge=1, le=50)
    entity_extraction_strict_mode: bool = False
    entity_extraction_timeout_seconds: float = Field(default=60.0, ge=5.0, le=300.0)
    entity_extraction_max_retries: int = Field(default=2, ge=0, le=5)
    # Entity resolution and canonicalization (F285): merges aliases and source
    # mentions into canonical records when the confidence threshold is met.
    # Requires enterprise_graph_enabled=true. Remains off by default.
    feature_enable_entity_resolution: bool = False
    entity_resolution_auto_merge_threshold: float = Field(default=0.88, ge=0.0, le=1.0)
    entity_resolution_review_threshold: float = Field(default=0.65, ge=0.0, le=1.0)
    # Relation extraction pipeline (F284): LLM-based relation extraction, runs after entity
    # extraction. Requires enterprise_graph_enabled=true and feature_enable_entity_extraction=true.
    # confidence_threshold: relations below this value receive status=low_confidence.
    # review_mode: when true, all relations start as unverified regardless of confidence.
    # strict_mode: when true, pipeline fails on extraction error (default: continue).
    feature_enable_relation_extraction: bool = False
    relation_extraction_batch_size: int = Field(default=10, ge=1, le=50)
    relation_extraction_strict_mode: bool = False
    relation_extraction_timeout_seconds: float = Field(default=60.0, ge=5.0, le=300.0)
    relation_extraction_max_retries: int = Field(default=2, ge=0, le=5)
    relation_confidence_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    relation_extraction_review_mode: bool = False
    graph_rag_max_hops: int = Field(default=2, ge=1, le=5)
    graph_rag_max_related_entities: int = Field(default=8, ge=1, le=50)
    graph_rag_max_chunks: int = Field(default=5, ge=1, le=50)
    graph_rag_confidence_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    graph_rag_relation_type_allowlist: list[str] = Field(
        default_factory=lambda: [
            "RELATES_TO",
            "OWNS",
            "COVERS_CONTROL",
            "CONTAINS_OBLIGATION",
            "PROVIDES_SERVICE_TO",
            "SUPERSEDES",
            "AFFECTS",
            "DEPENDS_ON",
        ]
    )
    # Graph observability alert thresholds (F291).
    # Admins can override these via environment variables to tune alerting sensitivity.
    # extraction_failure_rate_max: fraction of extraction runs that must fail to trigger an alert.
    # query_failure_rate_max: fraction of GraphRAG queries that must fail to trigger an alert.
    # graphrag_fallback_rate_max: fraction of GraphRAG queries that fall back to standard RAG.
    # low_confidence_entity_rate_max: fraction of entities with confidence < 0.5.
    # query_latency_ms_max: p95 GraphRAG latency ceiling in milliseconds.
    graph_alert_extraction_failure_rate_max: float = Field(default=0.2, ge=0.0, le=1.0)
    graph_alert_query_failure_rate_max: float = Field(default=0.1, ge=0.0, le=1.0)
    graph_alert_graphrag_fallback_rate_max: float = Field(default=0.3, ge=0.0, le=1.0)
    graph_alert_low_confidence_entity_rate_max: float = Field(default=0.3, ge=0.0, le=1.0)
    graph_alert_query_latency_ms_max: float = Field(default=2000.0, ge=0.0)

    @field_validator("graph_rag_relation_type_allowlist", mode="before")
    @classmethod
    def validate_graph_rag_relation_types(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            raw_items = [item.strip() for item in value.split(",")]
        elif isinstance(value, list):
            raw_items = [str(item).strip() for item in value]
        else:
            raise ValueError(
                "graph_rag_relation_type_allowlist must be a comma-separated string or list"
            )

        normalized: list[str] = []
        for relation_type in raw_items:
            if not relation_type:
                continue
            upper = relation_type.upper()
            if upper not in normalized:
                normalized.append(upper)
        if not normalized:
            raise ValueError("graph_rag_relation_type_allowlist must contain at least one value")
        return normalized

    ws_chat_max_connections_per_user: int = Field(default=3, ge=1, le=20)
    ws_chat_idle_timeout_seconds: int = Field(default=300, ge=30, le=3600)
    ws_chat_heartbeat_interval_seconds: int = Field(default=30, ge=10, le=120)
    # Table-aware retrieval (F298): boost table chunks when the query looks tabular.
    # feature_enable_table_aware_retrieval gates the entire feature.
    # table_retrieval_boost_multiplier: score multiplier applied to table chunks on table-like queries.
    feature_enable_table_aware_retrieval: bool = True
    table_retrieval_boost_multiplier: float = Field(default=1.25, ge=1.0, le=5.0)
    # OCR quality downranking (F299): penalise retrieval scores for low-confidence OCR chunks.
    feature_enable_ocr_quality_downranking: bool = True
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
    mcp_server_name: str = Field(default="Rudix MCP Server", min_length=3, max_length=120)
    mcp_transport: MCPTransport = MCPTransport.streamable_http
    mcp_http_host: str = Field(default="0.0.0.0", min_length=1, max_length=255)
    mcp_http_port: int = Field(default=8010, ge=1, le=65535)
    mcp_http_path: str = Field(default="/mcp", pattern=r"^/[a-zA-Z0-9/_-]*$")
    mcp_require_bearer_auth: bool = True
    mcp_dev_principal_user_id: str | None = Field(default=None, min_length=3, max_length=128)
    mcp_dev_principal_organization_id: str | None = Field(
        default=None, min_length=3, max_length=128
    )
    mcp_dev_principal_roles: Annotated[list[str], NoDecode] = Field(default_factory=list)
    mcp_capabilities_owner: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: list(_DEFAULT_MCP_ELEVATED_CAPABILITIES)
    )
    mcp_capabilities_admin: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: list(_DEFAULT_MCP_ELEVATED_CAPABILITIES)
    )
    mcp_capabilities_member: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: list(_DEFAULT_MCP_ELEVATED_CAPABILITIES)
    )
    mcp_capabilities_viewer: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: list(_DEFAULT_MCP_VIEWER_CAPABILITIES)
    )
    mcp_rate_limit_enabled: bool = True
    mcp_rate_limit_window_seconds: int = Field(default=60, ge=1, le=3600)
    mcp_rate_limit_requests: int = Field(default=30, ge=1, le=10000)
    mcp_external_servers: Annotated[list[MCPExternalServerSettings], NoDecode] = Field(
        default_factory=list
    )

    @field_validator("neo4j_uri")
    @classmethod
    def validate_neo4j_uri(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        allowed = ("bolt://", "neo4j://", "bolt+s://", "neo4j+s://", "bolt+ssc://", "neo4j+ssc://")
        if not any(cleaned.lower().startswith(scheme) for scheme in allowed):
            raise ValueError(
                "neo4j_uri must start with bolt://, neo4j://, bolt+s://, or neo4j+s://"
            )
        return cleaned

    @field_validator("cors_origins", mode="before")
    @classmethod
    def validate_cors_origins(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            parsed = [item.strip() for item in value.split(",") if item.strip()]
            return parsed
        if isinstance(value, list):
            parsed = [str(item).strip() for item in value if str(item).strip()]
            return parsed
        raise ValueError("cors_origins must be a comma-separated string or list of URLs")

    @field_validator("qdrant_collection")
    @classmethod
    def validate_qdrant_collection(cls, value: str) -> str:
        if not value.replace("_", "").replace("-", "").isalnum():
            raise ValueError(
                "qdrant_collection must contain only letters, numbers, underscores, or hyphens"
            )
        return value

    @field_validator("minio_bucket")
    @classmethod
    def validate_minio_bucket(cls, value: str) -> str:
        lowered = value.lower()
        if value != lowered:
            raise ValueError("minio_bucket must be lowercase")
        if ".." in lowered or ".-" in lowered or "-." in lowered:
            raise ValueError("minio_bucket has invalid separator sequence")
        if not lowered.replace("-", "").replace(".", "").isalnum():
            raise ValueError("minio_bucket contains invalid characters")
        return lowered

    @field_validator("openai_embedding_model", "openai_llm_model")
    @classmethod
    def validate_model_names(cls, value: str) -> str:
        cleaned = value.strip()
        if " " in cleaned:
            raise ValueError("model names must not contain whitespace")
        return cleaned

    @field_validator("document_index_version")
    @classmethod
    def validate_document_index_version(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("document_index_version must not be empty")
        if not cleaned.replace(".", "").replace("-", "").replace("_", "").isalnum():
            raise ValueError(
                "document_index_version may contain only letters, numbers, '.', '-', and '_'"
            )
        return cleaned

    @field_validator("sentry_release")
    @classmethod
    def validate_sentry_release(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        return cleaned

    @field_validator("mcp_dev_principal_roles", mode="before")
    @classmethod
    def validate_mcp_dev_principal_roles(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            raw_items = [item.strip() for item in value.split(",")]
        elif isinstance(value, list):
            raw_items = [str(item).strip() for item in value]
        else:
            raise ValueError("mcp_dev_principal_roles must be a comma-separated string or list")

        normalized_roles: list[str] = []
        for role in raw_items:
            if not role:
                continue
            normalized = role.lower()
            if normalized not in _ALLOWED_ORG_ROLES:
                raise ValueError(f"unsupported mcp_dev_principal_role: {role}")
            if normalized not in normalized_roles:
                normalized_roles.append(normalized)
        return normalized_roles

    @field_validator(
        "mcp_capabilities_owner",
        "mcp_capabilities_admin",
        "mcp_capabilities_member",
        "mcp_capabilities_viewer",
        mode="before",
    )
    @classmethod
    def validate_mcp_capability_list(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            raw_items = [item.strip() for item in value.split(",")]
        elif isinstance(value, list):
            raw_items = [str(item).strip() for item in value]
        else:
            raise ValueError("MCP capabilities must be a comma-separated string or list")

        normalized_capabilities: list[str] = []
        for capability in raw_items:
            if not capability:
                continue
            normalized = capability.lower()
            if not normalized.replace(".", "").replace("_", "").replace("-", "").isalnum():
                raise ValueError(f"invalid MCP capability identifier: {capability}")
            if normalized not in normalized_capabilities:
                normalized_capabilities.append(normalized)

        if not normalized_capabilities:
            raise ValueError("MCP capability list must contain at least one capability")
        return normalized_capabilities

    @field_validator("mcp_external_servers", mode="before")
    @classmethod
    def validate_external_mcp_servers(
        cls, value: object
    ) -> list[MCPExternalServerSettings] | list[dict[str, Any]]:
        if value is None:
            return []
        raw_items: list[object]
        if isinstance(value, str):
            normalized_text = value.strip()
            if not normalized_text:
                return []
            try:
                parsed = json.loads(normalized_text)
            except json.JSONDecodeError as exc:
                raise ValueError("mcp_external_servers must be valid JSON") from exc
            if not isinstance(parsed, list):
                raise ValueError("mcp_external_servers JSON value must be an array")
            raw_items = list(parsed)
        elif isinstance(value, list):
            raw_items = list(value)
        else:
            raise ValueError("mcp_external_servers must be a JSON array or list")

        normalized_items: list[MCPExternalServerSettings] = []
        seen_ids: set[str] = set()
        for item in raw_items:
            server_config = MCPExternalServerSettings.model_validate(item)
            if server_config.server_id in seen_ids:
                raise ValueError(f"duplicate external MCP server_id: {server_config.server_id}")
            seen_ids.add(server_config.server_id)
            normalized_items.append(server_config)
        return normalized_items

    @field_validator("connector_oauth_clients", mode="before")
    @classmethod
    def validate_connector_oauth_clients(
        cls, value: object
    ) -> list[ConnectorOAuthClientSettings] | list[dict[str, Any]]:
        if value is None:
            return []
        raw_items: list[object]
        if isinstance(value, str):
            normalized_text = value.strip()
            if not normalized_text:
                return []
            try:
                parsed = json.loads(normalized_text)
            except json.JSONDecodeError as exc:
                raise ValueError("connector_oauth_clients must be valid JSON") from exc
            if not isinstance(parsed, list):
                raise ValueError("connector_oauth_clients JSON value must be an array")
            raw_items = list(parsed)
        elif isinstance(value, list):
            raw_items = list(value)
        else:
            raise ValueError("connector_oauth_clients must be a JSON array or list")

        normalized_items: list[ConnectorOAuthClientSettings] = []
        seen_providers: set[str] = set()
        for item in raw_items:
            client_config = ConnectorOAuthClientSettings.model_validate(item)
            if client_config.provider_key in seen_providers:
                raise ValueError(
                    f"duplicate connector OAuth provider_key: {client_config.provider_key}"
                )
            seen_providers.add(client_config.provider_key)
            normalized_items.append(client_config)
        return normalized_items

    @field_validator(
        "celery_task_default_queue",
        "celery_queue_documents_processing",
        "celery_queue_documents_deletion",
        "celery_queue_documents_reindex",
        "celery_queue_evaluations",
        "celery_queue_connector_sync",
    )
    @classmethod
    def validate_celery_queue_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("celery queue names must not be empty")
        if not cleaned.replace(".", "").replace("-", "").replace("_", "").isalnum():
            raise ValueError(
                "celery queue names may contain only letters, numbers, '.', '-', and '_'"
            )
        return cleaned

    @model_validator(mode="after")
    def validate_consistency(self) -> "Settings":
        if not self.cors_origins:
            self.cors_origins = [self.frontend_base_url]

        if self.feature_enable_agents is None:
            self.feature_enable_agents = self.environment in {
                Environment.development,
                Environment.test,
            }

        if self.feature_enable_mcp and self.mcp_transport == MCPTransport.stdio:
            if self.environment in {Environment.production, Environment.staging}:
                raise ValueError(
                    "mcp_transport=stdio is only allowed in development or test environments"
                )
            if self.mcp_dev_principal_user_id is None:
                raise ValueError("mcp_dev_principal_user_id is required when mcp_transport=stdio")
            if self.mcp_dev_principal_organization_id is None:
                raise ValueError(
                    "mcp_dev_principal_organization_id is required when mcp_transport=stdio"
                )
            if not self.mcp_dev_principal_roles:
                raise ValueError("mcp_dev_principal_roles is required when mcp_transport=stdio")

        if self.feature_enable_mcp and self.mcp_transport == MCPTransport.streamable_http:
            self.mcp_http_host = self.mcp_http_host.strip()
            if not self.mcp_http_host:
                raise ValueError(
                    "mcp_http_host must not be empty when mcp transport is streamable_http"
                )
            if not self.mcp_require_bearer_auth and self.environment in {
                Environment.production,
                Environment.staging,
            }:
                raise ValueError(
                    "mcp_require_bearer_auth=false is only allowed in development or test environments"
                )
            if not self.mcp_require_bearer_auth:
                if self.mcp_dev_principal_user_id is None:
                    raise ValueError(
                        "mcp_dev_principal_user_id is required when mcp_require_bearer_auth=false"
                    )
                if self.mcp_dev_principal_organization_id is None:
                    raise ValueError(
                        "mcp_dev_principal_organization_id is required when mcp_require_bearer_auth=false"
                    )
                if not self.mcp_dev_principal_roles:
                    raise ValueError(
                        "mcp_dev_principal_roles is required when mcp_require_bearer_auth=false"
                    )

        if self.feature_enable_external_mcp_connectors:
            enabled_servers = [server for server in self.mcp_external_servers if server.enabled]
            if not enabled_servers:
                raise ValueError(
                    "feature_enable_external_mcp_connectors=true requires at least one enabled mcp_external_servers entry"
                )
            if self.environment in {Environment.production, Environment.staging}:
                for server in enabled_servers:
                    if server.auth_type == MCPExternalAuthType.none:
                        raise ValueError(
                            "external MCP servers require auth_type=bearer or auth_type=header in staging/production"
                        )

        if self.enterprise_graph_enabled:
            if not self.neo4j_uri:
                raise ValueError("neo4j_uri is required when enterprise_graph_enabled=true")
            if not self.neo4j_username:
                raise ValueError("neo4j_username is required when enterprise_graph_enabled=true")
            if self.neo4j_password is None or not self.neo4j_password.get_secret_value().strip():
                raise ValueError("neo4j_password is required when enterprise_graph_enabled=true")

        if self.connector_rollout_stage == ConnectorRolloutStage.off:
            self.feature_enable_connectors = False

        self.graph_rag_relation_type_allowlist = [
            relation_type.strip().upper()
            for relation_type in self.graph_rag_relation_type_allowlist
            if relation_type.strip()
        ]
        if not self.graph_rag_relation_type_allowlist:
            raise ValueError("graph_rag_relation_type_allowlist must contain at least one value")

        if self.retrieval_final_top_k > self.retrieval_initial_top_k:
            raise ValueError(
                "retrieval_final_top_k must be less than or equal to retrieval_initial_top_k"
            )

        if self.rerank_mmr_candidate_count < self.retrieval_final_top_k:
            raise ValueError("rerank_mmr_candidate_count must be >= retrieval_final_top_k")

        if self.rerank_default_input_candidates < self.retrieval_final_top_k:
            raise ValueError(
                "rerank_default_input_candidates must be >= retrieval_final_top_k"
            )
        if self.rerank_default_batch_size > self.rerank_default_input_candidates:
            raise ValueError(
                "rerank_default_batch_size must be <= rerank_default_input_candidates"
            )

        if self.confidence_high_threshold < self.confidence_medium_threshold:
            raise ValueError("confidence_high_threshold must be >= confidence_medium_threshold")

        if self.confidence_not_found_threshold > self.confidence_medium_threshold:
            raise ValueError(
                "confidence_not_found_threshold must be <= confidence_medium_threshold"
            )

        confidence_weight_sum = (
            self.confidence_weight_top_similarity
            + self.confidence_weight_average_similarity
            + self.confidence_weight_rerank_score
            + self.confidence_weight_citation_support
            + self.confidence_weight_agreement
        )
        if confidence_weight_sum <= 0:
            raise ValueError("confidence weights sum must be > 0")

        if self.chunk_overlap_tokens >= self.chunk_size_tokens:
            raise ValueError("chunk_overlap_tokens must be smaller than chunk_size_tokens")

        if self.embedding_retry_max_seconds < self.embedding_retry_base_seconds:
            raise ValueError("embedding_retry_max_seconds must be >= embedding_retry_base_seconds")

        if self.llm_retry_max_seconds < self.llm_retry_base_seconds:
            raise ValueError("llm_retry_max_seconds must be >= llm_retry_base_seconds")

        if self.embedding_batch_max_tokens < self.chunk_size_tokens:
            raise ValueError("embedding_batch_max_tokens must be >= chunk_size_tokens")

        normalized_same_site = self.app_auth_cookie_same_site.strip().lower()
        if normalized_same_site not in {"lax", "strict", "none"}:
            raise ValueError("app_auth_cookie_same_site must be one of: lax, strict, none")
        self.app_auth_cookie_same_site = normalized_same_site
        self.app_auth_cookie_path = self.app_auth_cookie_path.strip() or "/api/v1/auth"
        if self.app_auth_cookie_domain is not None:
            self.app_auth_cookie_domain = self.app_auth_cookie_domain.strip() or None
        if self.app_auth_cookie_secure is None:
            self.app_auth_cookie_secure = self.environment == Environment.production
        if self.app_auth_cookie_same_site == "none" and not self.app_auth_cookie_secure:
            raise ValueError(
                "app_auth_cookie_secure must be true when app_auth_cookie_same_site=none"
            )
        if self.environment == Environment.production and not self.app_auth_cookie_secure:
            raise ValueError("app_auth_cookie_secure must be true in production")

        if (
            self.malware_scan_max_bytes is not None
            and self.malware_scan_max_bytes > self.max_upload_size_mb * 1024 * 1024
        ):
            raise ValueError("malware_scan_max_bytes must be <= configured upload size limit")

        if self.malware_scan_required and not self.malware_scan_enabled:
            raise ValueError("malware_scan_enabled must be true when malware_scan_required is true")

        if (
            self.environment == Environment.production
            and self.malware_scan_required
            and self.malware_scan_bypass_on_unavailable
        ):
            raise ValueError(
                "malware_scan_bypass_on_unavailable must be false in production when scanning is required"
            )

        if self.redis_socket_timeout_seconds < self.redis_socket_connect_timeout_seconds:
            raise ValueError(
                "redis_socket_timeout_seconds must be >= redis_socket_connect_timeout_seconds"
            )

        if self.dependency_read_timeout_seconds < self.dependency_connect_timeout_seconds:
            raise ValueError(
                "dependency_read_timeout_seconds must be >= dependency_connect_timeout_seconds"
            )

        if (
            self.auth_provider == AuthProvider.app
            and not self.app_auth_secret.get_secret_value().strip()
        ):
            raise ValueError("app_auth_secret is required when auth_provider=app")

        if self.auth_provider == AuthProvider.clerk and self.clerk_jwks_url is None:
            raise ValueError("clerk_jwks_url is required when auth_provider=clerk")
        if self.auth_provider == AuthProvider.clerk and self.clerk_jwt_issuer is None:
            raise ValueError("clerk_jwt_issuer is required when auth_provider=clerk")
        if self.auth_provider == AuthProvider.clerk and self.clerk_jwt_audience is None:
            raise ValueError("clerk_jwt_audience is required when auth_provider=clerk")

        if self.auth_provider == AuthProvider.supabase and self.supabase_jwks_url is None:
            raise ValueError("supabase_jwks_url is required when auth_provider=supabase")
        if self.auth_provider == AuthProvider.supabase and self.supabase_jwt_issuer is None:
            raise ValueError("supabase_jwt_issuer is required when auth_provider=supabase")
        if self.auth_provider == AuthProvider.supabase and self.supabase_jwt_audience is None:
            raise ValueError("supabase_jwt_audience is required when auth_provider=supabase")

        needs_openai_for_llm = (
            self.feature_enable_llm or self.feature_enable_evaluations
        ) and self.llm_default_provider == "openai"
        needs_openai_for_embeddings = (
            self.feature_enable_embeddings and self.embedding_default_provider == "openai"
        )
        if (needs_openai_for_llm or needs_openai_for_embeddings) and self.openai_api_key is None:
            raise ValueError(
                "openai_api_key is required when llm_default_provider=openai or "
                "embedding_default_provider=openai and the corresponding feature is enabled"
            )

        if self.feature_enable_embeddings and self.embedding_default_provider == "local":
            if self.local_embedding_base_url is None:
                raise ValueError(
                    "local_embedding_base_url is required when embedding_default_provider=local"
                )
            if not self.local_embedding_model.strip():
                raise ValueError(
                    "local_embedding_model is required when embedding_default_provider=local"
                )

        if self.environment == Environment.production:
            if self.sentry_dsn is None:
                raise ValueError("sentry_dsn is required in production")
            if self.sentry_test_event_enabled:
                raise ValueError("sentry_test_event_enabled must be false in production")
            if (
                self.auth_provider == AuthProvider.app
                and self.app_auth_secret.get_secret_value() == "dev-insecure-change-me"
            ):
                raise ValueError("app_auth_secret must be overridden in production")
            if self.auth_provider == AuthProvider.app:
                self.app_auth_auto_provision_users = False
        elif self.environment == Environment.test:
            self.feature_expose_config_snapshot = True

        return self

    @property
    def is_production(self) -> bool:
        return self.environment == Environment.production

    @property
    def is_rate_limit_active(self) -> bool:
        if not self.rate_limit_enabled:
            return False
        if self.environment == Environment.development and self.rate_limit_disable_in_development:
            return False
        if self.environment == Environment.test and self.rate_limit_disable_in_test:
            return False
        return True

    @property
    def is_sentry_test_event_enabled(self) -> bool:
        if self.environment == Environment.production:
            return False
        if self.sentry_test_event_enabled is not None:
            return self.sentry_test_event_enabled
        return self.environment in {Environment.development, Environment.test}

    @staticmethod
    def _sanitize_url(url_value: str) -> str:
        parsed = urlsplit(url_value)
        if not parsed.netloc:
            return url_value

        host = parsed.hostname or ""
        if parsed.port is not None:
            host = f"{host}:{parsed.port}"

        return urlunsplit((parsed.scheme, host, parsed.path, parsed.query, parsed.fragment))

    def sanitized_snapshot(self) -> dict[str, Any]:
        return {
            "environment": self.environment.value,
            "log_level": self.log_level,
            "log_format": self.log_format.value,
            "api_name": self.api_name,
            "api_version": self.api_version,
            "api_prefix": self.api_prefix,
            "api_base_url": str(self.api_base_url),
            "frontend_base_url": str(self.frontend_base_url),
            "cors_origins": [str(origin) for origin in self.cors_origins],
            "database_url": self._sanitize_url(str(self.database_url)),
            "database_echo": self.database_echo,
            "qdrant_url": str(self.qdrant_url),
            "qdrant_collection": self.qdrant_collection,
            "qdrant_vector_size": self.qdrant_vector_size,
            "qdrant_distance": self.qdrant_distance.value,
            "qdrant_timeout_seconds": self.qdrant_timeout_seconds,
            "qdrant_bootstrap_collection": self.qdrant_bootstrap_collection,
            "qdrant_api_key_set": self.qdrant_api_key is not None,
            "minio_endpoint": str(self.minio_endpoint),
            "minio_access_key_set": bool(self.minio_access_key),
            "minio_bucket": self.minio_bucket,
            "minio_bootstrap_bucket": self.minio_bootstrap_bucket,
            "minio_secret_key_set": bool(self.minio_secret_key.get_secret_value()),
            "rabbitmq_url": self._sanitize_url(str(self.rabbitmq_url)),
            "rabbitmq_connect_timeout_seconds": self.rabbitmq_connect_timeout_seconds,
            "celery_result_backend_enabled": self.celery_result_backend_enabled,
            "celery_task_default_queue": self.celery_task_default_queue,
            "celery_queue_documents_processing": self.celery_queue_documents_processing,
            "celery_queue_documents_deletion": self.celery_queue_documents_deletion,
            "celery_queue_documents_reindex": self.celery_queue_documents_reindex,
            "celery_queue_evaluations": self.celery_queue_evaluations,
            "celery_queue_connector_sync": self.celery_queue_connector_sync,
            "connector_sync_schedule_poll_interval_seconds": self.connector_sync_schedule_poll_interval_seconds,
            "celery_task_max_retries": self.celery_task_max_retries,
            "celery_retry_backoff_seconds": self.celery_retry_backoff_seconds,
            "celery_retry_backoff_max_seconds": self.celery_retry_backoff_max_seconds,
            "celery_retry_jitter": self.celery_retry_jitter,
            "celery_worker_prefetch_multiplier": self.celery_worker_prefetch_multiplier,
            "redis_url": self._sanitize_url(str(self.redis_url)),
            "redis_socket_connect_timeout_seconds": self.redis_socket_connect_timeout_seconds,
            "redis_socket_timeout_seconds": self.redis_socket_timeout_seconds,
            "rate_limit_enabled": self.rate_limit_enabled,
            "rate_limit_disable_in_development": self.rate_limit_disable_in_development,
            "rate_limit_disable_in_test": self.rate_limit_disable_in_test,
            "rate_limit_redis_failure_mode": self.rate_limit_redis_failure_mode.value,
            "rate_limit_window_seconds": self.rate_limit_window_seconds,
            "rate_limit_upload_requests": self.rate_limit_upload_requests,
            "rate_limit_chat_requests": self.rate_limit_chat_requests,
            "rate_limit_evaluation_requests": self.rate_limit_evaluation_requests,
            "rate_limit_delete_requests": self.rate_limit_delete_requests,
            "rate_limit_admin_requests": self.rate_limit_admin_requests,
            "rate_limit_connector_requests": self.rate_limit_connector_requests,
            "rate_limit_bot_requests": self.rate_limit_bot_requests,
            "rate_limit_auth_login_requests": self.rate_limit_auth_login_requests,
            "rate_limit_auth_refresh_requests": self.rate_limit_auth_refresh_requests,
            "rate_limit_auth_logout_requests": self.rate_limit_auth_logout_requests,
            "rate_limit_auth_password_requests": self.rate_limit_auth_password_requests,
            "evaluation_prevent_duplicate_active_runs": self.evaluation_prevent_duplicate_active_runs,
            "dependency_connect_timeout_seconds": self.dependency_connect_timeout_seconds,
            "dependency_read_timeout_seconds": self.dependency_read_timeout_seconds,
            "dependency_max_retries": self.dependency_max_retries,
            "openai_api_key_set": self.openai_api_key is not None,
            "openai_embedding_model": self.openai_embedding_model,
            "openai_llm_model": self.openai_llm_model,
            "local_embedding_base_url_set": self.local_embedding_base_url is not None,
            "local_embedding_api_key_set": self.local_embedding_api_key is not None,
            "local_embedding_model": self.local_embedding_model,
            "local_embedding_timeout_seconds": self.local_embedding_timeout_seconds,
            "llm_retry_max_attempts": self.llm_retry_max_attempts,
            "llm_retry_base_seconds": self.llm_retry_base_seconds,
            "llm_retry_max_seconds": self.llm_retry_max_seconds,
            "openai_llm_input_cost_per_million_tokens_usd": self.openai_llm_input_cost_per_million_tokens_usd,
            "openai_llm_output_cost_per_million_tokens_usd": self.openai_llm_output_cost_per_million_tokens_usd,
            "auth_provider": self.auth_provider.value,
            "app_auth_secret_set": bool(self.app_auth_secret.get_secret_value()),
            "app_auth_access_token_ttl_seconds": self.app_auth_access_token_ttl_seconds,
            "app_auth_refresh_token_ttl_seconds": self.app_auth_refresh_token_ttl_seconds,
            "app_auth_issuer": self.app_auth_issuer,
            "app_auth_audience": self.app_auth_audience,
            "app_auth_clock_skew_seconds": self.app_auth_clock_skew_seconds,
            "app_auth_cookie_domain": self.app_auth_cookie_domain,
            "app_auth_cookie_secure": self.app_auth_cookie_secure,
            "app_auth_cookie_same_site": self.app_auth_cookie_same_site,
            "app_auth_cookie_path": self.app_auth_cookie_path,
            "app_auth_login_password_set": bool(
                self.app_auth_login_password and self.app_auth_login_password.get_secret_value()
            ),
            "app_auth_auto_provision_users": self.app_auth_auto_provision_users,
            "app_auth_password_hash_memory_cost_kib": self.app_auth_password_hash_memory_cost_kib,
            "app_auth_password_hash_time_cost": self.app_auth_password_hash_time_cost,
            "app_auth_password_hash_parallelism": self.app_auth_password_hash_parallelism,
            "app_auth_password_hash_length": self.app_auth_password_hash_length,
            "app_auth_password_salt_length": self.app_auth_password_salt_length,
            "auth_jwks_cache_ttl_seconds": self.auth_jwks_cache_ttl_seconds,
            "clerk_jwks_url": str(self.clerk_jwks_url) if self.clerk_jwks_url else None,
            "clerk_jwt_issuer": str(self.clerk_jwt_issuer) if self.clerk_jwt_issuer else None,
            "clerk_jwt_audience": self.clerk_jwt_audience,
            "supabase_jwks_url": str(self.supabase_jwks_url) if self.supabase_jwks_url else None,
            "supabase_jwt_issuer": str(self.supabase_jwt_issuer)
            if self.supabase_jwt_issuer
            else None,
            "supabase_jwt_audience": self.supabase_jwt_audience,
            "sentry_dsn_set": self.sentry_dsn is not None,
            "sentry_release": self.sentry_release,
            "sentry_error_sample_rate": self.sentry_error_sample_rate,
            "sentry_traces_sample_rate": self.sentry_traces_sample_rate,
            "sentry_profiles_sample_rate": self.sentry_profiles_sample_rate,
            "sentry_test_event_enabled": self.is_sentry_test_event_enabled,
            "email": {
                "enabled": self.email_enabled,
                "provider": self.email_provider,
                "from_address": self.email_from_address,
                "from_name": self.email_from_name,
                "smtp_host": self.smtp_host,
                "smtp_port": self.smtp_port,
                "smtp_use_tls": self.smtp_use_tls,
                "resend_api_key_set": self.resend_api_key is not None,
                "postmark_server_token_set": self.postmark_server_token is not None,
            },
            "langfuse_enabled": self.langfuse_enabled,
            "langfuse_base_url_set": self.langfuse_base_url is not None,
            "langfuse_public_key_set": self.langfuse_public_key is not None,
            "langfuse_secret_key_set": self.langfuse_secret_key is not None,
            "langfuse_sample_rate": self.langfuse_sample_rate,
            "langfuse_capture_input_output": self.langfuse_capture_input_output,
            "langfuse_redaction_mode": self.langfuse_redaction_mode.value,
            "max_upload_size_mb": self.max_upload_size_mb,
            "malware_scan": {
                "enabled": self.malware_scan_enabled,
                "required": self.malware_scan_required,
                "bypass_on_unavailable": self.malware_scan_bypass_on_unavailable,
                "clamav_host": self.malware_scan_clamav_host,
                "clamav_port": self.malware_scan_clamav_port,
                "timeout_seconds": self.malware_scan_timeout_seconds,
                "max_bytes": self.malware_scan_max_bytes,
                "stream_chunk_size_bytes": self.malware_scan_stream_chunk_size_bytes,
            },
            "duplicate_detection": {
                "enabled": self.duplicate_detection_enabled,
                "action": self.duplicate_detection_action,
            },
            "dlp": {
                "enabled": self.dlp_enabled,
                "action": self.dlp_action,
                "min_findings": self.dlp_min_findings,
            },
            "retrieval_initial_top_k": self.retrieval_initial_top_k,
            "retrieval_final_top_k": self.retrieval_final_top_k,
            "rerank_default_provider": self.rerank_default_provider,
            "rerank_default_model_name": self.rerank_default_model_name,
            "rerank_default_timeout_seconds": self.rerank_default_timeout_seconds,
            "rerank_default_batch_size": self.rerank_default_batch_size,
            "rerank_default_input_candidates": self.rerank_default_input_candidates,
            "rerank_default_candidate_chars": self.rerank_default_candidate_chars,
            "rerank_default_fallback_behavior": self.rerank_default_fallback_behavior.value,
            "rerank_input_cost_per_million_tokens_usd": self.rerank_input_cost_per_million_tokens_usd,
            "rerank_output_cost_per_million_tokens_usd": self.rerank_output_cost_per_million_tokens_usd,
            "rerank_mmr_lambda": self.rerank_mmr_lambda,
            "rerank_mmr_candidate_count": self.rerank_mmr_candidate_count,
            "rerank_mmr_duplicate_similarity_threshold": self.rerank_mmr_duplicate_similarity_threshold,
            "confidence_weight_top_similarity": self.confidence_weight_top_similarity,
            "confidence_weight_average_similarity": self.confidence_weight_average_similarity,
            "confidence_weight_rerank_score": self.confidence_weight_rerank_score,
            "confidence_weight_citation_support": self.confidence_weight_citation_support,
            "confidence_weight_agreement": self.confidence_weight_agreement,
            "confidence_medium_threshold": self.confidence_medium_threshold,
            "confidence_high_threshold": self.confidence_high_threshold,
            "confidence_not_found_threshold": self.confidence_not_found_threshold,
            "confidence_not_found_penalty_multiplier": self.confidence_not_found_penalty_multiplier,
            "confidence_citation_coverage_target": self.confidence_citation_coverage_target,
            "chunk_size_tokens": self.chunk_size_tokens,
            "chunk_overlap_tokens": self.chunk_overlap_tokens,
            "document_index_version": self.document_index_version,
            "embedding_batch_max_items": self.embedding_batch_max_items,
            "embedding_batch_max_tokens": self.embedding_batch_max_tokens,
            "embedding_retry_max_attempts": self.embedding_retry_max_attempts,
            "embedding_retry_base_seconds": self.embedding_retry_base_seconds,
            "embedding_retry_max_seconds": self.embedding_retry_max_seconds,
            "openai_embedding_cost_per_million_tokens_usd": self.openai_embedding_cost_per_million_tokens_usd,
            "request_timeout_seconds": self.request_timeout_seconds,
            "connector_credentials": {
                "encryption_key_set": self.connector_credential_encryption_key is not None,
                "encryption_key_id": self.connector_credential_encryption_key_id,
                "oauth_state_ttl_seconds": self.connector_oauth_state_ttl_seconds,
                "rollout_stage": self.connector_rollout_stage.value,
                "oauth_clients": [
                    {
                        "provider_key": client.provider_key,
                        "client_id_set": bool(client.client_id),
                        "client_secret_set": bool(client.client_secret.get_secret_value()),
                        "redirect_uri": str(client.redirect_uri)
                        if client.redirect_uri is not None
                        else None,
                    }
                    for client in self.connector_oauth_clients
                ],
            },
            "features": {
                "embeddings": self.feature_enable_embeddings,
                "llm": self.feature_enable_llm,
                "evaluations": self.feature_enable_evaluations,
                "pipeline_explorer": self.feature_enable_pipeline_explorer,
                "agents": self.feature_enable_agents,
                "chunking_profiles": self.feature_enable_chunking_profiles,
                "adaptive_chunking": self.feature_enable_adaptive_chunking,
                "hybrid_retrieval": self.feature_enable_hybrid_retrieval,
                "query_rewriting": self.feature_enable_query_rewriting,
                "grounded_answer_verification": self.feature_enable_grounded_answer_verification,
                "graph_rag": self.feature_enable_graph_rag,
                "entity_extraction": self.feature_enable_entity_extraction,
                "entity_resolution": self.feature_enable_entity_resolution,
                "mcp": self.feature_enable_mcp,
                "external_mcp_connectors": self.feature_enable_external_mcp_connectors,
                "connectors": self.feature_enable_connectors,
                "collaboration_bots": self.feature_enable_collaboration_bots,
                "expose_config_snapshot": self.feature_expose_config_snapshot,
                "language_aware_rag": self.feature_enable_language_aware_rag,
                "advanced_pdf_extraction": self.feature_enable_advanced_pdf_extraction,
                "pdf_extraction_tables": self.pdf_extraction_enable_tables,
                "pdf_extraction_images": self.pdf_extraction_enable_images,
                "ocr_quality_downranking": self.feature_enable_ocr_quality_downranking,
            },
            "enterprise_graph": {
                "enabled": self.enterprise_graph_enabled,
                "uri_set": self.neo4j_uri is not None,
                "database": self.neo4j_database,
                "connection_timeout_seconds": self.neo4j_connection_timeout_seconds,
                "query_timeout_seconds": self.neo4j_query_timeout_seconds,
                "max_connection_pool_size": self.neo4j_max_connection_pool_size,
                "entity_resolution_enabled": self.feature_enable_entity_resolution,
                "entity_resolution_auto_merge_threshold": self.entity_resolution_auto_merge_threshold,
                "entity_resolution_review_threshold": self.entity_resolution_review_threshold,
                "graph_rag_max_hops": self.graph_rag_max_hops,
                "graph_rag_max_related_entities": self.graph_rag_max_related_entities,
                "graph_rag_max_chunks": self.graph_rag_max_chunks,
                "graph_rag_confidence_threshold": self.graph_rag_confidence_threshold,
                "graph_rag_relation_type_allowlist": self.graph_rag_relation_type_allowlist,
            },
            "answer_language_workspace_default": self.answer_language_workspace_default,
            "collaboration_bots": {
                "slack_signing_secret_set": self.bot_slack_signing_secret is not None,
                "slack_client_id_set": self.bot_slack_client_id is not None,
                "slack_client_secret_set": self.bot_slack_client_secret is not None,
                "slack_oauth_redirect_uri_set": self.bot_slack_oauth_redirect_uri is not None,
                "teams_shared_secret_set": self.bot_teams_shared_secret is not None,
                "process_events_async": self.bot_process_events_async,
                "delivery_timeout_seconds": self.bot_delivery_timeout_seconds,
            },
            "mcp": {
                "server_name": self.mcp_server_name,
                "transport": self.mcp_transport.value,
                "http_host": self.mcp_http_host,
                "http_port": self.mcp_http_port,
                "http_path": self.mcp_http_path,
                "require_bearer_auth": self.mcp_require_bearer_auth,
                "dev_principal_user_id_set": self.mcp_dev_principal_user_id is not None,
                "dev_principal_organization_id_set": self.mcp_dev_principal_organization_id
                is not None,
                "dev_principal_roles": self.mcp_dev_principal_roles,
                "capabilities_owner": self.mcp_capabilities_owner,
                "capabilities_admin": self.mcp_capabilities_admin,
                "capabilities_member": self.mcp_capabilities_member,
                "capabilities_viewer": self.mcp_capabilities_viewer,
                "rate_limit_enabled": self.mcp_rate_limit_enabled,
                "rate_limit_window_seconds": self.mcp_rate_limit_window_seconds,
                "rate_limit_requests": self.mcp_rate_limit_requests,
                "external_connectors_enabled": self.feature_enable_external_mcp_connectors,
                "connector_rollout_stage": self.connector_rollout_stage.value,
                "external_servers": [
                    {
                        "server_id": server.server_id,
                        "enabled": server.enabled,
                        "transport": server.transport.value,
                        "base_url": str(server.base_url),
                        "auth_type": server.auth_type.value,
                        "auth_token_set": server.auth_token is not None,
                        "auth_header_name": server.auth_header_name,
                        "auth_header_value_set": server.auth_header_value is not None,
                        "allow_tools_count": len(server.allow_tools),
                        "allow_resources_count": len(server.allow_resources),
                        "required_roles": server.required_roles,
                        "capability_prefix": server.capability_prefix,
                        "expose_on_mcp_surface": server.expose_on_mcp_surface,
                    }
                    for server in self.mcp_external_servers
                ],
            },
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
