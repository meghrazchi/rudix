#!/usr/bin/env python3
"""CI security severity gate for Trivy and pip-audit JSON reports (R03-08).

Usage:
    security_severity_gate.py --trivy trivy-api.json --trivy trivy-worker.json
    security_severity_gate.py --pip-audit artifacts/pip-audit.json

Trivy findings keep the scanner's severity. pip-audit JSON carries no severity, so every
pip-audit finding counts as ``high`` (fail closed) unless an allowlist entry matches it.

Allowlist entries (``ci/security/security_gate_allowlist.json``) must have ``id``,
``reason`` and ``expires`` (ISO date). Optional ``scanner`` (``trivy`` or ``pip-audit``),
``package`` and ``severity`` narrow the match. An expired entry stops matching and is
printed so it gets renewed or removed.

Exit codes: 0 pass, 1 threshold exceeded, 2 invalid input (missing report, bad allowlist).
Policy environment variables: SECURITY_GATE_FAIL_ON_CRITICAL, SECURITY_GATE_FAIL_ON_HIGH,
SECURITY_GATE_MAX_CRITICAL, SECURITY_GATE_MAX_HIGH, SECURITY_GATE_ALLOWLIST_PATH.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

SCANNER_TRIVY = "trivy"
SCANNER_PIP_AUDIT = "pip-audit"
PIP_AUDIT_SEVERITY = "high"
DEFAULT_ALLOWLIST = "ci/security/security_gate_allowlist.json"

EXIT_OK = 0
EXIT_THRESHOLD = 1
EXIT_INVALID_INPUT = 2


class GateInputError(Exception):
    """A report or the allowlist is missing or malformed."""


@dataclass(frozen=True)
class SeverityGatePolicy:
    fail_on_critical: bool
    fail_on_high: bool
    max_critical: int
    max_high: int


@dataclass(frozen=True)
class Finding:
    report_path: str
    scanner: str
    vulnerability_id: str
    severity: str
    title: str
    package: str
    location: str
    match_ids: frozenset[str]


@dataclass(frozen=True)
class AllowRule:
    vulnerability_id: str
    reason: str
    expires: date
    scanner: str | None = None
    severity: str | None = None
    package: str | None = None

    def is_expired(self, today: date) -> bool:
        return today > self.expires

    def matches(self, finding: Finding) -> bool:
        if self.vulnerability_id not in finding.match_ids:
            return False
        if self.scanner and self.scanner != finding.scanner:
            return False
        if self.severity and self.severity != finding.severity:
            return False
        if self.package and self.package != finding.package:
            return False
        return True


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
        raise GateInputError(f"Invalid integer value for {name}: {raw!r}") from exc
    if parsed < 0:
        raise GateInputError(f"{name} must be >= 0")
    return parsed


def load_policy() -> SeverityGatePolicy:
    return SeverityGatePolicy(
        fail_on_critical=_env_bool("SECURITY_GATE_FAIL_ON_CRITICAL", True),
        fail_on_high=_env_bool("SECURITY_GATE_FAIL_ON_HIGH", True),
        max_critical=_env_int("SECURITY_GATE_MAX_CRITICAL", 0),
        max_high=_env_int("SECURITY_GATE_MAX_HIGH", 0),
    )


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _read_json(path: Path) -> Any:
    if not path.is_file():
        raise GateInputError(f"Report not found: {path}")
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise GateInputError(f"Report is not valid JSON: {path} ({exc.msg})") from exc


def parse_trivy_report(path: Path) -> list[Finding]:
    """Parse Trivy JSON: Results[].Vulnerabilities[]."""
    data = _read_json(path)
    if not isinstance(data, dict):
        raise GateInputError(f"Trivy report must be a JSON object: {path}")
    results = data.get("Results")
    if results is None:  # Trivy omits Results when nothing was scanned
        results = []
    if not isinstance(results, list):
        raise GateInputError(f"Trivy report 'Results' must be a list: {path}")

    findings: list[Finding] = []
    for result in results:
        if not isinstance(result, dict):
            continue
        target = _text(result.get("Target")) or "unknown-target"
        for vuln in result.get("Vulnerabilities") or []:
            if not isinstance(vuln, dict):
                continue
            vuln_id = _text(vuln.get("VulnerabilityID")) or "unknown-id"
            ids = {vuln_id}
            vendor_ids = vuln.get("VendorIDs") or []
            if isinstance(vendor_ids, list):
                ids.update(_text(item) for item in vendor_ids if _text(item))
            package = _text(vuln.get("PkgName")) or "unknown-package"
            installed = _text(vuln.get("InstalledVersion"))
            findings.append(
                Finding(
                    report_path=str(path),
                    scanner=SCANNER_TRIVY,
                    vulnerability_id=vuln_id,
                    severity=_text(vuln.get("Severity")).lower() or "unknown",
                    title=_text(vuln.get("Title")) or "No title",
                    package=package,
                    location=f"{target} {package}@{installed}".strip(),
                    match_ids=frozenset(ids),
                )
            )
    return findings


def parse_pip_audit_report(path: Path) -> list[Finding]:
    """Parse pip-audit JSON: dependencies[].vulns[]. Severity is unknown -> high."""
    data = _read_json(path)
    if isinstance(data, dict):
        dependencies = data.get("dependencies") or []
    elif isinstance(data, list):  # older pip-audit releases emitted a bare list
        dependencies = data
    else:
        raise GateInputError(f"pip-audit report has an unexpected shape: {path}")
    if not isinstance(dependencies, list):
        raise GateInputError(f"pip-audit report 'dependencies' must be a list: {path}")

    findings: list[Finding] = []
    seen: set[tuple[str, str, str]] = set()
    for dependency in dependencies:
        if not isinstance(dependency, dict):
            continue
        package = _text(dependency.get("name")) or "unknown-package"
        version = _text(dependency.get("version"))
        for vuln in dependency.get("vulns") or []:
            if not isinstance(vuln, dict):
                continue
            vuln_id = _text(vuln.get("id")) or "unknown-id"
            key = (package.lower(), version, vuln_id)
            if key in seen:  # the export can list a package once per hash set
                continue
            seen.add(key)
            ids = {vuln_id}
            aliases = vuln.get("aliases") or []
            if isinstance(aliases, list):
                ids.update(_text(alias) for alias in aliases if _text(alias))
            fixes = vuln.get("fix_versions") or []
            fix_text = ", ".join(_text(item) for item in fixes) if isinstance(fixes, list) else ""
            findings.append(
                Finding(
                    report_path=str(path),
                    scanner=SCANNER_PIP_AUDIT,
                    vulnerability_id=vuln_id,
                    severity=PIP_AUDIT_SEVERITY,
                    title=f"fix: {fix_text}" if fix_text else "no fixed version listed",
                    package=package,
                    location=f"{package}@{version}",
                    match_ids=frozenset(ids),
                )
            )
    return findings


def _parse_expires(raw: Any, vulnerability_id: str) -> date:
    text = _text(raw)
    if not text:
        raise GateInputError(f"Allowlist entry {vulnerability_id} needs 'expires' (YYYY-MM-DD)")
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise GateInputError(
            f"Allowlist entry {vulnerability_id} has an invalid 'expires': {text!r}"
        ) from exc


def load_allow_rules(path: Path) -> list[AllowRule]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise GateInputError(f"Allowlist is not valid JSON: {path} ({exc.msg})") from exc
    raw_rules = payload.get("allow", []) if isinstance(payload, dict) else None
    if not isinstance(raw_rules, list):
        raise GateInputError(f"Invalid allowlist format in {path}: 'allow' must be a list.")

    rules: list[AllowRule] = []
    for item in raw_rules:
        if not isinstance(item, dict):
            raise GateInputError(f"Invalid allowlist entry in {path}: {item!r}")
        vulnerability_id = _text(item.get("id"))
        if not vulnerability_id:
            raise GateInputError(f"Allowlist entry without 'id' in {path}")
        reason = _text(item.get("reason"))
        if not reason:
            raise GateInputError(f"Allowlist entry {vulnerability_id} needs a 'reason'")
        rules.append(
            AllowRule(
                vulnerability_id=vulnerability_id,
                reason=reason,
                expires=_parse_expires(item.get("expires"), vulnerability_id),
                scanner=_text(item.get("scanner")) or None,
                severity=_text(item.get("severity")).lower() or None,
                package=_text(item.get("package")) or None,
            )
        )
    return rules


def _print_findings(label: str, findings: Sequence[Finding]) -> None:
    if not findings:
        print(f"{label}: none")
        return
    print(f"{label}: {len(findings)}")
    for finding in findings[:50]:
        print(
            f"- [{finding.severity}] {finding.vulnerability_id} "
            f"scanner={finding.scanner} package={finding.package} "
            f"location={finding.location} title={finding.title}"
        )
    if len(findings) > 50:
        print(f"... {len(findings) - 50} more not shown")


def _count(findings: Sequence[Finding], severity: str) -> int:
    return sum(1 for finding in findings if finding.severity == severity)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument(
        "--trivy", action="append", default=[], metavar="PATH", help="Trivy JSON report"
    )
    parser.add_argument(
        "--pip-audit",
        dest="pip_audit",
        action="append",
        default=[],
        metavar="PATH",
        help="pip-audit JSON report (findings count as high)",
    )
    parser.add_argument(
        "--allowlist",
        default=os.getenv("SECURITY_GATE_ALLOWLIST_PATH", DEFAULT_ALLOWLIST),
        help="Allowlist JSON (default: SECURITY_GATE_ALLOWLIST_PATH or %(default)s)",
    )
    parser.add_argument("--today", default=None, help=argparse.SUPPRESS)
    return parser


def run(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if not args.trivy and not args.pip_audit:
        print("security gate: pass at least one --trivy or --pip-audit report", file=sys.stderr)
        return EXIT_INVALID_INPUT

    try:
        today = date.fromisoformat(args.today) if args.today else date.today()
        policy = load_policy()
        allowlist_path = Path(args.allowlist)
        all_rules = load_allow_rules(allowlist_path)
        findings: list[Finding] = []
        for trivy_path in args.trivy:
            findings.extend(parse_trivy_report(Path(trivy_path)))
        for pip_audit_path in args.pip_audit:
            findings.extend(parse_pip_audit_report(Path(pip_audit_path)))
    except (GateInputError, ValueError) as exc:
        print(f"security gate input error: {exc}", file=sys.stderr)
        return EXIT_INVALID_INPUT

    expired = [rule for rule in all_rules if rule.is_expired(today)]
    rules = [rule for rule in all_rules if not rule.is_expired(today)]
    allowed = [f for f in findings if any(rule.matches(f) for rule in rules)]
    actionable = [f for f in findings if not any(rule.matches(f) for rule in rules)]
    critical = _count(actionable, "critical")
    high = _count(actionable, "high")

    print(
        "security gate policy -> "
        f"fail_on_critical={policy.fail_on_critical} fail_on_high={policy.fail_on_high} "
        f"max_critical={policy.max_critical} max_high={policy.max_high}"
    )
    print(f"security gate reports -> trivy={args.trivy} pip-audit={args.pip_audit}")
    print(f"security gate allowlist -> {allowlist_path} (active={len(rules)})")
    for rule in expired:
        print(
            f"security gate EXPIRED allowlist entry (no longer matches): "
            f"{rule.vulnerability_id} expired={rule.expires.isoformat()} reason={rule.reason}"
        )
    _print_findings("security gate allowed findings", allowed)
    _print_findings("security gate actionable findings", actionable)
    print(f"security gate results -> critical={critical}, high={high}")

    too_many_critical = policy.fail_on_critical and critical > policy.max_critical
    too_many_high = policy.fail_on_high and high > policy.max_high
    if too_many_critical or too_many_high:
        print(
            "Failing: security severity gate threshold exceeded "
            f"(critical={critical}/{policy.max_critical}, high={high}/{policy.max_high}).",
            file=sys.stderr,
        )
        return EXIT_THRESHOLD
    return EXIT_OK


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
