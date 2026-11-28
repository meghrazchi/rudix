"""Staging and production compose parity (0.8.0, R08-12) and published ports (R08-01).

Both files define the same services. They may differ only in the allowlisted environment
names below (environment identity, public URLs, the Enterprise Graph switch and its Neo4j
wiring, edge host and noindex defaults) and in scale and resources (``deploy``). Optional
services exist in both, enabled by default or behind a profile that ``COMPOSE_PROFILES``
selects per environment. Only ``edge`` publishes host ports, and only 80 and 443.
"""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

_REPO = Path(__file__).resolve().parents[2]
_COMPOSE = _REPO / "deploy" / "compose"
_LOCAL = _REPO / "docker-compose.yml"

ALLOWED_ENV_DIFFERENCES = {
    "ENVIRONMENT",
    "API_BASE_URL",
    "FRONTEND_BASE_URL",
    "CORS_ORIGINS",
    "NEXT_PUBLIC_DEPLOYMENT_ENV",
    "NEXT_PUBLIC_APP_URL",
    "NEXT_PUBLIC_API_URL",
    "ENTERPRISE_GRAPH_ENABLED",
    "NEO4J_URI",
    "NEO4J_USERNAME",
    "NEO4J_PASSWORD",
    # edge host and noindex defaults
    "RUDIX_APP_HOST",
    "RUDIX_API_HOST",
    "EDGE_NOINDEX",
}
# Scale and resources may differ per environment.
ALLOWED_SERVICE_KEYS = {"deploy", "scale"}
OPTIONAL_SERVICES = {
    "clamav": None,
    "neo4j": "graph",
    "matomo": "analytics",
    "matomo-db": "analytics",
    "pgbouncer": "pooler",
    "redis-cache": "redis-split",
    "mcp": "mcp",
}
LOCAL_DEFAULT_SERVICES = (
    "api",
    "worker",
    "beat",
    "postgres",
    "qdrant",
    "minio",
    "minio-init",
    "clamav",
    "rabbitmq",
    "redis",
    "matomo-db",
    "matomo",
)


def _load(name: str) -> dict[str, Any]:
    document = yaml.safe_load((_COMPOSE / f"docker-compose.{name}.yml").read_text())
    assert isinstance(document, dict)
    return document


@pytest.fixture(scope="module")
def staging() -> dict[str, Any]:
    return _load("staging")


@pytest.fixture(scope="module")
def production() -> dict[str, Any]:
    return _load("production")


def _normalized(service: dict[str, Any]) -> dict[str, Any]:
    service = copy.deepcopy(service)
    for key in ALLOWED_SERVICE_KEYS:
        service.pop(key, None)
    env = service.get("environment")
    if isinstance(env, dict):
        service["environment"] = {
            key: value for key, value in env.items() if key not in ALLOWED_ENV_DIFFERENCES
        }
    return service


def test_both_files_define_the_same_services_and_volumes(
    staging: dict[str, Any], production: dict[str, Any]
) -> None:
    assert sorted(staging["services"]) == sorted(production["services"])
    assert sorted(staging["volumes"]) == sorted(production["volumes"])


def test_services_differ_only_in_allowlisted_settings(
    staging: dict[str, Any], production: dict[str, Any]
) -> None:
    differences = {
        name: sorted(
            key
            for key in set(service) | set(production["services"][name])
            if _normalized(service).get(key) != _normalized(production["services"][name]).get(key)
        )
        for name, service in staging["services"].items()
    }
    assert {name: keys for name, keys in differences.items() if keys} == {}


def test_allowlisted_differences_are_environment_identity(
    staging: dict[str, Any], production: dict[str, Any]
) -> None:
    api_staging = staging["services"]["api"]["environment"]
    api_production = production["services"]["api"]["environment"]
    assert api_staging["ENVIRONMENT"] == "staging"
    assert api_production["ENVIRONMENT"] == "production"
    assert staging["services"]["edge"]["environment"]["EDGE_NOINDEX"] == "${EDGE_NOINDEX:-true}"
    assert production["services"]["edge"]["environment"]["EDGE_NOINDEX"] == "${EDGE_NOINDEX:-false}"
    # Edge host defaults are the hosts each file already uses for its public URLs.
    for document in (staging, production):
        edge = document["services"]["edge"]["environment"]
        api_env = document["services"]["api"]["environment"]
        assert edge["RUDIX_APP_HOST"].endswith(api_env["FRONTEND_BASE_URL"][8:] + "}")
        assert edge["RUDIX_API_HOST"].endswith(api_env["API_BASE_URL"][8:] + "}")


def test_optional_services_exist_in_both_enabled_or_behind_a_profile(
    staging: dict[str, Any], production: dict[str, Any]
) -> None:
    for document in (staging, production):
        for name, profile in OPTIONAL_SERVICES.items():
            service = document["services"][name]
            if profile is None:
                assert "profiles" not in service, name
            else:
                assert service["profiles"] == [profile], name


def test_dependencies_on_profiled_services_are_optional(
    staging: dict[str, Any], production: dict[str, Any]
) -> None:
    for document in (staging, production):
        services = document["services"]
        for name, service in services.items():
            for dependency, condition in (service.get("depends_on") or {}).items():
                target_profiles = services[dependency].get("profiles")
                own_profiles = service.get("profiles")
                if target_profiles and target_profiles != own_profiles:
                    assert condition.get("required") is False, f"{name} -> {dependency}"


