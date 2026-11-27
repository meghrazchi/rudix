from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class ChatCompletionRequest:
    prompt: str
    model: str = ""
    temperature: float = 0.0
    json_mode: bool = True
    max_tokens: int | None = None
    system_message: str = "Answer questions only from retrieved document context."


@dataclass(frozen=True)
class ChatCompletionResponse:
    content: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_ms: int
    # True when a stream reported no usage and the counts are chars / 4 estimates (R05-03).
    usage_estimated: bool = False


@dataclass
class EmbeddingRequest:
    texts: list[str]
    model: str = ""


@dataclass(frozen=True)
class EmbeddingResponse:
    vectors: list[list[float]]
    model: str
    prompt_tokens: int
    total_tokens: int
    latency_ms: int


class ChatCompletionProvider(Protocol):
    """Provider-neutral interface for LLM chat completions."""

    async def complete(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        """Send a chat completion and return the structured response."""
        ...


@dataclass(frozen=True)
class ChatCompletionChunk:
    """One increment of a streamed chat completion (R05-03).

    ``text_delta`` is the raw content increment (may be empty). Usage fields are set only on
    the chunk that carries provider-reported usage (OpenAI: the last one with
    ``stream_options.include_usage``); ``None`` means not reported.
    """

    text_delta: str = ""
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cached_prompt_tokens: int | None = None
    model: str | None = None
    finish_reason: str | None = None


@runtime_checkable
class StreamingChatCompletionProvider(Protocol):
    """Optional streaming interface; providers without it fall back to ``complete()``."""

    def stream(self, request: ChatCompletionRequest) -> AsyncIterator[ChatCompletionChunk]:
        """Yield the completion as it is generated. Closing the iterator (``aclose``)
        closes the underlying provider stream."""
        ...


class EmbeddingProvider(Protocol):
    """Provider-neutral interface for text embedding generation."""

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        """Generate embeddings for the given texts, in input order."""
        ...
