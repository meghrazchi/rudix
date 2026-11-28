"""Multiprocess worker metrics (R08-09): explicit gauge modes, child counters exported, names
and labels unchanged, and the pool launcher preparing PROMETHEUS_MULTIPROC_DIR."""

from __future__ import annotations

import importlib
import re
from pathlib import Path
from typing import Any

from tests import metrics_support

metrics_support.ensure_env()

import pytest  # noqa: E402
from prometheus_client import CollectorRegistry  # noqa: E402
from prometheus_client import multiprocess as prometheus_multiprocess  # noqa: E402
from prometheus_client.metrics import Counter, Gauge, Histogram, MetricWrapperBase  # noqa: E402

from app.core.metrics_server import build_scrape_registry  # noqa: E402
from app.workers import pools  # noqa: E402

METRIC_MODULES = metrics_support.METRIC_MODULES

BACKEND_DIR = metrics_support.BACKEND_DIR
ALLOWED_GAUGE_MODES = {"livesum", "livemax", "max", "min", "mostrecent"}
_run_child = metrics_support.run_child


def _app_metrics() -> list[MetricWrapperBase]:
    for module in METRIC_MODULES:
        importlib.import_module(module)
    from app.core.metrics import registry

    return [c for c in list(registry._collector_to_names) if isinstance(c, MetricWrapperBase)]


def _families(registry: CollectorRegistry) -> dict[str, Any]:
    return {family.name: family for family in registry.collect()}


def test_every_gauge_has_an_explicit_mode_without_pid_label() -> None:
    gauges = [metric for metric in _app_metrics() if isinstance(metric, Gauge)]
    assert len(gauges) >= 14
    wrong = {g._name: g._multiprocess_mode for g in gauges}
    wrong = {name: mode for name, mode in wrong.items() if mode not in ALLOWED_GAUGE_MODES}
    assert wrong == {}


def test_every_gauge_declaration_in_app_names_its_mode() -> None:
    """Static check: a Gauge(...) call without multiprocess_mode defaults to ``all`` (pid
    label), which would change the exported labels."""
    missing: list[str] = []
    for path in (BACKEND_DIR / "app").rglob("*.py"):
        source = path.read_text()
        for match in re.finditer(r"\bGauge\(", source):
            depth, end = 0, match.end() - 1
            for end in range(match.end() - 1, len(source)):
                depth += {"(": 1, ")": -1}.get(source[end], 0)
                if depth == 0:
                    break
            call = source[match.start() : end + 1]
            if "multiprocess_mode=" not in call:
                missing.append(f"{path.relative_to(BACKEND_DIR)}:{call[:60]!r}")
    assert missing == []


def test_two_processes_sum_counters_and_keep_names_and_labels(tmp_path: Path) -> None:
    _run_child(tmp_path, 1.0)
    _run_child(tmp_path, 3.0)
    scraped = _families(build_scrape_registry(CollectorRegistry(), str(tmp_path)))
    metrics = {metric._name: metric for metric in _app_metrics()}

    # Same family names and types as the single-process registry.
    single = {
        family.name: family.type for metric in metrics.values() for family in metric.describe()
    }
    assert {name: scraped[name].type for name in single if name in scraped} == single
    assert set(single) <= set(scraped)

    for name, metric in metrics.items():
        family = scraped[name]
        expected_labels = set(metric._labelnames)
        for sample in family.samples:
            assert "pid" not in sample.labels, name
            assert set(sample.labels) - {"le"} == expected_labels, name
        values = {
            sample.name: sample.value for sample in family.samples if "le" not in sample.labels
        }
        if isinstance(metric, Counter):
            assert values == {f"{name}_total": 2.0}, name
        elif isinstance(metric, Histogram):
            assert values[f"{name}_count"] == 2.0, name
            assert values[f"{name}_sum"] == 4.0, name
        elif isinstance(metric, Gauge):
            expected = {"livesum": 4.0, "livemax": 3.0, "max": 3.0, "min": 1.0, "mostrecent": 3.0}
            assert values == {name: expected[metric._multiprocess_mode]}, name


