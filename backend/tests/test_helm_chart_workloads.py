"""Helm chart workloads (0.8.0, C1): Deployments, Services, PDBs, probes, resources, shutdown
budget, rollout, the single beat, the migrate hook Job, and the connection budget."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.workers.pools import POOL_NAMES
from tests.helm_support import (
    all_values_files,
    assert_common_invariants,
    containers,
    pod_specs,
    render_chart,
    render_failure,
    values_file,
)

CI_VALUES = values_file("ci/all-features-values.yaml")
WEB = ("frontend", "api", "mcp")
WORKERS = tuple(f"worker-{name}" for name in POOL_NAMES)
PING = "celery -A app.workers.celery_app:celery_app inspect ping -d {pool}@$HOSTNAME --timeout 10"


def _render_cases() -> list[tuple[str, list[str]]]:
    cases: list[tuple[str, list[str]]] = [("defaults", [])]
    cases.extend((Path(path).name, [path]) for path in all_values_files())
    return cases


def _by_kind(objects: list[dict[str, Any]], kind: str) -> dict[str, dict[str, Any]]:
    return {obj["metadata"]["name"]: obj for obj in objects if obj["kind"] == kind}


def _component(obj: dict[str, Any]) -> str:
    return str(obj["metadata"]["labels"]["app.kubernetes.io/component"])


def _workloads(objects: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        _component(obj): obj
        for obj in objects
        if obj["kind"] in ("Deployment", "Job") and pod_specs(obj)
    }


def _container(obj: dict[str, Any]) -> dict[str, Any]:
    found = containers(obj)
    assert len(found) == 1, f"{obj['metadata']['name']}: expected one container"
    return found[0]


def _env(container: dict[str, Any]) -> dict[str, Any]:
    return {item["name"]: item for item in container.get("env") or []}


def _write(tmp_path: Path, text: str) -> str:
    path = tmp_path / "override.yaml"
    path.write_text(text)
    return str(path)


@pytest.mark.parametrize(("label", "files"), _render_cases(), ids=lambda case: str(case))
def test_every_values_file_renders_the_workloads(label: str, files: list[str]) -> None:
    objects = render_chart(files)
    assert_common_invariants(objects)
    deployments = _by_kind(objects, "Deployment")
    expected = {"rudix-frontend", "rudix-api", "rudix-beat"}
    expected |= {f"rudix-{name}" for name in WORKERS}
    assert expected <= set(deployments), sorted(deployments)
    assert ("rudix-mcp" in deployments) == (label == "all-features-values.yaml")
    jobs = _by_kind(objects, "Job")
    assert list(jobs) == ["rudix-migrate"]
    services = _by_kind(objects, "Service")
    assert {"rudix-frontend", "rudix-api"} <= set(services)
    for service in services.values():
        assert service["spec"]["type"] == "ClusterIP"


@pytest.mark.parametrize(("label", "files"), _render_cases(), ids=lambda case: str(case))
def test_every_container_has_resources_security_context_and_tmp(
    label: str, files: list[str]
) -> None:
    for component, workload in _workloads(render_chart(files)).items():
        spec = pod_specs(workload)[0]
        assert spec["automountServiceAccountToken"] is False, component
        assert spec["securityContext"]["runAsNonRoot"] is True, component
        assert "hostNetwork" not in spec
        for container in containers(workload):
            resources = container["resources"]
            for section in ("requests", "limits"):
                assert {"cpu", "memory"} <= set(resources[section]), (component, section)
            security = container["securityContext"]
            assert security["readOnlyRootFilesystem"] is True, component
            assert security["allowPrivilegeEscalation"] is False, component
            assert security["capabilities"] == {"drop": ["ALL"]}, component
            assert {"name": "tmp", "mountPath": "/tmp"} in container["volumeMounts"]
            for port in container.get("ports") or []:
                assert "hostPort" not in port, component


def test_web_containers_ports_commands_and_probes() -> None:
    workloads = _workloads(render_chart([CI_VALUES]))
    api = _container(workloads["api"])
    assert api["command"] == ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
    assert "--workers" not in api["command"]
    assert api["ports"] == [{"name": "http", "containerPort": 8000, "protocol": "TCP"}]
    assert api["readinessProbe"]["httpGet"] == {"path": "/api/v1/ready", "port": "http"}
    assert api["livenessProbe"]["httpGet"] == {"path": "/api/v1/health", "port": "http"}
    assert api["startupProbe"]["httpGet"] == {"path": "/api/v1/health", "port": "http"}

    frontend = _container(workloads["frontend"])
    assert frontend["ports"][0] == {"name": "http", "containerPort": 3000, "protocol": "TCP"}
    for probe in ("startupProbe", "readinessProbe", "livenessProbe"):
        assert frontend[probe]["httpGet"] == {"path": "/robots.txt", "port": "http"}
    assert _env(frontend)["HOSTNAME"]["value"] == "0.0.0.0"
    assert frontend["envFrom"] == [
        {"configMapRef": {"name": "rudix-config"}},
        {"secretRef": {"name": "rudix-ci-app-env"}},
        {"configMapRef": {"name": "rudix-frontend"}},
    ]
    assert {"name": "next-cache", "mountPath": "/app/.next/cache"} in frontend["volumeMounts"]
    volumes = {v["name"]: v for v in pod_specs(workloads["frontend"])[0]["volumes"]}
    assert "emptyDir" in volumes["next-cache"]

    mcp = _container(workloads["mcp"])
    assert mcp["command"] == [
        "python",
        "-m",
        "app.mcp.main",
        "--transport",
        "streamable_http",
    ]
    assert mcp["ports"][0] == {"name": "http", "containerPort": 8010, "protocol": "TCP"}
    assert mcp["readinessProbe"]["httpGet"] == {"path": "/health", "port": "http"}
    assert _env(mcp)["MCP_HTTP_PORT"]["value"] == "8010"


def test_readiness_scope_is_set_for_the_api_probe() -> None:
    for files in ([], *([path] for path in all_values_files())):
        objects = render_chart(files)
        config = _by_kind(objects, "ConfigMap")["rudix-config"]
        assert config["data"]["READINESS_REQUIRED_DEPENDENCIES"] == "postgres,redis"


def test_worker_pools_commands_probes_metrics_port_and_grace() -> None:
    workloads = _workloads(render_chart([CI_VALUES]))
    for name in POOL_NAMES:
        workload = workloads[f"worker-{name}"]
        container = _container(workload)
        assert container["command"] == ["python", "-m", "app.workers.pools", name]
        assert container["ports"] == [{"name": "metrics", "containerPort": 9808, "protocol": "TCP"}]
        for probe in ("startupProbe", "readinessProbe", "livenessProbe"):
            command = container[probe]["exec"]["command"]
            assert command[:2] == ["sh", "-c"]
            assert command[2].startswith(PING.format(pool=name))
            assert container[probe]["timeoutSeconds"] >= 15
        assert container["livenessProbe"]["periodSeconds"] >= 30
        env = _env(container)
        assert env["WORKER_METRICS_ENABLED"]["value"] == "true"
        assert env[f"WORKER_POOL_{name.upper()}_CONCURRENCY"]["value"].isdigit()
        assert pod_specs(workload)[0]["terminationGracePeriodSeconds"] == 120
    ingest = _container(workloads["worker-ingest"])
    assert ingest["resources"]["requests"] == {"cpu": "1", "memory": "2Gi"}


def test_worker_metrics_port_only_when_metrics_enabled() -> None:
    objects = render_chart()
    for name in POOL_NAMES:
        container = _container(_workloads(objects)[f"worker-{name}"])
        assert "ports" not in container
        assert "WORKER_METRICS_ENABLED" not in _env(container)
    services = _by_kind(objects, "Service")
    assert not any(name.startswith("rudix-worker-") for name in services)
    services = _by_kind(render_chart([CI_VALUES]), "Service")
    for name in POOL_NAMES:
        port = services[f"rudix-worker-{name}"]["spec"]["ports"][0]
        assert port == {"name": "metrics", "port": 9808, "targetPort": "metrics", "protocol": "TCP"}


def test_graceful_shutdown_budget_for_the_api() -> None:
    workloads = _workloads(render_chart())
    spec = pod_specs(workloads["api"])[0]
    api = _container(workloads["api"])
    assert spec["terminationGracePeriodSeconds"] == 60
    assert api["lifecycle"]["preStop"]["exec"]["command"] == ["sleep", "10"]
    env = _env(api)
    assert env["UVICORN_TIMEOUT_GRACEFUL_SHUTDOWN"]["value"] == "30"
    assert env["API_SHUTDOWN_DRAIN_SECONDS"]["value"] == "15"
    assert 10 + 30 + 15 + 5 <= spec["terminationGracePeriodSeconds"]
    frontend = pod_specs(workloads["frontend"])[0]
    assert frontend["terminationGracePeriodSeconds"] == 30
    assert "preStop" in frontend["containers"][0]["lifecycle"]
    assert pod_specs(workloads["beat"])[0]["terminationGracePeriodSeconds"] == 10


@pytest.mark.parametrize(
    ("set_values", "message"),
    [
        ({"api.drainSeconds": "20"}, "exceeds terminationGracePeriodSeconds 60"),
        ({"api.terminationGracePeriodSeconds": "40"}, "exceeds terminationGracePeriodSeconds 40"),
        ({"frontend.preStopSleepSeconds": "30"}, "frontend preStopSleepSeconds must be below"),
        ({"beat.replicas": "2"}, "beat.replicas must be 1"),
        ({"beat.replicas": "0"}, "beat.replicas must be 1"),
    ],
)
def test_broken_budgets_fail_the_render(set_values: dict[str, str], message: str) -> None:
    assert message in render_failure(set_values=set_values)


@pytest.mark.parametrize(("label", "files"), _render_cases(), ids=lambda case: str(case))
def test_rolling_updates_never_reduce_availability(label: str, files: list[str]) -> None:
    deployments = _by_kind(render_chart(files), "Deployment")
    for name, deployment in deployments.items():
        spec = deployment["spec"]
        if name == "rudix-beat":
            assert spec["strategy"] == {"type": "Recreate"}
            assert spec["replicas"] == 1
            continue
        rolling = spec["strategy"]["rollingUpdate"]
        assert spec["strategy"]["type"] == "RollingUpdate"
        assert rolling["maxUnavailable"] == 0, name
        expected_surge = 1 if name.startswith("rudix-worker-") else "25%"
        assert rolling["maxSurge"] == expected_surge, name
        assert spec["minReadySeconds"] > 0
        assert spec["revisionHistoryLimit"] > 0


def test_replicas_and_spread_across_nodes() -> None:
    deployments = _by_kind(render_chart([values_file("values-production.yaml")]), "Deployment")
    assert deployments["rudix-api"]["spec"]["replicas"] == 3
    assert deployments["rudix-frontend"]["spec"]["replicas"] == 3
    assert deployments["rudix-worker-ingest"]["spec"]["replicas"] == 2
    defaults = _by_kind(render_chart(), "Deployment")
    assert defaults["rudix-api"]["spec"]["replicas"] == 2
    assert defaults["rudix-frontend"]["spec"]["replicas"] == 2
    for name in POOL_NAMES:
        assert defaults[f"rudix-worker-{name}"]["spec"]["replicas"] == 1
    for name in ("rudix-api", "rudix-frontend"):
        pod = defaults[name]["spec"]["template"]["spec"]
        anti = pod["affinity"]["podAntiAffinity"]
        assert "preferredDuringSchedulingIgnoredDuringExecution" in anti
        assert "requiredDuringSchedulingIgnoredDuringExecution" not in anti
        spread = pod["topologySpreadConstraints"][0]
        assert spread["whenUnsatisfiable"] == "ScheduleAnyway"
        assert spread["topologyKey"] == "kubernetes.io/hostname"
        component = name.removeprefix("rudix-")
        assert spread["labelSelector"]["matchLabels"]["app.kubernetes.io/component"] == component


def test_pod_disruption_budgets_cover_web_tiers_but_never_beat() -> None:
    pdbs = _by_kind(render_chart([CI_VALUES]), "PodDisruptionBudget")
    # all-features also turns on the PgBouncer pooler (C2), which has two replicas.
    assert sorted(pdbs) == sorted(f"rudix-{name}" for name in (*WEB, "pgbouncer"))
    for name, pdb in pdbs.items():
        assert pdb["spec"]["maxUnavailable"] == 1
        selector = pdb["spec"]["selector"]["matchLabels"]
        assert selector["app.kubernetes.io/component"] == name.removeprefix("rudix-")
    assert sorted(_by_kind(render_chart(), "PodDisruptionBudget")) == [
        "rudix-api",
        "rudix-frontend",
    ]
    hpa = values_file("ci/hpa-values.yaml")
    assert _by_kind(render_chart([hpa]), "PodDisruptionBudget") == {}


def test_beat_is_single_recreate_without_probe_pdb_or_autoscaler() -> None:
    for files in ([], [CI_VALUES], [values_file("ci/hpa-values.yaml")]):
        objects = render_chart(files)
        beat = _by_kind(objects, "Deployment")["rudix-beat"]
        assert beat["spec"]["replicas"] == 1
        assert beat["spec"]["strategy"] == {"type": "Recreate"}
        container = _container(beat)
        assert container["command"][:4] == [
            "celery",
            "-A",
            "app.workers.celery_app:celery_app",
            "beat",
        ]
        assert "/tmp/celerybeat-schedule" in container["command"]
        for probe in ("startupProbe", "readinessProbe", "livenessProbe"):
            assert probe not in container
        for obj in objects:
            if obj["kind"] in ("PodDisruptionBudget", "HorizontalPodAutoscaler", "ScaledObject"):
                assert _component(obj) != "beat", obj["metadata"]["name"]
                target = (obj["spec"].get("scaleTargetRef") or {}).get("name")
                assert target != "rudix-beat"


def test_migrate_job_is_a_pre_install_and_pre_upgrade_hook() -> None:
    objects = render_chart([CI_VALUES])
    job = _by_kind(objects, "Job")["rudix-migrate"]
    annotations = job["metadata"]["annotations"]
    assert annotations["helm.sh/hook"] == "pre-install,pre-upgrade"
    assert annotations["helm.sh/hook-delete-policy"] == "before-hook-creation"
    weight = int(annotations["helm.sh/hook-weight"])
    assert job["spec"]["backoffLimit"] == 0
    assert job["spec"]["activeDeadlineSeconds"] > 0
    spec = pod_specs(job)[0]
    assert spec["restartPolicy"] == "Never"
    assert spec["automountServiceAccountToken"] is False
    container = _container(job)
    script = container["command"][-1]
    steps = [
        "alembic upgrade head",
        "python -m app.clients.qdrant_bootstrap",
        "python scripts/run_graph_migrations.py",
    ]
    positions = [script.index(step) for step in steps]
    assert positions == sorted(positions)
    assert container["command"][:2] == ["sh", "-ec"]
    assert _env(container)["DATABASE_URL"]["valueFrom"] == {
        "secretKeyRef": {"name": "rudix-ci-app-env", "key": "DATABASE_MIGRATION_URL"}
    }
    # Hooks run before the release's objects exist: the Job's ConfigMap and ServiceAccount
    # are hooks too and are created first.
    assert container["envFrom"][0] == {"configMapRef": {"name": "rudix-migrate"}}
    assert spec["serviceAccountName"] == "rudix-migrate"
    for kind in ("ConfigMap", "ServiceAccount"):
        hook = _by_kind(objects, kind)["rudix-migrate"]["metadata"]["annotations"]
        assert hook["helm.sh/hook"] == "pre-install,pre-upgrade"
        assert int(hook["helm.sh/hook-weight"]) < weight
    config = _by_kind(objects, "ConfigMap")
    assert config["rudix-migrate"]["data"] == config["rudix-config"]["data"]


def test_migrate_job_without_migration_url_and_the_missing_secret_check() -> None:
    job = _by_kind(render_chart(), "Job")["rudix-migrate"]
    assert "env" not in _container(job)
    message = render_failure(set_values={"migrations.useMigrationUrl": "true"})
    assert "migrations.useMigrationUrl needs secrets.existingSecret" in message


def test_connection_budget_annotation_and_formula() -> None:
    api = _by_kind(render_chart(), "Deployment")["rudix-api"]
    worst = int(api["metadata"]["annotations"]["rudix.io/database-connections-worst-case"])
    per_process = 5 + 10
    # api: (2 replicas + 25% surge rounded up) x per process; workers: (replicas + surge 1)
    # x (concurrency + main process) x per process; beat one process; migrate one (NullPool).
    concurrency = {"ingest": 2, "graph": 2, "sync": 2, "eval": 1, "default": 2}
    workers = sum((1 + 1) * (value + 1) * per_process for value in concurrency.values())
    assert worst == (2 + 1) * per_process + workers + per_process + 1


def test_connection_budget_uses_autoscaling_maximum_and_pool_settings(tmp_path: Path) -> None:
    override = _write(
        tmp_path,
        "config:\n  env:\n    DB_POOL_SIZE: 2\n    DB_MAX_OVERFLOW: 1\n"
        "autoscaling:\n  enabled: true\n  mode: hpa\n  api:\n    maxReplicas: 8\n",
    )
    api = _by_kind(render_chart([override]), "Deployment")["rudix-api"]
    worst = int(api["metadata"]["annotations"]["rudix.io/database-connections-worst-case"])
    per_process = 3
    concurrency = {"ingest": 2, "graph": 2, "sync": 2, "eval": 1, "default": 2}
    workers = sum(2 * (value + 1) * per_process for value in concurrency.values())
    assert worst == (8 + 2) * per_process + workers + per_process + 1
    assert "replicas" not in api["spec"]


def test_connection_budget_fails_when_exceeded() -> None:
    message = render_failure(set_values={"connectionBudget.maxDatabaseConnections": "100"})
    assert "worst-case database connections 481 exceed" in message
    assert "connectionBudget.maxDatabaseConnections 100" in message
    objects = render_chart(set_values={"connectionBudget.maxDatabaseConnections": "481"})
    assert _by_kind(objects, "Deployment")["rudix-api"]
