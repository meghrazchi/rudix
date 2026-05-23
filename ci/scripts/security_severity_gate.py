#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SeverityGatePolicy:
    fail_on_critical: bool
    fail_on_high: bool
    max_critical: int
    max_high: int


@dataclass(frozen=True)
class AllowRule:
    vulnerability_id: str
    scanner: str | None = None
    severity: str | None = None
    package: str | None = None

    def matches(self, finding: "Finding") -> bool:
        if self.vulnerability_id != finding.vulnerability_id:
            return False
        if self.scanner and self.scanner != finding.scanner:
            return False
        if self.severity and self.severity != finding.severity:
            return False
        if self.package and self.package != finding.package:
            return False
        return True


@dataclass(frozen=True)
class Finding:
    report_path: str
    scanner: str
    vulnerability_id: str
    severity: str
    title: str
    package: str
    location: str


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        parsed = int(raw.strip())
    except ValueError as exc:
        raise SystemExit(f"Invalid integer value for {name}: {raw!r}") from exc
    if parsed < 0:
        raise SystemExit(f"{name} must be >= 0")
    return parsed


def _load_policy() -> SeverityGatePolicy:
    return SeverityGatePolicy(
        fail_on_critical=_env_bool("SECURITY_GATE_FAIL_ON_CRITICAL", True),
        fail_on_high=_env_bool("SECURITY_GATE_FAIL_ON_HIGH", True),
        max_critical=_env_int("SECURITY_GATE_MAX_CRITICAL", 0),
        max_high=_env_int("SECURITY_GATE_MAX_HIGH", 0),
    )


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _scanner_from_report_path(report_path: Path) -> str:
    name = report_path.name
    if "container" in name:
        return "container_scanning"
    if "dependency" in name:
        return "dependency_scanning"
    return "unknown"


def _extract_location(vuln: dict[str, Any]) -> tuple[str, str]:
    location = vuln.get("location")
    if not isinstance(location, dict):
        return "", ""

    package = _normalize_text(
        location.get("dependency", {}).get("package")
        if isinstance(location.get("dependency"), dict)
        else location.get("package")
    )

    parts = []
    file_path = _normalize_text(location.get("file"))
    if file_path:
        parts.append(file_path)
    os_name = _normalize_text(location.get("operating_system"))
    if os_name:
        parts.append(os_name)
    image = _normalize_text(location.get("image"))
    if image:
        parts.append(image)
    return package, " | ".join(parts)


def _load_findings(report_paths: list[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for report_path in report_paths:
        if not report_path.exists():
            continue
        data = json.loads(report_path.read_text())
        vulnerabilities = data.get("vulnerabilities", [])
        if not isinstance(vulnerabilities, list):
            continue

        scanner = _scanner_from_report_path(report_path)
        for vuln in vulnerabilities:
            if not isinstance(vuln, dict):
                continue
            severity = _normalize_text(vuln.get("severity")).lower()
            vulnerability_id = _normalize_text(vuln.get("id")) or _normalize_text(vuln.get("cve"))
            if not vulnerability_id:
                vulnerability_id = "unknown-id"
            title = _normalize_text(vuln.get("name")) or _normalize_text(vuln.get("message"))
            package, location = _extract_location(vuln)
            findings.append(
                Finding(
                    report_path=str(report_path),
                    scanner=scanner,
                    vulnerability_id=vulnerability_id,
                    severity=severity,
                    title=title or "No title",
                    package=package or "unknown-package",
                    location=location or "unknown-location",
                )
            )
    return findings


def _load_allow_rules(path: Path) -> list[AllowRule]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text())
    raw_rules = payload.get("allow", [])
    if not isinstance(raw_rules, list):
        raise SystemExit(f"Invalid allowlist format in {path}: 'allow' must be a list.")

    rules: list[AllowRule] = []
    for item in raw_rules:
        if not isinstance(item, dict):
            continue
        vulnerability_id = _normalize_text(item.get("id"))
        if not vulnerability_id:
            continue
        scanner = _normalize_text(item.get("scanner")) or None
        severity = _normalize_text(item.get("severity")).lower() or None
        package = _normalize_text(item.get("package")) or None
        rules.append(
            AllowRule(
                vulnerability_id=vulnerability_id,
                scanner=scanner,
                severity=severity,
                package=package,
            )
        )
    return rules


def _is_allowed(finding: Finding, rules: list[AllowRule]) -> bool:
    return any(rule.matches(finding) for rule in rules)


def _print_findings(label: str, findings: list[Finding]) -> None:
    if not findings:
        print(f"{label}: none")
        return
    print(f"{label}: {len(findings)}")
    for finding in findings[:25]:
        print(
            f"- [{finding.severity}] {finding.vulnerability_id} "
            f"scanner={finding.scanner} package={finding.package} "
            f"location={finding.location} title={finding.title}"
        )
    if len(findings) > 25:
        print(f"... {len(findings) - 25} more not shown")


def _count_severity(findings: list[Finding], *, severity: str) -> int:
    return sum(1 for finding in findings if finding.severity == severity)


def main() -> None:
    policy = _load_policy()
    report_paths = [
        Path("gl-dependency-scanning-report.json"),
        Path("gl-container-scanning-report.json"),
    ]
    allowlist_path = Path(
        os.getenv("SECURITY_GATE_ALLOWLIST_PATH", "ci/security/security_gate_allowlist.json")
    )

    findings = _load_findings(report_paths)
    allow_rules = _load_allow_rules(allowlist_path)
    actionable = [finding for finding in findings if not _is_allowed(finding, allow_rules)]
    allowed = [finding for finding in findings if _is_allowed(finding, allow_rules)]

    critical = _count_severity(actionable, severity="critical")
    high = _count_severity(actionable, severity="high")

    print(
        "security gate policy -> "
        f"fail_on_critical={policy.fail_on_critical} fail_on_high={policy.fail_on_high} "
        f"max_critical={policy.max_critical} max_high={policy.max_high}"
    )
    print(f"security gate reports -> {[str(path) for path in report_paths]}")
    print(f"security gate allowlist -> {allowlist_path} (rules={len(allow_rules)})")
    _print_findings("security gate allowed findings", allowed)
    _print_findings("security gate actionable findings", actionable)
    print(f"security gate results -> critical={critical}, high={high}")

    too_many_critical = policy.fail_on_critical and critical > policy.max_critical
    too_many_high = policy.fail_on_high and high > policy.max_high
    if too_many_critical or too_many_high:
        raise SystemExit(
            "Failing pipeline: security severity gate threshold exceeded "
            f"(critical={critical}/{policy.max_critical}, high={high}/{policy.max_high})."
        )


if __name__ == "__main__":
    main()
