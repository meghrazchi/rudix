"""SLO targets, recording rules, burn-rate alerts, and dashboard 08 agree (R08-09)."""

from __future__ import annotations

import importlib
import json
import re
from pathlib import Path
from typing import Any

from tests import metrics_support

metrics_support.ensure_env()

import pytest  # noqa: E402
import yaml  # noqa: E402
from prometheus_client.metrics import Histogram, MetricWrapperBase  # noqa: E402
from prometheus_client.utils import floatToGoString  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
OBSERVABILITY = REPO_ROOT / "infra" / "observability"
RULES_DIR = OBSERVABILITY / "prometheus" / "rules"
DASHBOARD = OBSERVABILITY / "grafana" / "dashboards" / "08-rudix-slo-targets.json"
WINDOWS = ["5m", "30m", "1h", "6h", "3d"]

# docs/26 section 4.6 table row (metric column) -> slo_targets ids covering it.
DOCS26_ROWS = {
    "Chat time to first token, default profile, p95": {"chat_ttft_p95"},
    "Chat full answer, default profile, p95": {"chat_full_answer_p95"},
    "Non-LLM API read endpoints, p95": {"api_read_p95"},
    "Ingestion of a 50-page text PDF to `indexed`, p95": {"ingestion_50_page_pdf_p95"},
    "Concurrent chat streams per API replica": {"chat_streams_per_replica"},
    "Database queries per chat request": {"db_queries_per_chat_request"},
    "API availability": {"api_availability_monthly"},
    "Recovery point / recovery time": {"rpo_15m", "rto_4h"},
}
DOCS12_ROWS = {
    "API availability": "docs12_api_availability",
    "Chat p95 latency": "docs12_chat_p95_latency",
    "Document indexing success": "docs12_document_indexing_success",
    "Retrieval hit rate": "docs12_retrieval_hit_rate",
    "Citation accuracy": "docs12_citation_accuracy",
    "Failed task rate": "docs12_failed_task_rate",
    "Not-found correctness": "docs12_not_found_correctness",
}


def _spec() -> dict[str, Any]:
    return yaml.safe_load((OBSERVABILITY / "slo_targets.yml").read_text())


def _targets() -> list[dict[str, Any]]:
    return list(_spec()["targets"])


def _rules(name: str) -> dict[str, dict[str, Any]]:
    document = yaml.safe_load((RULES_DIR / name).read_text())
    rules: dict[str, dict[str, Any]] = {}
    for group in document["groups"]:
        for rule in group["rules"]:
            rules[rule.get("record") or rule["alert"]] = rule
    return rules


def _metrics() -> dict[str, MetricWrapperBase]:
    for module in metrics_support.METRIC_MODULES:
        importlib.import_module(module)
    from app.core.metrics import registry

    return {
        c._name: c for c in list(registry._collector_to_names) if isinstance(c, MetricWrapperBase)
    }


def _table_rows(path: Path, heading: str) -> list[str]:
    text = path.read_text()
    section = text[text.index(heading) :]
    rows: list[str] = []
    started = False
    for line in section.splitlines()[1:]:
        if line.startswith("|"):
            started = True
            first = line.strip("|").split("|")[0].strip()
            if first and not set(first) <= {"-", " "} and first not in ("Metric",):
                rows.append(first)
        elif started:
            break
    return rows


def _prom_targets(target: dict[str, Any]) -> bool:
    return not target.get("measured_outside_prometheus")


def _record_names(target: dict[str, Any]) -> list[str]:
    if target["kind"] == "gauge":
        return list(target["records"])
    return [f"{target['record_prefix']}_rate{window}" for window in WINDOWS]


def test_windows_and_burn_rate_policy() -> None:
    spec = _spec()
    assert spec["windows"] == WINDOWS
    assert spec["burn_rate"]["page"] == {
        "long": "1h",
        "short": "5m",
        "factor": 14.4,
        "severity": "critical",
    }
    assert spec["burn_rate"]["ticket"] == {
        "long": "6h",
        "short": "30m",
        "factor": 6,
        "severity": "warning",
    }


def test_ids_are_unique_and_every_entry_is_mapped() -> None:
    targets = _targets()
    ids = [t["id"] for t in targets]
    assert len(ids) == len(set(ids))
    for target in targets:
        assert target["source"] and target["target"], target["id"]
        if target.get("measured_outside_prometheus"):
            assert len(str(target.get("reason", ""))) > 20, target["id"]
            assert "metric" not in target, target["id"]
        else:
            assert target["kind"] in {"latency", "ratio", "gauge"}, target["id"]
            assert target["metric"].startswith("rudix_"), target["id"]


def test_every_master_plan_target_is_listed() -> None:
    rows = _table_rows(REPO_ROOT / "docs" / "26_VERSIONED_ROADMAP_AND_RELEASE_PLAN.md", "### 4.6")
    assert rows == list(DOCS26_ROWS)
    by_id = {t["id"]: t for t in _targets()}
    for ids in DOCS26_ROWS.values():
        for target_id in ids:
            assert by_id[target_id]["source"] == "docs/26 4.6"
    assert by_id["rto_4h"]["measured_outside_prometheus"] is True
    assert "drill" in by_id["rto_4h"]["reason"]


def test_every_docs12_slo_is_listed() -> None:
    rows = _table_rows(REPO_ROOT / "docs" / "12_EVALUATION_AND_MONITORING.md", "## Production SLOs")
    assert rows == list(DOCS12_ROWS)
    by_id = {t["id"]: t for t in _targets()}
    for target_id in DOCS12_ROWS.values():
        assert by_id[target_id]["source"] == "docs/12 Production SLOs"


