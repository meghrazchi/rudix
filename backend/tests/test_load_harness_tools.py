"""Unit tests for the stdlib tools of the Locust load harness in ci/load (R03-09).

The harness lives outside backend/, so modules are loaded by path (precedent:
test_security_severity_gate.py). Tests touching Locust user classes are skipped unless
the optional ``load`` extra is installed.
"""

from __future__ import annotations

import csv
import importlib.util
import json
import math
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
LOAD_DIR = REPO_ROOT / "ci" / "load"
BASELINE_DOC = REPO_ROOT / "docs" / "roadmap" / "V0_3_0_LOAD_BASELINE.md"


def _load(name: str, relative: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, LOAD_DIR / relative)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


collect_metrics = _load("rudix_load_collect_metrics", "collect_metrics.py")
report = _load("rudix_load_report", "report.py")
load_config = _load("rudix_load_config", "common/config.py")

DOCS_ROUTE = 'method="GET",route="/api/v1/documents"'


def _metrics_text(
    buckets: dict[str, float], count: float, total: float, checked_out: float = 0.0
) -> str:
    lines = [
        "# HELP rudix_db_queries_per_request SQL statements per request",
        "# TYPE rudix_db_queries_per_request histogram",
    ]
    for le, value in buckets.items():
        lines.append(f'rudix_db_queries_per_request_bucket{{le="{le}",{DOCS_ROUTE}}} {value}')
    lines += [
        f"rudix_db_queries_per_request_count{{{DOCS_ROUTE}}} {count}",
        f"rudix_db_queries_per_request_sum{{{DOCS_ROUTE}}} {total}",
        "# TYPE rudix_db_pool_checked_out gauge",
        f"rudix_db_pool_checked_out {checked_out}",
        "rudix_db_pool_size 5.0",
        "rudix_db_pool_overflow -5.0",
        'rudix_http_requests_total{method="GET",route="/x",status_code="200"} 3.0 1700000000',
        "not a valid sample line",
        "bad_value NaNish",
    ]
    return "\n".join(lines) + "\n"


BEFORE = _metrics_text({"1.0": 0, "2.0": 0, "5.0": 1, "10.0": 1, "+Inf": 1}, 1, 4, 1)
AFTER = _metrics_text({"1.0": 0, "2.0": 10, "5.0": 91, "10.0": 101, "+Inf": 101}, 101, 404, 3)


# --- collect_metrics.py -------------------------------------------------------------------


def test_parse_prometheus_text_reads_labels_and_skips_noise() -> None:
    samples = collect_metrics.parse_prometheus_text(AFTER + 'esc{path="a\\"b"} 1\n# comment only\n')
    key = (
        "rudix_db_queries_per_request_count",
        (("method", "GET"), ("route", "/api/v1/documents")),
    )
    assert samples[key] == 101.0
    assert samples[("rudix_db_pool_size", ())] == 5.0
    assert samples[("esc", (("path", 'a"b'),))] == 1.0
    timestamped = (
        "rudix_http_requests_total",
        (("method", "GET"), ("route", "/x"), ("status_code", "200")),
    )
    assert samples[timestamped] == 3.0
    assert not any(name == "bad_value" for name, _ in samples)


def test_histogram_quantile_interpolates_like_prometheus() -> None:
    buckets = [(1.0, 0.0), (2.0, 10.0), (5.0, 90.0), (10.0, 100.0), (math.inf, 100.0)]
    assert collect_metrics.histogram_quantile(0.5, buckets) == pytest.approx(2 + 3 * 40 / 80)
    assert collect_metrics.histogram_quantile(0.95, buckets) == pytest.approx(7.5)
    assert collect_metrics.histogram_quantile(0.5, []) is None
    assert collect_metrics.histogram_quantile(0.5, [(1.0, 0.0), (math.inf, 0.0)]) is None
    # Everything above the last finite bucket reports that bound.
    assert collect_metrics.histogram_quantile(0.5, [(5.0, 0.0), (math.inf, 4.0)]) == 5.0
    # Rank landing on a bucket with no new samples returns its upper bound.
    assert collect_metrics.histogram_quantile(0.0, [(1.0, 0.0), (2.0, 0.0), (math.inf, 2.0)]) == 1.0


