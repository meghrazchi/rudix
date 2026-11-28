"""Shared 0.8.0 infrastructure gauges (S1): names, types, labels, modes, export, setters."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest
from prometheus_client import Gauge

from app.core import metrics, metrics_infra
from app.core.config import settings
from app.core.settings.backup import BackupSettings
from app.core.settings.deployment import DeploymentSettings
from app.core.settings.tracing import TracingSettings

EXPECTED = {
    "rudix_chat_ws_connections": (metrics_infra.CHAT_WS_CONNECTIONS, (), "livesum"),
    "rudix_beat_heartbeat_timestamp_seconds": (
        metrics_infra.BEAT_HEARTBEAT_TIMESTAMP_SECONDS,
        (),
        "max",
    ),
    "rudix_backup_last_success_timestamp_seconds": (
        metrics_infra.BACKUP_LAST_SUCCESS_TIMESTAMP_SECONDS,
        ("kind",),
        "max",
    ),
    "rudix_db_replica_lag_seconds": (metrics_infra.DB_REPLICA_LAG_SECONDS, (), "max"),
}


def _sample(name: str, labels: dict[str, str] | None = None) -> float | None:
    return metrics.registry.get_sample_value(name, labels or {})


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_gauge_shape(name: str) -> None:
    gauge, labels, mode = EXPECTED[name]
    assert isinstance(gauge, Gauge)
    assert gauge._name == name
    assert tuple(gauge._labelnames) == labels
    assert gauge._multiprocess_mode == mode


def test_gauges_are_exported_by_the_shared_registry() -> None:
    exported = {family.name for family in metrics.registry.collect()}
    assert set(EXPECTED) <= exported
    body = metrics.generate_prometheus_metrics().body
    assert isinstance(body, bytes)
    for name in EXPECTED:
        assert f"# TYPE {name} gauge".encode() in body


@pytest.mark.parametrize(
    "module",
    [
        "app.application.realtime.publisher",
        "app.application.realtime.stream_http",
        "app.interfaces.http.events",
    ],
)
def test_realtime_importers_also_import_the_module(module: str) -> None:
    loaded = importlib.import_module(module)
    source = Path(str(loaded.__file__)).read_text()
    assert "import app.core.metrics_infra" in source
    assert "app.core.metrics_infra" in sys.modules


def test_setters_write_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "metrics_enabled", True)
    metrics_infra.set_chat_ws_connections(3)
    assert _sample("rudix_chat_ws_connections") == 3.0
    metrics_infra.set_chat_ws_connections(-2)
    assert _sample("rudix_chat_ws_connections") == 0.0
    metrics_infra.set_beat_heartbeat_timestamp(1_700_000_000.0)
    assert _sample("rudix_beat_heartbeat_timestamp_seconds") == 1_700_000_000.0
    metrics_infra.set_backup_last_success_timestamp("postgres", 1_700_000_100.0)
    assert (
        _sample("rudix_backup_last_success_timestamp_seconds", {"kind": "postgres"})
        == 1_700_000_100.0
    )
    metrics_infra.set_db_replica_lag_seconds(2.5)
    assert _sample("rudix_db_replica_lag_seconds") == 2.5
    metrics_infra.set_db_replica_lag_seconds(-1.0)
    assert _sample("rudix_db_replica_lag_seconds") == 0.0


def test_setters_are_no_ops_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "metrics_enabled", True)
    metrics_infra.set_chat_ws_connections(1)
    metrics_infra.set_beat_heartbeat_timestamp(10.0)
    metrics_infra.set_backup_last_success_timestamp("qdrant", 20.0)
    metrics_infra.set_db_replica_lag_seconds(1.0)
    monkeypatch.setattr(settings, "metrics_enabled", False)
    metrics_infra.set_chat_ws_connections(9)
    metrics_infra.set_beat_heartbeat_timestamp(99.0)
    metrics_infra.set_backup_last_success_timestamp("qdrant", 99.0)
    metrics_infra.set_db_replica_lag_seconds(99.0)
    assert _sample("rudix_chat_ws_connections") == 1.0
    assert _sample("rudix_beat_heartbeat_timestamp_seconds") == 10.0
    assert _sample("rudix_backup_last_success_timestamp_seconds", {"kind": "qdrant"}) == 20.0
    assert _sample("rudix_db_replica_lag_seconds") == 1.0


def test_infrastructure_settings_stubs_are_registered_and_inert() -> None:
    from app.core.config import Settings

    for base in (DeploymentSettings, TracingSettings, BackupSettings):
        assert issubclass(Settings, base)
    infrastructure = settings.sanitized_snapshot()["infrastructure"]
    assert isinstance(infrastructure, dict)
    for value in infrastructure.values():
        assert isinstance(value, (bool, int, float, str, type(None), list, dict))
