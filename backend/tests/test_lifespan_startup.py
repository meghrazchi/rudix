from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.core import lifespan as lifespan_module
from app.core.config import Environment, Settings


def _patch_everything(monkeypatch: pytest.MonkeyPatch) -> dict[str, MagicMock]:
    mocks: dict[str, MagicMock] = {}
    for name in (
        "init_sentry",
        "init_langfuse",
        "init_minio",
        "init_clamav",
        "close_rabbitmq",
        "close_qdrant",
        "close_minio",
        "close_clamav",
        "shutdown_langfuse",
    ):
        mocks[name] = MagicMock()
        monkeypatch.setattr(lifespan_module, name, mocks[name])
    for name in ("close_redis", "init_neo4j", "close_neo4j", "run_graph_migrations"):
        mocks[name] = AsyncMock()
        monkeypatch.setattr(lifespan_module, name, mocks[name])
    monkeypatch.setattr(lifespan_module, "probe_local_providers", AsyncMock())
    return mocks


def _failing_async(exc: Exception) -> AsyncMock:
    return AsyncMock(side_effect=exc)


def test_optional_dependency_failures_do_not_abort_boot(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from app.main import app

    mocks = _patch_everything(monkeypatch)
    monkeypatch.setattr(lifespan_module, "init_redis", _failing_async(ConnectionError("redis")))
    monkeypatch.setattr(lifespan_module, "init_rabbitmq", MagicMock(side_effect=OSError("mq")))
    monkeypatch.setattr(lifespan_module, "init_qdrant", MagicMock(side_effect=RuntimeError("q")))

    with caplog.at_level("WARNING"):
        with TestClient(app) as client:
            response = client.get("/api/v1/health")
            assert response.status_code == 200

    unavailable = [r for r in caplog.records if r.message == "startup.dependency_unavailable"]
    assert {getattr(r, "dependency", None) for r in unavailable} == {"redis", "rabbitmq", "qdrant"}
    assert {getattr(r, "error", None) for r in unavailable} == {
        "ConnectionError",
        "OSError",
        "RuntimeError",
    }
    mocks["init_minio"].assert_called_once()
    mocks["close_redis"].assert_awaited_once()


def test_ready_reports_failed_dependencies_down(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api import health
    from app.main import app

    _patch_everything(monkeypatch)
    monkeypatch.setattr(lifespan_module, "init_redis", _failing_async(ConnectionError("x")))
    monkeypatch.setattr(lifespan_module, "init_rabbitmq", MagicMock(side_effect=OSError("x")))
    monkeypatch.setattr(lifespan_module, "init_qdrant", MagicMock(side_effect=OSError("x")))
    monkeypatch.setattr(health, "check_redis_health", AsyncMock(return_value=False))
    monkeypatch.setattr(health, "check_rabbitmq_health", AsyncMock(return_value=False))
    monkeypatch.setattr(health, "check_qdrant_health", MagicMock(return_value=False))

    with TestClient(app) as client:
        response = client.get("/api/v1/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    for name in ("redis", "rabbitmq", "qdrant"):
        assert body["dependencies"][name]["ok"] is False


@pytest.mark.parametrize(
    ("environment", "flag", "expected"),
    [
        (Environment.development, None, True),
        (Environment.test, None, True),
        (Environment.staging, None, False),
        (Environment.production, None, False),
        (Environment.production, True, True),
        (Environment.development, False, False),
    ],
)
def test_graph_migrations_on_startup_default(
    environment: Environment, flag: bool | None, expected: bool
) -> None:
    config = Settings.model_construct(environment=environment, graph_migrations_on_startup=flag)
    assert config.should_run_graph_migrations_on_startup is expected


@pytest.mark.parametrize("should_run", [True, False])
def test_lifespan_runs_graph_migrations_only_when_enabled(
    monkeypatch: pytest.MonkeyPatch, should_run: bool
) -> None:
    from app.main import app

    mocks = _patch_everything(monkeypatch)
    monkeypatch.setattr(lifespan_module, "init_redis", AsyncMock())
    monkeypatch.setattr(lifespan_module, "init_rabbitmq", MagicMock())
    monkeypatch.setattr(lifespan_module, "init_qdrant", MagicMock())
    from app.core.config import settings

    monkeypatch.setattr(settings, "graph_migrations_on_startup", should_run)

    with TestClient(app):
        pass

    if should_run:
        mocks["run_graph_migrations"].assert_awaited_once()
    else:
        mocks["run_graph_migrations"].assert_not_awaited()


@pytest.mark.asyncio
async def test_graph_migration_script_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib.util
    from pathlib import Path
    from types import SimpleNamespace

    path = Path(__file__).resolve().parent.parent / "scripts" / "run_graph_migrations.py"
    spec = importlib.util.spec_from_file_location("run_graph_migrations_script", path)
    assert spec is not None and spec.loader is not None
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)

    monkeypatch.setattr(script, "close_neo4j", AsyncMock())
    monkeypatch.setattr(script, "init_neo4j", AsyncMock())

    monkeypatch.setattr(script.settings, "enterprise_graph_enabled", False)
    assert await script.run() == 0

    monkeypatch.setattr(script.settings, "enterprise_graph_enabled", True)
    monkeypatch.setattr(script, "get_driver", lambda: None)
    assert await script.run() == 1

    monkeypatch.setattr(script, "get_driver", lambda: object())
    ok = SimpleNamespace(success=True, failed=None, applied=["a"], already_applied=[])
    monkeypatch.setattr(script, "run_graph_migrations", AsyncMock(return_value=ok))
    assert await script.run() == 0

    bad = SimpleNamespace(success=False, failed="boom", applied=[], already_applied=[])
    monkeypatch.setattr(script, "run_graph_migrations", AsyncMock(return_value=bad))
    assert await script.run() == 1

    monkeypatch.setattr(script, "run_graph_migrations", AsyncMock(side_effect=RuntimeError("x")))
    assert await script.run() == 1

    monkeypatch.setattr(script, "run_graph_migrations", AsyncMock(return_value=ok))
    monkeypatch.setattr(script.asyncio, "run", lambda coro: (coro.close(), 0)[1])
    assert script.main() == 0


@pytest.mark.parametrize(("pipeline_v2", "expected_warnings"), [(False, 1), (True, 0)])
def test_chat_pipeline_v2_false_logs_one_startup_warning(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    pipeline_v2: bool,
    expected_warnings: int,
) -> None:
    from app.core.config import settings
    from app.main import app

    _patch_everything(monkeypatch)
    monkeypatch.setattr(lifespan_module, "init_redis", AsyncMock())
    monkeypatch.setattr(lifespan_module, "init_rabbitmq", MagicMock())
    monkeypatch.setattr(lifespan_module, "init_qdrant", MagicMock())
    monkeypatch.setattr(settings, "chat_pipeline_v2", pipeline_v2)

    with caplog.at_level("WARNING"):
        with TestClient(app):
            pass

    ignored = [r for r in caplog.records if r.message == "chat.pipeline_v2_ignored"]
    assert len(ignored) == expected_warnings
    for record in ignored:
        assert getattr(record, "setting", None) == "CHAT_PIPELINE_V2"
