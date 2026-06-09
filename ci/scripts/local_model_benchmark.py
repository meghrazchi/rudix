#!/usr/bin/env python3
"""Local model benchmark runner (F226).

Triggers benchmark suite runs for cloud_baseline, local_profile, and
fallback_profile against the Rudix evaluation API, waits for all three to
complete, then fetches the model-profile comparison report and writes it to
a JSON artifact.

Exit codes:
  0  — all requested profile runs completed; report written
  1  — one or more runs failed, or the release-gate recommendation says not ready
  2  — configuration or API error

Required environment variables:
  RUDIX_API_BASE_URL   Base URL of the Rudix API (e.g. https://api.example.com/api/v1)
  RUDIX_API_TOKEN      Bearer token for authentication

Optional environment variables:
  BENCHMARK_SUITE_IDS          Comma-separated suite IDs to run (default: all suites)
  BENCHMARK_TOP_K              Retrieval top-k for benchmark runs (default: 5)
  BENCHMARK_PROVIDER_PROFILES  Comma-separated profiles to run
                               (default: cloud_baseline,local_profile)
  BENCHMARK_EVALUATION_SET_ID  Re-use an existing evaluation set instead of creating one
  BENCHMARK_REPORT_PATH        Output path for JSON report
                               (default: artifacts/local-model-benchmark.json)
  BENCHMARK_POLL_INTERVAL_SEC  Seconds between status polls (default: 10)
  BENCHMARK_TIMEOUT_SEC        Maximum seconds to wait for all runs (default: 600)
  BENCHMARK_REQUIRE_READY      Set to '1' to exit 1 when any gate fails (default: 1)
  BENCHMARK_DRY_RUN            Set to '1' to print plan without triggering runs
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


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
        _die(f"Environment variable {name!r} must be an integer, got: {raw!r}")
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes")


def _die(message: str) -> None:
    print(f"[benchmark] ERROR: {message}", file=sys.stderr)
    sys.exit(2)


def _api_request(
    base_url: str,
    token: str,
    path: str,
    method: str = "GET",
    body: dict | None = None,
) -> dict:
    url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode(errors="replace")
        _die(f"HTTP {exc.code} from {url}: {body_text[:400]}")
        raise


def _list_suites(base_url: str, token: str) -> list[dict]:
    resp = _api_request(base_url, token, "/evaluations/benchmark-suites")
    return resp.get("items", [])


def _trigger_run(
    base_url: str,
    token: str,
    suite_id: str,
    provider_profile: str,
    evaluation_set_id: str | None,
    top_k: int,
) -> dict:
    body: dict = {
        "suite_id": suite_id,
        "provider_profile": provider_profile,
        "top_k": top_k,
        "rerank": True,
    }
    if evaluation_set_id:
        body["evaluation_set_id"] = evaluation_set_id
    return _api_request(
        base_url, token, f"/evaluations/benchmark-suites/{suite_id}/run", "POST", body
    )


def _poll_run_status(base_url: str, token: str, run_id: str) -> str:
    resp = _api_request(base_url, token, f"/evaluations/runs/{run_id}")
    return resp.get("status", "queued")


def _get_comparison_report(
    base_url: str,
    token: str,
    evaluation_set_id: str | None,
) -> dict:
    path = "/evaluations/model-profile-report"
    if evaluation_set_id:
        path += f"?evaluation_set_id={evaluation_set_id}"
    return _api_request(base_url, token, path)


def main() -> None:
    base_url = _env("RUDIX_API_BASE_URL", required=True)
    token = _env("RUDIX_API_TOKEN", required=True)
    dry_run = _env_bool("BENCHMARK_DRY_RUN")
    require_ready = _env_bool("BENCHMARK_REQUIRE_READY", default=True)
    top_k = _env_int("BENCHMARK_TOP_K", default=5)
    poll_interval = _env_int("BENCHMARK_POLL_INTERVAL_SEC", default=10)
    timeout_sec = _env_int("BENCHMARK_TIMEOUT_SEC", default=600)
    report_path = Path(_env("BENCHMARK_REPORT_PATH", default="artifacts/local-model-benchmark.json"))

    evaluation_set_id = _env("BENCHMARK_EVALUATION_SET_ID") or None

    # Resolve suite IDs
    raw_suites = _env("BENCHMARK_SUITE_IDS")
    if raw_suites:
        requested_suite_ids = [s.strip() for s in raw_suites.split(",") if s.strip()]
    else:
        all_suites = _list_suites(base_url, token)
        requested_suite_ids = [s["suite_id"] for s in all_suites]

    # Resolve provider profiles
    raw_profiles = _env("BENCHMARK_PROVIDER_PROFILES", default="cloud_baseline,local_profile")
    requested_profiles = [p.strip() for p in raw_profiles.split(",") if p.strip()]

    print(f"[benchmark] Suites   : {', '.join(requested_suite_ids)}")
    print(f"[benchmark] Profiles : {', '.join(requested_profiles)}")
    print(f"[benchmark] Top-k    : {top_k}")
    if dry_run:
        print("[benchmark] DRY RUN — exiting without triggering runs.")
        sys.exit(0)

    # Trigger all runs
    pending_runs: list[dict] = []
    for suite_id in requested_suite_ids:
        for profile in requested_profiles:
            print(f"[benchmark] Triggering suite={suite_id} profile={profile} ...", end=" ")
            result = _trigger_run(base_url, token, suite_id, profile, evaluation_set_id, top_k)
            run_id = result["evaluation_run_id"]
            print(f"run_id={run_id}")
            pending_runs.append({"run_id": run_id, "suite_id": suite_id, "profile": profile})

    # Poll until all runs complete or timeout
    deadline = time.monotonic() + timeout_sec
    failed_runs: list[dict] = []
    while pending_runs:
        if time.monotonic() > deadline:
            ids = [r["run_id"] for r in pending_runs]
            _die(f"Timeout after {timeout_sec}s. Still pending: {ids}")
        time.sleep(poll_interval)
        still_pending: list[dict] = []
        for entry in pending_runs:
            run_status = _poll_run_status(base_url, token, entry["run_id"])
            if run_status == "completed":
                print(f"[benchmark]   completed: suite={entry['suite_id']} profile={entry['profile']} run={entry['run_id']}")
            elif run_status == "failed":
                print(f"[benchmark]   FAILED:    suite={entry['suite_id']} profile={entry['profile']} run={entry['run_id']}")
                failed_runs.append(entry)
            else:
                still_pending.append(entry)
        pending_runs = still_pending

    # Fetch comparison report
    print("[benchmark] Fetching model-profile comparison report ...")
    report = _get_comparison_report(base_url, token, evaluation_set_id)

    # Write artifact
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, default=str))
    print(f"[benchmark] Report written to: {report_path}")

    # Print summary
    for rec in report.get("release_gate_recommendations", []):
        ready = rec.get("is_ready", False)
        profile = rec.get("provider_profile", "?")
        icon = "✓" if ready else "✗"
        print(f"[benchmark] {icon} {profile}: {rec.get('recommendation', '')}")

    # Determine exit code
    any_failed = bool(failed_runs)
    any_not_ready = any(
        not rec.get("is_ready", False)
        for rec in report.get("release_gate_recommendations", [])
    )

    if any_failed:
        print(f"[benchmark] {len(failed_runs)} run(s) failed.", file=sys.stderr)
        sys.exit(1)

    if require_ready and any_not_ready:
        print("[benchmark] One or more profiles did not pass the release gate.", file=sys.stderr)
        sys.exit(1)

    print("[benchmark] All checks passed.")
    sys.exit(0)


if __name__ == "__main__":
    main()
