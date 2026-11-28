"""Helm chart skeleton (0.8.0, S1): renders, labels, safety invariants, values parity, helpers."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.helm_support import (
    CHART_DIR,
    REPO_ROOT,
    all_values_files,
    assert_common_invariants,
    assert_no_host_access,
    assert_no_literal_secrets,
    assert_standard_labels,
    is_secret_env_name,
    render_chart,
    render_failure,
    top_level_keys_without_owner,
    values_file,
    values_key_paths,
)

# Top-level keys and their owners, from plan section 5.1.
PLAN_OWNERS = {
    "global": "S1",
    "image": "S1",
    "config": "S1",
    "secrets": "S1",
    "serviceAccount": "S1",
    "podSecurityContext": "S1",
    "containerSecurityContext": "S1",
    "metrics": "S1",
    "ingress": "A1",
    "backup": "A2",
    "dataStores": "A2",
    "frontend": "C1",
    "api": "C1",
    "mcp": "C1",
    "workers": "C1",
    "beat": "C1",
    "migrations": "C1",
    "autoscaling": "C1",
    "networkPolicy": "C1",
    "podDisruptionBudget": "C1",
    "rollout": "C1",
    "connectionBudget": "C1",
    "database": "C2",
    "pgbouncer": "C2",
    "tracing": "B3",
    "runtimeConfig": "D1",
    "cdn": "D1",
}
ENV_ANCHORS = [f"# v080-{task}" for task in ("A1", "A2", "B1", "B2", "B3", "C1", "C2", "D1")]

# A template that calls every shared helper, rendered only from a copy of the chart.
HELPERS_PROBE = """\
{{- range $component := list "frontend" "api" "mcp" "worker-ingest" "beat" "migrate" "backup-postgres" }}
---
apiVersion: v1
kind: Pod
metadata:
  name: {{ include "rudix.componentName" (dict "root" $ "component" $component) }}
  labels:
    {{- include "rudix.labels" (dict "root" $ "component" $component) | nindent 4 }}
  annotations:
    selector: {{ include "rudix.selectorLabels" (dict "root" $ "component" $component) | fromYaml | toJson | quote }}
