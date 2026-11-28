from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Response, status

from app.core.config import settings
from app.core.metrics import generate_prometheus_metrics
from app.core.metrics_server import check_metrics_authorization

router = APIRouter(tags=["metrics"])


@router.get("/metrics", include_in_schema=False)
async def metrics_endpoint(
    authorization: Annotated[str | None, Header()] = None,
) -> Response:
    """Prometheus metrics scrape endpoint.

    When METRICS_ENABLED=false, returns 404.
    When METRICS_REQUIRE_AUTH=true, requires a valid Bearer token matching METRICS_BEARER_TOKEN
    (the worker metrics server applies the same check, ``app/core/metrics_server.py``).
    """
    if not settings.metrics_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Metrics collection is disabled",
        )

    failure = check_metrics_authorization(
        authorization,
        require_auth=settings.metrics_require_auth,
        expected_token=(
            settings.metrics_bearer_token.get_secret_value()
            if settings.metrics_bearer_token
            else None
        ),
    )
    if failure is not None:
        raise HTTPException(status_code=failure.status_code, detail=failure.detail)

    return generate_prometheus_metrics()
