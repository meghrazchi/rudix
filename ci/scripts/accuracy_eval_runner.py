#!/usr/bin/env python3
"""Accuracy evaluation CI runner — F302.

Triggers an evaluation run against a published evaluation set, waits for
completion, gates the result against a quality gate, and writes a combined
JSON report and JUnit XML artifact.

Two modes are supported:
  smoke   — fast subset for merge-request pipelines (respects QUESTION_LIMIT)
  nightly — full evaluation set for scheduled/release pipelines

Required environment variables:
  RUDIX_API_BASE_URL        Base URL of the Rudix API, e.g. https://staging.example.com/api/v1
  RUDIX_API_TOKEN           Bearer token for authentication
  ACCURACY_EVAL_SET_ID      UUID of the published evaluation set to run
  QUALITY_GATE_ID           UUID of the quality gate configuration

Optional:
  EVAL_MODE                 'smoke' (default) or 'nightly'
  QUESTION_LIMIT            Max questions for smoke mode (default: 20)
  ACCURACY_EVAL_REPORT_PATH Path for combined JSON report (default: artifacts/accuracy-eval-report.json)
  ACCURACY_EVAL_JUNIT_PATH  Path for JUnit XML report (default: artifacts/accuracy-eval-junit.xml)
  QUALITY_GATE_DRY_RUN      Set to '1' to evaluate without blocking (always exits 0)
  EVAL_POLL_INTERVAL_SEC    Seconds between status polls (default: 10)
  EVAL_TIMEOUT_SEC          Max seconds to wait for eval completion (default: 900)
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _env(name: str, required: bool = False, default: str = "") -> str:
    value = os.getenv(name, default).strip()
    if required and not value:
        _die(f"Required environment variable {name!r} is not set.")
    return value


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        _die(f"Environment variable {name!r} must be an integer, got {raw!r}")
        raise  # unreachable but satisfies type checker


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, "")
    return raw.strip().lower() in {"1", "true", "yes", "on"} if raw.strip() else default


def _die(message: str) -> None:
    print(f"[accuracy-eval] ERROR: {message}", file=sys.stderr)
    sys.exit(1)


def _info(message: str) -> None:
    print(f"[accuracy-eval] {message}")


def _api_request(
    url: str,
    *,
    token: str,
    method: str = "GET",
    body: dict | None = None,
    timeout: int = 60,
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
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode(errors="replace")
        _die(f"API request failed ({exc.code}): {url}\n{body_text}")
    except urllib.error.URLError as exc:
        _die(f"API connection error: {url}\n{exc.reason}")


# ---------------------------------------------------------------------------
# Artifact writers
# ---------------------------------------------------------------------------


def _write_json(report: dict, report_path: Path) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, default=str))
    _info(f"JSON report written to {report_path}")


def _write_junit_xml(report: dict, xml_path: Path) -> None:
    """Generate a JUnit-compatible XML from the gate report for CI consumers."""
    xml_path.parent.mkdir(parents=True, exist_ok=True)

    gate_name = report.get("quality_gate_name", "Accuracy Gate")
    verdict = report.get("verdict", "unknown")
    total = report.get("total_checks", 0)
    failures = report.get("fail_count", 0)
    eval_mode = report.get("eval_mode", "unknown")

    suite = ET.Element(
        "testsuite",
        {
            "name": f"Accuracy Eval Gate — {eval_mode} ({gate_name})",
            "tests": str(total),
            "failures": str(failures),
            "errors": "0",
            "time": "0",
        },
    )

    for check in report.get("passed_checks", []):
        tc = ET.SubElement(
            suite,
            "testcase",
            {
                "classname": "accuracy_gate",
                "name": check.get("label", check.get("metric", "check")),
                "time": "0",
            },
        )
        actual = check.get("actual")
        threshold = check.get("threshold")
        ET.SubElement(tc, "system-out").text = (
            f"PASS  actual={actual}  threshold={threshold}"
        )

    for check in report.get("failed_checks", []):
        tc = ET.SubElement(
            suite,
            "testcase",
            {
                "classname": "accuracy_gate",
                "name": check.get("label", check.get("metric", "check")),
                "time": "0",
            },
        )
        detail = check.get("detail") or f"actual={check.get('actual')} threshold={check.get('threshold')}"
        ET.SubElement(tc, "failure", {"message": detail, "type": "AccuracyRegression"}).text = (
            detail
        )

    # Baseline comparison as informational system-out on a summary case
    baseline = report.get("baseline_comparison")
    if baseline:
        tc_summary = ET.SubElement(
            suite,
            "testcase",
            {
                "classname": "accuracy_gate",
                "name": "Baseline Comparison Summary",
                "time": "0",
            },
        )
        lines = []
        for d in baseline:
            status = "REGRESSED" if d.get("regressed") else "ok"
            lines.append(
                f"  [{status}] {d.get('label')}: "
                f"baseline={d.get('baseline')}  current={d.get('current')}  "
                f"delta={d.get('delta')}"
            )
        ET.SubElement(tc_summary, "system-out").text = "\n".join(lines)

    if verdict == "overridden":
        reason = report.get("override_reason") or ""
        tc_override = ET.SubElement(
            suite,
            "testcase",
            {
                "classname": "accuracy_gate",
                "name": "Override",
                "time": "0",
            },
        )
        ET.SubElement(tc_override, "system-out").text = f"Gate overridden: {reason}"

    tree = ET.ElementTree(suite)
    ET.indent(tree, space="  ")
    xml_path.write_bytes(ET.tostring(suite, encoding="unicode").encode())
    _info(f"JUnit XML written to {xml_path}")


# ---------------------------------------------------------------------------
# Summary printer
# ---------------------------------------------------------------------------


def _print_summary(report: dict) -> None:
    _info(f"Gate:         {report.get('quality_gate_name', 'unknown')}")
    _info(f"Eval mode:    {report.get('eval_mode', 'unknown')}")
    _info(f"Eval run:     {report.get('evaluation_run_id', '(none)')}")
    _info(f"Verdict:      {report.get('verdict', 'unknown').upper()}")
    _info(
        f"Checks:       {report.get('pass_count', 0)} passed, "
        f"{report.get('fail_count', 0)} failed "
        f"({report.get('total_checks', 0)} total)"
    )

    for check in report.get("failed_checks", []):
        actual = check.get("actual")
        threshold = check.get("threshold")
        actual_str = f"{actual:.4f}" if isinstance(actual, float) else str(actual)
        threshold_str = f"{threshold:.4f}" if isinstance(threshold, float) else str(threshold)
        _info(f"  ✗ {check.get('label')}: actual={actual_str} threshold={threshold_str}")

    for check in report.get("passed_checks", []):
        actual = check.get("actual")
        actual_str = f"{actual:.4f}" if isinstance(actual, float) else str(actual)
        _info(f"  ✓ {check.get('label')}: actual={actual_str}")

    baseline = report.get("baseline_comparison")
    if baseline:
        _info("Baseline comparison:")
        for d in baseline:
            status = "↓ REGRESSED" if d.get("regressed") else "→"
            _info(
                f"  {status} {d.get('label')}: "
                f"baseline={d.get('baseline')}  current={d.get('current')}  "
                f"delta={d.get('delta')}"
            )

    if report.get("override_reason"):
        _info(f"Override: {report['override_reason']}")


# ---------------------------------------------------------------------------
# Evaluation run lifecycle
# ---------------------------------------------------------------------------


def _trigger_eval_run(
    api_base: str,
    token: str,
    eval_set_id: str,
    eval_mode: str,
    question_limit: int | None,
) -> str:
    """Trigger a new evaluation run and return the run ID."""
    body: dict = {"eval_mode": eval_mode}
    if question_limit and eval_mode == "smoke":
        body["question_limit"] = question_limit

    url = f"{api_base}/evaluation-sets/{eval_set_id}/runs"
    _info(f"Triggering {eval_mode} evaluation run on set {eval_set_id}...")
    resp = _api_request(url, token=token, method="POST", body=body)
    run_id = resp.get("evaluation_run_id") or resp.get("run_id") or resp.get("id")
    if not run_id:
        _die(f"API response missing evaluation run ID: {resp}")
    _info(f"Evaluation run started: {run_id}")
    return str(run_id)


def _wait_for_eval_run(
    api_base: str,
    token: str,
    run_id: str,
    poll_interval: int,
    timeout_sec: int,
) -> dict:
    """Poll until the evaluation run is completed or failed. Returns run dict."""
    url = f"{api_base}/evaluation-sets/runs/{run_id}"
    deadline = time.monotonic() + timeout_sec
    while True:
        run = _api_request(url, token=token)
        status = run.get("status", "unknown")
        _info(f"Eval run status: {status}")
        if status == "completed":
            return run
        if status == "failed":
            _die(f"Evaluation run {run_id} failed: {run.get('error', 'no details')}")
        if time.monotonic() >= deadline:
            _die(
                f"Timed out after {timeout_sec}s waiting for evaluation run {run_id}. "
                f"Last status: {status}"
            )
        time.sleep(poll_interval)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    api_base = _env("RUDIX_API_BASE_URL", required=True).rstrip("/")
    token = _env("RUDIX_API_TOKEN", required=True)
    eval_set_id = _env("ACCURACY_EVAL_SET_ID", required=True)
    gate_id = _env("QUALITY_GATE_ID", required=True)
    eval_mode = _env("EVAL_MODE", default="smoke").lower()
    if eval_mode not in {"smoke", "nightly"}:
        _die(f"EVAL_MODE must be 'smoke' or 'nightly', got {eval_mode!r}")

    question_limit_raw = _env_int("QUESTION_LIMIT", default=20)
    question_limit = question_limit_raw if eval_mode == "smoke" else None

    report_path = Path(
        _env("ACCURACY_EVAL_REPORT_PATH", default="artifacts/accuracy-eval-report.json")
    )
    junit_path = Path(
        _env("ACCURACY_EVAL_JUNIT_PATH", default="artifacts/accuracy-eval-junit.xml")
    )
    dry_run = _env_bool("QUALITY_GATE_DRY_RUN")
    poll_interval = _env_int("EVAL_POLL_INTERVAL_SEC", default=10)
    timeout_sec = _env_int("EVAL_TIMEOUT_SEC", default=900)

    _info(f"Eval mode:     {eval_mode}")
    _info(f"Eval set:      {eval_set_id}")
    _info(f"Gate:          {gate_id}")
    if question_limit:
        _info(f"Question limit: {question_limit}")
    _info(f"Dry run:       {dry_run}")

    # Step 1 — trigger evaluation run
    run_id = _trigger_eval_run(api_base, token, eval_set_id, eval_mode, question_limit)

    # Step 2 — wait for completion
    eval_run = _wait_for_eval_run(api_base, token, run_id, poll_interval, timeout_sec)
    _info(f"Evaluation run completed. Questions evaluated: {eval_run.get('question_count', '?')}")

    # Step 3 — trigger quality gate against the completed run
    gate_run_url = f"{api_base}/quality-gates/{gate_id}/runs"
    _info("Triggering quality gate check...")
    gate_run = _api_request(
        gate_run_url,
        token=token,
        method="POST",
        body={"evaluation_run_id": run_id},
    )
    gate_run_id = gate_run.get("gate_run_id") or gate_run.get("id")
    if not gate_run_id:
        _die(f"API response missing gate_run_id: {gate_run}")
    _info(f"Gate run ID:   {gate_run_id}")

    # Step 4 — fetch the full report
    report_url = f"{api_base}/quality-gates/runs/{gate_run_id}/report"
    report = _api_request(report_url, token=token)
    report["eval_mode"] = eval_mode

    # Step 5 — write artifacts
    _write_json(report, report_path)
    _write_junit_xml(report, junit_path)
    _print_summary(report)

    verdict = report.get("verdict", "failed")
    ci_exit_code = report.get("ci_exit_code", 1)

    if dry_run:
        _info(f"Dry run mode — ignoring verdict ({verdict.upper()}), exiting 0.")
        sys.exit(0)

    if ci_exit_code != 0:
        _info(f"Accuracy gate FAILED — blocking deploy. Reports: {report_path}, {junit_path}")
        sys.exit(1)

    _info(f"Accuracy gate PASSED ({verdict.upper()}).")
    sys.exit(0)


if __name__ == "__main__":
    main()
