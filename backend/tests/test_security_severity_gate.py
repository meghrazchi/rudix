"""Regression tests for the CI security severity gate script."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
GATE_SCRIPT = REPO_ROOT / "ci" / "scripts" / "security_severity_gate.py"
ALLOWLIST_PATH = REPO_ROOT / "ci" / "security" / "security_gate_allowlist.json"


def _run_gate(
    tmp_path: Path,
    *,
    container_report: dict[str, Any],
    allowlist: dict[str, Any] | None = None,
) -> subprocess.CompletedProcess[str]:
    dependency_report = tmp_path / "gl-dependency-scanning-report.json"
    container_path = tmp_path / "gl-container-scanning-report.json"
    allowlist_path = tmp_path / "security_gate_allowlist.json"

    dependency_report.write_text(json.dumps({"vulnerabilities": []}))
    container_path.write_text(json.dumps(container_report))
    if allowlist is not None:
        allowlist_path.write_text(json.dumps(allowlist))
    else:
        allowlist_path.write_text(ALLOWLIST_PATH.read_text())

    env = {
        **dict(**__import__("os").environ),
        "SECURITY_GATE_ALLOWLIST_PATH": str(allowlist_path),
    }
    return subprocess.run(
        [sys.executable, str(GATE_SCRIPT)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_gate_fails_on_unallowlisted_gitlab_hash_id(tmp_path: Path) -> None:
    report = {
        "vulnerabilities": [
            {
                "id": "gitlab-internal-hash-001",
                "severity": "high",
                "cve": "CVE-2025-69720",
                "name": "ncurses: buffer overflow",
                "location": {
                    "dependency": {"package": {"name": "libncursesw6"}},
                    "operating_system": "debian 13.5",
                },
            }
        ]
    }
    result = _run_gate(
        tmp_path,
        container_report=report,
        allowlist={"allow": []},
    )
    assert result.returncode != 0
    assert "high=1" in result.stdout


def test_gate_allows_high_ncurses_when_cve_is_allowlisted(tmp_path: Path) -> None:
    report = {
        "vulnerabilities": [
            {
                "id": "gitlab-internal-hash-001",
                "severity": "high",
                "cve": "CVE-2025-69720",
                "name": "ncurses: buffer overflow",
                "location": {
                    "dependency": {"package": {"name": "libncursesw6"}},
                    "operating_system": "debian 13.5",
                },
            }
        ]
    }
    result = _run_gate(
        tmp_path,
        container_report=report,
        allowlist={
            "allow": [
                {
                    "id": "CVE-2025-69720",
                    "scanner": "container_scanning",
                    "severity": "high",
                    "package": "libncursesw6",
                }
            ]
        },
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "high=0" in result.stdout