def test_dead_process_drops_live_gauges_but_keeps_counters(tmp_path: Path) -> None:
    first = _run_child(tmp_path, 1.0)
    _run_child(tmp_path, 3.0)
    prometheus_multiprocess.mark_process_dead(first, path=str(tmp_path))
    scraped = _families(build_scrape_registry(CollectorRegistry(), str(tmp_path)))
    in_progress = scraped["rudix_http_requests_in_progress"].samples
    assert [sample.value for sample in in_progress] == [3.0]  # livesum, one live process
    assert scraped["rudix_beat_heartbeat_timestamp_seconds"].samples[0].value == 3.0  # max
    assert scraped["rudix_beat_heartbeats"].samples[0].value == 2.0


def test_single_process_mode_serves_the_application_registry() -> None:
    registry = CollectorRegistry()
    assert build_scrape_registry(registry, None) is registry


def test_scrape_registry_keeps_process_local_custom_collectors(tmp_path: Path) -> None:
    from app.core.db_metrics import DbPoolCollector

    class _Pool:
        def size(self) -> int:
            return 7

    app_registry = CollectorRegistry()
    Counter("rudix_test_only_total", "test", registry=app_registry)
    app_registry.register(DbPoolCollector(lambda: _Pool()))
    scraped = _families(build_scrape_registry(app_registry, str(tmp_path)))
    assert scraped["rudix_db_pool_size"].samples[0].value == 7.0
    # The wrapped metric comes from the (empty) files only, never twice.
    assert "rudix_test_only" not in scraped


# --- pools.py: PROMETHEUS_MULTIPROC_DIR -----------------------------------------------------


def test_prepare_multiprocess_dir_creates_and_wipes_stale_files(tmp_path: Path) -> None:
    target = tmp_path / "metrics"
    assert pools.prepare_multiprocess_dir({"PROMETHEUS_MULTIPROC_DIR": str(target)}) == str(target)
    assert target.is_dir()
    (target / "counter_12.db").write_bytes(b"old")
    (target / "keep.txt").write_text("not a metrics file")
    pools.prepare_multiprocess_dir({"PROMETHEUS_MULTIPROC_DIR": str(target)})
    assert sorted(p.name for p in target.iterdir()) == ["keep.txt"]


def test_prepare_multiprocess_dir_default(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    default = tmp_path / "rudix-prometheus"
    monkeypatch.setattr(pools, "DEFAULT_MULTIPROC_DIR", str(default))
    assert pools.prepare_multiprocess_dir({}) == str(default)
    assert default.is_dir()


def test_build_worker_env_sets_or_removes_the_directory() -> None:
    env = pools.build_worker_env("graph", {"PATH": "/bin"}, "/tmp/m")
    assert env["PROMETHEUS_MULTIPROC_DIR"] == "/tmp/m"
    stale = {"PROMETHEUS_MULTIPROC_DIR": "/tmp/old"}
    assert "PROMETHEUS_MULTIPROC_DIR" not in pools.build_worker_env("graph", stale)


@pytest.mark.parametrize(
    ("enabled", "multiprocess", "expected"),
    [(True, True, True), (True, False, False), (False, True, False)],
)
def test_main_prepares_the_directory_only_with_worker_metrics(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    enabled: bool,
    multiprocess: bool,
    expected: bool,
) -> None:
    from app.core.config import settings

    calls: list[dict[str, str]] = []
    monkeypatch.setattr(pools.os, "execvpe", lambda file, args, env: calls.append(env))
    monkeypatch.setattr(settings, "worker_metrics_enabled", enabled)
    monkeypatch.setattr(settings, "worker_metrics_multiprocess", multiprocess)
    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(tmp_path / "mp"))
    assert pools.main(["default"]) == 0
    [env] = calls
    assert ("PROMETHEUS_MULTIPROC_DIR" in env) is expected
    assert (tmp_path / "mp").is_dir() is expected