def test_series_exist_in_the_application_registry() -> None:
    metrics = _metrics()
    for target in filter(_prom_targets, _targets()):
        name = target["metric"].removesuffix("_total")
        assert name in metrics, target["id"]
        if target["kind"] == "latency":
            assert isinstance(metrics[name], Histogram), target["id"]


def test_latency_thresholds_use_existing_bucket_boundaries() -> None:
    metrics = _metrics()
    for target in _targets():
        if target.get("kind") != "latency":
            continue
        histogram = metrics[target["metric"]]
        bounds = [b for b in histogram._upper_bounds if b != float("inf")]
        threshold = float(target.get("threshold_seconds", target.get("threshold")))
        bucket = float(target["bucket_le"])
        assert bucket in bounds, target["id"]
        assert bucket == min(b for b in bounds if b >= threshold), target["id"]
        if bucket != threshold:
            assert target.get("bucket_note"), target["id"]
        assert 0 < target["objective"] < 1


def test_every_entry_has_its_recording_rules() -> None:
    recording = _rules("slo-recording.yml")
    for target in filter(_prom_targets, _targets()):
        for record in _record_names(target):
            assert record in recording, (target["id"], record)
            expr = recording[record]["expr"]
            metric = target["metric"]
            if target["kind"] == "latency":
                le = floatToGoString(float(target["bucket_le"]))
                assert f"{metric}_bucket{{" in expr and f'le="{le}"' in expr, record
                assert f"{metric}_count" in expr, record
            else:
                assert metric in expr, record
            if target["kind"] == "ratio":
                assert target["bad_selector"] in expr, record
            window = record.rsplit("_rate", 1)[-1]
            if target["kind"] != "gauge":
                assert expr.count(f"[{window}]") == 2, record


def test_burn_rate_alerts_are_multi_window() -> None:
    spec = _spec()
    alerts = _rules("slo-burn-rate.yml")
    expected: set[str] = set()
    for target in _targets():
        burn = target.get("burn_rate")
        if not burn:
            continue
        budget = round(1 - target["objective"], 6)
        prefix = target["record_prefix"]
        for tier, suffix in (("page", "Page"), ("ticket", "Ticket")):
            policy = spec["burn_rate"][tier]
            name = f"{burn['alert']}{suffix}"
            expected.add(name)
            rule = alerts[name]
            expr = rule["expr"]
            assert f"{prefix}_rate{policy['long']} > ({policy['factor']} * {budget})" in expr
            assert f"{prefix}_rate{policy['short']} > ({policy['factor']} * {budget})" in expr
            assert rule["labels"] == {
                "severity": policy["severity"],
                "service": burn["service"],
                "slo": target["id"],
            }
            assert rule["annotations"]["summary"] and rule["annotations"]["runbook"]
    assert set(alerts) == expected
    # Spec: availability, chat latency (TTFT and full answer), ingestion, and queue age.
    assert {
        "RudixSloAvailabilityBurnRatePage",
        "RudixSloChatTtftBurnRatePage",
        "RudixSloChatAnswerLatencyBurnRatePage",
        "RudixSloIngestionLatencyBurnRatePage",
        "RudixSloQueueWaitBurnRatePage",
    } <= expected


def test_dashboard_has_one_panel_per_target() -> None:
    dashboard = json.loads(DASHBOARD.read_text())
    panels = [p for p in dashboard["panels"] if p["type"] != "row"]
    titles = [p["title"] for p in panels]
    assert sorted(titles) == sorted(t["id"] for t in _targets())
    assert len({p["id"] for p in dashboard["panels"]}) == len(dashboard["panels"])
    by_title = {p["title"]: p for p in panels}
    for target in _targets():
        panel = by_title[target["id"]]
        if target.get("measured_outside_prometheus"):
            assert panel["type"] == "text"
            continue
        exprs = " ".join(t["expr"] for t in panel["targets"])
        records = _record_names(target)
        assert any(record in exprs for record in records), target["id"]
    for required in ("rpo_15m", "db_replica_lag", "beat_heartbeat_age"):
        assert required in by_title


@pytest.mark.parametrize(
    ("record", "metric"),
    [
        (
            "slo:rudix_backup_last_success_timestamp_seconds:age_max",
            "rudix_backup_last_success_timestamp_seconds",
        ),
        ("slo:rudix_db_replica_lag_seconds:max", "rudix_db_replica_lag_seconds"),
        (
            "slo:rudix_beat_heartbeat_timestamp_seconds:age_max",
            "rudix_beat_heartbeat_timestamp_seconds",
        ),
    ],
)
def test_s1_infrastructure_series_are_recorded(record: str, metric: str) -> None:
    assert re.search(rf"\b{metric}\b", _rules("slo-recording.yml")[record]["expr"])


def test_existing_alerts_file_keeps_its_alert_names() -> None:
    document = yaml.safe_load((OBSERVABILITY / "prometheus" / "alerts.yml").read_text())
    names = {rule["alert"] for group in document["groups"] for rule in group["rules"]}
    assert {
        "RudixApiHighErrorRate",
        "RudixChatP95LatencyHigh",
        "RudixDocumentIndexingFailureRateHigh",
        "RudixCeleryQueueWaitHigh",
        "RudixChatTimeToFirstTokenHigh",
    } <= names
