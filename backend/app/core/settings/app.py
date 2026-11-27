"""Application, API, logging, and CORS settings."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    Field,
    field_validator,
)
from pydantic_settings import NoDecode

from app.core.settings.enums import (
    AuthProvider,
    Environment,
    LogFormat,
)

if TYPE_CHECKING:
    from app.core.config import Settings


class AppSettings(BaseModel):
    environment: Environment = Environment.development
    log_level: str = Field(default="INFO", pattern=r"^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$")
    log_format: LogFormat = LogFormat.auto
    api_name: str = Field(default="AI Document Q&A Assistant API", min_length=3, max_length=120)
    api_version: str = Field(default="0.1.0", min_length=1, max_length=32)
    api_prefix: str = Field(default="/api/v1", pattern=r"^/[a-zA-Z0-9/_-]*$")
    api_base_url: AnyHttpUrl
    frontend_base_url: AnyHttpUrl
    public_status_organization_slug: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
    )
    cors_origins: Annotated[list[AnyHttpUrl], NoDecode] = Field(default_factory=list)
    request_timeout_seconds: int = Field(default=30, ge=1, le=300)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def validate_cors_origins(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            parsed = [item.strip() for item in value.split(",") if item.strip()]
            return parsed
        if isinstance(value, list):
            parsed = [str(item).strip() for item in value if str(item).strip()]
            return parsed
        raise ValueError("cors_origins must be a comma-separated string or list of URLs")


def validate_app_settings(settings: Settings) -> None:
    if not settings.cors_origins:
        settings.cors_origins = [settings.frontend_base_url]

    if settings.environment in {Environment.production, Environment.staging}:
        settings._validate_production_public_url("api_base_url", settings.api_base_url)
        settings._validate_production_public_url(
            "frontend_base_url",
            settings.frontend_base_url,
        )


def validate_environment_rules(settings: Settings) -> None:
    if settings.environment == Environment.production:
        if settings.sentry_dsn is None:
            raise ValueError("sentry_dsn is required in production")
        if settings.sentry_test_event_enabled:
            raise ValueError("sentry_test_event_enabled must be false in production")
        if (
            settings.auth_provider == AuthProvider.app
            and settings._secret_value(settings.app_auth_secret) == "dev-insecure-change-me"
        ):
            raise ValueError("app_auth_secret must be overridden in production")
        if settings.auth_provider == AuthProvider.app:
            settings.app_auth_auto_provision_users = False
    elif settings.environment == Environment.staging:
        if settings.auth_provider == AuthProvider.app:
            settings.app_auth_auto_provision_users = False
    elif settings.environment == Environment.test:
        settings.feature_expose_config_snapshot = True
