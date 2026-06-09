from __future__ import annotations

from time import perf_counter
from typing import Any, Protocol

from openai import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    InternalServerError,
    PermissionDeniedError,
    RateLimitError,
)

from app.domains.ai.providers.errors import (
    InvalidProviderResponseError,
    ProviderInternalError,
    ProviderPolicyBlockedError,
    ProviderQuotaExceededError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from app.domains.ai.providers.protocols import EmbeddingRequest, EmbeddingResponse


def _redact(message: str) -> str:
    for fragment in ("sk-", "Bearer ", "token=", "key=", "secret="):
        if fragment in message:
            idx = message.index(fragment)
            message = message[:idx] + "[REDACTED]"
            break
    return message


class _EmbeddingsEndpointLike(Protocol):
    async def create(self, *, model: str, input: list[str]) -> Any: ...


class LocalEmbeddingClientLike(Protocol):
    embeddings: _EmbeddingsEndpointLike


class OpenAICompatibleEmbeddingProvider:
    """EmbeddingProvider for OpenAI-compatible local endpoints.

    Compatible with Ollama, vLLM, LocalAI, LiteLLM proxy, and any gateway
    that implements /v1/embeddings with the OpenAI wire format.

    Usage tokens are optional — local endpoints often omit them. When missing,
    prompt_tokens and total_tokens are reported as 0 rather than raising an error.
    """

    def __init__(self, *, client: LocalEmbeddingClientLike, model_name: str) -> None:
        self._client = client
        self._model_name = model_name

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        model = request.model or self._model_name
        started = perf_counter()
        try:
            response = await self._client.embeddings.create(
                model=model, input=request.texts
            )
        except RateLimitError as exc:
            raise ProviderQuotaExceededError(
                f"Local embedding rate limit exceeded: {_redact(str(exc))}"
            ) from exc
        except APITimeoutError as exc:
            raise ProviderTimeoutError(
                f"Local embedding timed out: {_redact(str(exc))}"
            ) from exc
        except APIConnectionError as exc:
            raise ProviderUnavailableError(
                f"Local embedding endpoint unreachable: {_redact(str(exc))}"
            ) from exc
        except (AuthenticationError, PermissionDeniedError) as exc:
            raise ProviderPolicyBlockedError(
                f"Local embedding rejected the request: {_redact(str(exc))}"
            ) from exc
        except InternalServerError as exc:
            raise ProviderInternalError(
                f"Local embedding internal error: {_redact(str(exc))}"
            ) from exc
        except OSError as exc:
            raise ProviderUnavailableError(
                f"Network error reaching local embedding endpoint: {_redact(str(exc))}"
            ) from exc
        except Exception as exc:
            raise ProviderInternalError(
                f"Unexpected local embedding error: {_redact(str(exc))}"
            ) from exc

        latency_ms = int((perf_counter() - started) * 1000)
        n = len(request.texts)
        vectors: list[list[float] | None] = [None] * n
        for item in response.data:
            index = int(item.index)
            if index < 0 or index >= n:
                raise InvalidProviderResponseError(
                    f"Local embedding response index out of range: {index}"
                )
            vectors[index] = [float(v) for v in item.embedding]

        if any(v is None for v in vectors):
            raise InvalidProviderResponseError(
                "Local embedding response is missing vectors"
            )

        # Local endpoints may omit usage entirely; fall back to 0 rather than failing.
        usage = getattr(response, "usage", None)
        prompt_tokens = int(getattr(usage, "prompt_tokens", 0)) if usage is not None else 0
        total_tokens = int(getattr(usage, "total_tokens", prompt_tokens)) if usage is not None else 0

        return EmbeddingResponse(
            vectors=[v for v in vectors if v is not None],
            model=model,
            prompt_tokens=prompt_tokens,
            total_tokens=total_tokens,
            latency_ms=latency_ms,
        )
