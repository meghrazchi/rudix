"""Celery beat heartbeat (R08-09, deferred from R02-03): task, schedule, metrics, alerts."""

from __future__ import annotations

from pathlib import Path

from tests import metrics_support

metrics_support.ensure_env()

import pytest  # noqa: E402
import yaml  # noqa: E402

from app.core import metrics_infra  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.workers import celery_app as celery_module  # noqa: E402
from app.workers import ops_tasks  # noqa: E402

BEAT_RULES = Path(__file__).resolve().parents[2] / "infra/observability/prometheus/rules/beat.yml"


def _heartbeats() -> float:
    return metrics_infra.BEAT_HEARTBEATS_TOTAL._value.get()


def test_task_is_included_routed_and_scheduled() -> None:
    assert "app.workers.ops_tasks" in celery_module.INCLUDE
    assert celery_module.TASK_ROUTES["ops.beat.heartbeat"] == {
        "queue": settings.celery_task_default_queue,
        "routing_key": settings.celery_task_default_queue,
    }
    entry = celery_module.BEAT_SCHEDULE["ops-beat-heartbeat"]
    assert entry["task"] == ops_tasks.BEAT_HEARTBEAT_TASK == "ops.beat.heartbeat"
    assert entry["schedule"] == settings.beat_heartbeat_interval_seconds == 60
    assert entry["options"] == {"expires": settings.beat_heartbeat_interval_seconds}
    assert "ops.beat.heartbeat" in celery_module.celery_app.tasks


def test_heartbeat_sets_timestamp_and_counter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "metrics_enabled", True)
    monkeypatch.setattr(ops_tasks, "clock", lambda: 1_800_000_000.5)
    before = _heartbeats()
    assert ops_tasks.beat_heartbeat_task.run() == 1_800_000_000.5
    assert metrics_infra.BEAT_HEARTBEAT_TIMESTAMP_SECONDS._value.get() == 1_800_000_000.5
    assert _heartbeats() == before + 1


def test_heartbeat_is_a_no_op_for_metrics_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "metrics_enabled", False)
    monkeypatch.setattr(ops_tasks, "clock", lambda: 42.0)
    before = _heartbeats()
    assert ops_tasks.beat_heartbeat() == 42.0
    assert _heartbeats() == before


def test_interval_setting_bounds() -> None:
    from pydantic import ValidationError

    from app.core.settings.observability import ObservabilitySettings

    assert ObservabilitySettings().beat_heartbeat_interval_seconds == 60
    with pytest.raises(ValidationError):
        ObservabilitySettings(beat_heartbeat_interval_seconds=5)


def test_beat_alert_rules() -> None:
    document = yaml.safe_load(BEAT_RULES.read_text())
    rules = {rule["alert"]: rule for group in document["groups"] for rule in group["rules"]}
    assert set(rules) == {"RudixBeatHeartbeatStale", "RudixBeatHeartbeatMissing"}
    stale = rules["RudixBeatHeartbeatStale"]
    assert stale["expr"].strip() == "time() - max(rudix_beat_heartbeat_timestamp_seconds) > 300"
    assert (stale["for"], stale["labels"]["severity"]) == ("5m", "critical")
    missing = rules["RudixBeatHeartbeatMissing"]
    assert "absent(rudix_beat_heartbeat_timestamp_seconds)" in missing["expr"]
    assert 'up{job="rudix-worker"} == 1' in missing["expr"]
    assert missing["for"] == "15m"
    for rule in rules.values():
        assert rule["annotations"]["summary"]
        assert rule["annotations"].get("runbook")


def test_connector_runbook_no_longer_says_there_is_no_beat_alert() -> None:
    runbook = Path(__file__).resolve().parents[2] / "docs/17_CONNECTOR_OPERATIONS_RUNBOOK.md"
    text = runbook.read_text()
    assert "There is no beat alert yet" not in text
    assert "RudixBeatHeartbeatStale" in text
