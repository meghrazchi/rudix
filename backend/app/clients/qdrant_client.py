"""Qdrant clients (R06-07).

- ``qdrant_client``: the synchronous client for startup bootstrap, the readiness probe,
  and scripts. ``init_qdrant`` creates it and, with ``QDRANT_BOOTSTRAP_COLLECTION``, runs
  ``ensure_qdrant_collection`` once (API startup, worker process start, migrate job).
- ``get_async_search_client()`` / ``get_async_write_client()``: ``AsyncQdrantClient``
  instances with the short search and the long write timeout, created lazily for the
  running event loop (the API loop, the worker loop of ``app.workers.async_runtime``)
  and closed by ``close_async_qdrant_clients()`` on shutdown.
- A client assigned to ``qdrant_client`` by anything other than ``init_qdrant`` (tests,
  tools) is an injected override: ``injected_sync_client()`` returns it, and the request
  and write paths then use it through their synchronous fallback.
"""

from __future__ import annotations

import asyncio

from qdrant_client import AsyncQdrantClient, QdrantClient
from qdrant_client.http.models import (
    IntegerIndexParams,
    IntegerIndexType,
    KeywordIndexParams,
    KeywordIndexType,
    VectorParams,
)

from app.clients.factory import (
    create_async_qdrant_client,
    create_qdrant_client,
    qdrant_distance_to_model,
)
from app.clients.qdrant_tuning import (
    create_collection_kwargs,
    vectors_on_disk,
    warn_on_tuning_drift,
)
from app.core.config import settings
from app.core.logging import get_logger

qdrant_client: QdrantClient | None = None
# The client init_qdrant created; any other value of ``qdrant_client`` was injected.
_initialized_client: QdrantClient | None = None
# (kind, id(loop)) -> (loop, client); entries of closed loops are dropped on access.
_async_clients: dict[tuple[str, int], tuple[asyncio.AbstractEventLoop, AsyncQdrantClient]] = {}
logger = get_logger("clients.qdrant")


def init_qdrant() -> None:
    global qdrant_client, _initialized_client
    qdrant_client = create_qdrant_client(settings)
    _initialized_client = qdrant_client
    try:
        qdrant_client.get_collections()
        if settings.qdrant_bootstrap_collection:
            ensure_qdrant_collection()
        logger.info(
            "qdrant.init.success",
            url=str(settings.qdrant_url),
            collection=settings.qdrant_collection,
            vector_size=settings.qdrant_vector_size,
            distance=settings.qdrant_distance.value,
            bootstrap_collection=settings.qdrant_bootstrap_collection,
        )
    except Exception as exc:
        logger.error(
            "qdrant.init.failed",
            url=str(settings.qdrant_url),
            collection=settings.qdrant_collection,
            error=exc.__class__.__name__,
            exc_info=exc,
        )
        try:
            close_qdrant()
        finally:
            # A closed client cannot reconnect; None lets consumers and the
            # readiness probe re-initialize once Qdrant is reachable (R04-12).
            qdrant_client = None
            _initialized_client = None
        raise


def close_qdrant() -> None:
    if qdrant_client is not None:
        qdrant_client.close()
        logger.info("qdrant.close")


def injected_sync_client() -> QdrantClient | None:
    """``qdrant_client`` when it was set by something other than ``init_qdrant``."""
    if qdrant_client is not None and qdrant_client is not _initialized_client:
        return qdrant_client
    return None


def search_timeout_seconds() -> float:
    configured = settings.qdrant_search_timeout_seconds
    return configured if configured is not None else settings.qdrant_timeout_seconds


def _async_client(kind: str, timeout_seconds: float) -> AsyncQdrantClient:
    loop = asyncio.get_running_loop()
    for key in [key for key, (owner, _) in _async_clients.items() if owner.is_closed()]:
        _async_clients.pop(key, None)
    entry = _async_clients.get((kind, id(loop)))
    if entry is not None and entry[0] is loop:
        return entry[1]
    client = create_async_qdrant_client(settings, timeout_seconds=timeout_seconds)
    _async_clients[(kind, id(loop))] = (loop, client)
    logger.info("qdrant.async_client.created", kind=kind, timeout_seconds=timeout_seconds)
    return client


def get_async_search_client() -> AsyncQdrantClient:
    """Request-path client (``QDRANT_SEARCH_TIMEOUT_SECONDS``) of the running loop."""
    return _async_client("search", search_timeout_seconds())


def get_async_write_client() -> AsyncQdrantClient:
    """Write client (``QDRANT_WRITE_TIMEOUT_SECONDS``) of the running loop."""
    return _async_client("write", settings.qdrant_write_timeout_seconds)


