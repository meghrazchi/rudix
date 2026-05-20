from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlsplit, urlunsplit

from pydantic import (
    AmqpDsn,
    AnyHttpUrl,
    AnyUrl,
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
    celery_queue_documents_processing: str = Field(default="documents.processing", min_length=1, max_length=64)
    celery_queue_documents_deletion: str = Field(default="documents.deletion", min_length=1, max_length=64)
    celery_queue_documents_reindex: str = Field(default="documents.reindex", min_length=1, max_length=64)
    celery_queue_evaluations: str = Field(default="evaluations", min_length=1, max_length=64)
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
    evaluation_prevent_duplicate_active_runs: bool = True

    dependency_connect_timeout_seconds: float = Field(default=1.0, ge=0.1, le=30.0)
    dependency_read_timeout_seconds: float = Field(default=1.0, ge=0.1, le=120.0)
    dependency_max_retries: int = Field(default=0, ge=0, le=10)

    openai_api_key: SecretStr | None = None
    openai_embedding_model: str = Field(default="text-embedding-3-small", min_length=3, max_length=128)
    openai_llm_model: str = Field(default="gpt-5.4-mini", min_length=3, max_length=128)
    llm_retry_max_attempts: int = Field(default=2, ge=1, le=10)
    llm_retry_base_seconds: float = Field(default=0.4, ge=0.1, le=30.0)
    llm_retry_max_seconds: float = Field(default=3.0, ge=0.1, le=120.0)
    openai_llm_input_cost_per_million_tokens_usd: float = Field(default=0.0, ge=0.0, le=1000.0)
    openai_llm_output_cost_per_million_tokens_usd: float = Field(default=0.0, ge=0.0, le=1000.0)

    auth_provider: AuthProvider = AuthProvider.app
    app_auth_secret: SecretStr = SecretStr("dev-insecure-change-me")
    app_auth_access_token_ttl_seconds: int = Field(default=3600, ge=60, le=604800)
    app_auth_refresh_token_ttl_seconds: int = Field(default=1209600, ge=300, le=7776000)
    app_auth_issuer: str = Field(default="rudix-app", min_length=3, max_length=120)
    app_auth_audience: str = Field(default="rudix-api", min_length=3, max_length=120)
    app_auth_login_password: SecretStr | None = None
    app_auth_auto_provision_users: bool = True
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

    max_upload_size_mb: int = Field(default=25, ge=1, le=512)
    retrieval_initial_top_k: int = Field(default=20, ge=1, le=200)
    retrieval_final_top_k: int = Field(default=5, ge=1, le=50)
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

    feature_enable_embeddings: bool = True
    feature_enable_llm: bool = True
    feature_enable_evaluations: bool = True
    feature_enable_pipeline_explorer: bool = True
    feature_enable_agents: bool = False
    feature_expose_config_snapshot: bool = True

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
            raise ValueError("qdrant_collection must contain only letters, numbers, underscores, or hyphens")
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
            raise ValueError("document_index_version may contain only letters, numbers, '.', '-', and '_'")
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

    @field_validator(
        "celery_task_default_queue",
        "celery_queue_documents_processing",
        "celery_queue_documents_deletion",
        "celery_queue_documents_reindex",
        "celery_queue_evaluations",
    )
    @classmethod
    def validate_celery_queue_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("celery queue names must not be empty")
        if not cleaned.replace(".", "").replace("-", "").replace("_", "").isalnum():
            raise ValueError("celery queue names may contain only letters, numbers, '.', '-', and '_'")
        return cleaned

    @model_validator(mode="after")
    def validate_consistency(self) -> "Settings":
        if not self.cors_origins:
            self.cors_origins = [self.frontend_base_url]

        if self.retrieval_final_top_k > self.retrieval_initial_top_k:
            raise ValueError("retrieval_final_top_k must be less than or equal to retrieval_initial_top_k")

        if self.rerank_mmr_candidate_count < self.retrieval_final_top_k:
            raise ValueError("rerank_mmr_candidate_count must be >= retrieval_final_top_k")

        if self.confidence_high_threshold < self.confidence_medium_threshold:
            raise ValueError("confidence_high_threshold must be >= confidence_medium_threshold")

        if self.confidence_not_found_threshold > self.confidence_medium_threshold:
            raise ValueError("confidence_not_found_threshold must be <= confidence_medium_threshold")

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

        if self.redis_socket_timeout_seconds < self.redis_socket_connect_timeout_seconds:
            raise ValueError("redis_socket_timeout_seconds must be >= redis_socket_connect_timeout_seconds")

        if self.dependency_read_timeout_seconds < self.dependency_connect_timeout_seconds:
            raise ValueError("dependency_read_timeout_seconds must be >= dependency_connect_timeout_seconds")

        if self.auth_provider == AuthProvider.app and not self.app_auth_secret.get_secret_value().strip():
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

        needs_openai = self.feature_enable_embeddings or self.feature_enable_llm or self.feature_enable_evaluations
        if needs_openai and self.openai_api_key is None:
            raise ValueError(
                "openai_api_key is required when embeddings, llm, or evaluations are enabled"
            )

        if self.environment == Environment.production:
            if self.sentry_dsn is None:
                raise ValueError("sentry_dsn is required in production")
            if self.sentry_test_event_enabled:
                raise ValueError("sentry_test_event_enabled must be false in production")
            if self.auth_provider == AuthProvider.app and self.app_auth_secret.get_secret_value() == "dev-insecure-change-me":
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
            "evaluation_prevent_duplicate_active_runs": self.evaluation_prevent_duplicate_active_runs,
            "dependency_connect_timeout_seconds": self.dependency_connect_timeout_seconds,
            "dependency_read_timeout_seconds": self.dependency_read_timeout_seconds,
            "dependency_max_retries": self.dependency_max_retries,
            "openai_api_key_set": self.openai_api_key is not None,
            "openai_embedding_model": self.openai_embedding_model,
            "openai_llm_model": self.openai_llm_model,
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
            "app_auth_login_password_set": bool(self.app_auth_login_password and self.app_auth_login_password.get_secret_value()),
            "app_auth_auto_provision_users": self.app_auth_auto_provision_users,
            "auth_jwks_cache_ttl_seconds": self.auth_jwks_cache_ttl_seconds,
            "clerk_jwks_url": str(self.clerk_jwks_url) if self.clerk_jwks_url else None,
            "clerk_jwt_issuer": str(self.clerk_jwt_issuer) if self.clerk_jwt_issuer else None,
            "clerk_jwt_audience": self.clerk_jwt_audience,
            "supabase_jwks_url": str(self.supabase_jwks_url) if self.supabase_jwks_url else None,
            "supabase_jwt_issuer": str(self.supabase_jwt_issuer) if self.supabase_jwt_issuer else None,
            "supabase_jwt_audience": self.supabase_jwt_audience,
            "sentry_dsn_set": self.sentry_dsn is not None,
            "sentry_release": self.sentry_release,
            "sentry_error_sample_rate": self.sentry_error_sample_rate,
            "sentry_traces_sample_rate": self.sentry_traces_sample_rate,
            "sentry_profiles_sample_rate": self.sentry_profiles_sample_rate,
            "sentry_test_event_enabled": self.is_sentry_test_event_enabled,
            "max_upload_size_mb": self.max_upload_size_mb,
            "retrieval_initial_top_k": self.retrieval_initial_top_k,
            "retrieval_final_top_k": self.retrieval_final_top_k,
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
            "features": {
                "embeddings": self.feature_enable_embeddings,
                "llm": self.feature_enable_llm,
                "evaluations": self.feature_enable_evaluations,
                "pipeline_explorer": self.feature_enable_pipeline_explorer,
                "expose_config_snapshot": self.feature_expose_config_snapshot,
            },
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
