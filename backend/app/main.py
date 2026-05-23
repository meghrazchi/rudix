from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import settings
from app.core.lifespan import lifespan
from app.core.logging import attach_access_log_middleware, configure_logging

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

attach_access_log_middleware(app)
app.include_router(api_router, prefix=settings.api_prefix)
