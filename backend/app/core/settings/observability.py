"""Sentry, Langfuse, metrics, and analytics settings."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import (
    AnyHttpUrl,
    AnyUrl,
    BaseModel,
    Field,
    SecretStr,
    field_validator,
)

from app.core.settings.enums import (
    LangfuseRedactionMode,
)

if TYPE_CHECKING:
    pass


class ObservabilitySettings(BaseModel):
    feature_enable_product_analytics: bool = True
    analytics_dedupe_window_seconds: int = Field(default=86400, ge=60, le=604800)
    feature_enable_query_analytics: bool = True
    query_analytics_redact_query_text: bool = False
    sentry_dsn: AnyUrl | None = None
    sentry_release: str | None = Field(default=None, max_length=128)
    sentry_error_sample_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    sentry_traces_sample_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    sentry_profiles_sample_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    sentry_test_event_enabled: bool | None = None
    # Langfuse observability (optional, F271)
    langfuse_enabled: bool = False
    langfuse_base_url: AnyHttpUrl | None = None
    langfuse_public_key: str | None = Field(default=None, max_length=256)
    langfuse_secret_key: SecretStr | None = None
    langfuse_sample_rate: float = Field(default=1.0, ge=0.0, le=1.0)
    langfuse_capture_input_output: bool = True
    langfuse_redaction_mode: LangfuseRedactionMode = LangfuseRedactionMode.none
    # Prometheus metrics observability
    metrics_enabled: bool = False
    metrics_path: str = Field(default="/metrics", min_length=1, max_length=128)
    metrics_require_auth: bool = False
    metrics_bearer_token: SecretStr | None = None
    # Count SQL statements per HTTP request (rudix_db_queries_per_request, R03-09).
    metrics_db_query_counting_enabled: bool = True
    # Event-loop lag monitor (rudix_event_loop_lag_seconds, R04-11).
    loop_lag_monitor_enabled: bool = True
    loop_lag_monitor_interval_ms: int = Field(default=50, ge=5, le=5000)
    # GZip responses at or above this size; 0 disables compression (R04-11).
    http_gzip_minimum_bytes: int = Field(default=1024, ge=0)
    worker_metrics_enabled: bool = False
    worker_metrics_port: int = Field(default=9808, ge=1024, le=65535)

    @field_validator("sentry_release")
    @classmethod
    def validate_sentry_release(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        return cleaned
