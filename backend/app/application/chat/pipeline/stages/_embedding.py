"""Query embedding of the chat pipeline: cache and overlap with configuration (R05-04/05).

Dependency graph (checked for R05-04): the query embedding depends only on the retrieval
query text and on ``QueryRetrievalService.embedding_model`` / ``vector_size``, which come
from settings at start-up (``OPENAI_EMBEDDING_MODEL``, ``QDRANT_VECTOR_SIZE``) and never from
the RAG profile, the model profile, the AI policy, or the tool policy (B1 keeps query
embeddings on the index's embedding model). What can change is *which* texts are embedded:
query rewriting (stage 5) may replace or decompose the question. So the original question's
embedding is started in ``resolve_config`` as a background task only when rewriting cannot
apply (``FEATURE_ENABLE_QUERY_REWRITING`` off, or the RAG profile disables both rewriting
and decomposition) and the question goes down the grounded path; ``retrieve`` awaits it when
the original question is among the retrieval queries. Otherwise nothing is started, so no
provider call is ever wasted.

The overlap is off by default (``CHAT_QUERY_EMBEDDING_PREFETCH_ENABLED=false``): while
stage 2 runs, its read-phase connection is checked out, so a prefetched embedding runs while
a connection is held. The connection is not held *longer* (the read phase ends when stage 4
does, whether or not the embedding finished), but R05-02's invariant is that no connection
is checked out during a provider call, and ``test_chat_session_lifetime`` asserts exactly
that.
"""

import asyncio

from app.application.chat.pipeline.context import ChatContext
from app.core.config import settings
from app.domains.chat.services.parallel_retrieval_optimizer import QueryEmbedder
from app.domains.chat.services.query_embedding_cache import CachedEmbedding, embed_query_cached
from app.domains.rag_profiles.schemas.rag_profiles import RagProfileConfig


def _rewriting_possible(ctx: ChatContext) -> bool:
    if not settings.feature_enable_query_rewriting:
        return False
    rag_profile = ctx.config.rag_profile
    if rag_profile is None:
        return True
    profile_cfg = RagProfileConfig.model_validate(dict(rag_profile.config))
    return profile_cfg.query_rewriting_enabled or profile_cfg.query_decomposition_enabled


def _grounded_retrieval_expected(ctx: ChatContext) -> bool:
    cfg = ctx.config
    return (
        not cfg.blocked
        and cfg.answer_mode_result is not None
        and cfg.answer_mode_result.mode == "grounded"
        and not cfg.scope_inventory_requested
    )


def _consume_exception(task: "asyncio.Task[CachedEmbedding]") -> None:
    # Retrieve sees a failed prefetch and embeds again; never leave the error unretrieved.
    if not task.cancelled():
        task.exception()


def start_embedding_prefetch(ctx: ChatContext) -> bool:
    """Start the original question's embedding in the background when it is safe to."""
    if ctx.prefetched_embedding is not None:
        return True
    if not settings.chat_query_embedding_prefetch_enabled:
        return False
    if not _grounded_retrieval_expected(ctx) or _rewriting_possible(ctx):
        return False
    task = asyncio.create_task(
        embed_query_cached(
            ctx.deps.query_retrieval_service,
            organization_id=ctx.request.organization_id,
            question=ctx.request.payload.question,
        )
    )
    task.add_done_callback(_consume_exception)
    ctx.prefetched_embedding = task
    ctx.background_tasks.append(task)
    return True


def build_query_embedder(ctx: ChatContext) -> QueryEmbedder:
    """Embedder for the retrieval branches: the prefetched original question (once), else
    the query-embedding cache, else the provider."""
    service = ctx.deps.query_retrieval_service
    organization_id = ctx.request.organization_id
    original = ctx.request.payload.question
    prefetch = ctx.prefetched_embedding
    consumed = False

    async def embed(query: str) -> tuple[list[float], int]:
        nonlocal consumed
        if prefetch is not None and not consumed and query == original:
            try:
                # Shielded: a branch timeout must not cancel the shared task.
                result = await asyncio.shield(prefetch)
            except asyncio.CancelledError:
                if not prefetch.cancelled():
                    raise
            except Exception:  # the cached path below embeds again
                pass
            else:
                consumed = True
                return result.vector, result.prompt_tokens
        cached = await embed_query_cached(service, organization_id=organization_id, question=query)
        return cached.vector, cached.prompt_tokens

    return embed
