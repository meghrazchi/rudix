"""Deploy configs of the observability stack (R08-09): authenticated scrape, Alertmanager
routes with file-based receivers, Compose overlay, and the CI steps that check them."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from tests import metrics_support

metrics_support.ensure_env()  # the autouse conftest fixtures load settings

REPO_ROOT = Path(__file__).resolve().parents[2]
OBSERVABILITY = REPO_ROOT / "infra" / "observability"
TOKEN_FILE = "/etc/prometheus/secrets/metrics_token"
POOLS = ("ingest", "graph", "sync", "eval", "default")


class _ComposeLoader(yaml.SafeLoader):
    """Accepts the Compose merge tags (!reset, !override) as plain values."""


def _tagged(loader: yaml.SafeLoader, node: yaml.Node) -> Any:
    if isinstance(node, yaml.SequenceNode):
        return {"tag": node.tag, "value": loader.construct_sequence(node)}
    if isinstance(node, yaml.MappingNode):
        return {"tag": node.tag, "value": loader.construct_mapping(node)}
    return {"tag": node.tag, "value": loader.construct_scalar(node)}  # type: ignore[arg-type]


_ComposeLoader.add_constructor("!reset", _tagged)
_ComposeLoader.add_constructor("!override", _tagged)


def _load(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text())


def _jobs(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {job["job_name"]: job for job in config["scrape_configs"]}


def test_prometheus_deploy_scrapes_app_jobs_with_the_token_file() -> None:
    dev = _load(OBSERVABILITY / "prometheus" / "prometheus.yml")
    deploy = _load(OBSERVABILITY / "prometheus" / "prometheus.deploy.yml")
    assert deploy["rule_files"] == dev["rule_files"]
    assert deploy["alerting"] == dev["alerting"]
    assert deploy["global"] == dev["global"]
    dev_jobs, deploy_jobs = _jobs(dev), _jobs(deploy)
    assert set(deploy_jobs) == set(dev_jobs)
    for name, job in deploy_jobs.items():
        if name in ("rudix-api", "rudix-worker"):
            assert job["authorization"] == {"type": "Bearer", "credentials_file": TOKEN_FILE}
        else:
            assert "authorization" not in job
            assert job == dev_jobs[name]
    [workers] = deploy_jobs["rudix-worker"]["static_configs"]
    assert workers["targets"] == [f"worker-{pool}:9808" for pool in POOLS]
    assert "worker:9808" in dev_jobs["rudix-worker"]["static_configs"][0]["targets"]


def test_dev_alertmanager_keeps_its_null_receiver() -> None:
    dev = _load(OBSERVABILITY / "alertmanager" / "alertmanager.yml")
    assert dev["route"]["receiver"] == "default-receiver"
    assert dev["receivers"] == [{"name": "default-receiver"}]
    assert "routes" not in dev["route"]


def test_deploy_alertmanager_routes_by_severity_to_file_receivers() -> None:
    config = _load(OBSERVABILITY / "alertmanager" / "alertmanager.deploy.yml")
    routes = {tuple(r["matchers"]): r for r in config["route"]["routes"]}
    assert routes[('severity="critical"',)]["receiver"] == "oncall-pager"
    assert routes[('severity="warning"',)]["receiver"] == "oncall-ticket"
    for route in routes.values():
        assert route["repeat_interval"]
    receivers = {r["name"]: r for r in config["receivers"]}
    assert set(receivers) == {"oncall-pager", "oncall-ticket"}
    assert receivers["oncall-pager"]["webhook_configs"][0]["url_file"] == (
        "/etc/alertmanager/secrets/oncall_pager_url"
    )
    assert receivers["oncall-ticket"]["webhook_configs"][0]["url_file"] == (
        "/etc/alertmanager/secrets/oncall_ticket_url"
    )
    inhibit = config["inhibit_rules"][0]
    assert inhibit["source_matchers"] == ['severity="critical"']
    assert inhibit["target_matchers"] == ['severity="warning"']
    assert inhibit["equal"] == ["alertname", "service"]
    # A page on one queue must not hide the ticket of another queue (per-queue SLO).
    slo_inhibit = config["inhibit_rules"][1]
    assert slo_inhibit["equal"] == ["slo", "queue"]
    # No endpoint or secret in the repository.
    text = (OBSERVABILITY / "alertmanager" / "alertmanager.deploy.yml").read_text()
    assert not re.search(r"https?://", text)
    assert "url:" not in text.replace("url_file:", "")


def test_compose_deploy_overlay_hides_ports_and_requires_grafana_password() -> None:
    overlay = yaml.load(
        (OBSERVABILITY / "docker-compose.deploy.yml").read_text(), Loader=_ComposeLoader
    )
    services = overlay["services"]
    for name in ("prometheus", "alertmanager", "postgres-exporter", "redis-exporter"):
        assert services[name]["ports"] == {"tag": "!reset", "value": []}, name
    grafana = services["grafana"]
    assert grafana["ports"]["value"] == ["127.0.0.1:${GRAFANA_PORT:-3001}:3000"]
    assert grafana["environment"]["GF_SECURITY_ADMIN_PASSWORD"].startswith(
        "${GRAFANA_ADMIN_PASSWORD:?"
    )
    assert grafana["environment"]["GF_AUTH_ANONYMOUS_ENABLED"] == "false"
    for name, target in (
        ("prometheus", "/etc/prometheus/secrets:ro"),
        ("alertmanager", "/etc/alertmanager/secrets:ro"),
    ):
        assert f"./secrets:{target}" in services[name]["volumes"]["value"]
    for value in (
        services["postgres-exporter"]["environment"]["DATA_SOURCE_NAME"],
        services["redis-exporter"]["environment"]["REDIS_PASSWORD"],
    ):
        assert ":?" in value and ":-postgres}" not in value.split("@")[0]
    # lib/pq (postgres-exporter) rejects sslmode=prefer; the operator picks a supported mode.
    dsn = services["postgres-exporter"]["environment"]["DATA_SOURCE_NAME"]
    assert "sslmode=${POSTGRES_EXPORTER_SSLMODE:?" in dsn
    assert "prefer" not in dsn


def test_observability_secrets_are_git_ignored() -> None:
    assert "infra/observability/secrets/" in (REPO_ROOT / ".gitignore").read_text()
    assert not (OBSERVABILITY / "secrets").exists() or not any(
        (OBSERVABILITY / "secrets").iterdir()
    )


def test_ci_checks_rules_alertmanager_and_compose_after_manifest_validation() -> None:
    workflow = _load(REPO_ROOT / ".github" / "workflows" / "ci.yml")
    steps = workflow["jobs"]["deploy-config"]["steps"]
    names = [step["name"] for step in steps]
    start = names.index("Validate rendered manifests")
    assert names[start + 1 : start + 4] == [
        "Check Prometheus rules",
        "Check Alertmanager config",
        "Check observability compose",
    ]
    by_name = {step["name"]: step.get("run", "") for step in steps}
    rules = by_name["Check Prometheus rules"]
    assert "prom/prometheus:v2.54.1" in rules and "--entrypoint promtool" in rules
    assert "check rules" in rules and "test rules" in rules
    alertmanager = by_name["Check Alertmanager config"]
    assert "--entrypoint amtool" in alertmanager and "prom/alertmanager:v0.27.0" in alertmanager
    assert "alertmanager.yml" in alertmanager and "alertmanager.deploy.yml" in alertmanager
    assert by_name["Check observability compose"].strip() == (
        "deploy/scripts/check_observability_config.sh"
    )
    assert (
        REPO_ROOT / "deploy" / "scripts" / "check_observability_config.sh"
    ).stat().st_mode & 0o111


def test_promtool_unit_tests_cover_the_b2_rule_files() -> None:
    covered: set[str] = set()
    for path in (OBSERVABILITY / "prometheus" / "tests").glob("*.yml"):
        document = _load(path)
        assert document["tests"], path.name
        covered.update(Path(name).name for name in document["rule_files"])
    assert {"beat.yml", "slo-recording.yml", "slo-burn-rate.yml"} <= covered
