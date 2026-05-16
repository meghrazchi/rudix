from __future__ import annotations

import asyncio
from dataclasses import dataclass
from decimal import Decimal
from time import perf_counter
from typing import Any, Protocol
from uuid import UUID

from openai import (
    APIConnectionError,
    APITimeoutError,
    AsyncOpenAI,
    InternalServerError,
    RateLimitError,
)

from app.core.config import settings


class ChunkLike(Protocol):
    id: UUID
    text: str
    token_count: int


class EmbeddingsEndpointLike(Protocol):
    async def create(self, *, model: str, input: list[str]) -> Any:
        ...


class OpenAIClientLike(Protocol):
    embeddings: EmbeddingsEndpointLike


class TransientEmbeddingError(Exception):
    """Retryable embedding generation failure."""


class PermanentEmbeddingError(Exception):
    """Non-retryable embedding generation failure."""


@dataclass(frozen=True)
class EmbeddingResult:
    vectors_by_chunk_id: dict[UUID, list[float]]
    model_name: str
    index_version: str
    batch_count: int
    retry_count: int
    input_tokens: int
    total_tokens: int
    latency_ms: int
    approximate_cost_usd: Decimal


class EmbeddingService:
    """Generate chunk embeddings with batching, retries, and usage tracking."""

    def __init__(
        self,
        *,
        model_name: str | None = None,
        index_version: str | None = None,
        batch_max_items: int | None = None,
        batch_max_tokens: int | None = None,
        retry_max_attempts: int | None = None,
        retry_base_seconds: float | None = None,
        retry_max_seconds: float | None = None,
        cost_per_million_tokens_usd: float | None = None,
        openai_client: OpenAIClientLike | None = None,
    ) -> None:
        self.model_name = (model_name or settings.openai_embedding_model).strip()
        self.index_version = (index_version or settings.document_index_version).strip()
        self.batch_max_items = batch_max_items or settings.embedding_batch_max_items
        self.batch_max_tokens = batch_max_tokens or settings.embedding_batch_max_tokens
        self.retry_max_attempts = retry_max_attempts or settings.embedding_retry_max_attempts
        self.retry_base_seconds = retry_base_seconds or settings.embedding_retry_base_seconds
        self.retry_max_seconds = retry_max_seconds or settings.embedding_retry_max_seconds
        self.cost_per_million_tokens_usd = Decimal(
            str(cost_per_million_tokens_usd or settings.openai_embedding_cost_per_million_tokens_usd)
        )
        self._openai_client = openai_client

    @property
    def openai_client(self) -> OpenAIClientLike:
        if self._openai_client is None:
            if settings.openai_api_key is None:
                raise PermanentEmbeddingError("openai_api_key is not configured")
            timeout_seconds = max(
                settings.dependency_connect_timeout_seconds,
                settings.dependency_read_timeout_seconds,
            )
            self._openai_client = AsyncOpenAI(
                api_key=settings.openai_api_key.get_secret_value(),
                timeout=timeout_seconds,
                max_retries=0,
            )
        return self._openai_client

    def _build_batches(self, chunks: list[ChunkLike]) -> list[list[ChunkLike]]:
        batches: list[list[ChunkLike]] = []
        current_batch: list[ChunkLike] = []
        current_tokens = 0

        for chunk in chunks:
            chunk_tokens = max(0, chunk.token_count)
            if not chunk.text.strip():
                raise PermanentEmbeddingError(f"chunk {chunk.id} has empty text")

            exceeds_items = len(current_batch) >= self.batch_max_items
            exceeds_tokens = current_batch and (current_tokens + chunk_tokens > self.batch_max_tokens)
            if exceeds_items or exceeds_tokens:
                batches.append(current_batch)
                current_batch = []
                current_tokens = 0

            current_batch.append(chunk)
            current_tokens += chunk_tokens

        if current_batch:
            batches.append(current_batch)

        return batches

    @staticmethod
    def _is_transient_error(exc: Exception) -> bool:
        return isinstance(
            exc,
            (
                TransientEmbeddingError,
                APIConnectionError,
                APITimeoutError,
                RateLimitError,
                InternalServerError,
                TimeoutError,
                ConnectionError,
                OSError,
            ),
        )

    async def _embed_single_batch(self, *, batch: list[ChunkLike]) -> tuple[list[list[float]], int, int, int, int]:
        texts = [chunk.text for chunk in batch]
        fallback_tokens = sum(max(0, chunk.token_count) for chunk in batch)
        attempts = 0

        while attempts < self.retry_max_attempts:
            attempts += 1
            started = perf_counter()
            try:
                response = await self.openai_client.embeddings.create(model=self.model_name, input=texts)
                latency_ms = int((perf_counter() - started) * 1000)

                vectors: list[list[float] | None] = [None] * len(batch)
                for item in response.data:
                    index = int(item.index)
                    if index < 0 or index >= len(batch):
                        raise PermanentEmbeddingError(f"embedding response index out of range: {index}")
                    vectors[index] = [float(value) for value in item.embedding]

                if any(vector is None for vector in vectors):
                    raise PermanentEmbeddingError("embedding response is missing vectors")

                prompt_tokens = int(getattr(response.usage, "prompt_tokens", fallback_tokens))
                total_tokens = int(getattr(response.usage, "total_tokens", prompt_tokens))
                retries_used = attempts - 1
                return [vector for vector in vectors if vector is not None], prompt_tokens, total_tokens, latency_ms, retries_used
            except Exception as exc:
                if not self._is_transient_error(exc):
                    raise PermanentEmbeddingError(f"embedding request failed permanently: {exc}") from exc
                if attempts >= self.retry_max_attempts:
                    raise TransientEmbeddingError(f"embedding request failed after retries: {exc}") from exc
                backoff_seconds = min(
                    self.retry_max_seconds,
                    self.retry_base_seconds * (2 ** (attempts - 1)),
                )
                await asyncio.sleep(backoff_seconds)

        raise TransientEmbeddingError("embedding request failed after retries")

    async def embed_chunks(self, *, chunks: list[ChunkLike]) -> EmbeddingResult:
        if not chunks:
            return EmbeddingResult(
                vectors_by_chunk_id={},
                model_name=self.model_name,
                index_version=self.index_version,
                batch_count=0,
                retry_count=0,
                input_tokens=0,
                total_tokens=0,
                latency_ms=0,
                approximate_cost_usd=Decimal("0"),
            )

        batches = self._build_batches(chunks)

        vectors_by_chunk_id: dict[UUID, list[float]] = {}
        total_input_tokens = 0
        total_tokens = 0
        total_latency_ms = 0
        total_retries = 0

        for batch in batches:
            vectors, batch_input_tokens, batch_total_tokens, latency_ms, retries_used = await self._embed_single_batch(batch=batch)
            for chunk, vector in zip(batch, vectors, strict=True):
                vectors_by_chunk_id[chunk.id] = vector
            total_input_tokens += batch_input_tokens
            total_tokens += batch_total_tokens
            total_latency_ms += latency_ms
            total_retries += retries_used

        cost_usd = (Decimal(total_tokens) * self.cost_per_million_tokens_usd) / Decimal(1_000_000)

        return EmbeddingResult(
            vectors_by_chunk_id=vectors_by_chunk_id,
            model_name=self.model_name,
            index_version=self.index_version,
            batch_count=len(batches),
            retry_count=total_retries,
            input_tokens=total_input_tokens,
            total_tokens=total_tokens,
            latency_ms=total_latency_ms,
            approximate_cost_usd=cost_usd,
        )
