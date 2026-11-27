"""Provider proxies that route chat completions and embeddings to an optional OpenAI client.

The client is read through ``client_getter`` on every call, so the chat module can keep its
rebindable ``_openai_client`` global (tests set it to a fake; ``None`` means the provider
factory). See contract 4.2.2 in docs/roadmap/V0_5_0_IMPLEMENTATION_PLAN.md.
"""

from collections.abc import AsyncIterator, Callable
from contextlib import aclosing
from time import perf_counter
from types import MethodType
from typing import Any

from app.domains.ai.providers.factory import default_provider_factory
from app.domains.ai.providers.openai.streaming import close_stream, parse_stream_chunk
from app.domains.ai.providers.protocols import (
    ChatCompletionChunk,
    ChatCompletionProvider,
    ChatCompletionRequest,
    ChatCompletionResponse,
    EmbeddingRequest,
    EmbeddingResponse,
)
from app.domains.ai.providers.resilience import unwrap
from app.domains.chat.services.llm_service import LLMService
from app.domains.chat.services.query_retrieval_service import QueryRetrievalService

ClientGetter = Callable[[], Any | None]


def _create_kwargs(request: ChatCompletionRequest) -> dict[str, Any]:
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": f"{request.system_message}\n\n{request.prompt}"},
    ]
    create_kwargs: dict[str, Any] = {
        "model": request.model,
        "messages": messages,
        "temperature": request.temperature,
    }
    if request.json_mode:
        create_kwargs["response_format"] = {"type": "json_object"}
    if request.max_tokens is not None:
        create_kwargs["max_tokens"] = request.max_tokens
    return create_kwargs


def _response_from_completion(
    response: Any, request: ChatCompletionRequest, latency_ms: int
) -> ChatCompletionResponse:
    choice = response.choices[0]
    message = getattr(choice, "message", None)
    content = getattr(message, "content", None) if message is not None else None
    usage = getattr(response, "usage", None)
    prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
    completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
    total_tokens = int(getattr(usage, "total_tokens", 0) or (prompt_tokens + completion_tokens))
    return ChatCompletionResponse(
        content=str(content or ""),
        model=str(getattr(response, "model", request.model) or request.model),
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        latency_ms=latency_ms,
    )


def _single_chunk(response: ChatCompletionResponse) -> ChatCompletionChunk:
    """A whole completion as one stream chunk (providers or clients without streaming)."""
    return ChatCompletionChunk(
        text_delta=response.content,
        prompt_tokens=response.prompt_tokens,
        completion_tokens=response.completion_tokens,
        model=response.model,
        finish_reason="stop",
    )


def _factory_chat_provider() -> ChatCompletionProvider:
    """The factory's default chat provider without its resilience wrapper: ``LLMService``
    wraps the proxy itself (R05-06), so one call passes one breaker and one org slot."""
    return unwrap(default_provider_factory.get_chat_provider(None))  # type: ignore[no-any-return]


class _ChatCompletionProviderProxy:
    def __init__(self, client_getter: ClientGetter) -> None:
        self._client_getter = client_getter

    async def complete(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        client = self._client_getter()
        if client is None:
            provider = _factory_chat_provider()
            return await provider.complete(request)

        started = perf_counter()
        response = await client.chat.completions.create(**_create_kwargs(request))
        latency_ms = max(0, int((perf_counter() - started) * 1000))
        return _response_from_completion(response, request, latency_ms)

    async def stream(self, request: ChatCompletionRequest) -> AsyncIterator[ChatCompletionChunk]:
        """Stream through the injected client when it answers ``stream=True`` with an async
        iterator, else (or for the provider factory without ``stream()``) one chunk."""
        client = self._client_getter()
        if client is None:
            provider = _factory_chat_provider()
            stream_fn = getattr(provider, "stream", None)
            if callable(stream_fn):
                async with aclosing(stream_fn(request)) as chunks:
                    async for chunk in chunks:
                        yield chunk
                return
            yield _single_chunk(await provider.complete(request))
            return

        create_kwargs = _create_kwargs(request)
        create_kwargs["stream"] = True
        create_kwargs["stream_options"] = {"include_usage": True}
        started = perf_counter()
        response = await client.chat.completions.create(**create_kwargs)
        if not hasattr(response, "__aiter__"):
            # A client (test fake) that ignores ``stream``: its answer is the whole completion.
            latency_ms = max(0, int((perf_counter() - started) * 1000))
            yield _single_chunk(_response_from_completion(response, request, latency_ms))
            return
        try:
            async for event in response:
                yield parse_stream_chunk(event)
        finally:
            await close_stream(response)


class _EmbeddingProviderProxy:
    def __init__(self, client_getter: ClientGetter) -> None:
        self._client_getter = client_getter

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        client = self._client_getter()
        if client is None:
            provider = default_provider_factory.get_embedding_provider()
            return await provider.embed(request)

        started = perf_counter()
        response = await client.embeddings.create(
            model=request.model,
            input=request.texts,
        )
        latency_ms = max(0, int((perf_counter() - started) * 1000))
        data = getattr(response, "data", []) or []
        vectors = [list(getattr(item, "embedding", []) or []) for item in data]
        usage = getattr(response, "usage", None)
        prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        total_tokens = int(getattr(usage, "total_tokens", 0) or prompt_tokens)
        return EmbeddingResponse(
            vectors=vectors,
            model=str(getattr(response, "model", request.model) or request.model),
            prompt_tokens=prompt_tokens,
            total_tokens=total_tokens,
            latency_ms=latency_ms,
        )


def bind_openai_client_proxies(
    *,
    llm_service: LLMService,
    query_retrieval_service: QueryRetrievalService,
    client_getter: ClientGetter,
) -> None:
    """Install the proxies and the provider resolvers on the two chat singletons."""
    llm_service._provider = _ChatCompletionProviderProxy(client_getter)
    query_retrieval_service._embedding_provider = _EmbeddingProviderProxy(client_getter)

    def _resolve_chat_embedding_provider(self: QueryRetrievalService) -> Any:
        if self._embedding_provider is not None:
            return self._embedding_provider
        if client_getter() is not None:
            return _EmbeddingProviderProxy(client_getter)
        return default_provider_factory.get_embedding_provider()

    def _resolve_chat_completion_provider(self: LLMService, provider_key: str | None = None) -> Any:
        if self._provider is not None:
            return self._provider
        if client_getter() is not None:
            return _ChatCompletionProviderProxy(client_getter)
        return default_provider_factory.get_chat_provider(provider_key)

    query_retrieval_service._resolve_embedding_provider = MethodType(  # type: ignore[method-assign]
        _resolve_chat_embedding_provider,
        query_retrieval_service,
    )
    llm_service._resolve_provider = MethodType(  # type: ignore[method-assign]
        _resolve_chat_completion_provider, llm_service
    )
