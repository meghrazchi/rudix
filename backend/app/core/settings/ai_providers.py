"""LLM and embedding provider settings (OpenAI and local)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    Field,
    SecretStr,
    field_validator,
)

if TYPE_CHECKING:
    from app.core.config import Settings


class AiProvidersSettings(BaseModel):
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
    openai_embedding_cost_per_million_tokens_usd: float = Field(default=0.02, ge=0.0, le=1000.0)

    @field_validator("openai_embedding_model", "openai_llm_model")
    @classmethod
    def validate_model_names(cls, value: str) -> str:
        cleaned = value.strip()
        if " " in cleaned:
            raise ValueError("model names must not contain whitespace")
        return cleaned


def validate_ai_providers(settings: Settings) -> None:
    needs_openai_for_llm = (
        settings.feature_enable_llm or settings.feature_enable_evaluations
    ) and settings.llm_default_provider == "openai"
    needs_openai_for_embeddings = (
        settings.feature_enable_embeddings and settings.embedding_default_provider == "openai"
    )
    if (needs_openai_for_llm or needs_openai_for_embeddings) and settings.openai_api_key is None:
        raise ValueError(
            "openai_api_key is required when llm_default_provider=openai or "
            "embedding_default_provider=openai and the corresponding feature is enabled"
        )

    if settings.feature_enable_embeddings and settings.embedding_default_provider == "local":
        if settings.local_embedding_base_url is None:
            raise ValueError(
                "local_embedding_base_url is required when embedding_default_provider=local"
            )
        if not settings.local_embedding_model.strip():
            raise ValueError(
                "local_embedding_model is required when embedding_default_provider=local"
            )