def test_build_summary_diffs_histograms_and_tracks_pool_max() -> None:
    before = collect_metrics.parse_prometheus_text(BEFORE)
    after = collect_metrics.parse_prometheus_text(AFTER)

    summary = collect_metrics.build_summary(before, after, [7.0, 2.0])

    docs = summary["queries_per_request"]["GET /api/v1/documents"]
    assert docs["count"] == 100
    assert docs["mean"] == 4.0
    assert docs["p50"] == pytest.approx(2 + 3 * 40 / 80, abs=1e-3)
    assert docs["p95"] == pytest.approx(7.5)
    assert summary["pool"] == {
        "max_checked_out": 7.0,
        "size": 5.0,
        "overflow_after": -5.0,
        "samples": 4,
    }


def test_summary_skips_routes_without_new_requests() -> None:
    samples = collect_metrics.parse_prometheus_text(BEFORE)
    summary = collect_metrics.build_summary(samples, samples)
    assert summary["queries_per_request"] == {}
    assert summary["pool"]["max_checked_out"] == 1.0


def test_summary_without_pool_gauges() -> None:
    summary = collect_metrics.build_summary({}, {})
    assert summary["pool"]["max_checked_out"] is None
    assert summary["pool"]["samples"] == 0


def test_sample_pool_polls_until_deadline_and_skips_failures() -> None:
    now = [0.0]
    responses: list[Any] = [AFTER, OSError("down"), "no gauges here\n", BEFORE]

    def fetch() -> str:
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return str(item)

    def sleep(seconds: float) -> None:
        now[0] += seconds

    values = collect_metrics.sample_pool(
        fetch, duration=4.0, interval=1.0, sleep=sleep, clock=lambda: now[0]
    )
    assert values == [3.0, 1.0]
    assert responses == []


def test_diff_command_writes_summary(tmp_path: Path) -> None:
    before, after, out = tmp_path / "b.prom", tmp_path / "a.prom", tmp_path / "m.json"
    before.write_text(BEFORE, encoding="utf-8")
    after.write_text(AFTER, encoding="utf-8")

    code = collect_metrics.main(
        [
            "diff",
            "--before",
            str(before),
            "--after",
            str(after),
            "--pool-max",
            "9",
            "--out",
            str(out),
        ]
    )

    assert code == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["pool"]["max_checked_out"] == 9.0
    assert payload["queries_per_request"]["GET /api/v1/documents"]["count"] == 100


