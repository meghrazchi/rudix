from __future__ import annotations

from time import perf_counter
from typing import Any, Protocol

from openai import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
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
    UnsupportedCapabilityError,
)
from app.domains.ai.providers.protocols import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    EmbeddingRequest,
    EmbeddingResponse,
)


def _redact(message: str) -> str:
    """Strip potential credential fragments from error messages."""
    for fragment in ("sk-", "Bearer ", "token=", "key=", "secret="):
        if fragment in message:
            idx = message.index(fragment)
            message = message[:idx] + "[REDACTED]"
            break
    return message


def _extract_content(content: object) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            text = getattr(item, "text", None)
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
        return "\n".join(parts).strip()
    return ""


class _ChatEndpointLike(Protocol):
    async def create(self, **kwargs: object) -> Any: ...


class _ChatClientLike(Protocol):
    completions: _ChatEndpointLike


class OpenAIChatClientLike(Protocol):
    chat: _ChatClientLike


class OpenAIChatProvider:
    """ChatCompletionProvider backed by the OpenAI chat completions API."""

    def __init__(self, *, client: OpenAIChatClientLike, model_name: str) -> None:
        self._client = client
        self._model_name = model_name

    async def complete(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        model = request.model or self._model_name
        payload: dict[str, object] = {
            "model": model,
            "messages": [
                {"role": "system", "content": request.system_message},
                {"role": "user", "content": request.prompt},
            ],
            "temperature": request.temperature,
        }
        if request.json_mode:
            payload["response_format"] = {"type": "json_object"}
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens

        started = perf_counter()
        try:
            response = await self._client.chat.completions.create(**payload)
        except RateLimitError as exc:
            raise ProviderQuotaExceededError(
                f"OpenAI rate limit exceeded: {_redact(str(exc))}"
            ) from exc
        except APITimeoutError as exc:
            raise ProviderTimeoutError(f"OpenAI request timed out: {_redact(str(exc))}") from exc
        except APIConnectionError as exc:
            raise ProviderUnavailableError(f"OpenAI is unreachable: {_redact(str(exc))}") from exc
        except (AuthenticationError, PermissionDeniedError) as exc:
            raise ProviderPolicyBlockedError(
                f"OpenAI rejected the request: {_redact(str(exc))}"
            ) from exc
        except BadRequestError as exc:
            msg = str(exc).lower()
            if "response_format" in msg and ("support" in msg or "not supported" in msg):
                raise UnsupportedCapabilityError(
                    "Model does not support JSON response_format"
                ) from exc
            raise InvalidProviderResponseError(f"OpenAI bad request: {_redact(str(exc))}") from exc
        except InternalServerError as exc:
            raise ProviderInternalError(f"OpenAI internal error: {_redact(str(exc))}") from exc
        except OSError as exc:
            raise ProviderUnavailableError(
                f"Network error reaching OpenAI: {_redact(str(exc))}"
            ) from exc
        except Exception as exc:
            raise ProviderInternalError(f"Unexpected OpenAI error: {_redact(str(exc))}") from exc

        latency_ms = int((perf_counter() - started) * 1000)
        choices = getattr(response, "choices", None) or []
        if not choices:
            raise InvalidProviderResponseError("OpenAI response contained no choices")

        content = _extract_content(choices[0].message.content)
        resolved_model = str(getattr(response, "model", model))
        usage = getattr(response, "usage", None)
        prompt_tokens = int(getattr(usage, "prompt_tokens", 0)) if usage is not None else 0
        completion_tokens = int(getattr(usage, "completion_tokens", 0)) if usage is not None else 0
        total_tokens = (
            int(getattr(usage, "total_tokens", prompt_tokens + completion_tokens))
            if usage is not None
            else prompt_tokens + completion_tokens
        )
        return ChatCompletionResponse(
            content=content,
            model=resolved_model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            latency_ms=latency_ms,
        )


class _EmbeddingsEndpointLike(Protocol):
    async def create(self, *, model: str, input: list[str]) -> Any: ...


class OpenAIEmbeddingClientLike(Protocol):
    embeddings: _EmbeddingsEndpointLike


class OpenAIEmbeddingProvider:
    """EmbeddingProvider backed by the OpenAI embeddings API."""

    def __init__(self, *, client: OpenAIEmbeddingClientLike, model_name: str) -> None:
        self._client = client
        self._model_name = model_name

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        model = request.model or self._model_name
        started = perf_counter()
        try:
            response = await self._client.embeddings.create(model=model, input=request.texts)
        except RateLimitError as exc:
            raise ProviderQuotaExceededError(
                f"OpenAI rate limit exceeded: {_redact(str(exc))}"
            ) from exc
        except APITimeoutError as exc:
            raise ProviderTimeoutError(f"OpenAI embedding timed out: {_redact(str(exc))}") from exc
        except APIConnectionError as exc:
            raise ProviderUnavailableError(
                f"OpenAI embeddings unreachable: {_redact(str(exc))}"
            ) from exc
        except (AuthenticationError, PermissionDeniedError) as exc:
            raise ProviderPolicyBlockedError(
                f"OpenAI rejected the embedding request: {_redact(str(exc))}"
            ) from exc
        except InternalServerError as exc:
            raise ProviderInternalError(
                f"OpenAI embedding internal error: {_redact(str(exc))}"
            ) from exc
        except OSError as exc:
            raise ProviderUnavailableError(
                f"Network error reaching OpenAI embeddings: {_redact(str(exc))}"
            ) from exc
        except Exception as exc:
            raise ProviderInternalError(
                f"Unexpected OpenAI embedding error: {_redact(str(exc))}"
            ) from exc

        latency_ms = int((perf_counter() - started) * 1000)
        n = len(request.texts)
        vectors: list[list[float] | None] = [None] * n
        for item in response.data:
            index = int(item.index)
            if index < 0 or index >= n:
                raise InvalidProviderResponseError(
                    f"OpenAI embedding response index out of range: {index}"
                )
            vectors[index] = [float(v) for v in item.embedding]

        if any(v is None for v in vectors):
            raise InvalidProviderResponseError("OpenAI embedding response is missing vectors")

        usage = getattr(response, "usage", None)
        prompt_tokens = int(getattr(usage, "prompt_tokens", 0)) if usage is not None else 0
        total_tokens = (
            int(getattr(usage, "total_tokens", prompt_tokens))
            if usage is not None
            else prompt_tokens
        )

        return EmbeddingResponse(
            vectors=[v for v in vectors if v is not None],
            model=model,
            prompt_tokens=prompt_tokens,
            total_tokens=total_tokens,
            latency_ms=latency_ms,
        )
