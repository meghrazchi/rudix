import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from fastapi import FastAPI

from app.clients.clamav_client import close_clamav, init_clamav
from app.clients.minio_client import close_minio, init_minio
from app.clients.neo4j_client import close_neo4j, init_neo4j
from app.clients.qdrant_client import close_qdrant, init_qdrant
from app.clients.rabbitmq_client import close_rabbitmq, init_rabbitmq
from app.clients.redis_client import close_redis, init_redis
from app.core.langfuse_tracer import init_langfuse, shutdown_langfuse
from app.core.sentry import init_sentry
from app.db.session import dispose_engine
from app.domains.graph.migration_runner import run_graph_migrations

logger = logging.getLogger(__name__)


async def _tcp_reachable(host: str, port: int, timeout: float = 2.0) -> bool:
    """Return True if a TCP connection to host:port succeeds within timeout."""
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout)
        writer.close()
        await writer.wait_closed()
        return True
    except (TimeoutError, OSError):
        return False


async def probe_local_providers() -> None:
    """Log warnings when a local provider is configured but its endpoint is unreachable.

    Non-fatal: the API starts normally so that operators can diagnose connectivity
    issues without being locked out of other features.
    """
    from app.core.config import settings

    checks: list[tuple[str, str | None, str]] = [
        (
            settings.llm_default_provider,
            str(settings.local_llm_base_url) if settings.local_llm_base_url else None,
            "chat (LLM_DEFAULT_PROVIDER=local)",
        ),
        (
            settings.embedding_default_provider,
            str(settings.local_embedding_base_url) if settings.local_embedding_base_url else None,
            "embeddings (EMBEDDING_DEFAULT_PROVIDER=local)",
        ),
    ]

    for provider_key, base_url, label in checks:
        if provider_key != "local":
            continue
        if base_url is None:
            logger.warning(
                "[local-llm] %s is enabled but the base URL is not configured — "
                "set LOCAL_LLM_BASE_URL or LOCAL_EMBEDDING_BASE_URL in .env",
                label,
            )
            continue

        parsed = urlparse(base_url)
        host = parsed.hostname or "localhost"
        port = parsed.port or (443 if parsed.scheme == "https" else 80)

        if await _tcp_reachable(host, port):
            logger.info("[local-llm] %s endpoint %s is reachable", label, base_url)
        else:
            logger.warning(
                "[local-llm] %s endpoint %s is not reachable — "
                "start the container first (e.g. make up-ollama) then restart the API",
                label,
                base_url,
            )


async def _init_optional_dependency(name: str, init: Callable[[], Awaitable[None] | None]) -> None:
    """Run a dependency init; log and continue so the API can boot degraded.

    ``/ready`` reports the dependency as down; consumers handle a ``None`` client.
    """
    try:
        outcome = init()
        if outcome is not None:
            await outcome
    except Exception as exc:
        logger.warning(
            "startup.dependency_unavailable",
            extra={"dependency": name, "error": exc.__class__.__name__},
        )


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    from app.core.config import settings

    try:
        init_sentry(runtime="api")
        init_langfuse(runtime="api")
        await _init_optional_dependency("redis", init_redis)
        await _init_optional_dependency("rabbitmq", init_rabbitmq)
        await _init_optional_dependency("qdrant", init_qdrant)
        init_minio()
        init_clamav()
        await init_neo4j()
        if settings.should_run_graph_migrations_on_startup:
            await run_graph_migrations()
        else:
            logger.info(
                "startup.graph_migrations_skipped",
                extra={"environment": settings.environment.value},
            )
        await probe_local_providers()
        yield
    finally:
        await close_redis()
        close_rabbitmq()
        close_qdrant()
        close_minio()
        close_clamav()
        await close_neo4j()
        await dispose_engine()
        shutdown_langfuse()
