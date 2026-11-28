"""Authenticated worker metrics server (R08-09, contract 5.2.8) on a real ephemeral port."""

from __future__ import annotations

import http.client
import logging
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from tests import metrics_support

metrics_support.ensure_env()

import pytest  # noqa: E402
from prometheus_client import CollectorRegistry, Counter  # noqa: E402
from pydantic import SecretStr  # noqa: E402

from app.core import metrics_server  # noqa: E402
from app.core.config import Environment, Settings, settings  # noqa: E402
from app.core.metrics_server import (  # noqa: E402
    MetricsServer,
    check_metrics_authorization,
    start_metrics_server,
    warn_if_metrics_auth_disabled,
)

TOKEN = "metrics-test-token"


def _config(**update: object) -> Settings:
    values: dict[str, object] = {
        "metrics_require_auth": False,
        "metrics_bearer_token": None,
        "worker_metrics_multiprocess": True,
    }
    values.update(update)
    return settings.model_copy(update=values)


def _registry() -> CollectorRegistry:
    registry = CollectorRegistry()
    Counter("rudix_server_test_total", "test", registry=registry).inc(5)
    return registry


@pytest.fixture
def serve(monkeypatch: pytest.MonkeyPatch) -> Iterator[object]:
    servers: list[MetricsServer] = []
    monkeypatch.delenv("PROMETHEUS_MULTIPROC_DIR", raising=False)

    def _start(config: Settings, registry: CollectorRegistry | None = None) -> MetricsServer:
        server = start_metrics_server(
            0, config=config, app_registry=registry or _registry(), addr="127.0.0.1"
        )
        servers.append(server)
        return server

    yield _start
    for server in servers:
        server.shutdown()


def _get(
    server: MetricsServer, path: str = "/metrics", method: str = "GET", **headers: str
) -> tuple[int, dict[str, str], str]:
    connection = http.client.HTTPConnection("127.0.0.1", server.port, timeout=10)
    try:
        connection.request(method, path, headers=headers)
        response = connection.getresponse()
        body = response.read().decode()
        return response.status, {k.lower(): v for k, v in response.getheaders()}, body
    finally:
        connection.close()


def test_serves_the_application_registry_without_auth(serve: object) -> None:
    server = serve(_config())  # type: ignore[operator]
    assert server.port > 0
    assert server.multiprocess is False
    status, headers, body = _get(server)
    assert status == 200
    assert headers["content-type"].startswith("text/plain")
    assert "rudix_server_test_total 5.0" in body
    assert _get(server, method="HEAD")[0] == 200


def test_auth_required_rejects_missing_and_wrong_tokens(serve: object) -> None:
    server = serve(  # type: ignore[operator]
        _config(metrics_require_auth=True, metrics_bearer_token=SecretStr(TOKEN))
    )
    status, headers, body = _get(server)
    assert (status, headers["www-authenticate"]) == (401, "Bearer")
    assert TOKEN not in body
    assert _get(server, Authorization="Basic abc")[0] == 401
    status, _, body = _get(server, Authorization="Bearer wrong")
    assert status == 403
    assert TOKEN not in body
    status, _, body = _get(server, Authorization=f"Bearer {TOKEN}")
    assert status == 200
    assert "rudix_server_test_total" in body


def test_auth_required_without_configured_token_is_401(serve: object) -> None:
    server = serve(_config(metrics_require_auth=True))  # type: ignore[operator]
    status, _, body = _get(server, Authorization="Bearer anything")
    assert status == 401
    assert "no token is configured" in body


def test_other_paths_and_methods(serve: object) -> None:
    server = serve(_config())  # type: ignore[operator]
    assert _get(server, "/")[0] == 404
    assert _get(server, "/metrics/extra")[0] == 404
    assert _get(server, method="POST")[0] == 405


def test_multiprocess_mode_exports_child_counters(
    serve: object, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    metrics_support.run_child(tmp_path, 1.0)
    metrics_support.run_child(tmp_path, 1.0)
    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(tmp_path))
    server = serve(  # type: ignore[operator]
        _config(metrics_require_auth=True, metrics_bearer_token=SecretStr(TOKEN))
    )
    assert server.multiprocess is True
    assert _get(server)[0] == 401
    status, _, body = _get(server, Authorization=f"Bearer {TOKEN}")
    assert status == 200
    assert "rudix_beat_heartbeats_total 2.0" in body
    assert 'pid="' not in body
    # The process-local test registry is not exported: values come from the files.
    assert "rudix_server_test_total" not in body


def test_multiprocess_setting_off_serves_the_registry(
    serve: object, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(tmp_path))
    server = serve(_config(worker_metrics_multiprocess=False))  # type: ignore[operator]
    assert server.multiprocess is False
    assert "rudix_server_test_total 5.0" in _get(server)[2]


