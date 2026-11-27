"""EVALUATION_RUN_ID=latest in ci/scripts/quality_gate_runner.py (R03-03).

The runner talks to a deployed Rudix API through urllib; these tests replace
``urllib.request.urlopen`` and never open a socket.
"""

from __future__ import annotations

import importlib.util
import io
import json
import urllib.parse
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

RUNNER_PATH = Path(__file__).resolve().parents[2] / "ci" / "scripts" / "quality_gate_runner.py"
API = "https://staging.example.test/api/v1"
SET_ID = "11111111-1111-1111-1111-111111111111"
GATE_ID = "22222222-2222-2222-2222-222222222222"
NOW = datetime(2026, 11, 26, 12, 0, tzinfo=UTC)


@pytest.fixture
def runner() -> Iterator[ModuleType]:
    spec = importlib.util.spec_from_file_location("quality_gate_runner_under_test", RUNNER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    yield module


class _Response(io.BytesIO):
    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def _run(run_id: str, completed_at: datetime | None, *, status: str = "completed") -> dict:
    return {
        "evaluation_run_id": run_id,
        "evaluation_set_id": SET_ID,
        "status": status,
        "completed_at": completed_at.isoformat() if completed_at else None,
    }


def _install_api(
    monkeypatch: pytest.MonkeyPatch,
    runner: ModuleType,
    routes: dict[str, Callable[[Any], dict]],
) -> list[Any]:
    requests: list[Any] = []

    def _urlopen(request: Any, timeout: float = 0) -> _Response:
        requests.append(request)
        path = urllib.parse.urlsplit(request.full_url).path
        for suffix, handler in routes.items():
            if path.endswith(suffix):
                return _Response(json.dumps(handler(request)).encode())
        raise AssertionError(f"unexpected request: {request.full_url}")

    monkeypatch.setattr(runner.urllib.request, "urlopen", _urlopen)
    return requests


def test_latest_picks_newest_completed_run(
    monkeypatch: pytest.MonkeyPatch, runner: ModuleType
) -> None:
    listing = {
        "items": [
            _run("old", NOW - timedelta(hours=30)),
            _run("newest", NOW - timedelta(hours=2)),
            _run("running", None, status="running"),
            _run("middle", NOW - timedelta(hours=10)),
        ]
    }
    requests = _install_api(monkeypatch, runner, {"/evaluations/runs": lambda _: listing})

    run_id = runner.resolve_latest_evaluation_run(
        API, token="t", evaluation_set_id=SET_ID, max_age_hours=36, now=NOW
    )

    assert run_id == "newest"
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(requests[0].full_url).query)
    assert query["evaluation_set_id"] == [SET_ID]
    assert query["status"] == ["completed"]
    assert requests[0].get_header("Authorization") == "Bearer t"


