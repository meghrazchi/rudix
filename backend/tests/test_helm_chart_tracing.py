"""Helm chart tracing values (0.8.0, B3, R08-10): off everywhere by default, switches in
config.env agree with the `tracing` block, https collector in staging and production."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.helm_support import (
    CHART_DIR,
    all_values_files,
    assert_common_invariants,
    render_chart,
    render_failure,
    values_file,
)

STAGING = values_file("values-staging.yaml")
PRODUCTION = values_file("values-production.yaml")
HTTPS_ENDPOINT = "https://otel-collector.observability.svc:4318"


def _config_env(objects: list[dict[str, Any]]) -> dict[str, str]:
    [config] = [
        o for o in objects if o["kind"] == "ConfigMap" and o["metadata"]["name"] == "rudix-config"
    ]
    return dict(config["data"])


def _values(tmp_path: Path, document: dict[str, Any]) -> str:
    path = tmp_path / "tracing.yaml"
    path.write_text(yaml.safe_dump(document))
    return str(path)


def _enabled(endpoint: str, **env: str) -> dict[str, Any]:
    return {
        "tracing": {"enabled": True, "endpoint": endpoint},
        "config": {
            "env": {"TRACING_ENABLED": "true", "OTEL_EXPORTER_OTLP_ENDPOINT": endpoint, **env}
        },
    }


def test_tracing_is_off_in_every_values_file() -> None:
    for path in [str(CHART_DIR / "values.yaml"), *all_values_files()]:
        if path.endswith("hpa-values.yaml"):
            continue
        tracing = yaml.safe_load(Path(path).read_text())["tracing"]
        assert tracing["enabled"] is False, path
        assert tracing["endpoint"] == "", path
        assert tracing["headersSecretKey"] == "OTEL_EXPORTER_OTLP_HEADERS", path


def test_defaults_render_tracing_switches_off() -> None:
    for files in ([], [STAGING], [PRODUCTION]):
        objects = render_chart(files)
        assert_common_invariants(objects)
        env = _config_env(objects)
        assert env["TRACING_ENABLED"] == "false"
        assert env["OTEL_EXPORTER_OTLP_ENDPOINT"] == ""
        assert env["TRACING_SAMPLE_RATIO"] == "0.05"
        assert env["TRACING_TRUST_INBOUND_CONTEXT"] == "false"
        assert "OTEL_EXPORTER_OTLP_HEADERS" not in env  # only from the Secret


def test_enabled_with_https_collector_renders(tmp_path: Path) -> None:
    env = _config_env(render_chart([PRODUCTION, _values(tmp_path, _enabled(HTTPS_ENDPOINT))]))
    assert env["TRACING_ENABLED"] == "true"
    assert env["OTEL_EXPORTER_OTLP_ENDPOINT"] == HTTPS_ENDPOINT


def test_insecure_collector_needs_the_explicit_switch(tmp_path: Path) -> None:
    plain = "http://otel-collector.observability.svc:4318"
    error = render_failure([STAGING, _values(tmp_path, _enabled(plain))])
    assert "must use https:// in staging and production" in error
    allowed = _enabled(plain, TRACING_ALLOW_INSECURE_ENDPOINT="true")
    env = _config_env(render_chart([STAGING, _values(tmp_path, allowed)]))
    assert env["OTEL_EXPORTER_OTLP_ENDPOINT"] == plain
    # Development accepts a plain collector without the switch.
    assert render_chart([_values(tmp_path, _enabled(plain))])


@pytest.mark.parametrize(
    ("document", "message"),
    [
        (
            {"tracing": {"enabled": True}, "config": {"env": {"TRACING_ENABLED": "true"}}},
            "tracing.enabled needs tracing.endpoint",
        ),
        ({"tracing": {"enabled": True, "endpoint": HTTPS_ENDPOINT}}, "TRACING_ENABLED disagrees"),
        (
            {"config": {"env": {"OTEL_EXPORTER_OTLP_ENDPOINT": HTTPS_ENDPOINT}}},
            "OTEL_EXPORTER_OTLP_ENDPOINT must equal tracing.endpoint",
        ),
        (
            {"tracing": {"headersSecretKey": "COLLECTOR_HEADERS"}},
            "headersSecretKey must be OTEL_EXPORTER_OTLP_HEADERS",
        ),
    ],
)
def test_inconsistent_tracing_values_fail(
    tmp_path: Path, document: dict[str, Any], message: str
) -> None:
    assert message in render_failure([_values(tmp_path, document)])
