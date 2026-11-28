"""Application settings.

The fields live in per-area mixins under ``app.core.settings``; this module composes them into
``Settings``, runs the cross-field validation, and re-exports the names other modules import.
"""

from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from pydantic import AnyHttpUrl, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.settings.ai_providers import (
    AiProvidersSettings,
    validate_ai_providers,
)
from app.core.settings.app import (
    AppSettings,
    validate_app_settings,
    validate_environment_rules,
)
from app.core.settings.auth import (
    AuthSettings,
    validate_auth_cookies,
    validate_auth_provider,
)
from app.core.settings.backup import BackupSettings
from app.core.settings.celery import CelerySettings
from app.core.settings.connectors import (
    ConnectorsSettings,
    validate_connector_rollout,
)
from app.core.settings.database import DatabaseSettings
from app.core.settings.deployment import DeploymentSettings
from app.core.settings.email_bots import EmailBotsSettings
from app.core.settings.enums import (
    AuthProvider,
    ConnectorOAuthClientSettings,
    ConnectorRolloutStage,
    Environment,
    LangfuseRedactionMode,
    LogFormat,
    MCPExternalAuthType,
    MCPExternalServerSettings,
    MCPExternalTransport,
    MCPTransport,
    QdrantDistance,
    RateLimitRedisFailureMode,
    RerankFallbackBehavior,
    RlsEnforcement,
)
from app.core.settings.features import (
    FeaturesSettings,
    validate_agents_default,
)
from app.core.settings.graph import (
    GraphSettings,
    validate_enterprise_graph,
    validate_graph_rag,
)
from app.core.settings.mcp import (
    McpSettings,
    validate_mcp_settings,
)
from app.core.settings.observability import ObservabilitySettings
from app.core.settings.rag import (
    RagSettings,
    validate_rag_thresholds,
)
from app.core.settings.realtime import RealtimeSettings
from app.core.settings.redis_rate_limit import (
    RedisRateLimitSettings,
    validate_timeouts,
)
from app.core.settings.snapshot import sanitized_snapshot as _sanitized_snapshot
from app.core.settings.storage import (
    StorageSettings,
    validate_upload_security,
)
from app.core.settings.tracing import TracingSettings
from app.core.settings.workers import WorkersSettings

__all__ = [
    "AuthProvider",
    "ConnectorOAuthClientSettings",
    "ConnectorRolloutStage",
    "Environment",
    "LangfuseRedactionMode",
    "LogFormat",
    "MCPExternalAuthType",
    "MCPExternalServerSettings",
    "MCPExternalTransport",
    "MCPTransport",
    "QdrantDistance",
    "RateLimitRedisFailureMode",
    "RerankFallbackBehavior",
    "RlsEnforcement",
    "Settings",
    "get_settings",
    "settings",
]

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT_DIR = BACKEND_DIR.parent
ENV_FILES = (
    str(BACKEND_DIR / ".env"),
    str(PROJECT_ROOT_DIR / ".env"),
)


class Settings(
    AppSettings,
    DatabaseSettings,
    RedisRateLimitSettings,
    StorageSettings,
    CelerySettings,
    AuthSettings,
    AiProvidersSettings,
    RagSettings,
    GraphSettings,
    McpSettings,
    ConnectorsSettings,
    ObservabilitySettings,
    EmailBotsSettings,
    FeaturesSettings,
    WorkersSettings,
    RealtimeSettings,
    # Production infrastructure (0.8.0): B1, B3, and A2 fill these.
    DeploymentSettings,
    TracingSettings,
    BackupSettings,
    BaseSettings,
):
    model_config = SettingsConfigDict(
        env_file=ENV_FILES,
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        case_sensitive=False,
        extra="ignore",
        validate_by_name=True,
    )

    @staticmethod
    def _secret_value(secret: Any | None) -> str:
        if secret is None:
            return ""
        if hasattr(secret, "get_secret_value"):
            return secret.get_secret_value()
        return str(secret)

    @staticmethod
    def _is_loopback_public_host(host: str) -> bool:
        normalized = host.lower().strip("[]")
        return (
            normalized == "localhost"
            or normalized.endswith(".localhost")
            or normalized == "::1"
            or normalized == "0.0.0.0"
            or normalized.startswith("127.")
        )

    @classmethod
    def _validate_production_public_url(cls, field_name: str, url: AnyHttpUrl) -> None:
        parsed = urlsplit(str(url))
        if parsed.scheme != "https":
            raise ValueError(
                f"{field_name} must use https:// in staging or production environments"
            )
        if parsed.hostname and cls._is_loopback_public_host(parsed.hostname):
            raise ValueError(
                f"{field_name} must not point to localhost in staging or production environments"
            )

    @model_validator(mode="after")
    def validate_consistency(self) -> "Settings":
        # Order matters: some steps mutate fields that later steps read.
        validate_app_settings(self)
        validate_agents_default(self)
        validate_mcp_settings(self)
        validate_enterprise_graph(self)
        validate_connector_rollout(self)
        validate_graph_rag(self)
        validate_rag_thresholds(self)
        validate_auth_cookies(self)
        validate_upload_security(self)
        validate_timeouts(self)
        validate_auth_provider(self)
        validate_ai_providers(self)
        validate_environment_rules(self)
        return self

    @property
    def should_run_graph_migrations_on_startup(self) -> bool:
        if self.graph_migrations_on_startup is not None:
            return self.graph_migrations_on_startup
        return self.environment in {Environment.development, Environment.test}

    @property
    def is_production(self) -> bool:
        return self.environment == Environment.production

    @property
    def effective_rls_enforcement(self) -> RlsEnforcement:
        """``RLS_ENFORCEMENT`` when set; else ``strict`` in development and test (0.5.0) and
        ``soft`` in staging and production until the soft-denial week and the role split."""
        if self.rls_enforcement is not None:
            return self.rls_enforcement
        if self.environment in {Environment.development, Environment.test}:
            return RlsEnforcement.strict
        if self.environment in {Environment.production, Environment.staging}:
            return RlsEnforcement.soft
        return RlsEnforcement.off

    @property
    def is_rate_limit_active(self) -> bool:
        if not self.rate_limit_enabled:
            return False
        if self.environment == Environment.development and self.rate_limit_disable_in_development:
            return False
        if self.environment == Environment.test and self.rate_limit_disable_in_test:
            return False
        return True

    @property
    def is_sentry_test_event_enabled(self) -> bool:
        if self.environment == Environment.production:
            return False
        if self.sentry_test_event_enabled is not None:
            return self.sentry_test_event_enabled
        return self.environment in {Environment.development, Environment.test}

    @property
    def active_index_versions(self) -> tuple[str, ...]:
        """Index versions production retrieval serves, current version first."""
        extra = [
            version
            for version in self.document_active_index_versions
            if version != self.document_index_version
        ]
        return (self.document_index_version, *extra)

    @staticmethod
    def _sanitize_url(url_value: str) -> str:
        parsed = urlsplit(url_value)
        if not parsed.netloc:
            return url_value

        host = parsed.hostname or ""
        if parsed.port is not None:
            host = f"{host}:{parsed.port}"

        return urlunsplit((parsed.scheme, host, parsed.path, parsed.query, parsed.fragment))

    def sanitized_snapshot(self) -> dict[str, Any]:
        return _sanitized_snapshot(self)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
