"""Readiness scope (R08-02, contract 5.2.6): ``READINESS_REQUIRED_DEPENDENCIES``.

Only the listed dependencies decide the ``/ready`` status code; the body and the
``rudix_dependency_readiness`` gauge still report every dependency. Unset keeps the
pre-0.8.0 behaviour (any failure answers 503).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api import health
from app.core.config import Settings, settings
from app.core.settings.deployment import READINESS_DEPENDENCY_NAMES, DeploymentSettings
from app.main import app
from app.shared.schemas.common import HealthDependency


def _patch_checks(monkeypatch: pytest.MonkeyPatch, *, down: set[str]) -> list[tuple[str, bool]]:
    def async_check(name: str) -> Callable[[], Awaitable[bool]]:
        async def check() -> bool:
            return name not in down

        return check

    monkeypatch.setattr(health, "check_database_health", async_check("postgres"))
    monkeypatch.setattr(health, "check_redis_health", async_check("redis"))
    monkeypatch.setattr(health, "check_cache_redis_health", async_check("redis_cache"))
    monkeypatch.setattr(health, "check_rabbitmq_health", async_check("rabbitmq"))
    monkeypatch.setattr(health, "check_neo4j_health", async_check("neo4j"))
    monkeypatch.setattr(health, "check_qdrant_health", lambda: "qdrant" not in down)
    monkeypatch.setattr(health, "check_minio_health", lambda: "minio" not in down)
    monkeypatch.setattr(health, "_openai_configuration_health", lambda: HealthDependency(ok=True))
    recorded: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        health, "set_dependency_readiness", lambda name, ok: recorded.append((name, ok))
    )
    return recorded


def test_unset_scope_fails_on_any_dependency(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "readiness_required_dependencies", None)
    _patch_checks(monkeypatch, down={"qdrant"})
    response = TestClient(app).get("/api/v1/ready")
    assert response.status_code == 503
    assert response.json()["failed_dependencies"] == ["qdrant"]
    assert response.json()["status"] == "degraded"


def test_scope_ignores_optional_failures_but_reports_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "readiness_required_dependencies", ["postgres", "redis"])
    recorded = _patch_checks(monkeypatch, down={"qdrant", "minio", "rabbitmq"})
    response = TestClient(app).get("/api/v1/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert sorted(body["failed_dependencies"]) == ["minio", "qdrant", "rabbitmq"]
    assert body["dependencies"]["qdrant"]["ok"] is False
    assert dict(recorded)["qdrant"] is False and dict(recorded)["postgres"] is True
    assert {"postgres", "redis", "rabbitmq", "qdrant", "minio", "openai_config"} <= set(
        dict(recorded)
    )


def test_scope_fails_on_a_required_dependency(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "readiness_required_dependencies", ["postgres", "redis"])
    _patch_checks(monkeypatch, down={"redis"})
    response = TestClient(app).get("/api/v1/ready")
    assert response.status_code == 503
    assert response.json()["failed_dependencies"] == ["redis"]


def test_scope_all_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "readiness_required_dependencies", ["postgres"])
    _patch_checks(monkeypatch, down=set())
    response = TestClient(app).get("/api/v1/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_every_reported_dependency_is_a_valid_scope_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "enterprise_graph_enabled", True)
    monkeypatch.setattr(settings, "redis_cache_url", "redis://cache.invalid:6379/0")
    monkeypatch.setattr(settings, "readiness_required_dependencies", None)
    _patch_checks(monkeypatch, down={"redis_cache"})
    response = TestClient(app).get("/api/v1/ready")
    names = set(response.json()["dependencies"])
    assert names == READINESS_DEPENDENCY_NAMES
    assert response.status_code == 503
    assert response.json()["failed_dependencies"] == ["redis_cache"]
    assert response.json()["dependencies"]["redis_cache"]["metadata"]["url"] == (
        "redis://cache.invalid:6379/0"
    )


def test_redis_cache_is_absent_unless_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "redis_cache_url", None)
    monkeypatch.setattr(settings, "readiness_required_dependencies", None)
    _patch_checks(monkeypatch, down=set())
    response = TestClient(app).get("/api/v1/ready")
    assert "redis_cache" not in response.json()["dependencies"]


def test_scope_setting_parses_a_comma_list() -> None:
    parsed = DeploymentSettings(readiness_required_dependencies=" postgres, Redis,,postgres ")
    assert parsed.readiness_required_dependencies == ["postgres", "redis"]
    listed = DeploymentSettings(readiness_required_dependencies=["redis"])
    assert listed.readiness_required_dependencies == ["redis"]
    assert (
        DeploymentSettings(readiness_required_dependencies=" , ").readiness_required_dependencies
        is None
    )
    assert DeploymentSettings().readiness_required_dependencies is None
    with pytest.raises(ValidationError, match="unknown dependency 'elasticsearch'"):
        DeploymentSettings(readiness_required_dependencies="postgres,elasticsearch")
    with pytest.raises(ValidationError, match="comma list"):
        DeploymentSettings(readiness_required_dependencies=5)


def test_scope_setting_reads_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("READINESS_REQUIRED_DEPENDENCIES", "postgres,redis")
    loaded = Settings()  # type: ignore[call-arg]
    assert loaded.readiness_required_dependencies == ["postgres", "redis"]
