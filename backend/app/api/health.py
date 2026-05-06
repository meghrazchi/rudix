from datetime import datetime, timezone

from fastapi import APIRouter, status
from fastapi.responses import ORJSONResponse

from app.clients.minio_client import check_minio_health
from app.clients.qdrant_client import check_qdrant_health
from app.clients.redis_client import check_redis_health
from app.db.session import check_database_health
from app.schemas.common import HealthDependency, HealthResponse

router = APIRouter(tags=["health"])


@router.get("/healthz", response_model=HealthResponse)
async def healthz() -> HealthResponse:
    return HealthResponse(status="ok", timestamp=datetime.now(timezone.utc))


@router.get("/readyz", response_model=HealthResponse)
async def readyz() -> ORJSONResponse:
    db_ok = await check_database_health()
    redis_ok = await check_redis_health()
    qdrant_ok = check_qdrant_health()
    minio_ok = check_minio_health()

    dependencies = {
        "postgres": HealthDependency(ok=db_ok),
        "redis": HealthDependency(ok=redis_ok),
        "qdrant": HealthDependency(ok=qdrant_ok),
        "minio": HealthDependency(ok=minio_ok),
    }

    is_ready = all(item.ok for item in dependencies.values())
    payload = HealthResponse(
        status="ok" if is_ready else "degraded",
        timestamp=datetime.now(timezone.utc),
        dependencies=dependencies,
    )

    return ORJSONResponse(
        content=payload.model_dump(mode="json"),
        status_code=status.HTTP_200_OK if is_ready else status.HTTP_503_SERVICE_UNAVAILABLE,
    )
