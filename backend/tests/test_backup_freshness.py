"""Backup freshness: markers to metrics, the beat task, the CLI gate, and the deploy gate."""

from __future__ import annotations

import io
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml
from backup_support import BUCKET, NOW, FakeS3, backup_config, load_script, make_store

from app.core.config import settings
from app.core.metrics import registry
from app.ops.backup import freshness
from app.ops.backup.markers import BackupMarker, marker_key
from app.workers import backup_tasks, celery_app

REPO = Path(__file__).resolve().parents[2]
RELEASE = REPO / ".github" / "workflows" / "release.yml"
MARKER_GATE = REPO / "deploy" / "scripts" / "check_backup_markers.sh"
RULES = REPO / "infra" / "observability" / "prometheus" / "rules" / "backups.yml"


def _marker(kind: str, completed_at: datetime) -> BackupMarker:
    return BackupMarker(
        kind=kind,
        completed_at=completed_at,
        object_key=f"rudix/{kind}/run/{kind}.rbk",
        size_bytes=1,
        sha256="b" * 64,
    )


def _store_with(**ages_hours: float) -> Any:
    store = make_store()
    for kind, age in ages_hours.items():
        store.write_marker(_marker(kind, NOW - timedelta(hours=age)))
    return store


def _gauge(kind: str) -> float | None:
    return registry.get_sample_value("rudix_backup_last_success_timestamp_seconds", {"kind": kind})


def _checks(outcome: str) -> float:
    return (
        registry.get_sample_value("rudix_backup_freshness_checks_total", {"outcome": outcome})
        or 0.0
    )


@pytest.fixture
def metrics_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "metrics_enabled", True)


def test_check_freshness_classifies_kinds() -> None:
    store = _store_with(postgres=1, qdrant=30)
    store.client.objects[(BUCKET, marker_key("rudix", "neo4j"))] = b"{broken"
    results = freshness.check_freshness(
        store, ["postgres", "qdrant", "objects", "neo4j"], max_age_hours=26, now=NOW
    )
    assert [(r.kind, r.status) for r in results] == [
        ("postgres", "fresh"),
        ("qdrant", "stale"),
        ("objects", "missing"),
        ("neo4j", "invalid"),
    ]
    assert results[0].age_seconds == pytest.approx(3600)
    assert results[0].describe() == "postgres fresh age_hours=1.00"
    assert results[2].describe() == "objects missing"
    assert freshness.overall_outcome(results) == "missing"
    assert freshness.overall_outcome(results[:2]) == "stale"
    assert freshness.overall_outcome(results[:1]) == "fresh"


def test_record_freshness_sets_gauge_and_counter(metrics_on: None) -> None:
    store = _store_with(postgres=2, qdrant=40)
    before = _checks("stale")
    results = freshness.check_freshness(store, ["postgres", "qdrant"], max_age_hours=26, now=NOW)
    assert freshness.record_freshness(results) == "stale"
    assert _gauge("postgres") == (NOW - timedelta(hours=2)).timestamp()
    assert _gauge("qdrant") == (NOW - timedelta(hours=40)).timestamp()
    assert _checks("stale") == before + 1


def test_metrics_off_records_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "metrics_enabled", False)
    before = _checks("fresh")
    freshness.record_freshness([freshness.KindFreshness(kind="objects", status="fresh")])
    assert _checks("fresh") == before


def test_task_is_a_no_op_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "backup_freshness_check_enabled", False)

    def fail() -> Any:
        raise AssertionError("store must not be built")

    monkeypatch.setattr(backup_tasks, "store_factory", fail)
    assert backup_tasks.check_backup_freshness_task.run() == {"status": "disabled"}


@pytest.mark.parametrize(
    ("ages", "outcome"),
    [
        ({"postgres": 1, "qdrant": 2, "objects": 3}, "fresh"),
        ({"postgres": 1, "qdrant": 27, "objects": 3}, "stale"),
        ({"postgres": 1, "qdrant": 2}, "missing"),
    ],
)
def test_task_reports_outcome(
    monkeypatch: pytest.MonkeyPatch, metrics_on: None, ages: dict[str, float], outcome: str
) -> None:
    now = datetime.now(UTC)
    store = make_store()
    for kind, age in ages.items():
        store.write_marker(_marker(kind, now - timedelta(hours=age)))
    monkeypatch.setattr(settings, "backup_freshness_check_enabled", True)
    monkeypatch.setattr(settings, "backup_kinds", ["postgres", "qdrant", "objects"])
    monkeypatch.setattr(settings, "backup_max_age_hours", 26)
    monkeypatch.setattr(backup_tasks, "store_factory", lambda: store)
    before = _checks(outcome)
    result = backup_tasks.run_freshness_check()
    assert result["status"] == outcome and _checks(outcome) == before + 1
    assert set(result["kinds"]) == {"postgres", "qdrant", "objects"}
    if "objects" not in ages:
        assert result["kinds"]["objects"] == {"status": "missing", "age_seconds": None}
        assert _gauge("postgres") is not None


