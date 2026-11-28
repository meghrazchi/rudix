"""``deploy/scripts/restore_drill.sh`` with stub tools (R08-06, R08-04): it refuses live
stores, and runs download, pg_restore, verify, the Qdrant upload, and the smoke in order."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

DRILL = Path(__file__).resolve().parents[2] / "deploy" / "scripts" / "restore_drill.sh"
SCRATCH = "postgresql://drill@scratch-db.internal/rudix_drill"

STUB_PYTHON = """#!/bin/sh
echo "python $*" >> "$STUB_LOG"
case "$*" in
  -c*) exec python3 "$@" ;;
  *"--kind qdrant"*)
    out=""
    prev=""
    for arg in "$@"; do
      [ "$prev" = "--out" ] && out="$arg"
      prev="$arg"
    done
    mkdir -p "$out"
    printf 'snap' > "$out/documents.snapshot"
    printf '[{"alias": "live", "collection": "documents"}]' > "$out/aliases.json"
    ;;
esac
"""
STUB_TOOL = """#!/bin/sh
echo "$(basename "$0") $*" >> "$STUB_LOG"
"""


def _drill(tmp_path: Path, **env: str) -> tuple[subprocess.CompletedProcess[str], str]:
    stubs = tmp_path / "stubs"
    stubs.mkdir(exist_ok=True)
    for name, body in (("python", STUB_PYTHON), ("pg_restore", STUB_TOOL), ("curl", STUB_TOOL)):
        (stubs / name).write_text(body)
        (stubs / name).chmod(0o755)
    log = tmp_path / "calls.log"
    log.write_text("")
    base = {
        "PATH": f"{stubs}:{os.environ['PATH']}",
        "PYTHON": str(stubs / "python"),
        "STUB_LOG": str(log),
        "RESTORE_DATABASE_URL": SCRATCH,
        "RESTORE_QDRANT_URL": "http://scratch-qdrant:6333",
    }
    base.update(env)
    result = subprocess.run(
        ["sh", str(DRILL)], env=base, capture_output=True, text=True, check=False, timeout=60
    )
    return result, log.read_text()


@pytest.mark.parametrize(
    "live", ["DATABASE_URL", "DATABASE_MIGRATION_URL", "DATABASE_MAINTENANCE_URL"]
)
def test_drill_refuses_a_live_database(tmp_path: Path, live: str) -> None:
    same = "postgresql+asyncpg://drill@scratch-db.internal/rudix_drill/"
    result, calls = _drill(tmp_path, **{live: same})
    assert result.returncode == 2 and f"equals {live}" in result.stderr
    assert calls == ""


def test_drill_refuses_the_live_qdrant_and_missing_inputs(tmp_path: Path) -> None:
    result, calls = _drill(tmp_path, QDRANT_URL="http://scratch-qdrant:6333/")
    assert result.returncode == 2 and "QDRANT_URL" in result.stderr and calls == ""
    result, _ = _drill(tmp_path, RESTORE_DATABASE_URL="")
    assert result.returncode == 1 and "RESTORE_DATABASE_URL" in result.stderr
    result, _ = _drill(tmp_path, RESTORE_QDRANT_URL="")
    assert result.returncode == 1 and "RESTORE_SKIP_QDRANT" in result.stderr


def test_drill_dry_run_prints_the_plan(tmp_path: Path) -> None:
    result, calls = _drill(
        tmp_path,
        RESTORE_DRILL_DRY_RUN="true",
        RESTORE_API_URL="http://scratch-api:8000",
        RESTORE_EXPECT_REVISION="20261128_0003",
    )
    assert result.returncode == 0 and calls == ""
    assert "--expect-revision 20261128_0003" in result.stdout
    assert "scratch Qdrant" in result.stdout and "smoke" in result.stdout


def test_drill_runs_every_step_against_scratch_stores(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    result, calls = _drill(
        tmp_path,
        RESTORE_WORK_DIR=str(work),
        RESTORE_API_URL="http://scratch-api:8000/",
        RESTORE_QDRANT_API_KEY="scratch-key",
        RESTORE_KEY_FILES="/keys/old.key",
        RESTORE_MANIFEST="/drill/floors.json",
    )
    assert result.returncode == 0, result.stderr
    lines = calls.splitlines()
    assert lines[0].startswith("python scripts/backup_restore.py --kind postgres --latest")
    assert "--key-file /keys/old.key" in lines[0]
    assert lines[1].startswith("pg_restore --no-owner --no-privileges --exit-on-error")
    assert SCRATCH in lines[1]
    assert lines[2] == (
        f"python scripts/verify_postgres_restore.py --database-url {SCRATCH} "
        "--manifest /drill/floors.json"
    )
    assert "--kind qdrant" in lines[3]
    assert any("collections/documents/snapshots/upload?priority=snapshot" in x for x in lines)
    assert any("collections/aliases" in x and '"live"' in x for x in lines)
    assert lines[-2:] == [
        "curl -fsS http://scratch-api:8000/api/v1/health",
        "curl -fsS http://scratch-api:8000/api/v1/ready",
    ]
    assert "| Smoke | passed |" in result.stdout and "<measured>" in result.stdout
    assert list(work.iterdir()) == []


def test_drill_postgres_only_keeps_files_on_request(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    (work / "postgres.dump").write_text("x")
    result, calls = _drill(
        tmp_path, RESTORE_SKIP_QDRANT="true", RESTORE_WORK_DIR=str(work), RESTORE_KEEP_FILES="true"
    )
    assert result.returncode == 0, result.stderr
    assert "--kind qdrant" not in calls and "| Qdrant restored | skipped |" in result.stdout
    assert "not run (RESTORE_API_URL unset)" in result.stdout
    assert (work / "postgres.dump").exists()


@pytest.mark.parametrize(
    "live",
    [
        "postgresql+asyncpg://rudix_app:secret@scratch-db.internal/rudix_drill",
        "postgresql://rudix_maintenance@SCRATCH-DB.internal:5432/rudix_drill?sslmode=require",
        "postgres://scratch-db.internal/rudix_drill",
    ],
)
def test_drill_refuses_the_live_database_under_another_role_or_options(
    tmp_path: Path, live: str
) -> None:
    result, calls = _drill(tmp_path, DATABASE_URL=live)
    assert result.returncode == 2 and "DATABASE_URL" in result.stderr
    assert calls == ""


def test_drill_accepts_another_port_or_database_and_passes_a_libpq_url(tmp_path: Path) -> None:
    for live in (
        "postgresql://drill@scratch-db.internal:6432/rudix_drill",
        "postgresql://drill@scratch-db.internal/rudix",
    ):
        result, _ = _drill(tmp_path, DATABASE_URL=live, RESTORE_DRILL_DRY_RUN="true")
        assert result.returncode == 0, result.stderr
    asyncpg_url = "postgresql+asyncpg://drill@scratch-db.internal/rudix_drill"
    result, calls = _drill(tmp_path, RESTORE_DATABASE_URL=asyncpg_url, RESTORE_SKIP_QDRANT="true")
    assert result.returncode == 0, result.stderr
    assert "+asyncpg" not in calls and calls.count(SCRATCH) == 2
