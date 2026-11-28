"""Helm chart database values and the optional PgBouncer pooler (0.8.0, C2, R08-04)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.helm_support import (
    CHART_DIR,
    all_values_files,
    assert_common_invariants,
    containers,
    pod_specs,
    render_chart,
    render_failure,
    values_file,
)

CI_VALUES = values_file("ci/all-features-values.yaml")
IMAGE = "registry.invalid/pgbouncer@sha256:" + "0" * 64
POOLER_ON: dict[str, Any] = {
    "pgbouncer.enabled": True,
    "pgbouncer.image": IMAGE,
    "pgbouncer.configSecretName": "pgbouncer-config",
    "database.pgbouncerMode": True,
    "config.env.DB_PGBOUNCER_MODE": "true",
    "secrets.existingSecret": "app-env",
    "migrations.useMigrationUrl": True,
}
REPLICA_ENV = {
    "DB_PGBOUNCER_MODE",
    "DB_REPLICA_MAX_LAG_SECONDS",
    "DB_REPLICA_LAG_CHECK_INTERVAL_SECONDS",
    "DB_REPLICA_LAG_QUERY_TIMEOUT_MS",
}


def _by_kind(objects: list[dict[str, Any]], kind: str) -> dict[str, dict[str, Any]]:
    return {obj["metadata"]["name"]: obj for obj in objects if obj["kind"] == kind}


def _config(objects: list[dict[str, Any]]) -> dict[str, str]:
    return _by_kind(objects, "ConfigMap")["rudix-config"]["data"]


def _values(tmp_path: Path, flat: dict[str, Any]) -> list[str]:
    """A typed values file from dotted keys (``--set-string`` would make false truthy)."""
    tree: dict[str, Any] = {}
    for dotted, value in flat.items():
        node = tree
        *parents, leaf = dotted.split(".")
        for parent in parents:
            node = node.setdefault(parent, {})
        node[leaf] = value
    path = tmp_path / f"override-{len(list(tmp_path.iterdir()))}.yaml"
    path.write_text(yaml.safe_dump(tree))
    return [str(path)]


def test_defaults_render_no_pooler_and_replica_settings_in_config() -> None:
    objects = render_chart()
    assert_common_invariants(objects)
    assert not any("pgbouncer" in obj["metadata"]["name"] for obj in objects)
    config = _config(objects)
    assert REPLICA_ENV <= set(config)
    assert config["DB_PGBOUNCER_MODE"] == "false"
    assert config["DB_REPLICA_MAX_LAG_SECONDS"] == "30"
    # Connection strings come only from the Secret; the ConfigMap never holds one.
    assert not any(key.startswith("DATABASE_") for key in config)


@pytest.mark.parametrize("path", all_values_files(), ids=lambda path: Path(path).name)
def test_every_values_file_sets_the_replica_settings(path: str) -> None:
    assert REPLICA_ENV <= set(_config(render_chart([path])))


def test_database_values_hold_secret_key_names_only() -> None:
    values = yaml.safe_load((CHART_DIR / "values.yaml").read_text())
    database = values["database"]
    assert database["secretKeys"] == {
        "url": "DATABASE_URL",
        "replicaUrl": "DATABASE_REPLICA_URL",
        "migrationUrl": "DATABASE_MIGRATION_URL",
        "maintenanceUrl": "DATABASE_MAINTENANCE_URL",
    }
    assert database["pgbouncerMode"] is False
    assert values["pgbouncer"]["enabled"] is False
    assert values["pgbouncer"]["image"] == ""
    for name in ("values.yaml", "values-staging.yaml", "values-production.yaml"):
        text = (CHART_DIR / name).read_text()
        assert "postgresql://" not in text and "postgresql+asyncpg://" not in text, name


def test_pooler_renders_deployment_service_pdb_and_policy(tmp_path: Path) -> None:
    objects = render_chart(_values(tmp_path, POOLER_ON))
    assert_common_invariants(objects)
    deployment = _by_kind(objects, "Deployment")["rudix-pgbouncer"]
    spec = pod_specs(deployment)[0]
    assert spec["securityContext"]["runAsNonRoot"] is True
    assert spec["automountServiceAccountToken"] is False
    (container,) = containers(deployment)
    assert container["image"] == IMAGE
    assert container["ports"] == [{"name": "postgres", "containerPort": 6432, "protocol": "TCP"}]
    assert container["readinessProbe"]["tcpSocket"] == {"port": "postgres"}
    assert container["securityContext"]["readOnlyRootFilesystem"] is True
    assert {"name": "tmp", "mountPath": "/tmp"} in container["volumeMounts"]
    assert {"name": "config", "mountPath": "/etc/pgbouncer", "readOnly": True} in container[
        "volumeMounts"
    ]
    volumes = {volume["name"]: volume for volume in spec["volumes"]}
    assert volumes["config"]["secret"]["secretName"] == "pgbouncer-config"
    assert "envFrom" not in container and "env" not in container
    rolling = deployment["spec"]["strategy"]["rollingUpdate"]
    assert rolling["maxUnavailable"] == 0

    service = _by_kind(objects, "Service")["rudix-pgbouncer"]
    assert service["spec"]["type"] == "ClusterIP"
    assert service["spec"]["ports"][0]["name"] == "postgres"
    assert service["spec"]["ports"][0]["port"] == 6432

    pdb = _by_kind(objects, "PodDisruptionBudget")["rudix-pgbouncer"]
    assert pdb["spec"]["selector"]["matchLabels"]["app.kubernetes.io/component"] == "pgbouncer"

    policy = _by_kind(objects, "NetworkPolicy")["rudix-pgbouncer"]
    selector = policy["spec"]["podSelector"]["matchLabels"]
    assert selector["app.kubernetes.io/component"] == "pgbouncer"
    (rule,) = policy["spec"]["ingress"]
    assert rule["ports"] == [{"port": "postgres", "protocol": "TCP"}]
    (source,) = rule["from"]
    (expression,) = source["podSelector"]["matchExpressions"]
    clients = set(expression["values"])
    assert {"api", "mcp", "beat", "migrate", "worker-ingest"} <= clients
    assert {"frontend", "pgbouncer", "networkpolicy"}.isdisjoint(clients)
    assert "namespaceSelector" not in source


def test_single_pooler_replica_has_no_pdb_and_policy_follows_the_switch(
    tmp_path: Path,
) -> None:
    objects = render_chart(_values(tmp_path, {**POOLER_ON, "pgbouncer.replicas": 1}))
    assert "rudix-pgbouncer" not in _by_kind(objects, "PodDisruptionBudget")
    objects = render_chart(_values(tmp_path, {**POOLER_ON, "networkPolicy.enabled": False}))
    assert "rudix-pgbouncer" not in _by_kind(objects, "NetworkPolicy")
    assert "rudix-pgbouncer" in _by_kind(objects, "Deployment")


def test_pooler_may_reach_in_cluster_postgres() -> None:
    policies = _by_kind(render_chart([CI_VALUES]), "NetworkPolicy")
    postgres = policies["rudix-datastore-postgres"]
    (source,) = postgres["spec"]["ingress"][0]["from"]
    (expression,) = source["podSelector"]["matchExpressions"]
    assert "pgbouncer" in expression["values"]
    defaults = _by_kind(render_chart(), "NetworkPolicy")
    assert "rudix-pgbouncer" not in defaults


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"pgbouncer.image": ""}, "pgbouncer.image is required"),
        ({"pgbouncer.configSecretName": ""}, "pgbouncer.configSecretName is required"),
        (
            {"database.pgbouncerMode": False, "config.env.DB_PGBOUNCER_MODE": "false"},
            "pgbouncer.enabled needs database.pgbouncerMode",
        ),
        ({"config.env.DB_PGBOUNCER_MODE": "false"}, "database.pgbouncerMode must equal"),
        ({"migrations.useMigrationUrl": False}, "pgbouncer.enabled needs migrations"),
        ({"pgbouncer.replicas": 0}, "pgbouncer.replicas must be at least 1"),
    ],
)
def test_pooler_misconfiguration_fails_the_render(
    tmp_path: Path, overrides: dict[str, Any], message: str
) -> None:
    assert message in render_failure(_values(tmp_path, {**POOLER_ON, **overrides}))


def test_mode_mismatch_fails_without_the_pooler(tmp_path: Path) -> None:
    message = render_failure(_values(tmp_path, {"database.pgbouncerMode": True}))
    assert "database.pgbouncerMode must equal config.env.DB_PGBOUNCER_MODE" in message
    # A provider's pooler: mode on in both places, no chart pooler.
    objects = render_chart(
        _values(
            tmp_path,
            {"database.pgbouncerMode": True, "config.env.DB_PGBOUNCER_MODE": "true"},
        )
    )
    assert _config(objects)["DB_PGBOUNCER_MODE"] == "true"


def test_connection_budget_counts_the_pooler_server_side(tmp_path: Path) -> None:
    objects = render_chart(_values(tmp_path, POOLER_ON))
    deployments = _by_kind(objects, "Deployment")
    api = deployments["rudix-api"]
    database_side = int(api["metadata"]["annotations"]["rudix.io/database-connections-worst-case"])
    # (2 replicas + 25% surge rounded up) x (default_pool_size 20 + reserve 5) + migrate 1.
    assert database_side == (2 + 1) * (20 + 5) + 1
    pooler = deployments["rudix-pgbouncer"]
    clients = int(
        pooler["metadata"]["annotations"]["rudix.io/pooler-client-connections-worst-case"]
    )
    # Without the pooler the same application side is the database side (C1 formula).
    direct = render_chart()
    direct_api = _by_kind(direct, "Deployment")["rudix-api"]
    assert clients == int(
        direct_api["metadata"]["annotations"]["rudix.io/database-connections-worst-case"]
    )
    # The database limit now applies to the pooler's server connections only.
    budget = "connectionBudget.maxDatabaseConnections"
    objects = render_chart(_values(tmp_path, {**POOLER_ON, budget: 76}))
    assert "rudix-pgbouncer" in _by_kind(objects, "Deployment")
    message = render_failure(_values(tmp_path, {**POOLER_ON, budget: 75}))
    assert "worst-case database connections 76 exceed" in message


def test_pooler_client_limit_is_checked(tmp_path: Path) -> None:
    limits = {"pgbouncer.replicas": 1, "pgbouncer.maxClientConnections": 100}
    message = render_failure(_values(tmp_path, {**POOLER_ON, **limits}))
    assert "worst-case pooler client connections" in message
    assert "pgbouncer.maxClientConnections 100" in message


def test_all_features_renders_the_pooler() -> None:
    objects = render_chart([CI_VALUES])
    assert "rudix-pgbouncer" in _by_kind(objects, "Deployment")
    assert _config(objects)["DB_PGBOUNCER_MODE"] == "true"