def test_task_counts_bucket_errors(monkeypatch: pytest.MonkeyPatch, metrics_on: None) -> None:
    client = FakeS3()
    client.fail_on.add("get_object")
    monkeypatch.setattr(settings, "backup_freshness_check_enabled", True)
    monkeypatch.setattr(backup_tasks, "store_factory", lambda: make_store(client))
    before = _checks("error")
    assert backup_tasks.run_freshness_check() == {"status": "error"}
    assert _checks("error") == before + 1


def test_default_store_factory_reads_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "backup_bucket", "rudix-backups")
    monkeypatch.setattr(settings, "backup_enabled", False)
    store = backup_tasks.store_factory()
    assert store.bucket == "rudix-backups" and store.prefix == settings.backup_prefix


def test_task_is_registered_routed_and_scheduled() -> None:
    assert "app.workers.backup_tasks" in celery_app.INCLUDE
    assert celery_app.TASK_ROUTES["ops.backups.check_freshness"]["queue"] == (
        settings.celery_task_default_queue
    )
    entry = celery_app.BEAT_SCHEDULE["ops-backups-check-freshness"]
    assert entry == {
        "task": "ops.backups.check_freshness",
        "schedule": settings.backup_freshness_interval_seconds,
    }


# --- check_backup_freshness.py ------------------------------------------------------------


def _cli(store: Any, tmp_path: Path, *argv: str) -> tuple[int, str, str]:
    module = load_script("check_backup_freshness")
    out, err = io.StringIO(), io.StringIO()
    code = module.main(list(argv), config=backup_config(tmp_path), store=store, out=out, err=err)
    return code, out.getvalue(), err.getvalue()


