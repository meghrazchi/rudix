"""Helm chart network policies (0.8.0, C1): default deny, explicit allows, data stores reachable
only from application pods, optional egress restriction."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.workers.pools import POOL_NAMES
from tests.helm_support import (
    NAMESPACE,
    assert_common_invariants,
    render_chart,
    values_file,
)

CI_VALUES = values_file("ci/all-features-values.yaml")
RELEASE_SELECTOR = {"app.kubernetes.io/name": "rudix", "app.kubernetes.io/instance": "rudix"}
DATA_CLIENTS = {"api", "mcp", "beat", "migrate"} | {f"worker-{name}" for name in POOL_NAMES}


def _policies(objects: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {o["metadata"]["name"]: o for o in objects if o["kind"] == "NetworkPolicy"}


def _component_selector(policy: dict[str, Any]) -> str | None:
    labels = policy["spec"]["podSelector"].get("matchLabels") or {}
    return labels.get("app.kubernetes.io/component")


def _in_values(selector: dict[str, Any]) -> set[str]:
    expressions = selector.get("matchExpressions") or []
    assert len(expressions) == 1
    assert expressions[0]["key"] == "app.kubernetes.io/component"
    assert expressions[0]["operator"] == "In"
    return set(expressions[0]["values"])


def test_default_deny_ingress_for_every_pod_of_the_release() -> None:
    for files in (
        [],
        [values_file("values-staging.yaml")],
        [values_file("values-production.yaml")],
    ):
        policies = _policies(render_chart(files))
        deny = policies["rudix-default-deny"]
        assert deny["spec"]["podSelector"] == {"matchLabels": RELEASE_SELECTOR}
        assert deny["spec"]["policyTypes"] == ["Ingress"]
        assert "ingress" not in deny["spec"]
        assert "rudix-allow-egress" not in policies


def test_every_pod_template_is_selected_by_the_default_deny() -> None:
    objects = render_chart([CI_VALUES])
    for obj in objects:
        template = (obj.get("spec") or {}).get("template") or {}
        labels = (template.get("metadata") or {}).get("labels")
        if labels is None:
            continue
        assert RELEASE_SELECTOR.items() <= labels.items(), obj["metadata"]["name"]


def test_ingress_controller_reaches_only_frontend_api_and_mcp() -> None:
    objects = render_chart([CI_VALUES])
    assert_common_invariants(objects)
    policies = _policies(objects)
    allowed = {
        _component_selector(policy): policy
        for name, policy in policies.items()
        if name.endswith("-from-ingress")
    }
    assert set(allowed) == {"frontend", "api", "mcp"}
    for policy in allowed.values():
        rule = policy["spec"]["ingress"][0]
        assert rule["from"] == [
            {"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "ingress-nginx"}}}
        ]
        assert rule["ports"] == [{"port": "http", "protocol": "TCP"}]
    defaults = _policies(render_chart())
    assert "rudix-mcp-from-ingress" not in defaults
    assert "rudix-api-from-frontend" not in defaults


def test_frontend_to_api_when_enabled() -> None:
    policy = _policies(render_chart([CI_VALUES]))["rudix-api-from-frontend"]
    assert _component_selector(policy) == "api"
    source = policy["spec"]["ingress"][0]["from"][0]["podSelector"]["matchLabels"]
    assert source["app.kubernetes.io/component"] == "frontend"


def test_monitoring_reaches_metrics_ports_only_when_metrics_enabled() -> None:
    assert not any("monitoring" in name for name in _policies(render_chart()))
    policies = _policies(render_chart([CI_VALUES]))
    web = policies["rudix-metrics-from-monitoring"]["spec"]
    # mcp is enabled in the CI values but serves no /metrics: its port stays closed.
    assert _in_values(web["podSelector"]) == {"api"}
    assert web["ingress"][0]["ports"] == [{"port": "http", "protocol": "TCP"}]
    workers = policies["rudix-worker-metrics-from-monitoring"]["spec"]
    assert _in_values(workers["podSelector"]) == {f"worker-{name}" for name in POOL_NAMES}
    assert workers["ingress"][0]["ports"] == [{"port": "metrics", "protocol": "TCP"}]
    source = workers["ingress"][0]["from"][0]["namespaceSelector"]["matchLabels"]
    assert source == {"kubernetes.io/metadata.name": "monitoring"}


def test_data_stores_accept_only_application_pods() -> None:
    assert not any("datastore" in name for name in _policies(render_chart()))
    policies = _policies(render_chart([CI_VALUES]))
    postgres = policies["rudix-datastore-postgres"]
    assert postgres["metadata"]["namespace"] == NAMESPACE
    assert postgres["spec"]["podSelector"] == {"matchLabels": {"example.invalid/app": "postgres"}}
    assert postgres["spec"]["policyTypes"] == ["Ingress"]
    rule = postgres["spec"]["ingress"][0]
    assert rule["ports"] == [{"port": 5432, "protocol": "TCP"}]
    (source,) = rule["from"]
    assert source["podSelector"]["matchLabels"] == RELEASE_SELECTOR
    clients = _in_values(source["podSelector"])
    assert DATA_CLIENTS <= clients
    assert {"frontend", "networkpolicy"}.isdisjoint(clients)
    assert all(c in DATA_CLIENTS or c.startswith("backup-") for c in clients)
    assert "namespaceSelector" not in source

    redis = policies["rudix-datastore-redis"]
    assert redis["metadata"]["namespace"] == "data"
    (source,) = redis["spec"]["ingress"][0]["from"]
    # Another namespace: the source pods must also be in the release namespace (same entry).
    assert source["namespaceSelector"] == {
        "matchLabels": {"kubernetes.io/metadata.name": NAMESPACE}
    }


def test_data_store_entries_need_name_selector_and_ports(tmp_path: Path) -> None:
    override = tmp_path / "bad.yaml"
    override.write_text("networkPolicy:\n  dataStores:\n    - name: qdrant\n      ports: []\n")
    try:
        render_chart([str(override)])
    except AssertionError as exc:
        assert "networkPolicy.dataStores qdrant needs a podSelector" in str(exc)
    else:  # pragma: no cover - the render must fail
        raise AssertionError("render succeeded without a podSelector")


def test_egress_restriction_is_optional() -> None:
    policies = _policies(render_chart([CI_VALUES]))
    assert policies["rudix-default-deny"]["spec"]["policyTypes"] == ["Ingress", "Egress"]
    egress = policies["rudix-allow-egress"]["spec"]
    assert egress["podSelector"] == {"matchLabels": RELEASE_SELECTOR}
    dns, internal, extra = egress["egress"]
    assert {p["port"] for p in dns["ports"]} == {53}
    assert dns["to"][0]["namespaceSelector"]["matchLabels"] == {
        "kubernetes.io/metadata.name": "kube-system"
    }
    assert internal == {"to": [{"podSelector": {"matchLabels": RELEASE_SELECTOR}}]}
    assert extra["to"][0]["ipBlock"]["cidr"] == "192.0.2.0/24"


def test_network_policies_can_be_disabled() -> None:
    assert _policies(render_chart([values_file("ci/hpa-values.yaml")])) == {}
