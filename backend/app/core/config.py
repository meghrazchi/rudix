from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    environment: Literal["development", "test", "staging", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    api_name: str = "AI Document Q&A Assistant API"
    api_version: str = "0.1.0"
    api_prefix: str = "/api/v1"
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["http://localhost:3000"])

    database_url: str = "postgresql+asyncpg://postgres:postgres@postgres:5432/rag_app"
    database_echo: bool = False

    qdrant_url: str = "http://qdrant:6333"
    qdrant_api_key: SecretStr | None = None
    qdrant_collection: str = "documents"

    minio_endpoint: str = "minio:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: SecretStr = SecretStr("minioadmin")
    minio_bucket: str = "documents"
    minio_secure: bool = False

    rabbitmq_url: str = "amqp://guest:guest@rabbitmq:5672//"
    redis_url: str = "redis://redis:6379/0"

    openai_api_key: SecretStr | None = None
    openai_embedding_model: str = "text-embedding-3-small"
    openai_llm_model: str = "gpt-5.4-mini"

    auth_provider: Literal["clerk", "supabase"] = "clerk"
    clerk_jwks_url: str | None = None
    supabase_jwks_url: str | None = None

    sentry_dsn: str | None = None
    max_upload_size_mb: int = 25

    @field_validator("cors_origins", mode="before")
    @classmethod
    def validate_cors_origins(cls, value: object) -> list[str]:
        if isinstance(value, str):
            parsed = [item.strip() for item in value.split(",") if item.strip()]
            if not parsed:
                raise ValueError("cors_origins must not be empty")
            return parsed
        if isinstance(value, list):
            parsed = [str(item).strip() for item in value if str(item).strip()]
            if not parsed:
                raise ValueError("cors_origins must not be empty")
            return parsed
        raise ValueError("cors_origins must be a comma-separated string or list of strings")

    @model_validator(mode="before")
    @classmethod
    def parse_cors_origins(cls, data: object) -> object:
        if isinstance(data, dict):
            for key in ("clerk_jwks_url", "supabase_jwks_url", "qdrant_api_key", "openai_api_key", "sentry_dsn"):
                if data.get(key) == "":
                    data[key] = None
        return data

    @model_validator(mode="after")
    def validate_auth_settings(self) -> "Settings":
        if self.max_upload_size_mb <= 0:
            raise ValueError("max_upload_size_mb must be positive")

        if self.environment == "production":
            if self.auth_provider == "clerk" and not self.clerk_jwks_url:
                raise ValueError("clerk_jwks_url is required when auth_provider=clerk in production")
            if self.auth_provider == "supabase" and not self.supabase_jwks_url:
                raise ValueError("supabase_jwks_url is required when auth_provider=supabase in production")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
