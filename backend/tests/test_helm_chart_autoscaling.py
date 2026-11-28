"""Helm chart autoscaling (0.8.0, C1, R08-07): KEDA ScaledObjects and autoscaling/v2 HPAs."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.core.config import settings
from app.workers.pools import POOL_NAMES, default_pool_queues
from tests.helm_support import (
    CHART_DIR,
    assert_common_invariants,
    render_chart,
    render_failure,
    values_file,
)
from tests.test_prometheus_rules import exported_series, referenced_series

CI_VALUES = values_file("ci/all-features-values.yaml")
HPA_VALUES = values_file("ci/hpa-values.yaml")
_QUEUE_RE = re.compile(r'queue=~"([^"]+)"')


def _by_kind(objects: list[dict[str, Any]], kind: str) -> dict[str, dict[str, Any]]:
    return {obj["metadata"]["name"]: obj for obj in objects if obj["kind"] == kind}


def _triggers(scaled: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {t.get("name") or t["type"]: t for t in scaled["spec"]["triggers"]}


def _queues_in(query: str) -> list[str]:
    match = _QUEUE_RE.search(query)
    assert match, query
    # The PromQL string holds `documents\\.processing`: one escaped backslash per dot.
    return [name.replace("\\\\.", ".") for name in match.group(1).split("|")]


def test_autoscaling_is_off_by_default_with_fixed_replicas() -> None:
    objects = render_chart()
    assert not [o for o in objects if o["kind"] in ("ScaledObject", "HorizontalPodAutoscaler")]
    deployments = _by_kind(objects, "Deployment")
    assert all("replicas" in d["spec"] for d in deployments.values())


def test_keda_scaled_objects_for_api_frontend_and_every_pool() -> None:
    objects = render_chart([CI_VALUES])
    assert_common_invariants(objects)
    scaled = _by_kind(objects, "ScaledObject")
    expected = {"rudix-api", "rudix-frontend"} | {f"rudix-worker-{n}" for n in POOL_NAMES}
    assert set(scaled) == expected
    assert _by_kind(objects, "HorizontalPodAutoscaler") == {}
    deployments = _by_kind(objects, "Deployment")
    for name, obj in scaled.items():
        assert obj["apiVersion"] == "keda.sh/v1alpha1"
        assert obj["spec"]["scaleTargetRef"]["name"] == name
        # The autoscaler owns the replica count; the Deployment leaves it unset.
        assert "replicas" not in deployments[name]["spec"], name
        behavior = obj["spec"]["advanced"]["horizontalPodAutoscalerConfig"]["behavior"]
        assert behavior["scaleDown"]["stabilizationWindowSeconds"] >= 60
    assert deployments["rudix-beat"]["spec"]["replicas"] == 1


def test_api_scales_on_in_flight_requests_and_streams_never_below_two() -> None:
    api = _by_kind(render_chart([CI_VALUES]), "ScaledObject")["rudix-api"]
    assert api["spec"]["minReplicaCount"] == 2
    assert api["spec"]["maxReplicaCount"] >= 2
    triggers = _triggers(api)
    in_flight = triggers["in-flight-requests"]
    assert in_flight["type"] == "prometheus"
    assert in_flight["metricType"] == "AverageValue"
    assert "sum(rudix_http_requests_in_progress{" in in_flight["metadata"]["query"]
    assert in_flight["metadata"]["serverAddress"].endswith(".invalid:9090")
    streams = triggers["open-streams"]
    query = streams["metadata"]["query"]
    assert "rudix_realtime_connections" in query and "rudix_chat_ws_connections" in query
    assert 0 < int(streams["metadata"]["threshold"]) < 200
    assert 'namespace="rudix"' in query
    assert triggers["cpu"]["metricType"] == "Utilization"


def test_worker_pools_scale_on_their_own_queues_and_never_to_zero() -> None:
    scaled = _by_kind(render_chart([CI_VALUES]), "ScaledObject")
    defaults = default_pool_queues(settings)
    for name in POOL_NAMES:
        obj = scaled[f"rudix-worker-{name}"]
        assert obj["spec"]["minReplicaCount"] == 1
        assert obj["spec"]["maxReplicaCount"] >= 1
        triggers = _triggers(obj)
        depth = triggers["queue-depth"]["metadata"]["query"]
        wait = triggers["queue-wait-p95"]["metadata"]["query"]
        assert depth.startswith("max(rudix_celery_queue_depth{")
        assert (
            "histogram_quantile(0.95" in wait and "rudix_celery_queue_wait_seconds_bucket" in wait
        )
        expected = list(dict.fromkeys(defaults[name]))
        assert _queues_in(depth) == expected, name
        assert _queues_in(wait) == expected, name
        assert triggers["queue-depth"]["metricType"] == "AverageValue"
        assert triggers["queue-wait-p95"]["metricType"] == "Value"


def test_values_queue_lists_equal_the_pool_defaults() -> None:
    values = yaml.safe_load((CHART_DIR / "values.yaml").read_text())
    pools = values["workers"]["pools"]
    assert sorted(pools) == sorted(POOL_NAMES)
    defaults = default_pool_queues(settings)
    for name in POOL_NAMES:
        assert pools[name]["queues"] == list(dict.fromkeys(defaults[name])), name
        concurrency = getattr(settings, f"worker_pool_{name}_concurrency")
        assert pools[name]["concurrency"] == concurrency, name
    assert sorted(values["autoscaling"]["workers"]["pools"]) == sorted(POOL_NAMES)


def test_every_series_in_the_queries_is_exported() -> None:
    exported = exported_series()
    for obj in _by_kind(render_chart([CI_VALUES]), "ScaledObject").values():
        for trigger in obj["spec"]["triggers"]:
            if trigger["type"] != "prometheus":
                continue
            names = referenced_series(trigger["metadata"]["query"])
            assert names, trigger
            assert names <= exported, sorted(names - exported)


def test_keda_requires_a_prometheus_server_address(tmp_path: Path) -> None:
    override = tmp_path / "keda.yaml"
    override.write_text("autoscaling:\n  enabled: true\n  mode: keda\n")
    message = render_failure([str(override)])
    assert "autoscaling.prometheus.serverAddress is required" in message


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("autoscaling:\n  enabled: true\n  mode: vpa\n", "autoscaling.mode must be keda or hpa"),
        (
            "autoscaling:\n  enabled: true\n  mode: hpa\n  api:\n    minReplicas: 1\n",
            "autoscaling.api.minReplicas must be at least 2",
        ),
    ],
)
def test_invalid_autoscaling_values_fail(tmp_path: Path, text: str, message: str) -> None:
    override = tmp_path / "bad.yaml"
    override.write_text(text)
    assert message in render_failure([str(override)])


def test_custom_label_matchers_and_pool_minimum(tmp_path: Path) -> None:
    override = tmp_path / "matchers.yaml"
    override.write_text(
        'autoscaling:\n  prometheus:\n    labelMatchers: job="rudix-api"\n'
        "  workers:\n    pools:\n      eval:\n        minReplicas: 0\n"
    )
    scaled = _by_kind(render_chart([CI_VALUES, str(override)]), "ScaledObject")
    query = _triggers(scaled["rudix-api"])["in-flight-requests"]["metadata"]["query"]
    assert 'job="rudix-api"' in query and "namespace=" not in query
    assert scaled["rudix-worker-eval"]["spec"]["minReplicaCount"] == 0


def test_hpa_mode_scales_api_and_frontend_on_cpu_and_memory() -> None:
    objects = render_chart([HPA_VALUES])
    assert_common_invariants(objects)
    assert _by_kind(objects, "ScaledObject") == {}
    hpas = _by_kind(objects, "HorizontalPodAutoscaler")
    assert sorted(hpas) == ["rudix-api", "rudix-frontend"]
    deployments = _by_kind(objects, "Deployment")
    for name, hpa in hpas.items():
        assert hpa["apiVersion"] == "autoscaling/v2"
        assert hpa["spec"]["scaleTargetRef"] == {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "name": name,
        }
        assert hpa["spec"]["minReplicas"] >= 2
        metrics = {m["resource"]["name"] for m in hpa["spec"]["metrics"]}
        assert metrics == {"cpu", "memory"}
        assert hpa["spec"]["behavior"]["scaleDown"]["stabilizationWindowSeconds"] >= 60
        assert "replicas" not in deployments[name]["spec"]
    # Workers keep fixed replicas in hpa mode.
    for name in POOL_NAMES:
        assert deployments[f"rudix-worker-{name}"]["spec"]["replicas"] == 1
