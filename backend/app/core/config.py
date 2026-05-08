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

    dependency_connect_timeout_seconds: float = Field(default=1.0, ge=0.1, le=30.0)
    dependency_read_timeout_seconds: float = Field(default=1.0, ge=0.1, le=120.0)
    dependency_max_retries: int = Field(default=0, ge=0, le=10)

    openai_api_key: SecretStr | None = None
    openai_embedding_model: str = Field(default="text-embedding-3-small", min_length=3, max_length=128)
    openai_llm_model: str = Field(default="gpt-5.4-mini", min_length=3, max_length=128)

    auth_provider: AuthProvider = AuthProvider.app
    app_auth_secret: SecretStr = SecretStr("dev-insecure-change-me")
    app_auth_access_token_ttl_seconds: int = Field(default=3600, ge=60, le=604800)
    app_auth_issuer: str = Field(default="rudix-app", min_length=3, max_length=120)
    app_auth_audience: str = Field(default="rudix-api", min_length=3, max_length=120)
    clerk_jwks_url: AnyHttpUrl | None = None
    supabase_jwks_url: AnyHttpUrl | None = None

    sentry_dsn: AnyUrl | None = None

    max_upload_size_mb: int = Field(default=25, ge=1, le=512)
    retrieval_initial_top_k: int = Field(default=20, ge=1, le=200)
    retrieval_final_top_k: int = Field(default=5, ge=1, le=50)
    chunk_size_tokens: int = Field(default=700, ge=100, le=4000)
    chunk_overlap_tokens: int = Field(default=120, ge=0, le=2000)
    request_timeout_seconds: int = Field(default=30, ge=1, le=300)

    feature_enable_embeddings: bool = True
    feature_enable_llm: bool = True
    feature_enable_evaluations: bool = True
    feature_enable_pipeline_explorer: bool = True
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

        if self.chunk_overlap_tokens >= self.chunk_size_tokens:
            raise ValueError("chunk_overlap_tokens must be smaller than chunk_size_tokens")

        if self.redis_socket_timeout_seconds < self.redis_socket_connect_timeout_seconds:
            raise ValueError("redis_socket_timeout_seconds must be >= redis_socket_connect_timeout_seconds")

        if self.dependency_read_timeout_seconds < self.dependency_connect_timeout_seconds:
            raise ValueError("dependency_read_timeout_seconds must be >= dependency_connect_timeout_seconds")

        if self.auth_provider == AuthProvider.app and not self.app_auth_secret.get_secret_value().strip():
            raise ValueError("app_auth_secret is required when auth_provider=app")

        if self.auth_provider == AuthProvider.clerk and self.clerk_jwks_url is None:
            raise ValueError("clerk_jwks_url is required when auth_provider=clerk")

        if self.auth_provider == AuthProvider.supabase and self.supabase_jwks_url is None:
            raise ValueError("supabase_jwks_url is required when auth_provider=supabase")

        needs_openai = self.feature_enable_embeddings or self.feature_enable_llm or self.feature_enable_evaluations
        if needs_openai and self.openai_api_key is None:
            raise ValueError(
                "openai_api_key is required when embeddings, llm, or evaluations are enabled"
            )

        if self.environment == Environment.production:
            if self.sentry_dsn is None:
                raise ValueError("sentry_dsn is required in production")
            if self.auth_provider == AuthProvider.app and self.app_auth_secret.get_secret_value() == "dev-insecure-change-me":
                raise ValueError("app_auth_secret must be overridden in production")
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
            "dependency_connect_timeout_seconds": self.dependency_connect_timeout_seconds,
            "dependency_read_timeout_seconds": self.dependency_read_timeout_seconds,
            "dependency_max_retries": self.dependency_max_retries,
            "openai_api_key_set": self.openai_api_key is not None,
            "openai_embedding_model": self.openai_embedding_model,
            "openai_llm_model": self.openai_llm_model,
            "auth_provider": self.auth_provider.value,
            "app_auth_secret_set": bool(self.app_auth_secret.get_secret_value()),
            "app_auth_access_token_ttl_seconds": self.app_auth_access_token_ttl_seconds,
            "app_auth_issuer": self.app_auth_issuer,
            "app_auth_audience": self.app_auth_audience,
            "clerk_jwks_url": str(self.clerk_jwks_url) if self.clerk_jwks_url else None,
            "supabase_jwks_url": str(self.supabase_jwks_url) if self.supabase_jwks_url else None,
            "sentry_dsn_set": self.sentry_dsn is not None,
            "max_upload_size_mb": self.max_upload_size_mb,
            "retrieval_initial_top_k": self.retrieval_initial_top_k,
            "retrieval_final_top_k": self.retrieval_final_top_k,
            "chunk_size_tokens": self.chunk_size_tokens,
            "chunk_overlap_tokens": self.chunk_overlap_tokens,
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
