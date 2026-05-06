from fastapi import FastAPI
from fastapi.responses import ORJSONResponse

from app.api.router import api_router
from app.core.config import settings
from app.core.lifespan import lifespan
from app.core.logging import configure_logging

configure_logging(settings.log_level)

app = FastAPI(
    title=settings.api_name,
    version=settings.api_version,
    default_response_class=ORJSONResponse,
    lifespan=lifespan,
)

app.include_router(api_router, prefix=settings.api_prefix)
