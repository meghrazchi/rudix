"""Prometheus alert and recording rules reference only series the application exports (S1).

Loads ``infra/observability/prometheus/alerts.yml`` and every ``rules/*.yml`` file, then
checks each rule against the metric families registered on ``app.core.metrics.registry``
(the registry ``/metrics`` and the worker metrics server serve). Later tasks add their rule
files under ``rules/`` and this test covers them without changes.
"""

from __future__ import annotations

import importlib
import re
from collections import Counter
from pathlib import Path
from typing import Any

import pytest
import yaml

PROMETHEUS_DIR = Path(__file__).resolve().parents[2] / "infra" / "observability" / "prometheus"

# Every module that defines rudix_* series (grep '"rudix_' under backend/app). Importing them
# registers their collectors on the shared registry.
METRIC_MODULES = (
    "app.core.metrics",
    "app.core.db_metrics",
    "app.core.maintenance_metrics",
    "app.core.metrics_workers",
    "app.core.metrics_realtime",
    "app.core.metrics_frontend",
    "app.core.metrics_auth_session",
    "app.core.metrics_infra",
    "app.core.metrics_db_replica",
    "app.core.loop_lag",
    "app.core.cache",
    "app.db.tenant_context",
    "app.auth.usage_touch",
    "app.rate_limit.sliding_window",
    "app.ops.backup.freshness",
)

# Series an existing rule references although no module exports them, with the reason.
# Empty: every reference in alerts.yml resolves at S1. Add an entry only with a reason and
# report it; never to hide a typo in a new rule.
KNOWN_MISSING: dict[str, str] = {}

_SERIES_RE = re.compile(r"\b(rudix_[a-zA-Z0-9_]+)\b")
_QUOTED_RE = re.compile(r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'')
_SUFFIXES = {
    "counter": ("_total", "_created"),
    "histogram": ("_bucket", "_sum", "_count", "_created"),
    "summary": ("_sum", "_count", "_created"),
    "gaugehistogram": ("_bucket", "_gsum", "_gcount"),
    "info": ("_info",),
}


def rule_files() -> list[Path]:
    files = [PROMETHEUS_DIR / "alerts.yml"]
    files.extend(sorted((PROMETHEUS_DIR / "rules").glob("*.yml")))
    return [path for path in files if path.is_file()]


def load_rules(path: Path) -> list[dict[str, Any]]:
    document = yaml.safe_load(path.read_text()) or {}
    groups = document.get("groups") or []
    assert isinstance(groups, list), f"{path.name}: groups must be a list"
    rules: list[dict[str, Any]] = []
    for group in groups:
        assert group.get("name"), f"{path.name}: every group needs a name"
        for rule in group.get("rules") or []:
            rules.append(rule)
    return rules


def referenced_series(expr: str) -> set[str]:
    """rudix_* names in a PromQL expression, ignoring quoted label values."""
    return set(_SERIES_RE.findall(_QUOTED_RE.sub('""', expr)))


def exported_series() -> set[str]:
    """Every sample name the shared registry can expose, suffixes included."""
    for module in METRIC_MODULES:
        importlib.import_module(module)
    from app.core import db_metrics
    from app.core.metrics import registry

    families = list(registry.collect())
    # The pool collector is installed with the engine; describe() lists its gauges anyway.
    families.extend(db_metrics.DbPoolCollector(lambda: None).describe())
    names: set[str] = set()
    for family in families:
        names.add(family.name)
        for suffix in _SUFFIXES.get(family.type, ()):
            names.add(family.name + suffix)
        for sample in family.samples:
            names.add(sample.name)
    return names


def recorded_names() -> set[str]:
    return {
        rule["record"] for path in rule_files() for rule in load_rules(path) if "record" in rule
    }


def test_rule_directory_and_alerts_file_exist() -> None:
    assert (PROMETHEUS_DIR / "alerts.yml").is_file()
    assert (PROMETHEUS_DIR / "rules" / "README.md").is_file()
    config = yaml.safe_load((PROMETHEUS_DIR / "prometheus.yml").read_text())
    assert "/etc/prometheus/alerts.yml" in config["rule_files"]
    assert "/etc/prometheus/rules/*.yml" in config["rule_files"]


def test_exported_series_include_known_families() -> None:
    names = exported_series()
    for expected in (
        "rudix_http_requests_total",
        "rudix_rag_query_duration_seconds_bucket",
        "rudix_db_pool_timeouts_total",
        "rudix_chat_ws_connections",
        "rudix_backup_last_success_timestamp_seconds",
    ):
        assert expected in names
    assert "rudix_series_that_does_not_exist_total" not in names


@pytest.mark.parametrize("path", rule_files(), ids=lambda path: path.name)
def test_rule_expressions_reference_exported_series(path: Path) -> None:
    exported = exported_series() | recorded_names()
    missing: dict[str, list[str]] = {}
    for rule in load_rules(path):
        name = rule.get("alert") or rule.get("record") or "<unnamed>"
        expr = str(rule.get("expr", ""))
        assert expr.strip(), f"{path.name}:{name} has no expr"
        unknown = sorted(
            series
            for series in referenced_series(expr)
            if series not in exported and series not in KNOWN_MISSING
        )
        if unknown:
            missing[name] = unknown
    assert missing == {}, f"{path.name}: rules reference series no module exports: {missing}"


@pytest.mark.parametrize("path", rule_files(), ids=lambda path: path.name)
def test_alerts_have_severity_and_summary(path: Path) -> None:
    incomplete = [
        rule["alert"]
        for rule in load_rules(path)
        if "alert" in rule
        and (
            not (rule.get("labels") or {}).get("severity")
            or not (rule.get("annotations") or {}).get("summary")
        )
    ]
    assert incomplete == []


def test_rule_names_are_unique_across_files() -> None:
    counts: Counter[str] = Counter()
    for path in rule_files():
        for rule in load_rules(path):
            if "alert" in rule:
                counts[f"alert:{rule['alert']}"] += 1
            elif "record" in rule:
                counts[f"record:{rule['record']}"] += 1
    assert sorted(name for name, count in counts.items() if count > 1) == []


def test_known_missing_entries_are_still_missing() -> None:
    exported = exported_series()
    assert sorted(name for name in KNOWN_MISSING if name in exported) == []


def test_helpers_resolve_suffixes_and_ignore_quoted_values() -> None:
    expr = 'sum(rate(rudix_a_total{queue=~"rudix_not_a_series"}[5m])) / rudix_b_bucket'
    assert referenced_series(expr) == {"rudix_a_total", "rudix_b_bucket"}
