from __future__ import annotations

import asyncio
from dataclasses import dataclass
from decimal import Decimal
from time import perf_counter
from typing import Protocol
from uuid import UUID

from app.core.config import settings
from app.domains.ai.providers.errors import (
    ProviderInternalError,
    ProviderQuotaExceededError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from app.domains.ai.providers.protocols import EmbeddingProvider, EmbeddingRequest


class ChunkLike(Protocol):
    id: UUID
    text: str
    token_count: int


class TransientEmbeddingError(Exception):
    """Retryable embedding generation failure."""


class PermanentEmbeddingError(Exception):
    """Non-retryable embedding generation failure."""


@dataclass(frozen=True)
class EmbeddingResult:
    vectors_by_chunk_id: dict[UUID, list[float]]
    model_name: str
    index_version: str
    provider_type: str
    is_local: bool
    vector_dimension: int
    batch_count: int
    retry_count: int
    input_tokens: int
    total_tokens: int
    latency_ms: int
    approximate_cost_usd: Decimal


_TRANSIENT_PROVIDER_ERRORS = (
    TransientEmbeddingError,
    ProviderTimeoutError,
    ProviderQuotaExceededError,
    ProviderUnavailableError,
    ProviderInternalError,
)


class EmbeddingService:
    """Generate chunk embeddings with batching, retries, and usage tracking."""

    def __init__(
        self,
        *,
        model_name: str | None = None,
        index_version: str | None = None,
        provider_type: str | None = None,
        batch_max_items: int | None = None,
        batch_max_tokens: int | None = None,
        retry_max_attempts: int | None = None,
        retry_base_seconds: float | None = None,
        retry_max_seconds: float | None = None,
        cost_per_million_tokens_usd: float | None = None,
        provider: EmbeddingProvider | None = None,
    ) -> None:
        self.model_name = (model_name or settings.openai_embedding_model).strip()
        self.index_version = (index_version or settings.document_index_version).strip()
        self.provider_type = (provider_type or settings.embedding_default_provider).strip().lower()
        self.batch_max_items = batch_max_items or settings.embedding_batch_max_items
        self.batch_max_tokens = batch_max_tokens or settings.embedding_batch_max_tokens
        self.retry_max_attempts = retry_max_attempts or settings.embedding_retry_max_attempts
        self.retry_base_seconds = retry_base_seconds or settings.embedding_retry_base_seconds
        self.retry_max_seconds = retry_max_seconds or settings.embedding_retry_max_seconds
        self.cost_per_million_tokens_usd = Decimal(
            str(
                cost_per_million_tokens_usd
                or settings.openai_embedding_cost_per_million_tokens_usd
            )
        )
        self._provider = provider

    @property
    def embedding_provider(self) -> EmbeddingProvider:
        if self._provider is None:
            from app.domains.ai.providers.factory import default_provider_factory

            self._provider = default_provider_factory.get_embedding_provider()
        return self._provider

    def _build_batches(self, chunks: list[ChunkLike]) -> list[list[ChunkLike]]:
        batches: list[list[ChunkLike]] = []
        current_batch: list[ChunkLike] = []
        current_tokens = 0

        for chunk in chunks:
            chunk_tokens = max(0, chunk.token_count)
            if not chunk.text.strip():
                raise PermanentEmbeddingError(f"chunk {chunk.id} has empty text")

            exceeds_items = len(current_batch) >= self.batch_max_items
            exceeds_tokens = current_batch and (
                current_tokens + chunk_tokens > self.batch_max_tokens
            )
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
        return isinstance(exc, _TRANSIENT_PROVIDER_ERRORS)

    async def _embed_single_batch(
        self, *, batch: list[ChunkLike]
    ) -> tuple[list[list[float]], int, int, int, int]:
        texts = [chunk.text for chunk in batch]
        attempts = 0

        while attempts < self.retry_max_attempts:
            attempts += 1
            try:
                response = await self.embedding_provider.embed(
                    EmbeddingRequest(texts=texts, model=self.model_name)
                )
                if len(response.vectors) != len(batch):
                    raise PermanentEmbeddingError(
                        f"embedding response has wrong number of vectors: "
                        f"expected {len(batch)}, got {len(response.vectors)}"
                    )
                retries_used = attempts - 1
                return (
                    response.vectors,
                    response.prompt_tokens,
                    response.total_tokens,
                    response.latency_ms,
                    retries_used,
                )
            except PermanentEmbeddingError:
                raise
            except Exception as exc:
                if not self._is_transient_error(exc):
                    raise PermanentEmbeddingError(
                        f"embedding request failed permanently: {exc}"
                    ) from exc
                if attempts >= self.retry_max_attempts:
                    raise TransientEmbeddingError(
                        f"embedding request failed after retries: {exc}"
                    ) from exc
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
                provider_type=self.provider_type,
                is_local=self.provider_type == "local",
                vector_dimension=0,
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
            (
                vectors,
                batch_input_tokens,
                batch_total_tokens,
                latency_ms,
                retries_used,
            ) = await self._embed_single_batch(batch=batch)
            for chunk, vector in zip(batch, vectors, strict=True):
                vectors_by_chunk_id[chunk.id] = vector
            total_input_tokens += batch_input_tokens
            total_tokens += batch_total_tokens
            total_latency_ms += latency_ms
            total_retries += retries_used

        cost_usd = (Decimal(total_tokens) * self.cost_per_million_tokens_usd) / Decimal(1_000_000)
        first_vector = next(iter(vectors_by_chunk_id.values()), None)
        vector_dimension = len(first_vector) if first_vector is not None else 0

        return EmbeddingResult(
            vectors_by_chunk_id=vectors_by_chunk_id,
            model_name=self.model_name,
            index_version=self.index_version,
            provider_type=self.provider_type,
            is_local=self.provider_type == "local",
            vector_dimension=vector_dimension,
            batch_count=len(batches),
            retry_count=total_retries,
            input_tokens=total_input_tokens,
            total_tokens=total_tokens,
            latency_ms=total_latency_ms,
            approximate_cost_usd=cost_usd,
        )