def _published(port: Any) -> str:
    if isinstance(port, dict):
        return str(port.get("published", ""))
    text = str(port).split("/")[0]
    parts = text.split(":")
    return parts[-2] if len(parts) >= 2 else ""


@pytest.mark.parametrize("name", ["staging", "production"])
def test_only_edge_publishes_ports_80_and_443(name: str) -> None:
    services = _load(name)["services"]
    published = {
        service_name: sorted({_published(port) for port in service.get("ports") or []})
        for service_name, service in services.items()
        if service.get("ports")
    }
    assert published == {"edge": ["443", "80"]}
    assert all("expose" not in service for service in services.values())
    assert "443:443/udp" in services["edge"]["ports"]


def test_published_port_parser() -> None:
    assert _published("80:80") == "80"
    assert _published("127.0.0.1:8000:8000") == "8000"
    assert _published("443:443/udp") == "443"
    assert _published("3000") == ""
    assert _published({"published": 8081, "target": 80}) == "8081"


@pytest.mark.parametrize("name", ["staging", "production"])
def test_edge_service_contract(name: str) -> None:
    services = _load(name)["services"]
    edge = services["edge"]
    assert edge["image"] == "${CADDY_IMAGE:-caddy:2}"
    assert "container_name" not in edge
    assert edge["volumes"] == ["./edge:/etc/caddy:ro", "edge_data:/data", "edge_config:/config"]
    env = edge["environment"]
    assert env["EDGE_TLS_MODE"] == "${EDGE_TLS_MODE:-acme}"
    assert env["EDGE_MATOMO"] == "${EDGE_MATOMO:-off}"
    assert env["EDGE_ACME_EMAIL"] == "${EDGE_ACME_EMAIL:-}"
    assert env["RUDIX_MATOMO_HOST"] == "${RUDIX_MATOMO_HOST:-}"
    # The edge does not receive the application env file (secrets).
    assert "env_file" not in edge
    # No container_name anywhere, so `docker compose up --scale api=N` works.
    assert all("container_name" not in service for service in services.values())


@pytest.mark.parametrize("name", ["staging", "production"])
def test_api_shutdown_and_forwarded_headers(name: str) -> None:
    services = _load(name)["services"]
    api = services["api"]
    env = api["environment"]
    assert env["FORWARDED_ALLOW_IPS"] == "${FORWARDED_ALLOW_IPS:-*}"
    assert env["UVICORN_TIMEOUT_GRACEFUL_SHUTDOWN"] == "${UVICORN_TIMEOUT_GRACEFUL_SHUTDOWN:-20}"
    assert env["API_SHUTDOWN_DRAIN_SECONDS"] == "${API_SHUTDOWN_DRAIN_SECONDS:-0}"
    match = re.fullmatch(r"(\d+)s", api["stop_grace_period"])
    assert match, api["stop_grace_period"]
    # Contract 5.2.5: graceful timeout + drain + margin fits inside the stop grace period.
    assert 20 + 0 + 10 <= int(match.group(1)) == 45
    assert services["mcp"]["environment"]["FORWARDED_ALLOW_IPS"] == "${FORWARDED_ALLOW_IPS:-*}"


@pytest.mark.parametrize("name", ["staging", "production"])
def test_redis_roles_pooler_and_bucket_versioning(name: str) -> None:
    services = _load(name)["services"]
    assert "--maxmemory-policy noeviction" in " ".join(services["redis"]["command"])
    cache = " ".join(services["redis-cache"]["command"])
    assert "--maxmemory-policy allkeys-lru" in cache
    assert '--maxmemory "$$REDIS_CACHE_MAXMEMORY"' in cache
    assert "--appendonly no" in cache and "--save ''" in cache
    assert "--requirepass" in cache
    assert "volumes" not in services["redis-cache"]
    assert services["redis-cache"]["environment"]["REDIS_CACHE_MAXMEMORY"] == (
        "${REDIS_CACHE_MAXMEMORY:-256mb}"
    )
    pooler = services["pgbouncer"]
    assert pooler["image"].startswith("${PGBOUNCER_IMAGE:-")
    assert pooler["environment"]["POOL_MODE"] == "transaction"
    assert pooler["environment"]["DB_HOST"] == "postgres"
    init = services["minio-init"]
    assert init["environment"]["MINIO_BUCKET_VERSIONING"] == "${MINIO_BUCKET_VERSIONING:-false}"
    assert 'if [ "$${MINIO_BUCKET_VERSIONING}" = "true" ]' in init["entrypoint"]
    assert "mc version enable local/$${MINIO_BUCKET};" in init["entrypoint"]


def test_local_compose_keeps_its_ports_and_default_services() -> None:
    # The development file keeps host ports and gains no default service in 0.8.0 (the
    # frontend runs from `npm run dev` on the host).
    local = yaml.safe_load(_LOCAL.read_text())["services"]
    defaults = sorted(name for name, service in local.items() if not service.get("profiles"))
    assert defaults == sorted(LOCAL_DEFAULT_SERVICES)
    assert "edge" not in local
    assert local["api"]["ports"] == ["8000:8000"]
    assert local["matomo"]["ports"] == ["8081:80"]
