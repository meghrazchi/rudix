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
)


def _redact(message: str) -> str:
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


class LocalLLMClientLike(Protocol):
    chat: _ChatClientLike


class OpenAICompatibleChatProvider:
    """ChatCompletionProvider for OpenAI-compatible local endpoints.

    Compatible with Ollama, vLLM, LocalAI, LiteLLM proxy, and any gateway
    that implements /v1/chat/completions with the OpenAI wire format.
    """

    def __init__(
        self,
        *,
        client: LocalLLMClientLike,
        model_name: str,
        json_mode_enabled: bool = True,
    ) -> None:
        self._client = client
        self._model_name = model_name
        self._json_mode_enabled = json_mode_enabled

    async def complete(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        model = request.model or self._model_name
        use_json_mode = request.json_mode and self._json_mode_enabled

        payload: dict[str, object] = {
            "model": model,
            "messages": [
                {"role": "system", "content": request.system_message},
                {"role": "user", "content": request.prompt},
            ],
            "temperature": request.temperature,
        }
        if use_json_mode:
            payload["response_format"] = {"type": "json_object"}
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens

        started = perf_counter()
        try:
            response = await self._client.chat.completions.create(**payload)
        except RateLimitError as exc:
            raise ProviderQuotaExceededError(
                f"Local LLM rate limit exceeded: {_redact(str(exc))}"
            ) from exc
        except APITimeoutError as exc:
            raise ProviderTimeoutError(
                f"Local LLM request timed out: {_redact(str(exc))}"
            ) from exc
        except APIConnectionError as exc:
            raise ProviderUnavailableError(
                f"Local LLM is unreachable: {_redact(str(exc))}"
            ) from exc
        except (AuthenticationError, PermissionDeniedError) as exc:
            raise ProviderPolicyBlockedError(
                f"Local LLM rejected the request: {_redact(str(exc))}"
            ) from exc
        except BadRequestError as exc:
            msg = str(exc).lower()
            if "response_format" in msg and ("support" in msg or "not supported" in msg):
                raise UnsupportedCapabilityError(
                    "Local LLM does not support JSON response_format"
                ) from exc
            raise InvalidProviderResponseError(
                f"Local LLM bad request: {_redact(str(exc))}"
            ) from exc
        except InternalServerError as exc:
            raise ProviderInternalError(
                f"Local LLM internal error: {_redact(str(exc))}"
            ) from exc
        except OSError as exc:
            raise ProviderUnavailableError(
                f"Network error reaching local LLM: {_redact(str(exc))}"
            ) from exc
        except Exception as exc:
            raise ProviderInternalError(
                f"Unexpected local LLM error: {_redact(str(exc))}"
            ) from exc

        latency_ms = int((perf_counter() - started) * 1000)
        choices = getattr(response, "choices", None) or []
        if not choices:
            raise InvalidProviderResponseError("Local LLM response contained no choices")

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
