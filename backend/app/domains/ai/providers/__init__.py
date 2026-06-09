"""AI provider package.

Importing this package registers known OpenAI models with the default
capability registry so capability checks work at startup.
"""

from app.domains.ai.providers.capability_registry import default_capability_registry
from app.domains.ai.providers.errors import (
    InvalidProviderResponseError,
    ProviderError,
    ProviderInternalError,
    ProviderPolicyBlockedError,
    ProviderQuotaExceededError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    UnsupportedCapabilityError,
)
from app.domains.ai.providers.factory import UnknownProviderError, default_provider_factory
from app.domains.ai.providers.protocols import (
    ChatCompletionProvider,
    ChatCompletionRequest,
    ChatCompletionResponse,
    EmbeddingProvider,
    EmbeddingRequest,
    EmbeddingResponse,
)
from app.domains.ai.providers.schemas import CostBehavior, ModelCapability

# Register known OpenAI chat models
default_capability_registry.register(
    ModelCapability(
        provider="openai",
        model_name="gpt-5.4-mini",
        context_window=128000,
        max_input_tokens=128000,
        supports_json_mode=True,
        supports_streaming=True,
        supports_tool_calling=True,
        is_chat_model=True,
        is_embedding_model=False,
        cost_behavior=CostBehavior.per_token,
    )
)
default_capability_registry.register(
    ModelCapability(
        provider="openai",
        model_name="gpt-4o",
        context_window=128000,
        max_input_tokens=128000,
        supports_json_mode=True,
        supports_streaming=True,
        supports_tool_calling=True,
        is_chat_model=True,
        is_embedding_model=False,
        cost_behavior=CostBehavior.per_token,
    )
)
default_capability_registry.register(
    ModelCapability(
        provider="openai",
        model_name="gpt-4o-mini",
        context_window=128000,
        max_input_tokens=128000,
        supports_json_mode=True,
        supports_streaming=True,
        supports_tool_calling=True,
        is_chat_model=True,
        is_embedding_model=False,
        cost_behavior=CostBehavior.per_token,
    )
)

# Register known OpenAI embedding models
default_capability_registry.register(
    ModelCapability(
        provider="openai",
        model_name="text-embedding-3-small",
        context_window=8191,
        max_input_tokens=8191,
        embedding_dimension=1536,
        supports_json_mode=False,
        supports_streaming=False,
        supports_tool_calling=False,
        is_chat_model=False,
        is_embedding_model=True,
        cost_behavior=CostBehavior.per_token,
    )
)
default_capability_registry.register(
    ModelCapability(
        provider="openai",
        model_name="text-embedding-3-large",
        context_window=8191,
        max_input_tokens=8191,
        embedding_dimension=3072,
        supports_json_mode=False,
        supports_streaming=False,
        supports_tool_calling=False,
        is_chat_model=False,
        is_embedding_model=True,
        cost_behavior=CostBehavior.per_token,
    )
)
default_capability_registry.register(
    ModelCapability(
        provider="openai",
        model_name="text-embedding-ada-002",
        context_window=8191,
        max_input_tokens=8191,
        embedding_dimension=1536,
        supports_json_mode=False,
        supports_streaming=False,
        supports_tool_calling=False,
        is_chat_model=False,
        is_embedding_model=True,
        cost_behavior=CostBehavior.per_token,
    )
)

__all__ = [
    "ChatCompletionProvider",
    "ChatCompletionRequest",
    "ChatCompletionResponse",
    "CostBehavior",
    "EmbeddingProvider",
    "EmbeddingRequest",
    "EmbeddingResponse",
    "InvalidProviderResponseError",
    "ModelCapability",
    "ProviderError",
    "ProviderInternalError",
    "ProviderPolicyBlockedError",
    "ProviderQuotaExceededError",
    "ProviderTimeoutError",
    "ProviderUnavailableError",
    "UnknownProviderError",
    "UnsupportedCapabilityError",
    "default_capability_registry",
    "default_provider_factory",
]
