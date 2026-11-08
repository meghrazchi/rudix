from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Response, status

from app.core.config import settings
from app.core.metrics import generate_prometheus_metrics

router = APIRouter(tags=["metrics"])


@router.get("/metrics", include_in_schema=False)
async def metrics_endpoint(
    authorization: Annotated[str | None, Header()] = None,
) -> Response:
    """Prometheus metrics scrape endpoint.

    When METRICS_ENABLED=false, returns 404.
    When METRICS_REQUIRE_AUTH=true, requires a valid Bearer token matching METRICS_BEARER_TOKEN.
    """
    if not settings.metrics_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Metrics collection is disabled",
        )

    if settings.metrics_require_auth:
        expected_token = (
            settings.metrics_bearer_token.get_secret_value()
            if settings.metrics_bearer_token
            else None
        )
        if not expected_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Metrics authentication required but no token is configured",
            )
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing or invalid Authorization header",
            )
        token = authorization[7:].strip()
        if not hmac.compare_digest(token, expected_token):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid metrics token",
            )

    return generate_prometheus_metrics()
