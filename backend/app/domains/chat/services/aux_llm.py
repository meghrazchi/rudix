"""Model routing and usage accounting for auxiliary chat LLM calls (R05-07, R05-08).

Query rewriting, conflict detection, grounded verification, and the answer refiner (and
the reranker when no rerank model is configured) run on the organisation's resolved
``chat`` model profile when the pipeline passes one. Without a profile (callers outside
the chat pipeline, such as evaluations) they keep the environment default provider and
``OPENAI_LLM_MODEL``, as before.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.core.config import settings
from app.domains.ai.profile.schemas import ResolvedTaskProfile
from app.domains.ai.providers.protocols import ChatCompletionResponse


@dataclass(frozen=True)
class AuxRoute:
    """Provider and model for one auxiliary call; ``provider_key`` is ``None`` without a
    profile, meaning the factory's default provider."""

    provider_key: str | None
    model_name: str

    @property
    def reported_provider_key(self) -> str:
        return self.provider_key or settings.llm_default_provider


@dataclass(frozen=True)
class AuxCallUsage:
    """Token usage of one completed provider call (ledger input, no text)."""

    provider_key: str
    model_name: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    cost_usd: Decimal | None = None

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


def resolve_aux_route(resolved_profile: ResolvedTaskProfile | None) -> AuxRoute:
    if resolved_profile is not None:
        return AuxRoute(
            provider_key=resolved_profile.provider_type,
            model_name=resolved_profile.base_model,
        )
    return AuxRoute(provider_key=None, model_name=settings.openai_llm_model)


def estimate_llm_cost(prompt_tokens: int, completion_tokens: int) -> Decimal:
    """Approximate cost with the configured LLM token prices (same rates as the answer)."""
    input_rate = Decimal(str(settings.openai_llm_input_cost_per_million_tokens_usd))
    output_rate = Decimal(str(settings.openai_llm_output_cost_per_million_tokens_usd))
    return (
        Decimal(prompt_tokens) * input_rate + Decimal(completion_tokens) * output_rate
    ) / Decimal(1_000_000)


def cached_prompt_tokens(response: object) -> int:
    """Cached prompt tokens when the provider reports them (0 otherwise)."""
    value = getattr(response, "cached_prompt_tokens", 0) or 0
    return int(value) if isinstance(value, int) else 0


def usage_from_response(route: AuxRoute, response: ChatCompletionResponse) -> AuxCallUsage:
    # Providers that report no usage (some local servers) count as 0 tokens.
    prompt_tokens = max(0, int(getattr(response, "prompt_tokens", 0) or 0))
    completion_tokens = max(0, int(getattr(response, "completion_tokens", 0) or 0))
    return AuxCallUsage(
        provider_key=route.reported_provider_key,
        model_name=route.model_name,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cached_tokens=cached_prompt_tokens(response),
        cost_usd=estimate_llm_cost(prompt_tokens, completion_tokens),
    )
