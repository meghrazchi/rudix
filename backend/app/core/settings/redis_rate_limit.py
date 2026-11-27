"""Redis, rate-limit, and dependency timeout settings."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import (
    BaseModel,
    Field,
    RedisDsn,
)

from app.core.settings.enums import (
    RateLimitRedisFailureMode,
)

if TYPE_CHECKING:
    from app.core.config import Settings


class RedisRateLimitSettings(BaseModel):
    redis_url: RedisDsn
    redis_socket_connect_timeout_seconds: float = Field(default=2.0, ge=0.1, le=30.0)
    redis_socket_timeout_seconds: float = Field(default=2.0, ge=0.1, le=30.0)
    rate_limit_enabled: bool = True
    rate_limit_disable_in_development: bool = True
    rate_limit_disable_in_test: bool = True
    rate_limit_redis_failure_mode: RateLimitRedisFailureMode = RateLimitRedisFailureMode.open
    rate_limit_window_seconds: int = Field(default=60, ge=1, le=3600)
    rate_limit_upload_requests: int = Field(default=20, ge=1, le=10000)
    rate_limit_chat_requests: int = Field(default=30, ge=1, le=10000)
    rate_limit_evaluation_requests: int = Field(default=10, ge=1, le=10000)
    rate_limit_delete_requests: int = Field(default=20, ge=1, le=10000)
    rate_limit_admin_requests: int = Field(default=15, ge=1, le=10000)
    rate_limit_connector_requests: int = Field(default=15, ge=1, le=10000)
    rate_limit_contact_requests: int = Field(default=5, ge=1, le=10000)
    rate_limit_bot_requests: int = Field(default=30, ge=1, le=10000)
    rate_limit_auth_login_requests: int = Field(default=10, ge=1, le=10000)
    rate_limit_auth_refresh_requests: int = Field(default=60, ge=1, le=10000)
    rate_limit_auth_logout_requests: int = Field(default=30, ge=1, le=10000)
    rate_limit_auth_password_requests: int = Field(default=10, ge=1, le=10000)
    # R04-07: organisation aggregate per scope/endpoint = scope limit x multiplier.
    rate_limit_org_enabled: bool = True
    rate_limit_org_limit_multiplier: int = Field(default=10, ge=1, le=10000)
    # R04-06: API-key/service-account last_used_* buffered in Redis, flushed by beat.
    usage_touch_flush_interval_seconds: int = Field(default=60, ge=10, le=3600)
    usage_touch_flush_batch_size: int = Field(default=500, ge=1, le=10000)
    dependency_connect_timeout_seconds: float = Field(default=1.0, ge=0.1, le=30.0)
    dependency_read_timeout_seconds: float = Field(default=1.0, ge=0.1, le=120.0)
    dependency_max_retries: int = Field(default=0, ge=0, le=10)


def validate_timeouts(settings: Settings) -> None:
    if settings.redis_socket_timeout_seconds < settings.redis_socket_connect_timeout_seconds:
        raise ValueError(
            "redis_socket_timeout_seconds must be >= redis_socket_connect_timeout_seconds"
        )

    if settings.dependency_read_timeout_seconds < settings.dependency_connect_timeout_seconds:
        raise ValueError(
            "dependency_read_timeout_seconds must be >= dependency_connect_timeout_seconds"
        )