async def close_async_qdrant_clients() -> None:
    """Close the async clients of the running loop (API and worker shutdown)."""
    loop = asyncio.get_running_loop()
    for key, (owner, client) in list(_async_clients.items()):
        if owner is not loop:
            continue
        _async_clients.pop(key, None)
        try:
            await client.close()
        except Exception as exc:
            logger.warning("qdrant.async_client.close_failed", error=type(exc).__name__)


def check_qdrant_health() -> bool:
    if qdrant_client is None:
        # Degraded boot (R04-12): reconnect from the readiness probe.
        try:
            init_qdrant()
        except Exception:
            return False
    client = qdrant_client
    if client is None:
        return False
    try:
        client.get_collections()
        return True
    except Exception:
        return False


def _normalize_distance(value: object) -> str:
    if value is None:
        return ""
    text = str(value).lower()
    if "." in text:
        text = text.split(".")[-1]
    return text


def ensure_qdrant_payload_indexes() -> None:
    """Ensure multi-tenant and retrieval filter payload indexes exist on the Qdrant collection.

    Idempotent: Qdrant accepts a repeated ``create_payload_index`` for the same schema.
    """
    if qdrant_client is None:
        raise RuntimeError("Qdrant client is not initialized")

    create_payload_index = getattr(qdrant_client, "create_payload_index", None)
    if not callable(create_payload_index):
        return

    collection_name = settings.qdrant_collection
    create_payload_index(
        collection_name=collection_name,
        field_name="organization_id",
        field_schema=KeywordIndexParams(
            type=KeywordIndexType.KEYWORD,
            is_tenant=True,
        ),
    )
    create_payload_index(
        collection_name=collection_name,
        field_name="document_id",
        field_schema=KeywordIndexParams(type=KeywordIndexType.KEYWORD),
    )
    create_payload_index(
        collection_name=collection_name,
        field_name="index_version",
        field_schema=KeywordIndexParams(type=KeywordIndexType.KEYWORD),
    )
    create_payload_index(
        collection_name=collection_name,
        field_name="chunk_level",
        field_schema=IntegerIndexParams(type=IntegerIndexType.INTEGER),
    )
    # R06-06: embedding reuse looks points up by chunk hash.
    create_payload_index(
        collection_name=collection_name,
        field_name="chunk_hash",
        field_schema=KeywordIndexParams(type=KeywordIndexType.KEYWORD),
    )
    logger.info(
        "qdrant.payload_indexes.ensured",
        collection=collection_name,
        tenant_field="organization_id",
    )


def ensure_qdrant_collection() -> None:
    """Create or check the collection and its payload indexes (startup and migrate only)."""
    if qdrant_client is None:
        raise RuntimeError("Qdrant client is not initialized")

    exists = qdrant_client.collection_exists(settings.qdrant_collection)
    if not exists:
        qdrant_client.create_collection(
            collection_name=settings.qdrant_collection,
            vectors_config=VectorParams(
                size=settings.qdrant_vector_size,
                distance=qdrant_distance_to_model(settings.qdrant_distance),
                **vectors_on_disk(settings),
            ),
            **create_collection_kwargs(settings),
        )
        ensure_qdrant_payload_indexes()
        logger.info(
            "qdrant.collection.created",
            collection=settings.qdrant_collection,
            vector_size=settings.qdrant_vector_size,
            distance=settings.qdrant_distance.value,
            tuning=sorted(create_collection_kwargs(settings)),
        )
        return

    collection_info = qdrant_client.get_collection(settings.qdrant_collection)
    vectors = getattr(collection_info.config.params, "vectors", None)
    existing_size = getattr(vectors, "size", None)
    existing_distance = _normalize_distance(getattr(vectors, "distance", None))
    expected_distance = settings.qdrant_distance.value

    if existing_size != settings.qdrant_vector_size or existing_distance != expected_distance:
        logger.error(
            "qdrant.collection.mismatch",
            collection=settings.qdrant_collection,
            expected_vector_size=settings.qdrant_vector_size,
            actual_vector_size=existing_size,
            expected_distance=expected_distance,
            actual_distance=existing_distance or None,
        )
        raise RuntimeError(
            "Existing Qdrant collection does not match configured vector size/distance "
            f"for collection '{settings.qdrant_collection}'."
        )

    warn_on_tuning_drift(settings, collection_info, collection=settings.qdrant_collection)
    ensure_qdrant_payload_indexes()
    logger.info(
        "qdrant.collection.exists",
        collection=settings.qdrant_collection,
        vector_size=settings.qdrant_vector_size,
        distance=expected_distance,
    )