def test_check_matches_the_api_route_semantics() -> None:
    assert check_metrics_authorization(None, require_auth=False, expected_token=None) is None
    missing = check_metrics_authorization(None, require_auth=True, expected_token=TOKEN)
    assert missing is not None and missing.status_code == 401
    wrong = check_metrics_authorization("Bearer x", require_auth=True, expected_token=TOKEN)
    assert wrong is not None and wrong.status_code == 403
    padded = check_metrics_authorization(
        f"Bearer  {TOKEN} ", require_auth=True, expected_token=TOKEN
    )
    assert padded is None


# --- metrics.auth_disabled warning ---------------------------------------------------------


@pytest.mark.parametrize(
    ("environment", "runtime", "update", "expected"),
    [
        (Environment.production, "api", {"metrics_enabled": True}, True),
        (Environment.staging, "worker", {"worker_metrics_enabled": True}, True),
        (Environment.production, "api", {"metrics_enabled": False}, False),
        (Environment.production, "worker", {"worker_metrics_enabled": False}, False),
        (
            Environment.production,
            "api",
            {"metrics_enabled": True, "metrics_require_auth": True},
            False,
        ),
        (Environment.development, "api", {"metrics_enabled": True}, False),
    ],
)
def test_warns_when_metrics_are_unauthenticated_in_staging_or_production(
    caplog: pytest.LogCaptureFixture,
    environment: Environment,
    runtime: str,
    update: dict[str, object],
    expected: bool,
) -> None:
    config = _config(environment=environment, **update)
    with caplog.at_level(logging.WARNING, logger="observability.metrics"):
        assert warn_if_metrics_auth_disabled(config, runtime=runtime) is expected
    records = [r for r in caplog.records if r.message == "metrics.auth_disabled"]
    assert len(records) == int(expected)
    if expected:
        assert getattr(records[0], "runtime", None) == runtime


def test_api_lifespan_runs_the_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient

    from app.core import lifespan as lifespan_module
    from app.main import app
    from tests.test_lifespan_startup import _patch_everything

    _patch_everything(monkeypatch)
    for name in ("init_redis", "init_cache_redis"):
        monkeypatch.setattr(lifespan_module, name, AsyncMock())
    for name in ("init_rabbitmq", "init_qdrant"):
        monkeypatch.setattr(lifespan_module, name, MagicMock())
    warn = MagicMock(return_value=False)
    monkeypatch.setattr(lifespan_module, "warn_if_metrics_auth_disabled", warn)
    with TestClient(app):
        pass
    warn.assert_called_once()
    assert warn.call_args.kwargs == {"runtime": "api"}


# --- celery signal handlers ----------------------------------------------------------------


def test_worker_ready_starts_the_server_only_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.workers import celery_app as celery_module

    start = MagicMock()
    warn = MagicMock(return_value=False)
    monkeypatch.setattr(metrics_server, "start_metrics_server", start)
    monkeypatch.setattr(metrics_server, "warn_if_metrics_auth_disabled", warn)
    monkeypatch.setattr(celery_module.settings, "worker_metrics_enabled", False)
    celery_module._on_worker_ready()
    start.assert_not_called()

    monkeypatch.setattr(celery_module.settings, "worker_metrics_enabled", True)
    celery_module._on_worker_ready()
    start.assert_called_once()
    assert start.call_args.args == (celery_module.settings.worker_metrics_port,)
    assert warn.call_args.kwargs == {"runtime": "worker"}


def test_worker_ready_logs_a_bind_failure(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from app.workers import celery_app as celery_module

    monkeypatch.setattr(
        metrics_server, "start_metrics_server", MagicMock(side_effect=OSError("in use"))
    )
    monkeypatch.setattr(celery_module.settings, "worker_metrics_enabled", True)
    with caplog.at_level(logging.WARNING):
        celery_module._on_worker_ready()
    assert any("worker.metrics_server_failed: OSError" in r.getMessage() for r in caplog.records)


def test_worker_process_shutdown_marks_the_process_dead(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from app.workers import celery_app as celery_module

    mark = MagicMock(return_value=True)
    monkeypatch.setattr(metrics_server, "mark_current_process_dead", mark)
    monkeypatch.setattr("app.workers.async_runtime.run_async", MagicMock())
    monkeypatch.setattr("app.clients.qdrant_client.close_qdrant", MagicMock())
    celery_module._shutdown_worker()
    mark.assert_called_once_with()

    mark.side_effect = OSError("gone")
    with caplog.at_level(logging.WARNING):
        celery_module._shutdown_worker()
    assert any("worker.metrics_mark_dead_failed" in r.getMessage() for r in caplog.records)


def test_mark_current_process_dead(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("PROMETHEUS_MULTIPROC_DIR", raising=False)
    assert metrics_server.mark_current_process_dead() is False
    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(tmp_path))
    live = tmp_path / f"gauge_livesum_{metrics_server.os.getpid()}.db"
    live.write_bytes(b"")
    kept = tmp_path / f"counter_{metrics_server.os.getpid()}.db"
    kept.write_bytes(b"")
    assert metrics_server.mark_current_process_dead() is True
    assert not live.exists()
    assert kept.exists()
