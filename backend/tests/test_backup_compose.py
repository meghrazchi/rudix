"""Compose profile `backup` and ``deploy/scripts/run_compose_backup.sh`` (R08-06)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
COMPOSE = REPO / "deploy" / "compose"
RUNNER = REPO / "deploy" / "scripts" / "run_compose_backup.sh"
CHECK = REPO / "deploy" / "scripts" / "check_compose_config.sh"


def _services(name: str) -> dict[str, Any]:
    document = yaml.safe_load((COMPOSE / f"docker-compose.{name}.yml").read_text())
    return dict(document["services"]), document


@pytest.mark.parametrize("name", ["staging", "production"])
def test_backup_services_are_profiled_one_shot_jobs(name: str) -> None:
    services, document = _services(name)
    dump, runner = services["backup-postgres-dump"], services["backup-runner"]
    for service in (dump, runner):
        assert service["profiles"] == ["backup"]
        assert service["restart"] == "no"
        assert "ports" not in service
        assert "backup_work:/backup" in service["volumes"]
    assert "backup_work" in document["volumes"]
    assert dump["image"] == "${BACKUP_POSTGRES_IMAGE:-postgres:16}"
    assert "pg_dump -Fc" in dump["command"][0] and "BACKUP_DATABASE_URL" in dump["command"][0]
    assert runner["image"] == "${RUDIX_WORKER_IMAGE}"
    assert runner["entrypoint"] == ["python", "scripts/backup_run.py"]
    environment = runner["environment"]
    assert environment["BACKUP_ENCRYPTION_KEY_FILE"] == "/run/secrets/rudix-backup.key"
    assert environment["ENVIRONMENT"] == name  # merged from the worker environment
    key_mount = next(v for v in runner["volumes"] if isinstance(v, dict))
    assert key_mount["read_only"] is True and key_mount["bind"]["create_host_path"] is False
    assert "BACKUP_ENCRYPTION_KEY" not in {k for k in environment if not k.endswith("_FILE")}


def test_backup_services_follow_redis() -> None:
    for name in ("staging", "production"):
        order = list(_services(name)[0])
        assert order.index("backup-postgres-dump") == order.index("redis") + 1
        assert order.index("backup-runner") == order.index("redis") + 2


def test_compose_check_covers_the_backup_profile() -> None:
    text = CHECK.read_text()
    assert "--profile backup" in text and "backup profile (dump + runner, key file mount)" in text


def _run(tmp_path: Path, *args: str, fail: str = "") -> tuple[int, list[str], str]:
    stubs = tmp_path / "stubs"
    stubs.mkdir(exist_ok=True)
    docker = stubs / "docker"
    docker.write_text(
        '#!/bin/sh\necho "docker $*" >> "$STUB_LOG"\n'
        'case "$*" in *"$STUB_FAIL"*) [ -n "$STUB_FAIL" ] && exit 1 ;; esac\nexit 0\n'
    )
    docker.chmod(0o755)
    app = tmp_path / "app"
    app.mkdir(exist_ok=True)
    (app / "docker-compose.production.yml").write_text("services: {}\n")
    log = tmp_path / "log"
    log.write_text("")
    result = subprocess.run(
        ["sh", str(RUNNER), *args],
        env={
            "PATH": f"{stubs}:{os.environ['PATH']}",
            "STUB_LOG": str(log),
            "STUB_FAIL": fail,
            "RUDIX_COMPOSE_DIR": str(app),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode, log.read_text().splitlines(), result.stderr


def test_runner_script_runs_dump_then_each_kind(tmp_path: Path) -> None:
    code, calls, _ = _run(tmp_path, "production", "all")
    prefix = "docker compose -f docker-compose.production.yml --profile backup run --rm --no-deps"
    assert code == 0
    assert calls == [
        f"{prefix} --entrypoint sh backup-postgres-dump -c chown 10001:10001 /backup "
        "&& chmod 700 /backup",
        f"{prefix} backup-postgres-dump",
        f"{prefix} backup-runner --kind postgres",
        f"{prefix} backup-runner --kind qdrant",
        f"{prefix} backup-runner --kind objects",
    ]
    code, calls, _ = _run(tmp_path, "production", "qdrant")
    assert code == 0 and calls[-1] == f"{prefix} backup-runner --kind qdrant" and len(calls) == 2


def test_runner_script_reports_failures(tmp_path: Path) -> None:
    code, calls, stderr = _run(tmp_path, "production", "all", fail="--kind qdrant")
    assert code == 1 and "backup failed for: qdrant" in stderr
    assert calls[-1].endswith("--kind objects")  # later kinds still run
    code, calls, stderr = _run(
        tmp_path, "production", "postgres", fail="no-deps backup-postgres-dump"
    )
    assert code == 1 and "pg_dump failed" in stderr
    assert not any("backup-runner" in call for call in calls)


@pytest.mark.parametrize("args", [(), ("dev", "all"), ("production", "redis"), ("staging", "all")])
def test_runner_script_rejects_bad_arguments(tmp_path: Path, args: tuple[str, ...]) -> None:
    code, calls, _ = _run(tmp_path, *args)
    assert code == 1 and calls == []
