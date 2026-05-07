from enum import Enum
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


class Environment(str, Enum):
    development = "development"
    test = "test"
    staging = "staging"
    production = "production"


class AuthProvider(str, Enum):
    clerk = "clerk"
    supabase = "supabase"


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

    minio_endpoint: AnyHttpUrl
    minio_access_key: str = Field(min_length=3, max_length=128)
    minio_secret_key: SecretStr
    minio_bucket: str = Field(min_length=3, max_length=63)

    rabbitmq_url: AmqpDsn
    redis_url: RedisDsn

    openai_api_key: SecretStr | None = None
    openai_embedding_model: str = Field(default="text-embedding-3-small", min_length=3, max_length=128)
    openai_llm_model: str = Field(default="gpt-5.4-mini", min_length=3, max_length=128)

    auth_provider: AuthProvider = AuthProvider.clerk
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

    @model_validator(mode="after")
    def validate_consistency(self) -> "Settings":
        if not self.cors_origins:
            self.cors_origins = [self.frontend_base_url]

        if self.retrieval_final_top_k > self.retrieval_initial_top_k:
            raise ValueError("retrieval_final_top_k must be less than or equal to retrieval_initial_top_k")

        if self.chunk_overlap_tokens >= self.chunk_size_tokens:
            raise ValueError("chunk_overlap_tokens must be smaller than chunk_size_tokens")

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
        elif self.environment == Environment.test:
            self.feature_expose_config_snapshot = True

        return self

    @property
    def is_production(self) -> bool:
        return self.environment == Environment.production

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
            "qdrant_api_key_set": self.qdrant_api_key is not None,
            "minio_endpoint": str(self.minio_endpoint),
            "minio_access_key_set": bool(self.minio_access_key),
            "minio_bucket": self.minio_bucket,
            "minio_secret_key_set": bool(self.minio_secret_key.get_secret_value()),
            "rabbitmq_url": self._sanitize_url(str(self.rabbitmq_url)),
            "redis_url": self._sanitize_url(str(self.redis_url)),
            "openai_api_key_set": self.openai_api_key is not None,
            "openai_embedding_model": self.openai_embedding_model,
            "openai_llm_model": self.openai_llm_model,
            "auth_provider": self.auth_provider.value,
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
    return Settings()


settings = get_settings()
