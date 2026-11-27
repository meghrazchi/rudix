"""Query-embedding cache of the chat pipeline (R05-05).

Query vectors are cached in the application cache (``app.core.cache``) under the
organisation scope, namespace ``query_embedding``. The key is the SHA-256 of
``embedding model | dimensions | index version | normalised question`` (NFKC, casefold,
whitespace collapsed, stripped), so the question text never appears in a Redis key and a
change of model, dimensions, or index version never reuses an old vector. A vector is never
shared across organisations: the organisation id is part of every key.

``CACHE_ENABLED=false``, a missing client, or any Redis failure falls back to the provider.
A hit costs no provider tokens: the caller records a zero-token ledger entry.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Final
from uuid import UUID

from pydantic import TypeAdapter

from app.core.cache import OrgScope, get_or_load
from app.core.config import settings
from app.core.metrics import record_chat_query_embedding_cache
from app.core.question_normalization import normalise_question
from app.domains.chat.services.query_retrieval_service import QueryRetrievalService

NAMESPACE_QUERY_EMBEDDING: Final = "query_embedding"
_VECTOR_ADAPTER: Final = TypeAdapter(list[float])


def query_embedding_key(*, model: str, dimensions: int, index_version: str, question: str) -> str:
    material = f"{model}|{dimensions}|{index_version}|{normalise_question(question)}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CachedEmbedding:
    vector: list[float]
    # Provider prompt tokens of this call; 0 on a cache hit.
    prompt_tokens: int
    cache_hit: bool


async def embed_query_cached(
    service: QueryRetrievalService,
    *,
    organization_id: UUID,
    question: str,
) -> CachedEmbedding:
    """Return the question's vector from the cache, or embed it and cache the vector."""
    calls: list[int] = []

    async def load() -> list[float]:
        vector, prompt_tokens = await service.embed_query(question=question)
        calls.append(prompt_tokens)
        return vector

    vector = await get_or_load(
        scope=OrgScope(organization_id),
        namespace=NAMESPACE_QUERY_EMBEDDING,
        key_id=query_embedding_key(
            model=service.embedding_model,
            dimensions=service.vector_size,
            index_version=settings.document_index_version,
            question=question,
        ),
        ttl=settings.chat_query_embedding_cache_ttl_seconds,
        adapter=_VECTOR_ADAPTER,
        loader=load,
    )
    hit = not calls
    record_chat_query_embedding_cache("hit" if hit else "miss")
    return CachedEmbedding(vector=vector, prompt_tokens=0 if hit else calls[0], cache_hit=hit)