def test_cli_exit_codes(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    store = make_store()
    for kind in ("postgres", "qdrant", "objects"):
        store.write_marker(_marker(kind, now - timedelta(hours=1)))
    code, out, _ = _cli(store, tmp_path)
    assert code == 0
    assert [line.split()[:2] for line in out.splitlines()] == [
        ["postgres", "fresh"],
        ["qdrant", "fresh"],
        ["objects", "fresh"],
    ]
    store.write_marker(_marker("qdrant", now - timedelta(hours=30)))
    code, out, err = _cli(store, tmp_path)
    assert code == 1 and "qdrant stale" in out and "qdrant" in err
    code, _, _ = _cli(store, tmp_path, "--max-age-hours", "48")
    assert code == 0
    code, out, _ = _cli(store, tmp_path, "--kinds", "postgres,neo4j")
    assert code == 1 and "neo4j missing" in out
    for text in (out, err):
        assert BUCKET not in text and "rudix/" not in text


def test_cli_fails_closed(tmp_path: Path) -> None:
    client = FakeS3()
    client.fail_on.add("get_object")
    code, out, err = _cli(make_store(client), tmp_path)
    assert code == 1 and out == "" and err.strip() == "backup freshness check failed: ClientError"
    module = load_script("check_backup_freshness")
    err_buffer = io.StringIO()
    code = module.main(
        [],
        config=backup_config(tmp_path, backup_bucket=None),
        out=io.StringIO(),
        err=err_buffer,
    )
    assert code == 1 and "BackupConfigurationError" in err_buffer.getvalue()
    code = module.main(
        [], config=backup_config(tmp_path, backup_kinds=[]), out=io.StringIO(), err=io.StringIO()
    )
    assert code == 1
    with pytest.raises(SystemExit):
        module.main(["--max-age-hours", "0"], config=backup_config(tmp_path))


# --- deploy gate --------------------------------------------------------------------------


def _backup_gate_step() -> dict[str, Any]:
    workflow = yaml.safe_load(RELEASE.read_text())
    steps = [
        step
        for job in workflow["jobs"].values()
        for step in job.get("steps", [])
        if "check_remote_backups.sh" in str(step.get("run", ""))
    ]
    assert len(steps) == 1
    return steps[0]


def test_release_gate_defaults_to_ssh() -> None:
    step = _backup_gate_step()
    assert step["env"]["DEPLOY_BACKUP_GATE"] == "${{ vars.DEPLOY_BACKUP_GATE || 'ssh' }}"
    run = step["run"]
    assert "ssh) deploy/scripts/check_remote_backups.sh ;;" in run
    assert "marker) deploy/scripts/check_backup_markers.sh ;;" in run
    for name in (
        "DEPLOY_POSTGRES_BACKUP_PATH",
        "DEPLOY_MINIO_BACKUP_PATH",
        "DEPLOY_QDRANT_BACKUP_PATH",
        "DEPLOY_BACKUP_MAX_AGE_HOURS",
        "DEPLOY_APP_PATH",
    ):
        assert name in step["env"]


@pytest.mark.parametrize(("gate", "script"), [("ssh", "remote"), ("marker", "markers")])
def test_release_gate_dispatch(tmp_path: Path, gate: str, script: str) -> None:
    """Run the step's shell with stub scripts: each mode calls only its own script."""
    scripts = tmp_path / "deploy" / "scripts"
    scripts.mkdir(parents=True)
    for name in ("check_remote_backups.sh", "check_backup_markers.sh"):
        stub = scripts / name
        stub.write_text(f"#!/bin/sh\necho {name}\n")
        stub.chmod(0o755)
    run = _backup_gate_step()["run"]
    result = subprocess.run(
        ["sh", "-c", run],
        cwd=tmp_path,
        env={**os.environ, "DEPLOY_BACKUP_GATE": gate},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    expected = "check_remote_backups.sh" if script == "remote" else "check_backup_markers.sh"
    assert result.stdout.strip() == expected
    bad = subprocess.run(
        ["sh", "-c", run],
        cwd=tmp_path,
        env={**os.environ, "DEPLOY_BACKUP_GATE": "none"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert bad.returncode == 1 and "ssh or marker" in bad.stderr


def _marker_gate(**env: str) -> subprocess.CompletedProcess[str]:
    base = {
        "PATH": os.environ["PATH"],
        "DEPLOY_SSH_HOST": "deploy.invalid",
        "DEPLOY_SSH_USER": "deploy",
        "DEPLOY_SSH_PRIVATE_KEY": "placeholder",
        "DEPLOY_APP_PATH": "/srv/rudix",
        "DEPLOY_BACKUP_CHECK_PRINT_ONLY": "true",
    }
    base.update(env)
    return subprocess.run(
        ["sh", str(MARKER_GATE)], env=base, capture_output=True, text=True, check=False
    )


def test_marker_gate_runs_the_check_in_the_api_container() -> None:
    result = _marker_gate(DEPLOY_APP_PATH="/srv/ru'dix", DEPLOY_BACKUP_MAX_AGE_HOURS="30")
    assert result.returncode == 0
    assert result.stdout.splitlines() == [
        "set -eu",
        "cd '/srv/ru'\\''dix'",
        "docker compose -f 'docker-compose.production.yml' exec -T api "
        "python scripts/check_backup_freshness.py --max-age-hours 30",
    ]
    staging = _marker_gate(DEPLOY_ENVIRONMENT="staging")
    assert "docker-compose.staging.yml" in staging.stdout


@pytest.mark.parametrize(
    "env",
    [
        {"DEPLOY_APP_PATH": ""},
        {"DEPLOY_ENVIRONMENT": "dev"},
        {"DEPLOY_BACKUP_MAX_AGE_HOURS": "010"},
        {"DEPLOY_BACKUP_MAX_AGE_HOURS": "x"},
    ],
)
def test_marker_gate_rejects_bad_input(env: dict[str, str]) -> None:
    assert _marker_gate(**env).returncode == 1


def test_rules_use_the_documented_threshold() -> None:
    rules = {
        rule["alert"]: rule
        for group in yaml.safe_load(RULES.read_text())["groups"]
        for rule in group["rules"]
    }
    stale = rules["RudixBackupStale"]
    assert "26 * 3600" in stale["expr"] and stale["for"] == "15m"
    assert stale["labels"]["severity"] == "critical"
    assert settings.model_fields["backup_max_age_hours"].default == 26
    assert "rudix_backup_freshness_checks_total" in rules["RudixBackupFreshnessUnknown"]["expr"]
