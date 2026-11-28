"""The hermetic test environment is in effect (0.9.0, S1; plan contract 5.2.8)."""

from __future__ import annotations

import os
import socket
from typing import Any

import pytest

from app.core.config import settings
from tests import hermetic


def test_connecting_to_a_public_address_raises_the_guard_error() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1)
        with pytest.raises(RuntimeError, match=r"203\.0\.113\.10:443; use the fakes"):
            sock.connect(("203.0.113.10", 443))
        with pytest.raises(RuntimeError, match="must not open network connections"):
            sock.connect_ex(("203.0.113.10", 443))


def test_ipv6_public_address_is_refused_too() -> None:
    guard = hermetic.NetworkGuard()
    with pytest.raises(RuntimeError, match=r"2001:db8::1:443"):
        guard.check(socket.AF_INET6, ("2001:db8::1", 443, 0, 0))


def test_loopback_connections_work() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
            client.settimeout(2)
            client.connect(("127.0.0.1", port))
            accepted, _ = server.accept()
            accepted.close()
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
            client.settimeout(2)
            assert client.connect_ex(("localhost", port)) == 0


def test_unix_sockets_and_local_names_are_allowed() -> None:
    guard = hermetic.NetworkGuard()
    guard.check(socket.AF_UNIX, "/tmp/rudix.sock")
    guard.check(socket.AF_INET, ("localhost", 5432))
    guard.check(socket.AF_INET, ("0.0.0.0", 5432))
    guard.check(socket.AF_INET6, ("::1", 5432, 0, 0))
    guard.check(socket.AF_INET, "not-a-tuple")


def test_configured_test_hosts_are_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    hosts = hermetic.allowed_hosts(
        {
            "TEST_DATABASE_URL": "postgresql+asyncpg://u:p@198.51.100.7:5432/db",
            "TEST_REDIS_URL": "redis://198.51.100.8:6379/0",
            "TEST_MIGRATIONS_DATABASE_URL": "",
        }
    )
    assert {"198.51.100.7", "198.51.100.8"} <= hosts
    guard = hermetic.NetworkGuard(hosts)
    guard.check(socket.AF_INET, ("198.51.100.7", 5432))
    with pytest.raises(RuntimeError):
        guard.check(socket.AF_INET, ("198.51.100.9", 5432))
    # A name resolves to an allowed address.
    monkeypatch.setattr(hermetic, "_resolve", lambda host: {host, "198.51.100.7"})
    guard.check(socket.AF_INET, ("db.internal", 5432))


def test_guard_install_is_idempotent_and_reversible() -> None:
    original = socket.socket.connect
    guard = hermetic.NetworkGuard()
    guard.install()
    patched = socket.socket.connect
    guard.install()
    assert socket.socket.connect is patched and guard.installed
    guard.uninstall()
    assert socket.socket.connect is original and not guard.installed


def test_provider_environment_pins_are_in_effect() -> None:
    for name, value in hermetic.PINNED_ENVIRONMENT.items():
        assert os.environ[name] == value
    for name in hermetic.PROVIDER_CREDENTIALS:
        assert name not in os.environ
    assert settings.email_provider == "console"
    assert settings.email_enabled is False
    assert settings.billing_provider == "none"
    assert settings.tracing_enabled is False
    assert settings.langfuse_enabled is False
    assert settings.openai_api_key is not None
    assert settings.openai_api_key.get_secret_value() == "test-placeholder-key"
    for attribute in hermetic.PROVIDER_CREDENTIALS.values():
        assert getattr(settings, attribute, None) is None, attribute


def test_clear_provider_credentials_reports_what_it_cleared() -> None:
    class Fake:
        resend_api_key: Any = "secret"
        sentry_dsn: Any = "https://key@example.invalid/1"

    fake = Fake()
    cleared = hermetic.clear_provider_credentials(fake)
    assert set(cleared) == {"resend_api_key", "sentry_dsn"}
    assert fake.resend_api_key is None and fake.sentry_dsn is None


def test_pin_overrides_values_exported_in_the_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMAIL_PROVIDER", "resend")
    monkeypatch.setenv("RESEND_API_KEY", "fake-live-key")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
    hermetic.pin_provider_environment()
    assert os.environ["EMAIL_PROVIDER"] == "console"
    assert os.environ["OPENAI_API_KEY"] == "test-placeholder-key"
    assert "RESEND_API_KEY" not in os.environ