def test_diff_command_prints_to_stdout(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    snap = tmp_path / "s.prom"
    snap.write_text(BEFORE, encoding="utf-8")
    assert collect_metrics.main(["diff", "--before", str(snap), "--after", str(snap)]) == 0
    assert json.loads(capsys.readouterr().out)["queries_per_request"] == {}


class _FakeResponse:
    def __init__(self, body: str) -> None:
        self._body = body

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body.encode("utf-8")


def test_scrape_sends_bearer_token(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[Any] = []

    def fake_urlopen(request: Any, timeout: float) -> _FakeResponse:
        seen.append(request)
        return _FakeResponse(BEFORE)

    monkeypatch.setattr(collect_metrics.urllib.request, "urlopen", fake_urlopen)

    assert collect_metrics.scrape("http://api/metrics", "tok") == BEFORE
    assert seen[0].get_header("Authorization") == "Bearer tok"
    collect_metrics.scrape("http://api/metrics")
    assert seen[1].get_header("Authorization") is None


def test_snapshot_and_run_commands(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    bodies = [BEFORE, AFTER]
    monkeypatch.setenv("RUDIX_LOAD_METRICS_TOKEN", "secret")
    tokens: list[str | None] = []

    def fake_scrape(url: str, token: str | None = None, timeout: float = 10.0) -> str:
        tokens.append(token)
        return bodies.pop(0) if bodies else AFTER

    monkeypatch.setattr(collect_metrics, "scrape", fake_scrape)
    snap = tmp_path / "snap.prom"
    assert collect_metrics.main(["snapshot", "http://api/metrics", "--out", str(snap)]) == 0
    assert snap.read_text(encoding="utf-8") == BEFORE

    out = tmp_path / "run.json"
    assert (
        collect_metrics.main(["run", "http://api/metrics", "--duration", "0", "--out", str(out)])
        == 0
    )
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["pool"]["max_checked_out"] == 3.0
    assert set(tokens) == {"secret"}


# --- report.py ----------------------------------------------------------------------------

STATS_FIELDS = ["Type", "Name", "Request Count", "Failure Count", "50%", "95%"]
STATS_ROWS = [
    ["GET", "GET /api/v1/documents", "200", "2", "41", "120"],
    ["WS", "full_answer", "10", "0", "900", "1500"],
    ["POST", "POST /api/v1/auth/login", "5", "0", "80", "N/A"],
    ["GET", "GET /unknown", "0", "0", "", ""],
    ["", "Aggregated", "215", "2", "50", "1400"],
]


def _write_stats(path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(STATS_FIELDS)
        writer.writerows(STATS_ROWS)


METRICS = {
    "queries_per_request": {"GET /api/v1/documents": {"p50": 3.5, "p95": 7.25}},
    "pool": {"max_checked_out": 4.0},
}


def test_render_table_merges_stats_and_metrics(tmp_path: Path) -> None:
    stats_path = tmp_path / "s_stats.csv"
    _write_stats(stats_path)

    table = report.render_table(report.read_locust_stats(stats_path), METRICS)
    lines = table.splitlines()

    assert lines[0].startswith("| Request | Requests | p50 (ms) | p95 (ms) | Error rate")
    assert "| `GET /api/v1/documents` | 200 | 41 | 120 | 1.00% | 3.5 | 7.2 |  |" in lines
    assert (
        "| `WS full_answer` | 10 | 900 | 1500 | 0.00% | n/a (not HTTP) | n/a (not HTTP) |  |"
        in lines
    )
    assert "| `POST /api/v1/auth/login` | 5 | 80 | n/a | 0.00% | n/a | n/a |  |" in lines
    assert "| `GET /unknown` | 0 | n/a | n/a | n/a | n/a | n/a |  |" in lines
    # The aggregate row is last and carries the pool maximum.
    assert lines[-1] == "| **All requests** | 215 | 50 | 1400 | 0.93% |  |  | 4 |"


def test_render_table_without_rows_is_not_measured() -> None:
    table = report.render_table([], {})
    assert table.splitlines()[-1].count("not yet measured") == 8


def test_number_and_display_helpers() -> None:
    assert report._number("abc") is None
    assert report._number(None) is None
    assert report.display_name({"Type": "WS", "Name": "WS connect"}) == "WS connect"
    assert report.error_rate({"Request Count": "4"}) == 0.0


def test_replace_block_only_touches_marked_section() -> None:
    doc = "intro\n<!-- load-report:x:start -->\nold\n<!-- load-report:x:end -->\noutro\n"
    updated = report.replace_block(doc, "x", "NEW")
    assert (
        updated == "intro\n<!-- load-report:x:start -->\nNEW\n<!-- load-report:x:end -->\noutro\n"
    )
    with pytest.raises(ValueError):
        report.replace_block("no markers", "x", "NEW")
    with pytest.raises(ValueError):
        report.replace_block("<!-- load-report:x:start --> only", "x", "NEW")


def test_main_prints_and_updates(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    stats_path, metrics_path = tmp_path / "s_stats.csv", tmp_path / "m.json"
    _write_stats(stats_path)
    metrics_path.write_text(json.dumps(METRICS), encoding="utf-8")

    assert report.main(["--scenario", "documents_list", "--stats", str(stats_path)]) == 0
    assert "`GET /api/v1/documents`" in capsys.readouterr().out

    target = tmp_path / "baseline.md"
    target.write_text(
        "a\n<!-- load-report:documents_list:start -->\nx\n<!-- load-report:documents_list:end -->\n",
        encoding="utf-8",
    )
    args = ["--scenario", "documents_list", "--stats", str(stats_path)]
    assert report.main([*args, "--metrics", str(metrics_path), "--update", str(target)]) == 0
    assert "| 3.5 | 7.2 |" in target.read_text(encoding="utf-8")

    assert (
        report.main(["--scenario", "missing", "--stats", str(stats_path), "--update", str(target)])
        == 2
    )
    assert "marker" in capsys.readouterr().err


def test_baseline_document_has_a_block_per_scenario() -> None:
    text = BASELINE_DOC.read_text(encoding="utf-8")
    assert "Not yet measured" in text
    for scenario in load_config.SCENARIO_NAMES:
        assert report.start_marker(scenario) in text
        assert report.end_marker(scenario) in text


# --- common/config.py ---------------------------------------------------------------------


def test_load_config_reads_environment(tmp_path: Path) -> None:
    questions = tmp_path / "q.txt"
    questions.write_text("# comment\nFirst?\n\n  Second?  \n", encoding="utf-8")

    config = load_config.load_config(
        {
            "RUDIX_LOAD_BASE_URL": "https://api.example.test/",
            "RUDIX_LOAD_EMAIL": "load@example.test",
            "RUDIX_LOAD_PASSWORD": "pw",
            "RUDIX_LOAD_ORG_ID": "org-1",
            "RUDIX_LOAD_SCENARIO_WEIGHTS": "chat_ws=0, documents_list=7,",
            "RUDIX_LOAD_QUESTIONS_FILE": str(questions),
            "RUDIX_LOAD_INGEST_TIMEOUT_SECONDS": "60",
        }
    )

    assert config.base_url == "https://api.example.test"
    assert config.ws_base_url == "wss://api.example.test"
    assert config.org_id == "org-1"
    assert config.weights["chat_ws"] == 0
    assert config.weights["documents_list"] == 7
    assert config.weights["chat_http"] == load_config.DEFAULT_WEIGHTS["chat_http"]
    assert config.questions == ("First?", "Second?")
    assert config.ingest_timeout_seconds == 60.0


def test_load_config_defaults() -> None:
    config = load_config.load_config({})
    assert config.base_url == "http://localhost:8000"
    assert config.ws_base_url == "ws://localhost:8000"
    assert config.org_id is None
    assert config.weights == load_config.DEFAULT_WEIGHTS
    assert config.questions == load_config.DEFAULT_QUESTIONS


def test_ws_base_url_passthrough_and_empty_questions_file(tmp_path: Path) -> None:
    empty = tmp_path / "empty.txt"
    empty.write_text("# nothing\n", encoding="utf-8")
    config = load_config.load_config(
        {"RUDIX_LOAD_BASE_URL": "ws://already", "RUDIX_LOAD_QUESTIONS_FILE": str(empty)}
    )
    assert config.ws_base_url == "ws://already"
    assert config.questions == load_config.DEFAULT_QUESTIONS


@pytest.mark.parametrize("raw", ["unknown=1", "chat_ws", "chat_ws=-1", "chat_ws=x"])
def test_parse_weights_rejects_bad_entries(raw: str) -> None:
    with pytest.raises(ValueError):
        load_config.parse_weights(raw)


def test_parse_weights_blank_keeps_defaults() -> None:
    assert load_config.parse_weights("  ") == load_config.DEFAULT_WEIGHTS


# --- Locust user classes (only with the optional `load` extra) ----------------------------


def test_locustfile_imports_user_classes(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("locust")
    monkeypatch.syspath_prepend(str(LOAD_DIR))
    locustfile = _load("rudix_load_locustfile", "locustfile.py")
    assert set(locustfile.USER_CLASSES) == set(load_config.SCENARIO_NAMES)

    from scenarios.chat_ws import AnswerProgress, start_message
    from scenarios.documents_list import next_offset
    from scenarios.upload_ingest import build_document

    progress = AnswerProgress()
    assert progress.observe({"event": "heartbeat.ping"}) == ("heartbeat", False)
    assert progress.observe({"event": "retrieval.started"}) == ("event", True)
    assert progress.observe({"event": "chat.completed"}) == ("completed", False)
    assert progress.done and progress.error is None
    failed = AnswerProgress()
    assert failed.observe({"event": "chat.error", "safe_error_code": "retrieval_failed"}) == (
        "error",
        True,
    )
    assert failed.error == "retrieval_failed"
    assert json.loads(start_message("Q?", "r1"))["command"] == "chat.start"
    assert next_offset(0) == 0
    assert next_offset(45) in {0, 20, 40}
    assert build_document("abc") != build_document("def")
