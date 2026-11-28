"""Helm chart ingress (0.8.0, A1, R08-01): one Ingress per host, TLS, NGINX annotations."""

from __future__ import annotations

from typing import Any

import pytest

from tests.helm_support import (
    all_values_files,
    assert_common_invariants,
    render_chart,
    render_failure,
    values_file,
)

_BODY = "nginx.ingress.kubernetes.io/proxy-body-size"
_READ = "nginx.ingress.kubernetes.io/proxy-read-timeout"
_SEND = "nginx.ingress.kubernetes.io/proxy-send-timeout"
_BUFFERING = "nginx.ingress.kubernetes.io/proxy-buffering"
_HEADERS = "nginx.ingress.kubernetes.io/custom-headers"
_ISSUER = "cert-manager.io/cluster-issuer"


def _ingresses(objects: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {obj["metadata"]["name"]: obj for obj in objects if obj["kind"] == "Ingress"}


def _backend(ingress: dict[str, Any]) -> tuple[str, str, str, str]:
    rule = ingress["spec"]["rules"][0]
    path = rule["http"]["paths"][0]
    service = path["backend"]["service"]
    return rule["host"], path["path"], service["name"], service["port"]["name"]


def test_ingress_is_off_by_default() -> None:
    objects = render_chart()
    assert _ingresses(objects) == {}
    assert not any(obj["metadata"]["name"].endswith("-ingress-headers") for obj in objects)


@pytest.mark.parametrize("path", all_values_files(), ids=lambda path: path.rsplit("/", 1)[-1])
def test_ingress_renders_with_every_values_file(path: str) -> None:
    objects = render_chart([path], {"mcp.enabled": "true"})
    assert_common_invariants(objects)
    ingresses = _ingresses(objects)
    assert sorted(ingresses) == ["rudix-api", "rudix-frontend", "rudix-mcp"]
    for name, ingress in ingresses.items():
        spec = ingress["spec"]
        assert spec["ingressClassName"] == "nginx"
        host, _, service, port = _backend(ingress)
        assert host.endswith(".invalid")
        assert service == name and port == "http"
        assert spec["tls"] == [{"hosts": [host], "secretName": spec["tls"][0]["secretName"]}]
        assert spec["tls"][0]["secretName"]
        assert ingress["metadata"]["annotations"][_BODY] == "26m"


def test_app_api_and_mcp_routes() -> None:
    objects = render_chart([values_file("values-production.yaml")], {"mcp.enabled": "true"})
    ingresses = _ingresses(objects)
    assert _backend(ingresses["rudix-frontend"]) == (
        "app.rudix.invalid",
        "/",
        "rudix-frontend",
        "http",
    )
    assert _backend(ingresses["rudix-api"]) == ("api.rudix.invalid", "/", "rudix-api", "http")
    # Without its own host, MCP shares the API host and certificate under /mcp.
    assert _backend(ingresses["rudix-mcp"]) == ("api.rudix.invalid", "/mcp", "rudix-mcp", "http")
    assert ingresses["rudix-mcp"]["spec"]["tls"][0]["secretName"] == "rudix-production-api-tls"
    assert ingresses["rudix-frontend"]["spec"]["tls"][0]["secretName"] == (
        "rudix-production-app-tls"
    )


def test_mcp_ingress_needs_mcp_enabled() -> None:
    objects = render_chart([values_file("values-staging.yaml")])
    assert sorted(_ingresses(objects)) == ["rudix-api", "rudix-frontend"]


def test_streaming_annotations_only_on_api_and_mcp() -> None:
    objects = render_chart([values_file("values-staging.yaml")], {"mcp.enabled": "true"})
    ingresses = _ingresses(objects)
    for name in ("rudix-api", "rudix-mcp"):
        annotations = ingresses[name]["metadata"]["annotations"]
        assert annotations[_READ] == annotations[_SEND] == "3600"
        assert annotations[_BUFFERING] == "off"
    frontend = ingresses["rudix-frontend"]["metadata"]["annotations"]
    assert not {_READ, _SEND, _BUFFERING} & set(frontend)


def test_cert_manager_annotation_only_with_an_issuer() -> None:
    staging = _ingresses(render_chart([values_file("values-staging.yaml")]))
    assert all(_ISSUER not in obj["metadata"]["annotations"] for obj in staging.values())
    ci = _ingresses(render_chart([values_file("ci/all-features-values.yaml")]))
    assert all(obj["metadata"]["annotations"][_ISSUER] == "ci-issuer" for obj in ci.values())
    assert all(
        obj["metadata"]["annotations"]["example.invalid/ci"] == "true" for obj in ci.values()
    )


def test_noindex_on_staging_not_production() -> None:
    staging = render_chart([values_file("values-staging.yaml")])
    headers = next(obj for obj in staging if obj["metadata"]["name"] == "rudix-ingress-headers")
    assert headers["kind"] == "ConfigMap"
    assert headers["data"] == {"X-Robots-Tag": "noindex, nofollow"}
    for ingress in _ingresses(staging).values():
        assert ingress["metadata"]["annotations"][_HEADERS] == "rudix/rudix-ingress-headers"
    production = render_chart([values_file("values-production.yaml")])
    assert not any(obj["metadata"]["name"] == "rudix-ingress-headers" for obj in production)
    for ingress in _ingresses(production).values():
        assert _HEADERS not in ingress["metadata"]["annotations"]


def test_mcp_own_host_uses_its_own_certificate() -> None:
    objects = render_chart([values_file("ci/all-features-values.yaml")], {"mcp.enabled": "true"})
    mcp = _ingresses(objects)["rudix-mcp"]
    assert _backend(mcp)[0] == "mcp.ci.rudix.invalid"
    assert mcp["spec"]["tls"][0]["secretName"] == "rudix-ci-mcp-tls"


@pytest.mark.parametrize(
    ("set_values", "message"),
    [
        ({"ingress.enabled": "true", "ingress.app.host": ""}, "ingress host for frontend"),
        (
            {"ingress.enabled": "true", "ingress.api.tlsSecretName": ""},
            "ingress TLS secret name for api is required",
        ),
    ],
)
def test_invalid_ingress_values_fail(set_values: dict[str, str], message: str) -> None:
    assert message in render_failure(set_values=set_values)
