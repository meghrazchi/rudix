#!/usr/bin/env python3
"""Quality gate CI runner.

Triggers a quality gate run against a completed evaluation run (and/or safety
eval run) by calling the Rudix API, waits for the result, and exits with
code 0 (pass / overridden) or 1 (fail).

The full gate report is written to QUALITY_GATE_REPORT_PATH (default:
artifacts/quality-gate-report.json) for upload as a CI artifact.

Required environment variables:
  RUDIX_API_BASE_URL     Base URL of the Rudix API, e.g. https://staging.example.com/api/v1
  RUDIX_API_TOKEN        Bearer token for authentication
  QUALITY_GATE_ID        UUID of the quality gate configuration to run against

Optional:
  EVALUATION_RUN_ID      UUID of the completed evaluation run to check, or 'latest' to
                         use the newest completed run of ACCURACY_EVAL_SET_ID
  ACCURACY_EVAL_SET_ID   Evaluation set UUID; required when EVALUATION_RUN_ID=latest
  QUALITY_GATE_MAX_RUN_AGE_HOURS  With 'latest': fail when the newest completed run
                         finished longer ago than this (default: 36)
  SAFETY_EVAL_RUN_ID     UUID of the completed safety eval run to check
  QUALITY_GATE_REPORT_PATH  Path to write the JSON report (default: artifacts/quality-gate-report.json)
  QUALITY_GATE_DRY_RUN   Set to '1' to evaluate and report but always exit 0
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

LATEST_RUN_ALIAS = "latest"
DEFAULT_MAX_RUN_AGE_HOURS = 36.0
RUN_LIST_LIMIT = 50
USER_AGENT = "rudix-ci/1.0 (quality-gate)"


def _env(name: str, required: bool = False, default: str = "") -> str:
    value = os.getenv(name, default).strip()
    if required and not value:
        _die(f"Required environment variable {name!r} is not set.")
    return value


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, "")
    return raw.strip().lower() in {"1", "true", "yes", "on"} if raw.strip() else default


def _die(message: str) -> None:
    print(f"[quality-gate] ERROR: {message}", file=sys.stderr)
    sys.exit(1)


def _info(message: str) -> None:
    print(f"[quality-gate] {message}")


def _api_request(
    url: str,
    *,
    token: str,
    method: str = "GET",
    body: dict | None = None,
) -> dict:
    data: bytes | None = None
    if body is not None:
        data = json.dumps(body).encode()

    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            # Cloudflare blocks the default Python-urllib User-Agent (error 1010).
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode(errors="replace")
        _die(f"API request failed ({exc.code}): {url}\n{body_text}")
    except urllib.error.URLError as exc:
        _die(f"API connection error: {url}\n{exc.reason}")


def _parse_timestamp(raw: object) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        parsed = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _max_run_age_hours() -> float:
    raw = _env("QUALITY_GATE_MAX_RUN_AGE_HOURS", default=str(DEFAULT_MAX_RUN_AGE_HOURS))
    try:
        hours = float(raw)
    except ValueError:
        _die(f"QUALITY_GATE_MAX_RUN_AGE_HOURS must be a number, got {raw!r}.")
    if hours <= 0:
        _die("QUALITY_GATE_MAX_RUN_AGE_HOURS must be greater than zero.")
    return hours


def resolve_latest_evaluation_run(
    api_base: str,
    *,
    token: str,
    evaluation_set_id: str,
    max_age_hours: float,
    now: datetime | None = None,
) -> str:
    """Return the newest completed run of ``evaluation_set_id``, or exit 1.

    Lists ``GET {api_base}/evaluations/runs?evaluation_set_id=...&status=completed``
    and picks the run with the latest ``completed_at``. Fails when no completed run
    exists or the newest one finished more than ``max_age_hours`` ago.
    """
    query = urllib.parse.urlencode(
        {"evaluation_set_id": evaluation_set_id, "status": "completed", "limit": RUN_LIST_LIMIT}
    )
    listing = _api_request(f"{api_base}/evaluations/runs?{query}", token=token)
    candidates: list[tuple[datetime, str]] = []
    for item in listing.get("items", []) if isinstance(listing, dict) else []:
        if not isinstance(item, dict) or item.get("status") != "completed":
            continue
        if str(item.get("evaluation_set_id", "")) != evaluation_set_id:
            continue
        completed_at = _parse_timestamp(item.get("completed_at"))
        run_id = str(item.get("evaluation_run_id", "")).strip()
        if completed_at is None or not run_id:
            continue
        candidates.append((completed_at, run_id))
    if not candidates:
        _die(f"No completed evaluation run found for evaluation set {evaluation_set_id}.")
    completed_at, run_id = max(candidates)
    current = now or datetime.now(UTC)
    age = current - completed_at
    if age > timedelta(hours=max_age_hours):
        _die(
            f"Newest completed evaluation run {run_id} finished at {completed_at.isoformat()}, "
            f"{age.total_seconds() / 3600:.1f}h ago; older than the {max_age_hours:g}h limit "
            "(QUALITY_GATE_MAX_RUN_AGE_HOURS). Has the nightly accuracy eval run?"
        )
    _info(f"Latest completed run: {run_id} (completed {completed_at.isoformat()})")
    return run_id


def _write_report(report: dict, report_path: Path) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, default=str))
    _info(f"Report written to {report_path}")


def _print_gate_summary(report: dict) -> None:
    _info(f"Quality gate: {report.get('quality_gate_name', 'unknown')}")
    _info(f"Verdict:      {report.get('verdict', 'unknown').upper()}")
    _info(
        f"Checks:       {report.get('pass_count', 0)} passed, "
        f"{report.get('fail_count', 0)} failed "
        f"({report.get('total_checks', 0)} total)"
    )

    failed_checks = report.get("failed_checks", [])
    if failed_checks:
        _info("Failed checks:")
        for check in failed_checks:
            actual = check.get("actual")
            threshold = check.get("threshold")
            actual_str = f"{actual:.4f}" if isinstance(actual, float) else str(actual)
            threshold_str = (
                f"{threshold:.4f}" if isinstance(threshold, float) else str(threshold)
            )
            _info(f"  ✗ {check.get('label')}: actual={actual_str} threshold={threshold_str}")

    passed_checks = report.get("passed_checks", [])
    if passed_checks:
        _info("Passed checks:")
        for check in passed_checks:
            actual = check.get("actual")
            actual_str = f"{actual:.4f}" if isinstance(actual, float) else str(actual)
            _info(f"  ✓ {check.get('label')}: actual={actual_str}")

    if report.get("override_reason"):
        _info(f"Override reason: {report['override_reason']}")


def main() -> None:
    api_base = _env("RUDIX_API_BASE_URL", required=True).rstrip("/")
    token = _env("RUDIX_API_TOKEN", required=True)
    gate_id = _env("QUALITY_GATE_ID", required=True)
    evaluation_run_id = _env("EVALUATION_RUN_ID")
    safety_eval_run_id = _env("SAFETY_EVAL_RUN_ID")
    report_path = Path(_env("QUALITY_GATE_REPORT_PATH", default="artifacts/quality-gate-report.json"))
    dry_run = _env_bool("QUALITY_GATE_DRY_RUN")

    if not evaluation_run_id and not safety_eval_run_id:
        _die("Set at least one of EVALUATION_RUN_ID or SAFETY_EVAL_RUN_ID.")

    if evaluation_run_id.lower() == LATEST_RUN_ALIAS:
        evaluation_run_id = resolve_latest_evaluation_run(
            api_base,
            token=token,
            evaluation_set_id=_env("ACCURACY_EVAL_SET_ID", required=True),
            max_age_hours=_max_run_age_hours(),
        )

    _info(f"Gate:          {gate_id}")
    _info(f"Eval run:      {evaluation_run_id or '(not set)'}")
    _info(f"Safety run:    {safety_eval_run_id or '(not set)'}")
    _info(f"Dry run:       {dry_run}")

    trigger_url = f"{api_base}/quality-gates/{gate_id}/runs"
    trigger_body: dict = {}
    if evaluation_run_id:
        trigger_body["evaluation_run_id"] = evaluation_run_id
    if safety_eval_run_id:
        trigger_body["safety_eval_run_id"] = safety_eval_run_id

    _info("Triggering quality gate run...")
    gate_run = _api_request(trigger_url, token=token, method="POST", body=trigger_body)
    gate_run_id = gate_run.get("gate_run_id", "")
    if not gate_run_id:
        _die(f"API response missing gate_run_id: {gate_run}")

    _info(f"Gate run ID:   {gate_run_id}")
    _info(f"Initial verdict: {gate_run.get('verdict', 'unknown').upper()}")

    report_url = f"{api_base}/quality-gates/runs/{gate_run_id}/report"
    report = _api_request(report_url, token=token)

    _write_report(report, report_path)
    _print_gate_summary(report)

    verdict = report.get("verdict", "failed")
    ci_exit_code = report.get("ci_exit_code", 1)

    if dry_run:
        _info(f"Dry run mode — ignoring verdict ({verdict.upper()}), exiting 0.")
        sys.exit(0)

    if ci_exit_code != 0:
        _info(f"Quality gate FAILED — blocking deploy. See report: {report_path}")
        sys.exit(1)

    _info(f"Quality gate PASSED ({verdict.upper()}).")
    sys.exit(0)


if __name__ == "__main__":
    main()
