"""Chart secrets and request-time frontend configuration (0.8.0, D1: R08-11, R08-12)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.helm_support import (
    CHART_DIR,
    REPO_ROOT,
    all_values_files,
    assert_common_invariants,
    render_chart,
    render_failure,
    values_file,
    walk,
)

CI_VALUES = values_file("ci/all-features-values.yaml")
PUBLIC_KEYS_FILE = REPO_ROOT / "frontend" / "config" / "public-runtime-keys.mjs"
EXTERNAL_SECRET_ON = {
    "secrets.existingSecret": "rudix-app-env",
    "secrets.externalSecret.enabled": "true",
    "secrets.externalSecret.data[0].secretKey": "APP_AUTH_SECRET",
    "secrets.externalSecret.data[0].remoteRef.key": "rudix/app-auth-secret",
}


def _external_secrets(objects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [obj for obj in objects if obj.get("kind") == "ExternalSecret"]


def _frontend_config(objects: list[dict[str, Any]]) -> dict[str, str]:
    config_map = next(obj for obj in objects if obj["metadata"]["name"] == "rudix-frontend")
    return dict(config_map.get("data") or {})


def _public_runtime_keys() -> set[str]:
    source = PUBLIC_KEYS_FILE.read_text()
    block = source.split("PUBLIC_RUNTIME_KEYS = Object.freeze([", 1)[1].split("]);", 1)[0]
    return set(re.findall(r'"(NEXT_PUBLIC_[A-Z0-9_]+)"', block))


@pytest.mark.parametrize("files", [[]] + [[path] for path in all_values_files()])
def test_external_secret_renders_only_when_enabled(files: list[str]) -> None:
    objects = render_chart(files)
    assert_common_invariants(objects)
    enabled = files == [CI_VALUES]
    assert len(_external_secrets(objects)) == (1 if enabled else 0)
    assert not [obj for obj in objects if obj.get("kind") == "Secret"]


def test_external_secret_targets_the_existing_secret_with_references_only() -> None:
    objects = render_chart(set_values=EXTERNAL_SECRET_ON)
    (external,) = _external_secrets(objects)
    assert external["apiVersion"] == "external-secrets.io/v1"
    assert external["metadata"]["name"] == "rudix-secrets"
    spec = external["spec"]
    assert spec["target"]["name"] == "rudix-app-env"
    assert spec["secretStoreRef"] == {"name": "rudix-secret-store", "kind": "ClusterSecretStore"}
    assert spec["refreshInterval"] == "1h"
    assert spec["data"] == [
        {"secretKey": "APP_AUTH_SECRET", "remoteRef": {"key": "rudix/app-auth-secret"}}
    ]
    # The pods read the target Secret through envFrom, never a literal value.
    assert_common_invariants(objects)


def test_ci_values_render_property_and_previous_secret_reference() -> None:
    (external,) = _external_secrets(render_chart([CI_VALUES]))
    keys = [item["secretKey"] for item in external["spec"]["data"]]
    assert "APP_AUTH_SECRET_PREVIOUS" in keys
    assert {"key": "rudix/ci/app-auth", "property": "previous"} in [
        item["remoteRef"] for item in external["spec"]["data"]
    ]


@pytest.mark.parametrize(
    ("set_values", "message"),
    [
        (
            {"secrets.externalSecret.enabled": "true"},
            "secrets.externalSecret needs secrets.existingSecret",
        ),
        (
            {**EXTERNAL_SECRET_ON, "secrets.externalSecret.secretStoreRef.name": ""},
            "secretStoreRef.name is required",
        ),
        (
            {**EXTERNAL_SECRET_ON, "secrets.externalSecret.secretStoreRef.kind": "Vault"},
            "must be SecretStore or ClusterSecretStore",
        ),
        (
            {**EXTERNAL_SECRET_ON, "secrets.externalSecret.data[0].remoteRef.key": ""},
            "needs secretKey and remoteRef.key",
        ),
        (
            {"runtimeConfig.env.NEXT_PUBLIC_ASSET_PREFIX": "https://cdn.example.com"},
            "runtimeConfig.env.NEXT_PUBLIC_ASSET_PREFIX is fixed when the frontend image",
        ),
        (
            {"runtimeConfig.env.PUBLIC_ASSET_CACHE_CONTROL": "max-age=60"},
            "runtimeConfig.env.PUBLIC_ASSET_CACHE_CONTROL is fixed",
        ),
        (
            {"runtimeConfig.env.NEXT_PUBLIC_RUNTIME_CONFIG_SOURCE": "runtime"},
            "must be build or request",
        ),
        ({"cdn.assetPrefix": "http://cdn.example.com"}, "cdn.assetPrefix must be an https"),
        (
            {"cdn.publicAssetCacheControl": "immutable"},
            "must not be immutable",
        ),
    ],
)
def test_invalid_d1_values_fail_with_clear_messages(
    set_values: dict[str, str], message: str
) -> None:
    assert message in render_failure(set_values=set_values)


def test_external_secret_without_data_fails() -> None:
    values = {
        "secrets.existingSecret": "rudix-app-env",
        "secrets.externalSecret.enabled": "true",
    }
    assert "data must list at least one secretKey" in render_failure(set_values=values)


@pytest.mark.parametrize("files", [[]] + [[path] for path in all_values_files()])
def test_runtime_config_holds_only_allowlisted_public_names(files: list[str]) -> None:
    data = _frontend_config(render_chart(files))
    allowed = _public_runtime_keys() | {"NEXT_PUBLIC_RUNTIME_CONFIG_SOURCE"}
    assert data, "runtimeConfig.env renders into the frontend ConfigMap"
    assert sorted(set(data) - allowed) == []
    assert data.get("NEXT_PUBLIC_RUNTIME_CONFIG_SOURCE", "build") in {"build", "request"}


def test_default_runtime_config_keeps_build_mode() -> None:
    data = _frontend_config(render_chart())
    assert data["NEXT_PUBLIC_RUNTIME_CONFIG_SOURCE"] == "build"
    assert data["NEXT_PUBLIC_API_URL"].endswith(".invalid/api/v1")


def test_values_files_hold_no_secret_literal() -> None:
    secretish = re.compile(r"(sk-|whsec_|svc_|rudix_[A-Za-z0-9]{8}|-----BEGIN|password=)", re.I)
    for path in [CHART_DIR / "values.yaml", *(Path(p) for p in all_values_files())]:
        document = yaml.safe_load(path.read_text()) or {}
        for key_path, value in walk(document):
            if isinstance(value, str):
                assert not secretish.search(value), f"{path.name}: {key_path}"
        external = (document.get("secrets") or {}).get("externalSecret") or {}
        for item in external.get("data") or []:
            assert set(item) <= {"secretKey", "remoteRef"}, f"{path.name}: {item}"
            assert set(item["remoteRef"]) <= {"key", "property", "version"}
