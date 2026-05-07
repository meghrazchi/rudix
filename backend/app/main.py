from fastapi import FastAPI

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

attach_access_log_middleware(app)
app.include_router(api_router, prefix=settings.api_prefix)
