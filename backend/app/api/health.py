import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Response, status

from app.clients.minio_client import check_minio_health
from app.clients.qdrant_client import check_qdrant_health
from app.clients.rabbitmq_client import check_rabbitmq_health
from app.clients.redis_client import check_redis_health
from app.core.config import settings
from app.db.session import check_database_health
from app.schemas.common import HealthDependency, HealthMetadataValue, HealthResponse

router = APIRouter(tags=["health"])
READINESS_CHECK_TIMEOUT_SECONDS = 2.0


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _sanitize_url(url: str) -> str:
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    return f"{parsed.scheme}://{host}{parsed.path or ''}"


def _build_dependency(
    *,
    ok: bool,
    detail: str | None = None,
    metadata: dict[str, HealthMetadataValue] | None = None,
) -> HealthDependency:
    return HealthDependency(
        ok=ok,
        detail=detail if not ok else None,
        metadata=metadata or {},
    )


def _openai_configuration_health() -> HealthDependency:
    key_set = settings.openai_api_key is not None
    embeddings_enabled = settings.feature_enable_embeddings
    llm_enabled = settings.feature_enable_llm
    evaluations_enabled = settings.feature_enable_evaluations
    requires_openai = embeddings_enabled or llm_enabled or evaluations_enabled

    missing_model = (
        (embeddings_enabled and not settings.openai_embedding_model.strip())
        or (llm_enabled and not settings.openai_llm_model.strip())
    )

    ok = (not requires_openai or key_set) and not missing_model
    detail = None
    if requires_openai and not key_set:
        detail = "openai_api_key_missing"
    elif missing_model:
        detail = "openai_model_missing"

    return _build_dependency(
        ok=ok,
        detail=detail,
        metadata={
            "api_key_set": key_set,
            "embedding_model": settings.openai_embedding_model if embeddings_enabled else None,
            "llm_model": settings.openai_llm_model if llm_enabled else None,
            "embeddings_enabled": embeddings_enabled,
            "llm_enabled": llm_enabled,
            "evaluations_enabled": evaluations_enabled,
        },
    )


async def _readiness_dependencies() -> dict[str, HealthDependency]:
    timeout = min(READINESS_CHECK_TIMEOUT_SECONDS, float(settings.request_timeout_seconds))

    async def run_async_check(check_fn: Callable[[], Awaitable[bool]]) -> bool:
        try:
            return bool(await asyncio.wait_for(check_fn(), timeout=timeout))
        except Exception:
            return False

    async def run_sync_check(check_fn: Callable[[], bool]) -> bool:
        try:
            return bool(await asyncio.wait_for(asyncio.to_thread(check_fn), timeout=timeout))
        except Exception:
            return False

    (
        postgres_ok,
        redis_ok,
        rabbitmq_ok,
        qdrant_ok,
        minio_ok,
    ) = await asyncio.gather(
        run_async_check(check_database_health),
        run_async_check(check_redis_health),
        run_async_check(check_rabbitmq_health),
        run_sync_check(check_qdrant_health),
        run_sync_check(check_minio_health),
    )

    return {
        "postgres": _build_dependency(
            ok=postgres_ok,
            detail="postgres_unreachable",
            metadata={"dsn": _sanitize_url(str(settings.database_url))},
        ),
        "redis": _build_dependency(
            ok=redis_ok,
            detail="redis_unreachable",
            metadata={"url": _sanitize_url(str(settings.redis_url))},
        ),
        "rabbitmq": _build_dependency(
            ok=rabbitmq_ok,
            detail="rabbitmq_unreachable",
            metadata={"url": _sanitize_url(str(settings.rabbitmq_url))},
        ),
        "qdrant": _build_dependency(
            ok=qdrant_ok,
            detail="qdrant_unreachable",
            metadata={
                "url": str(settings.qdrant_url),
                "collection": settings.qdrant_collection,
            },
        ),
        "minio": _build_dependency(
            ok=minio_ok,
            detail="minio_unreachable",
            metadata={
                "endpoint": str(settings.minio_endpoint),
                "bucket": settings.minio_bucket,
            },
        ),
        "openai_config": _openai_configuration_health(),
    }


def _failed_dependencies(dependencies: dict[str, HealthDependency]) -> list[str]:
    return [name for name, dependency in dependencies.items() if not dependency.ok]


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok", timestamp=_now_utc())


@router.get("/healthz", response_model=HealthResponse, include_in_schema=False)
async def healthz() -> HealthResponse:
    return await health()


@router.get("/ready", response_model=HealthResponse)
async def ready(response: Response) -> HealthResponse:
    dependencies = await _readiness_dependencies()
    failed_dependencies = _failed_dependencies(dependencies)
    is_ready = not failed_dependencies

    response.status_code = status.HTTP_200_OK if is_ready else status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(
        status="ok" if is_ready else "degraded",
        timestamp=_now_utc(),
        dependencies=dependencies,
        failed_dependencies=failed_dependencies,
    )


@router.get("/readyz", response_model=HealthResponse, include_in_schema=False)
async def readyz(response: Response) -> HealthResponse:
    return await ready(response)


@router.get("/configz")
async def configz() -> dict:
    if not settings.feature_expose_config_snapshot:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Configuration snapshot is disabled")
    return settings.sanitized_snapshot()
