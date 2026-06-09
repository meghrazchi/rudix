from __future__ import annotations

from app.domains.ai.providers.errors import ProviderError, ProviderUnavailableError
from app.domains.ai.providers.protocols import ChatCompletionProvider, EmbeddingProvider


class UnknownProviderError(ProviderError):
    """No provider adapter is registered for the requested provider key."""


class ProviderFactory:
    """Resolves and caches provider instances from settings."""

    def __init__(self) -> None:
        self._chat_providers: dict[str, ChatCompletionProvider] = {}
        self._embedding_providers: dict[str, EmbeddingProvider] = {}

    def get_chat_provider(self, provider_key: str | None = None) -> ChatCompletionProvider:
        from app.core.config import settings

        key = (provider_key or settings.llm_default_provider).strip().lower()
        if key not in self._chat_providers:
            self._chat_providers[key] = self._build_chat_provider(key)
        return self._chat_providers[key]

    def get_embedding_provider(self, provider_key: str | None = None) -> EmbeddingProvider:
        from app.core.config import settings

        key = (provider_key or settings.embedding_default_provider).strip().lower()
        if key not in self._embedding_providers:
            self._embedding_providers[key] = self._build_embedding_provider(key)
        return self._embedding_providers[key]

    def _build_chat_provider(self, key: str) -> ChatCompletionProvider:
        if key == "openai":
            return self._build_openai_chat_provider()
        raise UnknownProviderError(f"No chat provider registered for key '{key}'")

    def _build_embedding_provider(self, key: str) -> EmbeddingProvider:
        if key == "openai":
            return self._build_openai_embedding_provider()
        raise UnknownProviderError(f"No embedding provider registered for key '{key}'")

    def _build_openai_chat_provider(self) -> ChatCompletionProvider:
        from openai import AsyncOpenAI

        from app.core.config import settings
        from app.domains.ai.providers.openai.adapter import OpenAIChatProvider

        if settings.openai_api_key is None:
            raise ProviderUnavailableError(
                "OpenAI API key is not configured (OPENAI_API_KEY)"
            )
        timeout = max(
            float(settings.request_timeout_seconds), settings.dependency_read_timeout_seconds
        )
        client = AsyncOpenAI(
            api_key=settings.openai_api_key.get_secret_value(),
            timeout=timeout,
            max_retries=0,
        )
        return OpenAIChatProvider(client=client, model_name=settings.openai_llm_model)

    def _build_openai_embedding_provider(self) -> EmbeddingProvider:
        from openai import AsyncOpenAI

        from app.core.config import settings
        from app.domains.ai.providers.openai.adapter import OpenAIEmbeddingProvider

        if settings.openai_api_key is None:
            raise ProviderUnavailableError(
                "OpenAI API key is not configured (OPENAI_API_KEY)"
            )
        timeout = max(
            float(settings.request_timeout_seconds), settings.dependency_read_timeout_seconds
        )
        client = AsyncOpenAI(
            api_key=settings.openai_api_key.get_secret_value(),
            timeout=timeout,
            max_retries=0,
        )
        return OpenAIEmbeddingProvider(
            client=client, model_name=settings.openai_embedding_model
        )


default_provider_factory = ProviderFactory()
