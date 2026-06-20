from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


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


class EmbeddingProvider(Protocol):
    """Provider-neutral interface for text embedding generation."""

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        """Generate embeddings for the given texts, in input order."""
        ...
