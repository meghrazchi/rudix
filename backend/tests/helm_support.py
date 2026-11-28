"""Render the Rudix Helm chart and share the structural assertions (0.8.0, contract 5.2.3).

``render_chart`` runs ``helm template`` and returns the rendered objects; it skips the test
with a clear reason when ``helm`` is not installed (CI installs it; ``HELM_BIN`` overrides the
binary). The ``assert_*`` helpers are the common checks every ``test_helm_chart_*.py`` runs
on its own renders.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CHART_DIR = REPO_ROOT / "deploy" / "helm" / "rudix"
RELEASE_NAME = "rudix"
NAMESPACE = "rudix"

STANDARD_LABELS = (
    "helm.sh/chart",
    "app.kubernetes.io/name",
    "app.kubernetes.io/instance",
    "app.kubernetes.io/component",
    "app.kubernetes.io/version",
    "app.kubernetes.io/managed-by",
    "app.kubernetes.io/part-of",
)

# Environment names that look like secrets. Such a name may get its value only from a
# Secret (secretKeyRef or envFrom secretRef), never a literal or a ConfigMap.
SECRET_ENV_NAME = re.compile(r"PASSWORD|SECRET|TOKEN|_KEY")
# Names that match SECRET_ENV_NAME but hold no secret (durations, switches, key names).
NON_SECRET_ENV_NAME = re.compile(
    r"(_SECONDS|_MS|_TTL|_ENABLED|_REQUIRED|_MODE|_HEADER|_HEADER_NAME|_NAME|_PREFIX|_FILE"
    r"|_SECRET_KEY_NAME)$"
)
FORBIDDEN_SERVICE_TYPES = ("NodePort", "LoadBalancer")


def helm_binary() -> str | None:
    configured = os.environ.get("HELM_BIN")
    if configured:
        return configured if shutil.which(configured) or Path(configured).is_file() else None
    return shutil.which("helm")


def values_file(name: str) -> str:
    return str(CHART_DIR / name)


def all_values_files() -> list[str]:
    """Defaults are implied; staging, production, and every ci/*-values.yaml."""
    files = [values_file("values-staging.yaml"), values_file("values-production.yaml")]
    files.extend(str(path) for path in sorted((CHART_DIR / "ci").glob("*-values.yaml")))
    return files


def render_chart(
    values_files: list[str] | None = None,
    set_values: dict[str, str] | None = None,
    *,
    chart_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """``helm template`` the chart and return the rendered objects (empty documents dropped)."""
    binary = helm_binary()
    if binary is None:
        pytest.skip("helm is not installed (set HELM_BIN or install Helm 3 to run chart tests)")
    command = [
        binary,
        "template",
        RELEASE_NAME,
        str(chart_dir or CHART_DIR),
        "--namespace",
        NAMESPACE,
    ]
    for path in values_files or []:
        command.extend(["-f", path])
    for key, value in (set_values or {}).items():
        command.extend(["--set-string", f"{key}={value}"])
    result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=60)
    if result.returncode != 0:
        raise AssertionError(f"helm template failed: {result.stderr.strip()}")
    return [doc for doc in yaml.safe_load_all(result.stdout) if isinstance(doc, dict)]


def render_failure(
    values_files: list[str] | None = None,
    set_values: dict[str, str] | None = None,
) -> str:
    """Render expecting failure and return helm's error output."""
    try:
        render_chart(values_files, set_values)
    except AssertionError as exc:
        return str(exc)
    raise AssertionError("helm template succeeded but a failure was expected")


def object_id(obj: dict[str, Any]) -> str:
    return f"{obj.get('kind')}/{(obj.get('metadata') or {}).get('name')}"


def walk(node: Any, path: str = "") -> Iterator[tuple[str, Any]]:
    """Every (dotted path, value) pair in a nested structure."""
    yield path, node
    if isinstance(node, dict):
        for key, value in node.items():
            yield from walk(value, f"{path}.{key}" if path else str(key))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from walk(value, f"{path}[{index}]")


def pod_specs(obj: dict[str, Any]) -> list[dict[str, Any]]:
    """Pod specs of a workload: Pod, template-based kinds, and CronJob job templates."""
    spec = obj.get("spec") or {}
    if obj.get("kind") == "Pod":
        return [spec]
    if obj.get("kind") == "CronJob":
        spec = (spec.get("jobTemplate") or {}).get("spec") or {}
    template_spec = (spec.get("template") or {}).get("spec")
    return [template_spec] if isinstance(template_spec, dict) else []


def containers(obj: dict[str, Any]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for spec in pod_specs(obj):
        for key in ("initContainers", "containers", "ephemeralContainers"):
            found.extend(spec.get(key) or [])
    return found


def is_secret_env_name(name: str) -> bool:
    return bool(SECRET_ENV_NAME.search(name)) and not NON_SECRET_ENV_NAME.search(name)


def assert_standard_labels(objects: Iterable[dict[str, Any]]) -> None:
    missing = {
        object_id(obj): [
            label
            for label in STANDARD_LABELS
            if label not in ((obj.get("metadata") or {}).get("labels") or {})
        ]
        for obj in objects
    }
    unlabeled = {key: value for key, value in missing.items() if value}
    assert unlabeled == {}, f"objects missing standard labels: {unlabeled}"


def assert_no_host_access(objects: Iterable[dict[str, Any]]) -> None:
    """No hostPort, hostNetwork/PID/IPC, privileged containers, NodePort or LoadBalancer."""
    problems: list[str] = []
    for obj in objects:
        for path, value in walk(obj):
            leaf = path.rsplit(".", 1)[-1]
            if leaf in ("hostPort", "nodePort"):
                problems.append(f"{object_id(obj)}: {path}")
            if leaf in ("hostNetwork", "hostPID", "hostIPC", "privileged") and value is True:
                problems.append(f"{object_id(obj)}: {path}")
        if obj.get("kind") == "Service":
            service_type = (obj.get("spec") or {}).get("type", "ClusterIP")
            if service_type in FORBIDDEN_SERVICE_TYPES:
                problems.append(f"{object_id(obj)}: type {service_type}")
    assert problems == [], f"host access or external service types: {problems}"


def assert_no_literal_secrets(objects: Iterable[dict[str, Any]]) -> None:
    """Secret-like env names get values only from a Secret; ConfigMaps never hold them."""
    problems: list[str] = []
    for obj in objects:
        if obj.get("kind") == "Secret" and (obj.get("data") or obj.get("stringData")):
            problems.append(f"{object_id(obj)}: chart renders a Secret with values")
        if obj.get("kind") == "ConfigMap":
            problems.extend(
                f"{object_id(obj)}: data.{key}"
                for key in (obj.get("data") or {})
                if is_secret_env_name(str(key))
            )
        for container in containers(obj):
            for env in container.get("env") or []:
                name = str(env.get("name", ""))
                if not is_secret_env_name(name):
                    continue
                source = env.get("valueFrom") or {}
                if "value" in env or "secretKeyRef" not in source:
                    problems.append(f"{object_id(obj)}: {container.get('name')} env {name}")
    assert problems == [], f"secret-like values outside a Secret: {problems}"


def assert_common_invariants(objects: list[dict[str, Any]]) -> None:
    """The checks every chart test runs on every render (contract 5.2.3)."""
    assert objects, "helm template rendered no objects"
    assert_standard_labels(objects)
    assert_no_host_access(objects)
    assert_no_literal_secrets(objects)


def values_key_paths(path: Path) -> set[str]:
    """Dotted paths of every mapping key in a values file (lists are leaves)."""
    document = yaml.safe_load(path.read_text()) or {}
    return {key_path for key_path, _ in walk(document) if key_path and "[" not in key_path}


def top_level_keys_without_owner(path: Path) -> list[str]:
    """Top-level keys not directly preceded by a ``# owner: <task>`` comment line."""
    lines = path.read_text().splitlines()
    missing: list[str] = []
    for index, line in enumerate(lines):
        match = re.match(r"^([A-Za-z][A-Za-z0-9_]*):", line)
        if not match:
            continue
        previous = lines[index - 1] if index else ""
        if not re.match(r"^# owner: [A-Z][0-9]+$", previous):
            missing.append(match.group(1))
    return missing
