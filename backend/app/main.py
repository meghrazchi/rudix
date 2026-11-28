from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app.api.router import api_router
from app.core.config import Environment, settings
from app.core.errors import register_exception_handlers
from app.core.lifespan import lifespan
from app.core.logging import attach_access_log_middleware, configure_logging
from app.core.metrics import attach_metrics_middleware
from app.core.security_headers import SecurityHeadersMiddleware
from app.core.tracing import instrument_fastapi_app
from app.interfaces.http import metrics

configure_logging(
    settings.log_level,
    environment=settings.environment.value,
    log_format=settings.log_format.value,
)

app = FastAPI(
    title=settings.api_name,
    version=settings.api_version,
    lifespan=lifespan,
)
register_exception_handlers(app)


def _normalize_cors_origin(origin: str) -> str:
    parsed = urlsplit(origin)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return origin.rstrip("/")


normalized_cors_origins = sorted(
    {_normalize_cors_origin(str(origin)) for origin in settings.cors_origins}
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=normalized_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)


def attach_gzip_middleware(target: FastAPI, minimum_bytes: int) -> None:
    """GZip responses of at least ``minimum_bytes``; 0 disables compression (R04-11).

    Must be added before the ``@app.middleware("http")`` layers: those re-stream every
    body, so a GZip layer outside them never sees the final size and compresses all
    responses regardless of ``minimum_size``.
    """
    if minimum_bytes > 0:
        target.add_middleware(GZipMiddleware, minimum_size=minimum_bytes, compresslevel=5)


attach_gzip_middleware(app, settings.http_gzip_minimum_bytes)
attach_access_log_middleware(app)
attach_metrics_middleware(app)
app.add_middleware(
    SecurityHeadersMiddleware,
    hsts_enabled=settings.environment in {Environment.production, Environment.staging},
)
app.include_router(metrics.router)
app.include_router(api_router, prefix=settings.api_prefix)
# R08-10: outermost ASGI layer when TRACING_ENABLED=true; nothing is added otherwise.
instrument_fastapi_app(app, settings)
