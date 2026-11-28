"""Helm chart metrics scrape (0.8.0, B2, R08-09; contract 5.2.8): ServiceMonitors (off by
default), bearer token from the existing Secret, and metrics switches in config.env."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from app.workers.pools import POOL_NAMES
from tests.helm_support import (
    CHART_DIR,
    NAMESPACE,
    all_values_files,
    assert_common_invariants,
    render_chart,
    render_failure,
    values_file,
)

CI_VALUES = values_file("ci/all-features-values.yaml")
WORKER_COMPONENTS = sorted(f"worker-{name}" for name in POOL_NAMES)


def _monitors(objects: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {o["metadata"]["name"]: o for o in objects if o["kind"] == "ServiceMonitor"}


def _config_env(objects: list[dict[str, Any]]) -> dict[str, str]:
    [config] = [
        o for o in objects if o["kind"] == "ConfigMap" and o["metadata"]["name"] == "rudix-config"
    ]
    return dict(config["data"])


def _values(tmp_path: Path, document: dict[str, Any], name: str = "override.yaml") -> str:
    path = tmp_path / name
    path.write_text(yaml.safe_dump(document))
    return str(path)


def test_no_service_monitor_by_default_or_in_staging_and_production() -> None:
    for files in (
        [],
        [values_file("values-staging.yaml")],
        [values_file("values-production.yaml")],
    ):
        assert _monitors(render_chart(files)) == {}


def test_metrics_values_exist_in_every_values_file() -> None:
    for path in [str(CHART_DIR / "values.yaml"), *all_values_files()]:
        if path.endswith("hpa-values.yaml"):
            continue
        metrics = yaml.safe_load(Path(path).read_text())["metrics"]
        assert metrics["workers"]["multiprocess"] is True, path
        assert "enabled" in metrics["serviceMonitor"], path


def test_all_features_renders_api_and_worker_monitors_with_the_token_secret() -> None:
    objects = render_chart([CI_VALUES])
    assert_common_invariants(objects)
    monitors = _monitors(objects)
    assert set(monitors) == {"rudix-api-metrics", "rudix-worker-metrics"}
    api, workers = monitors["rudix-api-metrics"], monitors["rudix-worker-metrics"]
    for monitor in (api, workers):
        assert monitor["apiVersion"] == "monitoring.coreos.com/v1"
        assert monitor["metadata"]["labels"]["release"] == "kube-prometheus-stack"
        assert monitor["spec"]["namespaceSelector"] == {"matchNames": [NAMESPACE]}
        [endpoint] = monitor["spec"]["endpoints"]
        assert endpoint["path"] == "/metrics"
        assert endpoint["bearerTokenSecret"] == {
            "name": "rudix-ci-app-env",
            "key": "METRICS_BEARER_TOKEN",
        }
    assert api["spec"]["selector"]["matchLabels"]["app.kubernetes.io/component"] == "api"
    assert api["spec"]["endpoints"][0]["port"] == "http"
    assert api["spec"]["endpoints"][0]["relabelings"][0]["replacement"] == "rudix-api"
    [expression] = workers["spec"]["selector"]["matchExpressions"]
    assert expression["values"] == WORKER_COMPONENTS
    assert workers["spec"]["endpoints"][0]["port"] == "metrics"
    assert workers["spec"]["endpoints"][0]["relabelings"][0]["replacement"] == "rudix-worker"


def test_monitor_ports_match_the_services() -> None:
    objects = render_chart([CI_VALUES])
    services = {o["metadata"]["name"]: o for o in objects if o["kind"] == "Service"}
    assert services["rudix-api"]["spec"]["ports"][0]["name"] == "http"
    for component in WORKER_COMPONENTS:
        [port] = services[f"rudix-{component}"]["spec"]["ports"]
        assert (port["name"], port["port"]) == ("metrics", 9808)


def test_config_env_carries_the_metrics_switches() -> None:
    defaults = _config_env(render_chart([]))
    assert defaults["METRICS_ENABLED"] == "false"
    assert defaults["METRICS_REQUIRE_AUTH"] == "true"
    assert defaults["WORKER_METRICS_ENABLED"] == "false"
    assert defaults["WORKER_METRICS_MULTIPROCESS"] == "true"
    enabled = _config_env(render_chart([CI_VALUES]))
    assert enabled["METRICS_ENABLED"] == "true"
    assert enabled["WORKER_METRICS_ENABLED"] == "true"
    for files in ([values_file("values-staging.yaml")], [values_file("values-production.yaml")]):
        assert _config_env(render_chart(files))["METRICS_REQUIRE_AUTH"] == "true"


def test_bearer_token_omitted_only_without_auth_outside_staging(tmp_path: Path) -> None:
    override = _values(
        tmp_path,
        {
            "global": {"environment": "development"},
            "config": {"env": {"ENVIRONMENT": "development", "METRICS_REQUIRE_AUTH": "false"}},
            "metrics": {"requireAuth": False},
        },
    )
    monitors = _monitors(render_chart([CI_VALUES, override]))
    for monitor in monitors.values():
        assert "bearerTokenSecret" not in monitor["spec"]["endpoints"][0]


@pytest.mark.parametrize(
    ("document", "message"),
    [
        (
            {"config": {"env": {"METRICS_ENABLED": "false"}}},
            "config.env.METRICS_ENABLED=false disagrees with the metrics block",
        ),
        (
            {"config": {"env": {"WORKER_METRICS_MULTIPROCESS": "false"}}},
            "config.env.WORKER_METRICS_MULTIPROCESS=false disagrees",
        ),
        (
            {"config": {"env": {"WORKER_METRICS_ENABLED": "false"}}},
            "config.env.WORKER_METRICS_ENABLED=false disagrees",
        ),
        (
            {"metrics": {"requireAuth": False}},
            "config.env.METRICS_REQUIRE_AUTH=true disagrees with the metrics block (false)",
        ),
        (
            {
                "metrics": {"requireAuth": False},
                "config": {"env": {"METRICS_REQUIRE_AUTH": "false"}},
            },
            "metrics.requireAuth must be true in staging and production",
        ),
    ],
)
def test_inconsistent_metrics_values_fail(
    tmp_path: Path, document: dict[str, Any], message: str
) -> None:
    error = render_failure([CI_VALUES, _values(tmp_path, document)])
    assert message in error


def test_service_monitor_renders_only_with_metrics_enabled(tmp_path: Path) -> None:
    """Metrics off: no ServiceMonitor and no switch check, even with serviceMonitor on."""
    override = _values(
        tmp_path,
        {
            "metrics": {"enabled": False, "serviceMonitor": {"enabled": True}},
            "config": {"env": {"METRICS_ENABLED": "true"}},
            "autoscaling": {"enabled": False},
        },
    )
    assert _monitors(render_chart([CI_VALUES, override])) == {}
