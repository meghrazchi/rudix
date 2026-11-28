"""Hermetic test environment (0.9.0, S1; plan contract 5.2.8).

Tests run as in CI whatever a developer's ``.env`` holds:

* :func:`pin_provider_environment` sets the CI job environment (``.github/workflows/ci.yml``,
  backend job) as defaults, then pins ``ENVIRONMENT=test``, the provider selectors, and
  placeholder credentials in ``os.environ`` before anything imports ``app``. The environment
  beats ``.env`` in pydantic-settings, and the pins also beat values exported in the shell.
* :func:`rebuild_settings_without_env_file` rebuilds the settings singleton in place from the
  environment alone, so nothing in a developer's ``.env`` (feature flags, graph, metrics,
  credentials) reaches the suite; CI has no ``.env`` either.
* :func:`clear_provider_credentials` sets every provider credential on the singleton to
  ``None``. An empty environment variable cannot do that: ``Settings`` uses
  ``env_ignore_empty``, so an empty value falls back to ``.env``.
* :class:`NetworkGuard` makes ``socket.connect`` fail for any IPv4 or IPv6 address that is
  not loopback and not the host of ``TEST_DATABASE_URL``, ``TEST_MIGRATIONS_DATABASE_URL``,
  or ``TEST_REDIS_URL``. Unix sockets and name resolution are untouched.

Tests that need other values keep using ``monkeypatch`` on ``settings``. Running the suite
against live providers on purpose is not supported.

This module imports only the standard library, so ``conftest.py`` can use it before any
application import.
"""

from __future__ import annotations

import ipaddress
import os
import socket
from collections.abc import Callable, Iterable
from typing import Any
from urllib.parse import urlsplit

# The CI backend job environment (non-secret placeholders), applied with ``setdefault``:
# a value exported in the shell (another DATABASE_URL, say) still wins.
CI_ENVIRONMENT: dict[str, str] = {
    "API_BASE_URL": "http://localhost:8000",
    "FRONTEND_BASE_URL": "http://localhost:3000",
    "DATABASE_URL": "postgresql+asyncpg://postgres:postgres@localhost:5432/rag_app",
    "AUTH_PROVIDER": "app",
    "APP_AUTH_SECRET": "ci-local-secret",
    "APP_AUTH_ISSUER": "rudix-app",
    "APP_AUTH_AUDIENCE": "rudix-api",
    "MINIO_ENDPOINT": "http://localhost:9000",
    "MINIO_BUCKET": "documents",
    "MINIO_ACCESS_KEY": "minioadmin",
    "MINIO_SECRET_KEY": "minioadmin",
    "QDRANT_URL": "http://localhost:6333",
    "QDRANT_COLLECTION": "documents",
    "QDRANT_BOOTSTRAP_COLLECTION": "true",
    "QDRANT_VECTOR_SIZE": "1536",
    "QDRANT_DISTANCE": "cosine",
    "RABBITMQ_URL": "amqp://guest:guest@localhost:5672//",
    "REDIS_URL": "redis://localhost:6379/0",
    "MINIO_BOOTSTRAP_BUCKET": "true",
}

# Provider selectors and switches (env name -> pinned value). Explicit assignment, not
# setdefault: a developer's shell (EMAIL_PROVIDER=resend ...) must not reach the suite.
PINNED_ENVIRONMENT: dict[str, str] = {
    "ENVIRONMENT": "test",
    "OPENAI_API_KEY": "test-placeholder-key",
    "LLM_DEFAULT_PROVIDER": "openai",
    "EMBEDDING_DEFAULT_PROVIDER": "openai",
    "RERANK_DEFAULT_PROVIDER": "openai",
    "EMAIL_PROVIDER": "console",
    "EMAIL_ENABLED": "false",
    "BILLING_PROVIDER": "none",
    "TRACING_ENABLED": "false",
    "LANGFUSE_ENABLED": "false",
    # botocore would otherwise ask the instance metadata service (169.254.169.254) for
    # credentials whenever a test builds an S3 client without keys.
    "AWS_EC2_METADATA_DISABLED": "true",
}