spec:
  serviceAccountName: {{ include "rudix.serviceAccountName" $ }}
  securityContext:
    {{- include "rudix.podSecurityContext" (dict "root" $ "component" $component) | nindent 4 }}
  containers:
    - name: main
      image: {{ include "rudix.image" (dict "root" $ "component" $component) }}
      envFrom:
        {{- include "rudix.envFrom" $ | nindent 8 }}
      securityContext:
        {{- include "rudix.containerSecurityContext" $ | nindent 8 }}
      volumeMounts:
        {{- include "rudix.tmpVolumeMount" $ | nindent 8 }}
  volumes:
    {{- include "rudix.tmpVolume" $ | nindent 4 }}
{{- end }}
"""


def _render_cases() -> list[tuple[str, list[str]]]:
    cases: list[tuple[str, list[str]]] = [("defaults", [])]
    cases.extend((Path(path).name, [path]) for path in all_values_files())
    return cases


@pytest.fixture
def probe_chart(tmp_path: Path) -> Path:
    chart = tmp_path / "rudix"
    shutil.copytree(CHART_DIR, chart)
    (chart / "templates" / "zz-helpers-probe.yaml").write_text(HELPERS_PROBE)
    return chart


def _pods(objects: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {obj["metadata"]["name"]: obj for obj in objects if obj["kind"] == "Pod"}


@pytest.mark.parametrize(("label", "files"), _render_cases(), ids=lambda case: str(case))
def test_chart_renders_with_common_invariants(label: str, files: list[str]) -> None:
    objects = render_chart(files)
    assert_common_invariants(objects)
    kinds = sorted(f"{obj['kind']}/{obj['metadata']['name']}" for obj in objects)
    assert "ConfigMap/rudix-config" in kinds
    assert "ConfigMap/rudix-frontend" in kinds


def test_chart_metadata() -> None:
    chart = yaml.safe_load((CHART_DIR / "Chart.yaml").read_text())
    assert chart["apiVersion"] == "v2"
    assert chart["name"] == "rudix"
    assert chart["version"] == "0.8.0"
    assert chart["appVersion"] == "0.8.0"
    assert chart["type"] == "application"
    assert chart["kubeVersion"] == ">=1.27.0-0"


def test_config_map_holds_non_secret_env_and_defaults_render() -> None:
    objects = render_chart()
    config = next(obj for obj in objects if obj["metadata"]["name"] == "rudix-config")
    assert config["data"]["ENVIRONMENT"] == "development"
    assert config["data"]["LOG_FORMAT"] == "json"
    assert config["data"]["API_BASE_URL"].endswith(".invalid")
    frontend = next(obj for obj in objects if obj["metadata"]["name"] == "rudix-frontend")
    # D1 (R08-11) fills runtimeConfig.env with build mode and placeholder public values.
    assert frontend["data"]["NEXT_PUBLIC_RUNTIME_CONFIG_SOURCE"] == "build"
    account = next(obj for obj in objects if obj["kind"] == "ServiceAccount")
    assert account["automountServiceAccountToken"] is False


def test_runtime_config_renders_into_frontend_config_map() -> None:
    objects = render_chart(set_values={"runtimeConfig.env.NEXT_PUBLIC_SAMPLE": "on"})
    frontend = next(obj for obj in objects if obj["metadata"]["name"] == "rudix-frontend")
    assert frontend["data"]["NEXT_PUBLIC_SAMPLE"] == "on"


def test_helpers_render_contract_shapes(probe_chart: Path) -> None:
    objects = render_chart([values_file("ci/all-features-values.yaml")], chart_dir=probe_chart)
    assert_common_invariants(objects)
    pods = _pods(objects)
    components = ("frontend", "api", "mcp", "worker-ingest", "beat", "migrate", "backup-postgres")
    assert sorted(pods) == sorted(f"rudix-{name}" for name in components)
    api = pods["rudix-api"]["spec"]
    assert api["containers"][0]["image"] == ("registry.invalid/rudix/api@sha256:" + "0" * 63 + "1")
    worker = pods["rudix-worker-ingest"]["spec"]["containers"][0]
    assert worker["image"] == "registry.invalid/rudix/worker:ci-check"
    assert pods["rudix-mcp"]["spec"]["containers"][0]["image"].startswith(
        "registry.invalid/rudix/api@"
    )
    assert worker["envFrom"] == [
        {"configMapRef": {"name": "rudix-config"}},
        {"secretRef": {"name": "rudix-ci-app-env"}},
    ]
    assert worker["securityContext"] == {
        "allowPrivilegeEscalation": False,
        "readOnlyRootFilesystem": True,
        "runAsNonRoot": True,
        "capabilities": {"drop": ["ALL"]},
    }
    assert worker["volumeMounts"] == [{"name": "tmp", "mountPath": "/tmp"}]
    assert api["volumes"] == [{"name": "tmp", "emptyDir": {"sizeLimit": "256Mi"}}]
    assert api["securityContext"] == {
        "runAsNonRoot": True,
        "runAsUser": 10001,
        "runAsGroup": 10001,
        "fsGroup": 10001,
        "seccompProfile": {"type": "RuntimeDefault"},
    }
    assert pods["rudix-frontend"]["spec"]["securityContext"]["runAsUser"] == 1000
    selector = yaml.safe_load(pods["rudix-beat"]["metadata"]["annotations"]["selector"])
    assert selector == {
        "app.kubernetes.io/name": "rudix",
        "app.kubernetes.io/instance": "rudix",
        "app.kubernetes.io/component": "beat",
    }


def test_image_defaults_to_app_version_and_envfrom_without_secret(probe_chart: Path) -> None:
    pods = _pods(render_chart(chart_dir=probe_chart))
    container = pods["rudix-api"]["spec"]["containers"][0]
    assert container["image"] == "registry.invalid/rudix/api:0.8.0"
    assert container["envFrom"] == [{"configMapRef": {"name": "rudix-config"}}]
    pods = _pods(render_chart(set_values={"image.tag": "1.2.3"}, chart_dir=probe_chart))
    assert pods["rudix-beat"]["spec"]["containers"][0]["image"].endswith("/worker:1.2.3")


@pytest.mark.parametrize(
    ("set_values", "message"),
    [
        ({"secrets.create": "true"}, "secrets.create is not supported"),
        ({"global.environment": "qa"}, "is not development|test|staging|production"),
        ({"global.environment": "staging"}, "must equal global.environment"),
        ({"metrics.enabled": "true"}, "metrics.requireAuth needs secrets.existingSecret"),
    ],
)
def test_invalid_values_fail_with_clear_messages(set_values: dict[str, str], message: str) -> None:
    # --set-string passes "true" as a string, which templates treat as truthy.
    assert message in render_failure(set_values=set_values)


def test_bad_digest_and_unknown_component_fail(probe_chart: Path) -> None:
    with pytest.raises(AssertionError, match="must be sha256"):
        render_chart(set_values={"image.api.digest": "latest"}, chart_dir=probe_chart)
    probe = probe_chart / "templates" / "zz-helpers-probe.yaml"
    probe.write_text(HELPERS_PROBE.replace('"beat"', '"scheduler"'))
    with pytest.raises(AssertionError, match='unknown component "scheduler"'):
        render_chart(chart_dir=probe_chart)


def test_staging_and_production_have_the_same_keys_as_each_other_and_defaults() -> None:
    defaults = values_key_paths(CHART_DIR / "values.yaml")
    staging = values_key_paths(CHART_DIR / "values-staging.yaml")
    production = values_key_paths(CHART_DIR / "values-production.yaml")
    assert sorted(staging ^ production) == []
    assert sorted(staging - defaults) == []


def test_every_top_level_key_has_an_owner_comment() -> None:
    for name in (
        "values.yaml",
        "values-staging.yaml",
        "values-production.yaml",
        "ci/all-features-values.yaml",
    ):
        assert top_level_keys_without_owner(CHART_DIR / name) == [], name
    text = (CHART_DIR / "values.yaml").read_text()
    for key, owner in PLAN_OWNERS.items():
        assert f"# owner: {owner}\n{key}:" in text, key
    for anchor in ENV_ANCHORS:
        assert f"    {anchor}\n" in text


def test_shared_assertions_catch_violations() -> None:
    pod: dict[str, Any] = {
        "kind": "Deployment",
        "metadata": {"name": "bad", "labels": {}},
        "spec": {
            "template": {
                "spec": {
                    "hostNetwork": True,
                    "containers": [
                        {
                            "name": "c",
                            "ports": [{"containerPort": 80, "hostPort": 80}],
                            "securityContext": {"privileged": True},
                            "env": [
                                {"name": "DATABASE_PASSWORD", "value": "x"},
                                {
                                    "name": "APP_AUTH_SECRET",
                                    "valueFrom": {"secretKeyRef": {"name": "s", "key": "k"}},
                                },
                                {"name": "OPENAI_API_KEY", "valueFrom": {"configMapKeyRef": {}}},
                            ],
                        }
                    ],
                }
            }
        },
    }
    service = {"kind": "Service", "metadata": {"name": "s"}, "spec": {"type": "NodePort"}}
    config = {"kind": "ConfigMap", "metadata": {"name": "c"}, "data": {"REDIS_PASSWORD": "x"}}
    with pytest.raises(AssertionError):
        assert_standard_labels([pod])
    with pytest.raises(AssertionError) as host:
        assert_no_host_access([pod, service])
    assert "hostNetwork" in str(host.value) and "NodePort" in str(host.value)
    with pytest.raises(AssertionError) as secrets:
        assert_no_literal_secrets([pod, config])
    text = str(secrets.value)
    assert "DATABASE_PASSWORD" in text and "OPENAI_API_KEY" in text
    assert "REDIS_PASSWORD" in text and "APP_AUTH_SECRET" not in text
    assert is_secret_env_name("APP_AUTH_SECRET")
    assert not is_secret_env_name("APP_AUTH_ACCESS_TOKEN_TTL_SECONDS")


@pytest.mark.parametrize(
    "name",
    [
        "CHUNK_SIZE_TOKENS",
        "EMBEDDING_BATCH_MAX_TOKENS",
        "OPENAI_LLM_INPUT_COST_PER_MILLION_TOKENS_USD",
        "CONNECTOR_CREDENTIAL_ENCRYPTION_KEY_ID",
        "NEXT_PUBLIC_CONTACT_CAPTCHA_SITE_KEY",
    ],
)
def test_non_secret_names_with_secret_words_may_live_in_config_maps(name: str) -> None:
    assert not is_secret_env_name(name)


@pytest.mark.parametrize(
    "name",
    [
        "POSTGRES_PASSWORD",
        "OPENAI_API_KEY",
        "MINIO_SECRET_KEY",
        "METRICS_BEARER_TOKEN",
        "CONNECTOR_CREDENTIAL_ENCRYPTION_KEY",
        "BOT_SLACK_SIGNING_SECRET",
        "LANGFUSE_SECRET_KEY",
    ],
)
def test_secret_names_stay_secret(name: str) -> None:
    assert is_secret_env_name(name)


def test_numeric_env_values_render_as_plain_digits(tmp_path: Path) -> None:
    overrides = tmp_path / "numbers.yaml"
    overrides.write_text(
        "config:\n  env:\n    UPLOAD_MAX_BYTES: 52428800\n    RATIO: 0.25\n    FLAG: true\n"
        "runtimeConfig:\n  env:\n    NEXT_PUBLIC_POLL_MS: 15000000\n    NEXT_PUBLIC_EMPTY: null\n"
    )
    objects = render_chart([str(overrides)])
    config = next(obj for obj in objects if obj["metadata"]["name"] == "rudix-config")
    assert config["data"]["UPLOAD_MAX_BYTES"] == "52428800"
    assert config["data"]["RATIO"] == "0.25"
    assert config["data"]["FLAG"] == "true"
    frontend = next(obj for obj in objects if obj["metadata"]["name"] == "rudix-frontend")
    assert frontend["data"]["NEXT_PUBLIC_POLL_MS"] == "15000000"
    assert frontend["data"]["NEXT_PUBLIC_EMPTY"] == ""


def test_check_script_is_posix_and_covers_every_values_file() -> None:
    script = (REPO_ROOT / "deploy" / "scripts" / "check_helm_chart.sh").read_text()
    assert script.startswith("#!/bin/sh\n")
    assert "set -eu" in script
    assert "ci/*-values.yaml" in script and "RENDER_DIR" in script