def test_latest_fails_when_no_completed_run(
    monkeypatch: pytest.MonkeyPatch, runner: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    listing = {"items": [_run("queued", None, status="queued")]}
    _install_api(monkeypatch, runner, {"/evaluations/runs": lambda _: listing})

    with pytest.raises(SystemExit) as excinfo:
        runner.resolve_latest_evaluation_run(
            API, token="t", evaluation_set_id=SET_ID, max_age_hours=36, now=NOW
        )

    assert excinfo.value.code == 1
    assert "No completed evaluation run" in capsys.readouterr().err


def test_latest_fails_when_newest_run_is_too_old(
    monkeypatch: pytest.MonkeyPatch, runner: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    listing = {"items": [_run("stale", NOW - timedelta(hours=40))]}
    _install_api(monkeypatch, runner, {"/evaluations/runs": lambda _: listing})

    with pytest.raises(SystemExit) as excinfo:
        runner.resolve_latest_evaluation_run(
            API, token="t", evaluation_set_id=SET_ID, max_age_hours=36, now=NOW
        )

    assert excinfo.value.code == 1
    assert "older than the 36h limit" in capsys.readouterr().err


def test_latest_ignores_runs_of_other_sets(
    monkeypatch: pytest.MonkeyPatch, runner: ModuleType
) -> None:
    foreign = _run("foreign", NOW - timedelta(hours=1))
    foreign["evaluation_set_id"] = "33333333-3333-3333-3333-333333333333"
    listing = {"items": [foreign, _run("mine", NOW - timedelta(hours=5))]}
    _install_api(monkeypatch, runner, {"/evaluations/runs": lambda _: listing})

    run_id = runner.resolve_latest_evaluation_run(
        API, token="t", evaluation_set_id=SET_ID, max_age_hours=36, now=NOW
    )

    assert run_id == "mine"


def _set_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, **extra: str) -> Path:
    report_path = tmp_path / "report.json"
    values = {
        "RUDIX_API_BASE_URL": API,
        "RUDIX_API_TOKEN": "t",
        "QUALITY_GATE_ID": GATE_ID,
        "EVALUATION_RUN_ID": "latest",
        "ACCURACY_EVAL_SET_ID": SET_ID,
        "QUALITY_GATE_REPORT_PATH": str(report_path),
        **extra,
    }
    for name in ("SAFETY_EVAL_RUN_ID", "QUALITY_GATE_DRY_RUN", "QUALITY_GATE_MAX_RUN_AGE_HOURS"):
        monkeypatch.delenv(name, raising=False)
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    return report_path


def test_main_triggers_gate_with_resolved_run(
    monkeypatch: pytest.MonkeyPatch, runner: ModuleType, tmp_path: Path
) -> None:
    recent = datetime.now(UTC) - timedelta(hours=1)
    report_path = _set_env(monkeypatch, tmp_path)
    triggered: list[dict] = []

    def _trigger(request: Any) -> dict:
        triggered.append(json.loads(request.data))
        return {"gate_run_id": "gr-1", "verdict": "passed"}

    report = {"verdict": "passed", "ci_exit_code": 0, "quality_gate_name": "Release"}
    _install_api(
        monkeypatch,
        runner,
        {
            "/evaluations/runs": lambda _: {"items": [_run("resolved", recent)]},
            f"/quality-gates/{GATE_ID}/runs": _trigger,
            "/quality-gates/runs/gr-1/report": lambda _: report,
        },
    )

    with pytest.raises(SystemExit) as excinfo:
        runner.main()

    assert excinfo.value.code == 0
    assert triggered == [{"evaluation_run_id": "resolved"}]
    assert json.loads(report_path.read_text())["verdict"] == "passed"


def test_main_latest_requires_eval_set_id(
    monkeypatch: pytest.MonkeyPatch, runner: ModuleType, tmp_path: Path
) -> None:
    _set_env(monkeypatch, tmp_path)
    monkeypatch.delenv("ACCURACY_EVAL_SET_ID")
    _install_api(monkeypatch, runner, {})

    with pytest.raises(SystemExit) as excinfo:
        runner.main()

    assert excinfo.value.code == 1


@pytest.mark.parametrize("raw", ["abc", "0", "-5"])
def test_main_rejects_invalid_max_age(
    monkeypatch: pytest.MonkeyPatch, runner: ModuleType, tmp_path: Path, raw: str
) -> None:
    _set_env(monkeypatch, tmp_path, QUALITY_GATE_MAX_RUN_AGE_HOURS=raw)
    _install_api(monkeypatch, runner, {})

    with pytest.raises(SystemExit) as excinfo:
        runner.main()

    assert excinfo.value.code == 1


def test_max_age_env_overrides_default(
    monkeypatch: pytest.MonkeyPatch, runner: ModuleType, tmp_path: Path
) -> None:
    _set_env(monkeypatch, tmp_path, QUALITY_GATE_MAX_RUN_AGE_HOURS="48")
    assert runner._max_run_age_hours() == 48.0
    monkeypatch.delenv("QUALITY_GATE_MAX_RUN_AGE_HOURS")
    assert runner._max_run_age_hours() == runner.DEFAULT_MAX_RUN_AGE_HOURS


def test_api_requests_send_a_non_default_user_agent(
    runner: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Cloudflare answers the default Python-urllib User-Agent with error 1010.
    seen: dict[str, Any] = {}

    def _urlopen(request: Any, timeout: float = 0) -> _Response:
        seen["user_agent"] = request.get_header("User-agent")
        return _Response(b"{}")

    monkeypatch.setattr(runner.urllib.request, "urlopen", _urlopen)
    runner._api_request(f"{API}/evaluations/runs", token="token")
    assert seen["user_agent"] == runner.USER_AGENT
    assert not seen["user_agent"].startswith("Python-urllib")