# Provider credentials (env name -> settings attribute). Removed from the environment and
# set to None on the settings singleton. STRIPE_* have no field before B1 (0.9.0); the
# attribute is cleared once it exists.
PROVIDER_CREDENTIALS: dict[str, str] = {
    "LOCAL_LLM_API_KEY": "local_llm_api_key",
    "LOCAL_EMBEDDING_API_KEY": "local_embedding_api_key",
    "RESEND_API_KEY": "resend_api_key",
    "POSTMARK_SERVER_TOKEN": "postmark_server_token",
    "SMTP_PASSWORD": "smtp_password",
    "STRIPE_SECRET_KEY": "stripe_secret_key",
    "STRIPE_WEBHOOK_SECRET": "stripe_webhook_secret",
    "LANGFUSE_SECRET_KEY": "langfuse_secret_key",
    "LANGFUSE_PUBLIC_KEY": "langfuse_public_key",
    "BOT_SLACK_SIGNING_SECRET": "bot_slack_signing_secret",
    "BOT_SLACK_CLIENT_SECRET": "bot_slack_client_secret",
    "BOT_TEAMS_SHARED_SECRET": "bot_teams_shared_secret",
    "OTEL_EXPORTER_OTLP_HEADERS": "otel_exporter_otlp_headers",
    "BACKUP_S3_ACCESS_KEY": "backup_s3_access_key",
    "BACKUP_S3_SECRET_KEY": "backup_s3_secret_key",
    "SENTRY_DSN": "sentry_dsn",
}

ALLOWED_HOST_VARIABLES = ("TEST_DATABASE_URL", "TEST_MIGRATIONS_DATABASE_URL", "TEST_REDIS_URL")
GUARD_MESSAGE = "tests must not open network connections to {host}:{port}; use the fakes"


def pin_provider_environment() -> None:
    for name, value in CI_ENVIRONMENT.items():
        os.environ.setdefault(name, value)
    for name, value in PINNED_ENVIRONMENT.items():
        os.environ[name] = value
    for name in PROVIDER_CREDENTIALS:
        os.environ.pop(name, None)


def rebuild_settings_without_env_file(settings: Any) -> None:
    """Replace every field of the singleton with a value read from the environment only.

    Runs once, right after ``app.core.config`` is first imported and before any other
    application module copies a setting, so every module sees the rebuilt values.
    """
    fresh = type(settings)(_env_file=None)
    for name in type(settings).model_fields:
        setattr(settings, name, getattr(fresh, name))


def clear_provider_credentials(settings: Any) -> list[str]:
    """Set every provider credential on ``settings`` to ``None``; return the attributes."""
    cleared: list[str] = []
    for attribute in PROVIDER_CREDENTIALS.values():
        if hasattr(settings, attribute):
            setattr(settings, attribute, None)
            cleared.append(attribute)
    return cleared


def _is_local(host: str) -> bool:
    try:
        address = ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        return host == "localhost" or host.endswith(".localhost")
    return address.is_loopback or address.is_unspecified


def _resolve(host: str) -> set[str]:
    addresses = {host}
    try:
        for info in socket.getaddrinfo(host, None):
            addresses.add(str(info[4][0]))
    except OSError:
        pass
    return addresses


def allowed_hosts(environ: dict[str, str] | None = None) -> set[str]:
    """Hosts (and their addresses) of the configured test database and Redis."""
    env = os.environ if environ is None else environ
    hosts: set[str] = set()
    for name in ALLOWED_HOST_VARIABLES:
        url = env.get(name, "").strip()
        if not url:
            continue
        host = urlsplit(url).hostname
        if host:
            hosts |= _resolve(host)
    return hosts


class NetworkGuard:
    """Patch ``socket.socket.connect`` and ``connect_ex`` to refuse non-local addresses."""

    def __init__(self, extra_allowed: Iterable[str] = ()) -> None:
        self.allowed = set(extra_allowed)
        self._originals: dict[str, Callable[..., Any]] = {}

    def check(self, family: int, address: Any) -> None:
        if family not in (socket.AF_INET, socket.AF_INET6):
            return
        if not isinstance(address, tuple) or len(address) < 2:
            return
        host, port = str(address[0]), address[1]
        if _is_local(host) or host in self.allowed:
            return
        if not _looks_like_ip(host) and _resolve(host) & self.allowed:
            return
        raise RuntimeError(GUARD_MESSAGE.format(host=host, port=port))

    def install(self) -> None:
        if self._originals:
            return
        guard = self
        for name in ("connect", "connect_ex"):
            original = getattr(socket.socket, name)
            self._originals[name] = original

            def _guarded(
                sock: socket.socket,
                address: Any,
                _original: Callable[..., Any] = original,
            ) -> Any:
                guard.check(sock.family, address)
                return _original(sock, address)

            setattr(socket.socket, name, _guarded)

    def uninstall(self) -> None:
        for name, original in self._originals.items():
            setattr(socket.socket, name, original)
        self._originals.clear()

    @property
    def installed(self) -> bool:
        return bool(self._originals)


def _looks_like_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        return False
    return True
