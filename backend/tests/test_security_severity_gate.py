"""Regression tests for the CI security severity gate (R03-08).

The gate reads Trivy and pip-audit JSON reports, applies the allowlist (with mandatory
``reason`` and ``expires``) and fails on actionable critical/high findings.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GATE_SCRIPT = REPO_ROOT / "ci" / "scripts" / "security_severity_gate.py"
ALLOWLIST_PATH = REPO_ROOT / "ci" / "security" / "security_gate_allowlist.json"

POLICY_ENV = (
    "SECURITY_GATE_FAIL_ON_CRITICAL",
    "SECURITY_GATE_FAIL_ON_HIGH",
    "SECURITY_GATE_MAX_CRITICAL",
    "SECURITY_GATE_MAX_HIGH",
    "SECURITY_GATE_ALLOWLIST_PATH",
)


def _load_gate() -> ModuleType:
    spec = importlib.util.spec_from_file_location("security_severity_gate", GATE_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


gate = _load_gate()


@pytest.fixture(autouse=True)
def _clean_policy_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in POLICY_ENV:
        monkeypatch.delenv(name, raising=False)


def _trivy_report(*vulns: dict[str, Any], target: str = "rudix-api (debian 13.5)") -> dict:
    return {"SchemaVersion": 2, "Results": [{"Target": target, "Vulnerabilities": list(vulns)}]}


def _trivy_vuln(vuln_id: str, severity: str, package: str = "libncursesw6") -> dict[str, Any]:
    return {
        "VulnerabilityID": vuln_id,
        "PkgName": package,
        "InstalledVersion": "6.5-2",
        "Severity": severity,
        "Title": "test finding",
    }


def _pip_audit_report(*deps: dict[str, Any]) -> dict[str, Any]:
    return {"dependencies": list(deps), "fixes": []}


def _pip_dep(name: str, version: str, *vulns: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "version": version, "vulns": list(vulns)}


def _pip_vuln(vuln_id: str, aliases: list[str], fixes: list[str]) -> dict[str, Any]:
    return {"id": vuln_id, "aliases": aliases, "fix_versions": fixes, "description": "x"}


def _write(tmp_path: Path, name: str, payload: Any) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(payload))
    return path


def _allow(entries: list[dict[str, Any]], tmp_path: Path) -> Path:
    return _write(tmp_path, "allowlist.json", {"allow": entries})


def _entry(vuln_id: str, **extra: Any) -> dict[str, Any]:
    return {"id": vuln_id, "reason": "tracked upstream", "expires": "2099-01-01", **extra}


# ---------------------------------------------------------------- Trivy adapter


def test_trivy_parser_reads_results_and_vendor_ids(tmp_path: Path) -> None:
    vuln = _trivy_vuln("CVE-2025-0001", "CRITICAL", package="openssl")
    vuln["VendorIDs"] = ["DSA-1234-1"]
    report = _trivy_report(vuln)
    report["Results"].append({"Target": "app/requirements", "Vulnerabilities": None})
    findings = gate.parse_trivy_report(_write(tmp_path, "trivy.json", report))

    assert len(findings) == 1
    finding = findings[0]
    assert finding.scanner == "trivy"
    assert finding.severity == "critical"
    assert finding.package == "openssl"
    assert finding.match_ids == frozenset({"CVE-2025-0001", "DSA-1234-1"})
    assert "rudix-api" in finding.location


def test_trivy_high_finding_fails_gate(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    trivy = _write(tmp_path, "trivy.json", _trivy_report(_trivy_vuln("CVE-2025-0002", "HIGH")))
    code = gate.run(["--trivy", str(trivy), "--allowlist", str(_allow([], tmp_path))])
    out = capsys.readouterr()
    assert code == gate.EXIT_THRESHOLD
    assert "high=1" in out.out
    assert "threshold exceeded" in out.err


def test_trivy_low_and_medium_findings_pass(tmp_path: Path) -> None:
    trivy = _write(
        tmp_path,
        "trivy.json",
        _trivy_report(_trivy_vuln("CVE-1", "LOW"), _trivy_vuln("CVE-2", "MEDIUM")),
    )
    assert gate.run(["--trivy", str(trivy), "--allowlist", str(_allow([], tmp_path))]) == 0


def test_multiple_trivy_reports_are_combined(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    api = _write(tmp_path, "api.json", _trivy_report(_trivy_vuln("CVE-A", "CRITICAL")))
    worker = _write(tmp_path, "worker.json", _trivy_report(_trivy_vuln("CVE-B", "HIGH")))
    code = gate.run(
        ["--trivy", str(api), "--trivy", str(worker), "--allowlist", str(_allow([], tmp_path))]
    )
    assert code == gate.EXIT_THRESHOLD
    assert "critical=1, high=1" in capsys.readouterr().out


# ------------------------------------------------------------ pip-audit adapter


def test_pip_audit_findings_count_as_high_and_dedupe(tmp_path: Path) -> None:
    vuln = _pip_vuln("PYSEC-2026-1", ["CVE-2026-1", "GHSA-xxxx"], ["50.0.0"])
    report = _pip_audit_report(
        _pip_dep("cryptography", "49.0.0", vuln),
        _pip_dep("cryptography", "49.0.0", vuln),
        _pip_dep("fastapi", "0.1.0"),
    )
    findings = gate.parse_pip_audit_report(_write(tmp_path, "pa.json", report))

    assert len(findings) == 1
    assert findings[0].severity == "high"
    assert findings[0].scanner == "pip-audit"
    assert findings[0].match_ids == frozenset({"PYSEC-2026-1", "CVE-2026-1", "GHSA-xxxx"})
    assert findings[0].title == "fix: 50.0.0"


def test_pip_audit_legacy_list_shape_is_supported(tmp_path: Path) -> None:
    report = [_pip_dep("jinja2", "3.0.0", _pip_vuln("PYSEC-1", [], []))]
    findings = gate.parse_pip_audit_report(_write(tmp_path, "pa.json", report))
    assert [f.title for f in findings] == ["no fixed version listed"]


def test_pip_audit_finding_fails_closed(tmp_path: Path) -> None:
    report = _pip_audit_report(_pip_dep("virtualenv", "1.0", _pip_vuln("PYSEC-9", [], ["2.0"])))
    path = _write(tmp_path, "pa.json", report)
    assert gate.run(["--pip-audit", str(path), "--allowlist", str(_allow([], tmp_path))]) == 1


def test_clean_pip_audit_report_passes(tmp_path: Path) -> None:
    path = _write(tmp_path, "pa.json", _pip_audit_report(_pip_dep("fastapi", "1.0")))
    assert gate.run(["--pip-audit", str(path), "--allowlist", str(_allow([], tmp_path))]) == 0


# ------------------------------------------------------------------- allowlist


def test_allowlist_matches_alias_scanner_and_package(tmp_path: Path) -> None:
    report = _pip_audit_report(
        _pip_dep("cryptography", "49.0.0", _pip_vuln("PYSEC-1", ["CVE-2026-1"], []))
    )
    path = _write(tmp_path, "pa.json", report)
    allow = _allow([_entry("CVE-2026-1", scanner="pip-audit", package="cryptography")], tmp_path)
    assert gate.run(["--pip-audit", str(path), "--allowlist", str(allow)]) == 0


@pytest.mark.parametrize(
    "extra",
    [{"scanner": "pip-audit"}, {"package": "other"}, {"severity": "critical"}],
)
def test_allowlist_narrowing_fields_must_all_match(tmp_path: Path, extra: dict[str, str]) -> None:
    trivy = _write(tmp_path, "t.json", _trivy_report(_trivy_vuln("CVE-X", "HIGH")))
    allow = _allow([_entry("CVE-X", **extra)], tmp_path)
    assert gate.run(["--trivy", str(trivy), "--allowlist", str(allow)]) == 1


def test_expired_entry_stops_matching_and_is_printed(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    trivy = _write(tmp_path, "t.json", _trivy_report(_trivy_vuln("CVE-OLD", "HIGH")))
    allow = _allow([{"id": "CVE-OLD", "reason": "old", "expires": "2026-01-31"}], tmp_path)
    args = ["--trivy", str(trivy), "--allowlist", str(allow)]

    assert gate.run([*args, "--today", "2026-01-31"]) == 0  # still valid on the expiry date
    capsys.readouterr()
    assert gate.run([*args, "--today", "2026-02-01"]) == 1
    assert "EXPIRED allowlist entry (no longer matches): CVE-OLD" in capsys.readouterr().out


@pytest.mark.parametrize(
    "entry",
    [
        {"id": "CVE-1", "expires": "2099-01-01"},
        {"id": "CVE-1", "reason": "x"},
        {"id": "CVE-1", "reason": "x", "expires": "next year"},
        {"reason": "x", "expires": "2099-01-01"},
        "CVE-1",
    ],
)
def test_invalid_allowlist_entry_is_input_error(tmp_path: Path, entry: Any) -> None:
    trivy = _write(tmp_path, "t.json", _trivy_report())
    allow = _write(tmp_path, "allow.json", {"allow": [entry]})
    assert gate.run(["--trivy", str(trivy), "--allowlist", str(allow)]) == gate.EXIT_INVALID_INPUT


def test_allowlist_must_be_a_list(tmp_path: Path) -> None:
    trivy = _write(tmp_path, "t.json", _trivy_report())
    allow = _write(tmp_path, "allow.json", {"allow": {"id": "x"}})
    assert gate.run(["--trivy", str(trivy), "--allowlist", str(allow)]) == 2


def test_missing_allowlist_file_means_no_rules(tmp_path: Path) -> None:
    trivy = _write(tmp_path, "t.json", _trivy_report(_trivy_vuln("CVE-1", "HIGH")))
    assert gate.run(["--trivy", str(trivy), "--allowlist", str(tmp_path / "none.json")]) == 1


def test_committed_allowlist_is_valid_and_has_no_cryptography_exception() -> None:
    rules = gate.load_allow_rules(ALLOWLIST_PATH)
    assert rules, "the committed allowlist should parse"
    assert all(rule.reason and rule.expires for rule in rules)
    assert not any((rule.package or "").lower() == "cryptography" for rule in rules)


def test_committed_ncurses_entry_allowlists_trivy_base_image_cve(tmp_path: Path) -> None:
    trivy = _write(tmp_path, "t.json", _trivy_report(_trivy_vuln("CVE-2025-69720", "HIGH")))
    args = ["--trivy", str(trivy), "--allowlist", str(ALLOWLIST_PATH), "--today", "2026-12-01"]
    assert gate.run(args) == 0


# --------------------------------------------------------- inputs and policy


def test_no_reports_is_input_error() -> None:
    assert gate.run([]) == gate.EXIT_INVALID_INPUT


def test_missing_report_fails_closed(tmp_path: Path) -> None:
    assert gate.run(["--trivy", str(tmp_path / "absent.json")]) == gate.EXIT_INVALID_INPUT


def test_malformed_reports_are_input_errors(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert gate.run(["--pip-audit", str(bad)]) == 2
    assert gate.run(["--trivy", str(_write(tmp_path, "list.json", []))]) == 2
    assert gate.run(["--trivy", str(_write(tmp_path, "r.json", {"Results": {}}))]) == 2
    assert gate.run(["--pip-audit", str(_write(tmp_path, "s.json", "x"))]) == 2
    assert gate.run(["--pip-audit", str(_write(tmp_path, "d.json", {"dependencies": 1}))]) == 2


def test_policy_env_allows_high_budget(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    trivy = _write(tmp_path, "t.json", _trivy_report(_trivy_vuln("CVE-1", "HIGH")))
    args = ["--trivy", str(trivy), "--allowlist", str(_allow([], tmp_path))]
    monkeypatch.setenv("SECURITY_GATE_MAX_HIGH", "1")
    assert gate.run(args) == 0
    monkeypatch.setenv("SECURITY_GATE_MAX_HIGH", "0")
    monkeypatch.setenv("SECURITY_GATE_FAIL_ON_HIGH", "false")
    assert gate.run(args) == 0


@pytest.mark.parametrize("value", ["abc", "-1"])
def test_invalid_policy_env_is_input_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    trivy = _write(tmp_path, "t.json", _trivy_report())
    monkeypatch.setenv("SECURITY_GATE_MAX_CRITICAL", value)
    assert gate.run(["--trivy", str(trivy)]) == gate.EXIT_INVALID_INPUT


def test_allowlist_path_from_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    trivy = _write(tmp_path, "t.json", _trivy_report(_trivy_vuln("CVE-E", "CRITICAL")))
    monkeypatch.setenv("SECURITY_GATE_ALLOWLIST_PATH", str(_allow([_entry("CVE-E")], tmp_path)))
    assert gate.run(["--trivy", str(trivy)]) == 0


def test_cli_exit_codes_via_subprocess(tmp_path: Path) -> None:
    trivy = _write(tmp_path, "t.json", _trivy_report(_trivy_vuln("CVE-S", "CRITICAL")))
    allow = _allow([], tmp_path)
    result = subprocess.run(
        [sys.executable, str(GATE_SCRIPT), "--trivy", str(trivy), "--allowlist", str(allow)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "critical=1" in result.stdout

    missing = subprocess.run(
        [sys.executable, str(GATE_SCRIPT), "--pip-audit", str(tmp_path / "missing.json")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert missing.returncode == 2
    assert "Report not found" in missing.stderr
