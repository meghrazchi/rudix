from __future__ import annotations

from app.domains.ai.providers.errors import UnsupportedCapabilityError
from app.domains.ai.providers.schemas import ModelCapability


class UnknownModelError(UnsupportedCapabilityError):
    """Model is not registered in the capability registry."""


class ModelCapabilityRegistry:
    """Registry mapping (provider, model_name) to capability metadata."""

    def __init__(self) -> None:
        self._registry: dict[tuple[str, str], ModelCapability] = {}

    def register(self, capability: ModelCapability) -> None:
        self._registry[(capability.provider, capability.model_name)] = capability

    def get(self, provider: str, model_name: str) -> ModelCapability | None:
        return self._registry.get((provider, model_name))

    def require(self, provider: str, model_name: str) -> ModelCapability:
        cap = self.get(provider, model_name)
        if cap is None:
            raise UnknownModelError(
                f"Model '{model_name}' for provider '{provider}' is not registered"
            )
        return cap

    def assert_supports_json_mode(self, provider: str, model_name: str) -> None:
        cap = self.get(provider, model_name)
        if cap is not None and not cap.supports_json_mode:
            raise UnsupportedCapabilityError(
                f"Model '{model_name}' does not support JSON output mode"
            )

    def assert_supports_tool_calling(self, provider: str, model_name: str) -> None:
        cap = self.get(provider, model_name)
        if cap is not None and not cap.supports_tool_calling:
            raise UnsupportedCapabilityError(f"Model '{model_name}' does not support tool calling")

    def assert_is_embedding_model(self, provider: str, model_name: str) -> None:
        cap = self.get(provider, model_name)
        if cap is not None and not cap.is_embedding_model:
            raise UnsupportedCapabilityError(f"Model '{model_name}' is not an embedding model")

    def assert_is_chat_model(self, provider: str, model_name: str) -> None:
        cap = self.get(provider, model_name)
        if cap is not None and not cap.is_chat_model:
            raise UnsupportedCapabilityError(f"Model '{model_name}' is not a chat model")

    def assert_embedding_dimension(self, provider: str, model_name: str, expected_dim: int) -> None:
        cap = self.get(provider, model_name)
        if cap is not None and cap.embedding_dimension is not None:
            if cap.embedding_dimension != expected_dim:
                raise UnsupportedCapabilityError(
                    f"Model '{model_name}' produces {cap.embedding_dimension}-dimensional "
                    f"embeddings, but {expected_dim} was expected"
                )


default_capability_registry = ModelCapabilityRegistry()
